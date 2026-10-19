"""SupabaseStore 가 Supabase에 '올바른 요청'을 보내는지 확인해요. (가짜 서버 사용 — 실제 Supabase 연결 확인은 배포 후 /health?deep=true)"""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from ..config import get_settings
from ..store import CurrentUser, DuplicateNickname, RlsDenied, StoreError, SupabaseStore

USER = CurrentUser(id="user-1", email="a@test.local", token="USER-JWT")


def run(coro):
    return asyncio.run(coro)


def make_store(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseStore(client, get_settings())


def test_목록_조회는_사용자_토큰과_anon키로_호출한다_서비스키는_쓰지_않는다():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(method=req.method, url=str(req.url), headers=dict(req.headers))
        return httpx.Response(200, json=[])

    run(make_store(handler).list_members(USER))
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://test.supabase.co/rest/v1/family_members?")
    assert seen["headers"]["authorization"] == "Bearer USER-JWT"
    assert seen["headers"]["apikey"] == "anon-key"
    assert "service-key" not in json.dumps(seen["headers"])


def test_동의_추가는_POST로_목록을_보낸다():
    seen = {}

    def handler(req):
        seen.update(method=req.method, path=req.url.path, body=json.loads(req.content))
        return httpx.Response(201, json=[])

    rows = [{"consent_type": "terms", "granted": True, "policy_version": "v"}]
    run(make_store(handler).add_consents(USER, rows))
    assert (seen["method"], seen["path"], seen["body"]) == ("POST", "/rest/v1/consents", rows)


def test_수정과_삭제는_id를_지정한다():
    mid = uuid4()
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path, req.url.params.get("id")))
        return httpx.Response(200, json=[{"id": str(mid)}])

    s = make_store(handler)
    assert run(s.update_member(USER, mid, {"nickname": "x"})) == {"id": str(mid)}
    assert run(s.delete_member(USER, mid)) is True
    assert calls == [("PATCH", "/rest/v1/family_members", f"eq.{mid}"), ("DELETE", "/rest/v1/family_members", f"eq.{mid}")]


def test_결과가_비면_없는_것으로_본다():
    s = make_store(lambda req: httpx.Response(200, json=[]))
    assert run(s.update_member(USER, uuid4(), {})) is None
    assert run(s.delete_member(USER, uuid4())) is False


@pytest.mark.parametrize(
    "status,code,exc",
    [(409, "23505", DuplicateNickname), (403, "42501", RlsDenied), (401, "PGRST301", StoreError), (500, "", StoreError)],
)
def test_DB_오류를_구분해서_알린다(status, code, exc):
    s = make_store(lambda req: httpx.Response(status, json={"code": code, "message": "비밀 내용"}))
    with pytest.raises(exc) as e:
        run(s.create_member(USER, {"nickname": "x"}))
    assert "비밀 내용" not in str(e.value)


def test_연결이_안되면_StoreError():
    def handler(req):
        raise httpx.ConnectError("boom")

    with pytest.raises(StoreError):
        run(make_store(handler).list_members(USER))


def test_계정삭제는_관리자_API를_서비스키로_부른다_사용자_토큰은_보내지_않는다():
    seen = {}

    def handler(req):
        seen.update(method=req.method, path=req.url.path, headers=dict(req.headers))
        return httpx.Response(200, json={})

    run(make_store(handler).delete_account(USER))
    assert (seen["method"], seen["path"]) == ("DELETE", "/auth/v1/admin/users/user-1")
    assert seen["headers"]["apikey"] == "service-key"
    assert "USER-JWT" not in json.dumps(seen["headers"])


def test_새_sb_secret_키는_apikey_헤더만_쓰고_예전_JWT키는_Authorization도_쓴다(monkeypatch):
    got = []

    def handler(req):
        got.append(dict(req.headers))
        return httpx.Response(204)

    for key in ("sb_secret_abc", "eyJhbGciOi.payload.sig"):
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", key)
        get_settings.cache_clear()
        run(make_store(handler).delete_account(USER))
    assert "authorization" not in got[0] and got[0]["apikey"] == "sb_secret_abc"
    assert got[1]["authorization"] == "Bearer eyJhbGciOi.payload.sig"


def test_서비스키가_없으면_삭제하지_않고_오류(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "")
    get_settings.cache_clear()
    called = []
    with pytest.raises(StoreError):
        run(make_store(lambda req: called.append(1) or httpx.Response(200)).delete_account(USER))
    assert not called


def test_이미_삭제된_계정_404는_성공으로_본다_다른_오류는_실패():
    run(make_store(lambda req: httpx.Response(404)).delete_account(USER))
    with pytest.raises(StoreError):
        run(make_store(lambda req: httpx.Response(500)).delete_account(USER))
