-- 레시피 추천용 데이터 테이블 (초안)
-- 전제: auth.users 와 family_members(id, owner_id) 가 이미 있음 (기존 schema.sql)

create type safety_status as enum ('PASS', 'BLOCKED', 'NEEDS_REVIEW', 'SYSTEM_ERROR');

-- ===== A. 기준 데이터 (팀·공공 자료, 읽기 위주) =====

-- 정책 문서 버전 (정책 22종 + 공통 규칙 + 레시피 지침을 한 줄씩)
create table policy_versions (
  id uuid primary key default gen_random_uuid(),
  code text not null,                    -- COMMON, GUIDELINE, AL-03, NA-02 ...
  version text not null,
  content text not null,                 -- 그때의 정책 본문
  content_hash text not null,
  created_at timestamptz not null default now(),
  unique (code, version)
);

-- 판정 기준값·설정 (확정 여부를 함께 저장)
create table rule_settings (
  key text primary key,                  -- sodium_daily_mg, sodium_meal_mg, round_g ...
  value jsonb,                           -- 보류면 null
  unit text,
  status text not null check (status in ('confirmed', 'provisional', 'on_hold')),
  policy_code text,                      -- 어느 정책이 쓰는지 (예: NA-02)
  source text,
  updated_at timestamptz not null default now()
);

-- 알레르기 항목 (식약처 고시 항목과 정책 연결)
create table allergen_items (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,             -- peanut, walnut, shrimp ...
  name_ko text not null unique,          -- 땅콩, 호두, 새우 ...
  policy_code text,                      -- AL-03 ... (정책이 없으면 null)
  is_statutory boolean not null default true,
  notice_ref text,                       -- 고시·시행규칙 근거
  notice_checked_on date
);

-- 재료 사전
create table ingredients (
  id uuid primary key default gen_random_uuid(),
  search_name text not null unique,      -- 정확 일치 검색명 (DM-01, NA-01)
  display_name text not null,
  kfda_food_code text,                   -- 식약처 식품영양성분 DB의 식품 코드
  match_status text not null default 'review' check (match_status in ('confirmed', 'review')),
  sodium_caution boolean not null default false,   -- 간장, 된장, 젓갈 등 (NA-01)
  added_sugar boolean not null default false,      -- 설탕, 꿀, 시럽 등 (DM-03)
  is_processed boolean not null default false,     -- 원재료표 확인이 필요한 가공품
  updated_at timestamptz not null default now()
);

-- 별칭 (검색 후보일 뿐 단독 판정에 쓰지 않음)
create table ingredient_aliases (
  alias text primary key,
  ingredient_id uuid not null references ingredients(id) on delete cascade,
  status text not null default 'review' check (status in ('confirmed', 'review'))
);

-- 재료 ↔ 알레르기 항목
create table ingredient_allergens (
  ingredient_id uuid not null references ingredients(id) on delete cascade,
  allergen_item_id uuid not null references allergen_items(id) on delete cascade,
  relation text not null check (relation in ('contains', 'derivative_possible', 'cross_contact_note')),
  status text not null default 'review' check (status in ('confirmed', 'review')),
  primary key (ingredient_id, allergen_item_id, relation)
);

-- 정량 기준 (QT-01): 교환단위량, 1회 섭취참고량, 가식부 비율, 개당 중량 ...
create table ingredient_portions (
  id uuid primary key default gen_random_uuid(),
  ingredient_id uuid not null references ingredients(id) on delete cascade,
  basis text not null check (basis in ('exchange_unit', 'serving_reference', 'edible_ratio', 'piece_weight', 'discard_rate')),
  value numeric not null,                -- g 또는 비율
  source text not null,
  status text not null default 'review' check (status in ('confirmed', 'review')),
  unique (ingredient_id, basis, source)
);

-- 식약처 영양 데이터 캐시 (100g당)
create table food_nutrients (
  ingredient_id uuid primary key references ingredients(id) on delete cascade,
  energy_kcal numeric,
  carbohydrate_g numeric,
  sugars_g numeric,
  fiber_g numeric,
  sodium_mg numeric,
  source text not null,
  fetched_at timestamptz not null default now()
);

-- 재료 근거 태그 (DM-02: 설명·대체 제안용, 판정에는 쓰지 않음)
create table ingredient_tags (
  ingredient_id uuid not null references ingredients(id) on delete cascade,
  tag text not null,                     -- 예: 통곡물, 콩류, 정제곡물, 가공육
  direction text not null check (direction in ('favorable', 'unfavorable')),
  evidence_ref text,
  status text not null default 'review' check (status in ('confirmed', 'review')),
  primary key (ingredient_id, tag)
);

-- ===== B. 레시피 결과 (사용자 소유) =====

create table recipes (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  dish text not null,
  servings int not null default 4 check (servings = 4),          -- QT-01
  base_steps jsonb not null,
  model text,
  policy_snapshot jsonb not null,        -- {정책 코드: 버전}
  settings_snapshot jsonb not null,      -- 그때 쓴 기준값 (임시값 포함)
  created_at timestamptz not null default now()
);

-- 공통 베이스 재료 (분량은 규칙 엔진이 채움)
create table recipe_ingredients (
  recipe_id uuid not null references recipes(id) on delete cascade,
  ingredient_id uuid not null references ingredients(id),
  amount_g numeric,                      -- 엔진이 채우기 전에는 null
  primary key (recipe_id, ingredient_id)
);

create table recipe_variants (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  recipe_id uuid not null references recipes(id) on delete cascade,
  member_id uuid not null references family_members(id) on delete cascade,
  health_record_id uuid,                 -- 사용한 건강 기록 (member_health_records.id)
  health_snapshot_enc text not null,     -- 그날의 건강 상태 (암호화)
  applied_policies text[] not null default '{}',
  branches jsonb not null default '[]',  -- 단계, 정책 코드, 변경, 이유
  ingredients jsonb not null default '[]',  -- [{ingredient_id, amount_g, origin: base|add|substitute}]
  nutrition jsonb,
  created_at timestamptz not null default now()
);

-- 안전 검사 결과 (한 변형에 여러 번 쌓이고, 현재 유효한 것은 한 개)
create table safety_checks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  variant_id uuid not null references recipe_variants(id) on delete cascade,
  status safety_status not null,
  engine_version text not null,
  policy_snapshot jsonb not null,
  is_current boolean not null default true,
  stale_at timestamptz,                  -- 프로필이 바뀌어 다시 검사가 필요해진 시각
  checked_at timestamptz not null default now()
);
create unique index one_current_check_per_variant on safety_checks (variant_id) where is_current;

-- 판정 근거 (화면에는 보이지 않고 서버에서만 읽음)
create table safety_check_items (
  id uuid primary key default gen_random_uuid(),
  check_id uuid not null references safety_checks(id) on delete cascade,
  policy_code text not null,
  subject_type text not null check (subject_type in ('ingredient', 'nutrient', 'product', 'info')),
  subject_ref text,
  result text not null check (result in ('PASS', 'BLOCKED', 'NEEDS_REVIEW')),
  detail_code text not null,             -- ALLERGEN_MATCH, SUBINGREDIENT_UNKNOWN, NO_THRESHOLD, NO_AMOUNT, DATA_MISSING, NAME_AMBIGUOUS ...
  value numeric,
  limit_value numeric,
  evidence jsonb
);
create index on safety_check_items (check_id);
