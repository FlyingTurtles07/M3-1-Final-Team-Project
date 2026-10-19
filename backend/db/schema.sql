-- 온가족 한상 · Supabase(PostgreSQL) 스키마  (담당: feature/backend-infra)
-- 사용법: Supabase 대시보드 → SQL Editor 에 통째로 붙여 넣고 Run.
-- 여러 번 실행해도 안전하게 썼어요(이미 있으면 건너뛰거나 덮어써요).
--
-- 구성
--   consents        동의 이력 (FR-08)  : 쌓기만 하는 기록. 수정·삭제 불가
--   family_members  가족 구성원 (FR-01): 건강 정보는 서버가 암호화한 문장(health_enc)으로만 저장
-- 접근 제한: 모든 표에 행 단위 보안(RLS)을 켜서 "내 데이터는 나만" 읽고 쓰게 해요.
-- 계정 삭제: auth.users 의 행이 지워지면 아래 두 표의 내 행도 함께 지워져요(on delete cascade).

-- ───────────────────────── 1. 동의 이력 ─────────────────────────
create table if not exists public.consents (
  id             bigint generated always as identity primary key,
  user_id        uuid        not null default auth.uid()
                             references auth.users(id) on delete cascade,
  consent_type   text        not null
                             check (consent_type in ('terms','privacy','health','share','notification')),
  granted        boolean     not null,            -- true=동의, false=철회
  policy_version text        not null,            -- 어떤 버전의 약관 문구에 동의했는지
  created_at     timestamptz not null default now()
);
comment on table  public.consents is '동의·철회 이력. 한 번 쌓인 행은 고치거나 지우지 않는다(계정 삭제 시에만 함께 삭제).';
comment on column public.consents.consent_type is 'terms=이용약관, privacy=개인정보, health=건강정보(민감정보), share=게시물 공개, notification=알림';

create index if not exists consents_user_type_idx on public.consents (user_id, consent_type, id desc);

-- 항목별 "가장 최근 상태"만 보여 주는 보기. (보는 사람의 권한으로 조회하므로 RLS가 그대로 적용돼요)
create or replace view public.current_consents
with (security_invoker = true) as
select distinct on (user_id, consent_type)
       user_id, consent_type, granted, policy_version, created_at
from public.consents
order by user_id, consent_type, id desc;

-- 현재 로그인한 사용자가 해당 항목에 동의한 상태인지 (동의 기록이 없으면 false)
create or replace function public.has_consent(p_type text)
returns boolean
language sql
stable
as $$
  select coalesce(
    (select c.granted
       from public.consents c
      where c.user_id = auth.uid() and c.consent_type = p_type
      order by c.id desc
      limit 1),
    false);
$$;

-- ───────────────────────── 2. 가족 구성원 ─────────────────────────
create table if not exists public.family_members (
  id            uuid        primary key default gen_random_uuid(),
  user_id       uuid        not null default auth.uid()
                            references auth.users(id) on delete cascade,
  nickname      text        not null check (char_length(nickname) between 1 and 10),  -- 실명 대신 별칭
  avatar        text,                                  -- 화면에서 고른 캐릭터 이름
  proxy_consent boolean     not null default false,    -- 다른 가족 정보를 대신 입력하며 동의를 받았는지
  health_enc    text        not null,                  -- 연령대·알레르기·식사 조건·기피 재료·메모 (서버가 암호화)
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (user_id, nickname)
);
comment on column public.family_members.health_enc is '서버(FastAPI)가 Fernet으로 암호화한 JSON. 키는 HEALTH_DATA_KEY 환경 변수에만 있고 DB에는 없다.';

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists family_members_touch on public.family_members;
create trigger family_members_touch
  before update on public.family_members
  for each row execute function public.touch_updated_at();

-- ───────────────────────── 3. 행 단위 접근 제한 (RLS) ─────────────────────────
alter table public.consents       enable row level security;
alter table public.family_members enable row level security;

-- consents: 내 행만 보고, 내 이름으로만 새 행을 쌓는다. update/delete 정책이 없으므로 고치거나 지울 수 없다.
drop policy if exists consents_select_own on public.consents;
create policy consents_select_own on public.consents
  for select to authenticated
  using (user_id = auth.uid());

drop policy if exists consents_insert_own on public.consents;
create policy consents_insert_own on public.consents
  for insert to authenticated
  with check (user_id = auth.uid());

-- family_members: 내 행만 보고 지운다. 새로 넣거나 고칠 때는 "건강 정보 동의" 상태여야 한다(철회하면 입력이 막힘).
drop policy if exists members_select_own on public.family_members;
create policy members_select_own on public.family_members
  for select to authenticated
  using (user_id = auth.uid());

drop policy if exists members_insert_own on public.family_members;
create policy members_insert_own on public.family_members
  for insert to authenticated
  with check (user_id = auth.uid() and public.has_consent('health'));

drop policy if exists members_update_own on public.family_members;
create policy members_update_own on public.family_members
  for update to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid() and public.has_consent('health'));

drop policy if exists members_delete_own on public.family_members;
create policy members_delete_own on public.family_members
  for delete to authenticated
  using (user_id = auth.uid());

-- ───────────────────────── 4. 권한(grant) ─────────────────────────
-- 로그인 전(anon)에는 아무것도 못 보게 하고, 로그인한 사용자(authenticated)에게만 필요한 만큼만 연다.
revoke all on public.consents, public.family_members, public.current_consents from anon;
revoke all on public.consents, public.family_members, public.current_consents from authenticated;

grant select, insert on public.consents       to authenticated;
grant select         on public.current_consents to authenticated;
grant select, insert, update, delete on public.family_members to authenticated;
grant execute on function public.has_consent(text) to authenticated;
