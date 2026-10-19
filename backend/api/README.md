# 백엔드 API — 로그인·동의·가족 프로필

담당: `feature/backend-infra` · 범위: FR-01 가족 프로필, FR-08 동의·삭제, Supabase 스키마·Auth, Render 배포, GitHub Actions

체크리스트 0~2단계(공통 기반 → 동의와 로그인 → 가족 프로필)에 해당해요. 재고(3단계)·사진(4단계)·메뉴 생성(6단계)은 다음 작업이에요.

## 폴더

```
backend/
  api/              FastAPI 서버 (main.py, routers/, schemas.py, store.py, crypto.py ...)
    tests/          API 시험 (가짜 DB 사용, 인터넷·Supabase 없이 돌아가요)
  db/
    schema.sql      Supabase에 붙여 넣는 표·접근 제한 정의
    test_rls.py     "다른 계정은 못 본다"를 진짜 PostgreSQL로 확인하는 시험
.github/workflows/ci.yml   풀 리퀘스트마다 위 시험을 자동 실행
render.yaml                Render 배포 설정
```

## 구조 한눈에

```
화면(프론트) ──supabase-js로 가입·로그인──▶ Supabase Auth ──▶ 액세스 토큰(JWT)
     │
     └─ Authorization: Bearer <토큰> ─▶ FastAPI ─ 토큰 확인 ─▶ Supabase Auth
                                          │
                                          └─ 같은 토큰으로 DB 호출 ─▶ Supabase(PostgreSQL) + RLS
```

- 가입·로그인은 화면이 Supabase Auth를 직접 써요(서버에 가입 API 없음).
- 서버는 사용자의 토큰으로 DB를 호출해서 **DB의 행 단위 접근 제한(RLS)이 항상 적용**돼요. 서버가 관리자 권한으로 남의 데이터를 읽는 길이 없어요. 관리자 키(service_role)는 계정 삭제에만 써요.
- 건강 정보(연령대·알레르기·식사 조건·기피 재료·메모)는 서버가 **암호화해서** `health_enc` 한 칸에 저장해요. 별칭·캐릭터만 평문이에요.

## 처음 세팅 (내 컴퓨터)

1. **Supabase 프로젝트 만들기** → SQL Editor에 `backend/db/schema.sql` 전체를 붙여 넣고 Run
2. **키 복사**: Project Settings → API 에서 URL, anon(publishable) 키, service_role(secret) 키
3. **암호화 키 만들기**
   ```powershell
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. **.env 만들기**: `backend/api/.env.example` 을 `backend/api/.env` 로 복사해 값을 채우기 (`.env` 는 `.gitignore` 에 들어 있어요)
5. **설치와 실행** (저장소 맨 위 폴더에서)
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r backend/api/requirements-dev.txt
   uvicorn backend.api.main:app --reload
   ```
6. 확인: http://localhost:8000/health → `{"ok": true, ...}` / http://localhost:8000/health?deep=true → `"supabase": "ok"` / http://localhost:8000/docs 에서 API 직접 시험

## 화면에서 부르는 방법

```js
const { data } = await supabase.auth.getSession();           // supabase-js 로그인 후
const token = data.session.access_token;

// 가입 직후: 필수 동의 3개 기록
await fetch(`${API}/api/consents`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  body: JSON.stringify({ items: [
    { consent_type: 'terms', granted: true },
    { consent_type: 'privacy', granted: true },
    { consent_type: 'health', granted: true },
  ]}),
});
```
`GET /api/consents` 의 `can_use_service` 가 `false` 이면 서비스 화면으로 넘기지 말고 동의 화면으로 보내세요.

## API

모든 요청에 `Authorization: Bearer <토큰>` 이 필요해요 (`/health` 제외). 오류는 `{"detail": {"code": "...", "message": "..."}}` 모양이에요.

| 메서드·주소 | 하는 일 | 결과 |
|---|---|---|
| `GET /health` · `GET /health?deep=true` | 서버 상태 · Supabase 연결까지 확인 | 200 / 연결 실패 503 |
| `GET /api/consents` | 내 동의 현황, `can_use_service` | 200 |
| `POST /api/consents` | 동의·철회 기록 `{items:[{consent_type, granted}]}` | 200 (현재 상태) |
| `GET /api/consents/history` | 동의·철회 이력 (최근 200건) | 200 |
| `GET /api/members` | 가족 구성원 목록 | 200 · 동의 부족 403 |
| `POST /api/members` | 구성원 추가 | 201 · 중복 별칭 409 · 11번째 409 · 입력 오류 422 |
| `PUT /api/members/{id}` | 구성원 수정(전체 교체) | 200 · 없음/남의 것 404 |
| `DELETE /api/members/{id}` | 구성원·건강 정보 삭제 (동의 철회 후에도 가능) | 204 · 404 |
| `DELETE /api/account?confirm=true` | 계정과 모든 데이터 삭제 (되돌릴 수 없음) | 204 · confirm 없으면 400 |

동의 항목(`consent_type`): `terms` 이용약관 · `privacy` 개인정보 · `health` 건강정보(민감정보) · `share` 게시물 공개 · `notification` 알림.
서비스 이용 조건은 `terms`·`privacy`·`health` 모두 동의예요. 철회(`granted:false`)하면 구성원 조회·저장·수정이 막혀요(삭제는 가능).

### 구성원 요청 본문 (화면 family.html 입력 항목과 대응)

| 필드 | 화면 항목 | 규칙 |
|---|---|---|
| `nickname` | name | 1~10자, 한 계정 안에서 중복 불가 |
| `avatar` | char | 캐릭터 이름(선택) |
| `age` | 연령대 | 성인 · 어린이 · 노인 · 환자(회복식) |
| `allergies` | 알레르기 칩 | 표준 목록에서만. 없으면 `["없음"]`(다른 항목과 같이 못 씀) |
| `allergy_custom` | 직접 입력 | 목록에 없는 알레르기, 30자 |
| `conditions` | 식사 조건 | 일반식 · 당뇨식 · 저염식 · 유동식 · 이유식 (`일반식`은 단독) |
| `condition_custom` | 직접 입력 | 30자 |
| `avoid_ingredients` | 기피 재료 | 재료명 목록, 각 20자 이하 |
| `notes` | 메모 | 200자 |
| `proxy_consent` | proxy 체크 | 다른 가족 정보를 대신 입력하며 동의를 받았는지 |

## 표 명세

| 표 | 열 | 접근 규칙 |
|---|---|---|
| `consents` | id, user_id, consent_type, granted, policy_version, created_at | 내 행만 조회·추가. **수정·삭제 불가**(이력) |
| `family_members` | id, user_id, nickname, avatar, proxy_consent, health_enc(암호화), created_at, updated_at | 내 행만 조회·삭제. 추가·수정은 건강정보 동의 상태일 때만 |
| `current_consents` (보기) | 항목별 가장 최근 상태 | 내 행만 |

`auth.users` 의 계정이 삭제되면 위 표의 내 행이 모두 함께 삭제돼요(`on delete cascade`).

## 시험

```powershell
python -m pytest backend/api/tests -q                    # API 시험 (바로 실행 가능)
# DB 시험은 '연습용 빈 PostgreSQL'이 있어야 해요. (GitHub Actions 에서는 자동으로 띄워서 실행)
$env:DATABASE_URL="postgresql://postgres:비밀번호@localhost:5432/postgres"
python -m pytest backend/db -q
```
⚠ `backend/db/test_rls.py` 는 표를 지웠다 다시 만들어요. **실제 Supabase 주소로 절대 실행하지 마세요.**

## Render 배포

1. Render → New → Blueprint → 이 저장소 선택 (`render.yaml` 을 읽어요) 또는 Web Service 를 직접 만들고 아래처럼 입력
   - Build: `pip install -r backend/api/requirements.txt`
   - Start: `uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/health`
2. Environment 에 `.env.example` 의 키들을 입력 (`SUPABASE_*`, `HEALTH_DATA_KEY`, `CORS_ORIGINS`)
3. 배포 후 `https://<서비스>.onrender.com/health?deep=true` 로 Supabase 연결 확인
4. 무료 플랜은 15분쯤 요청이 없으면 잠들어서 첫 응답이 느려요. 발표·테스트 직전에 `/health` 를 한 번 호출해 깨워 두세요.

## 팀과 정해야 할 것

- [ ] **알레르기 표준 목록**: 지금은 화면의 8개 값이에요. 식약처 고시 기준 목록(김지혜 사전)으로 `constants.py` 를 교체
- [ ] **건강 정보 암호화 방식**: 서버에서 Fernet으로 암호화하는 방식으로 만들었어요. 팀 확정 필요
- [ ] **동의 철회 시 기존 데이터**: 지금은 조회·입력만 막고 데이터는 남겨요(삭제는 사용자가 직접). 철회 즉시 자동 삭제로 할지 결정
- [ ] **계정 삭제 시 동의 이력**: 지금은 함께 삭제돼요. 법적 증빙으로 일정 기간 보관할지 결정
- [ ] **프론트 연결**: 화면이 localStorage 에 저장하는 부분(`familyMembers`, `onfamily_session`)을 위 API로 교체 (김지혜)
- [ ] **Supabase Auth 이메일 확인(Confirm email)** 사용 여부
