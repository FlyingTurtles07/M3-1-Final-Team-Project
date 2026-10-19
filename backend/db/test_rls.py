"""schema.sql 의 접근 제한(RLS)이 정말 막아 주는지 시험해요.

실행:  DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres python -m pytest backend/db -q
- DATABASE_URL 이 없으면 시험을 건너뛰어요. (GitHub Actions에서는 임시 PostgreSQL을 띄워 자동 실행)
- 반드시 "연습용 빈 DB"에만 쓰세요. 아래 준비 단계가 auth 스키마와 역할을 가짜로 만들어요. 실제 Supabase에는 절대 쓰지 마세요.
"""
import os
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL 이 없어서 건너뜀")

SCHEMA = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")

# Supabase가 기본으로 만들어 두는 것들을 흉내 낸 준비 단계 (진짜 Supabase에는 이미 있음)
MOCK_SUPABASE = """
do $$ begin
  if not exists (select from pg_roles where rolname = 'anon')          then create role anon nologin; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key default gen_random_uuid(), email text);
create or replace function auth.uid() returns uuid language sql stable as
  $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant usage on schema public, auth to anon, authenticated;
grant execute on function auth.uid() to anon, authenticated;
"""


RESET = """
drop view if exists public.current_consents;
drop table if exists public.family_members, public.consents cascade;
drop function if exists public.has_consent(text), public.touch_updated_at();
"""


@pytest.fixture(scope="module", autouse=True)
def prepared_db():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(MOCK_SUPABASE)
        conn.execute(RESET)   # 매번 깨끗한 상태에서 schema.sql 만으로 만들어지는지 확인
        conn.execute(SCHEMA)
        conn.execute(SCHEMA)  # 두 번 실행해도 오류가 없어야 한다
    yield


class Db:
    def __init__(self, conn):
        self.conn = conn

    def new_user(self) -> str:
        uid = str(uuid.uuid4())
        self.conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid[:8]}@test.local"))
        return uid

    def login(self, uid: str | None):
        """이후 문장을 '로그인한 사용자(uid)' 권한으로 실행 (uid=None 이면 로그인 전 anon)."""
        self.conn.execute("reset role")
        self.conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (uid or "",))
        self.conn.execute("set local role " + ("authenticated" if uid else "anon"))

    def admin(self):
        self.conn.execute("reset role")

    def consent(self, uid, kind, granted=True):
        self.login(uid)
        self.conn.execute(
            "insert into public.consents (consent_type, granted, policy_version) values (%s, %s, 'test')", (kind, granted)
        )

    def add_member(self, uid, nickname="엄마"):
        self.login(uid)
        return self.conn.execute(
            "insert into public.family_members (nickname, health_enc) values (%s, 'ENC') returning id", (nickname,)
        ).fetchone()[0]

    def count(self, table):
        return self.conn.execute(f"select count(*) from public.{table}").fetchone()[0]


@pytest.fixture
def db():
    with psycopg.connect(DATABASE_URL) as conn:   # 시험마다 트랜잭션을 열고 끝에 되돌려요
        yield Db(conn)
        conn.rollback()


def test_건강정보_동의_없이는_구성원을_저장할_수_없다(db):
    a = db.new_user()
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.add_member(a)
    db.consent(a, "health")
    db.add_member(a)
    assert db.count("family_members") == 1


def test_다른_계정은_내_구성원을_보거나_고치거나_지울_수_없다(db):
    a, b = db.new_user(), db.new_user()
    db.consent(a, "health")
    member_id = db.add_member(a)

    db.login(b)
    assert db.count("family_members") == 0
    assert db.conn.execute("update public.family_members set nickname='해킹' where id=%s", (member_id,)).rowcount == 0
    assert db.conn.execute("delete from public.family_members where id=%s", (member_id,)).rowcount == 0

    db.admin()
    assert db.conn.execute("select nickname from public.family_members where id=%s", (member_id,)).fetchone()[0] == "엄마"


def test_남의_이름으로_행을_넣을_수_없다(db):
    a, b = db.new_user(), db.new_user()
    db.consent(b, "health")
    db.login(b)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.conn.execute("insert into public.family_members (user_id, nickname, health_enc) values (%s, 'x', 'ENC')", (a,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.conn.execute("insert into public.consents (user_id, consent_type, granted, policy_version) values (%s, 'health', true, 't')", (a,))


def test_다른_계정의_동의이력은_보이지_않고_내_것만_보인다(db):
    a, b = db.new_user(), db.new_user()
    db.consent(a, "terms")
    db.consent(b, "terms")
    db.consent(b, "privacy")
    db.login(a)
    assert db.count("consents") == 1
    assert db.count("current_consents") == 1


def test_동의이력은_쌓기만_하고_고치거나_지울_수_없다(db):
    a = db.new_user()
    db.consent(a, "terms")
    db.login(a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.conn.execute("update public.consents set granted=false")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.conn.execute("delete from public.consents")
    assert db.count("consents") == 1


def test_현재_동의상태는_가장_최근_기록이다(db):
    a = db.new_user()
    db.consent(a, "health", True)
    db.consent(a, "health", False)
    db.login(a)
    row = db.conn.execute("select granted from public.current_consents where consent_type='health'").fetchone()
    assert row[0] is False
    assert db.conn.execute("select public.has_consent('health')").fetchone()[0] is False
    assert db.count("consents") == 2


def test_동의를_철회하면_입력과_수정은_막히고_삭제는_된다(db):
    a = db.new_user()
    db.consent(a, "health")
    member_id = db.add_member(a)
    db.consent(a, "health", False)

    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.add_member(a, "아빠")
    db.login(a)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
        db.conn.execute("update public.family_members set nickname='바꿈' where id=%s", (member_id,))
    assert db.conn.execute("delete from public.family_members where id=%s", (member_id,)).rowcount == 1


def test_같은_별칭은_한_계정에서_중복될_수_없지만_다른_계정에서는_된다(db):
    a, b = db.new_user(), db.new_user()
    db.consent(a, "health")
    db.consent(b, "health")
    db.add_member(a, "엄마")
    with pytest.raises(psycopg.errors.UniqueViolation), db.conn.transaction():
        db.add_member(a, "엄마")
    db.add_member(b, "엄마")


def test_계정을_지우면_내_데이터가_모두_함께_지워진다(db):
    a, b = db.new_user(), db.new_user()
    for u in (a, b):
        db.consent(u, "health")
        db.add_member(u)
    db.admin()
    db.conn.execute("delete from auth.users where id=%s", (a,))
    assert db.conn.execute("select count(*) from public.family_members where user_id=%s", (a,)).fetchone()[0] == 0
    assert db.conn.execute("select count(*) from public.consents where user_id=%s", (a,)).fetchone()[0] == 0
    assert db.conn.execute("select count(*) from public.family_members where user_id=%s", (b,)).fetchone()[0] == 1


def test_로그인_전에는_아무것도_볼_수_없다(db):
    a = db.new_user()
    db.consent(a, "health")
    db.add_member(a)
    db.login(None)
    for table in ("family_members", "consents", "current_consents"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.conn.transaction():
            db.conn.execute(f"select * from public.{table}")
