# 온가족 한상 백엔드 (FastAPI)

화면(`frontend/`)이 쓰는 API 서버예요. Render에서는 `render.yaml`의 `onfamily-hansang-api` 서비스로 올라가요.

## 하는 일
| 기능 | API |
|---|---|
| 회원가입·로그인 (비밀번호는 해시로만 저장, 로그인 토큰 30일) | `POST /api/auth/signup`, `POST /api/auth/login`, `GET /api/me`, `DELETE /api/me`(탈퇴) |
| 가족 프로필·확인한 재료·보관함 저장 | `GET/PUT /api/me/data/{family,pantry,saved,collections}` |
| 다른 집 한상 (사진·레시피 공유, 좋아요, 신고, 내 글 삭제) | `GET/POST /api/posts`, `GET /api/posts/{id}/photo`, `POST /api/posts/{id}/like`, `POST /api/posts/{id}/report`, `DELETE /api/posts/{id}` |
| 식사 후 의견 | `POST /api/feedback` |
| 사진 재료 인식 (사진은 저장하지 않음) | `POST /api/ingredients/analyze` |
| 레시피 3개 추천 (재료만으로) + 안전 검사 결과 | `POST /api/recipes/recommend` |
| 알레르기·당뇨식·저염식 안전 검사 | `POST /api/safety/check` |

`GET /api/health` — 서버·DB 상태와 AI·식약처 키 설정 여부. 전체 문서는 `/docs`.

## 환경변수
| 이름 | 설명 | 없을 때 |
|---|---|---|
| `FIREBASE_CREDENTIALS` | Firebase 서비스 계정 키 JSON 내용 (데이터는 Firestore에 저장) | 프로젝트 폴더의 `*firebase-adminsdk*.json` 파일 |
| `JWT_SECRET` | 로그인 토큰 서명 키 (Render가 자동 생성) | 개발용 값 (배포 금지) |
| `OPENAI_API_KEY` | 사진 재료 인식·AI 레시피 | 예시 재료·기본 레시피 10개 |
| `MFDS_API_KEY` | 공공데이터포털 식품영양성분DB | 앱에 넣어 둔 기본 수치(임시값) |
| `CORS_ORIGINS` | 허용할 화면 주소 (쉼표로 구분) | `*` |

## 내 컴퓨터에서 실행
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # 필요한 키만 채워요
uvicorn main:app --reload       # http://localhost:8000/docs
```
화면은 `frontend` 폴더에서 `python -m http.server 8765` 로 열면 `api.js`가 자동으로 `http://localhost:8000`에 연결해요.

## [검토] 확정이 필요한 것
- 당뇨식·저염식 기준값(`safety.py`의 `LIMITS`)과 기본 영양 수치는 전문가 확정 전 임시값이에요.
- 식약처 API 주소·응답 필드 이름은 활용신청 후 참고문서로 확인해서 `MFDS_*` 환경변수로 맞춰 주세요.
- 데이터는 Firebase Firestore(프로젝트 ffff-da962)에 저장해요. 예전 Render Postgres 데이터는 `migrate_to_firestore.py`로 옮겼어요.
- `legacy/`는 예전 안전보고서(PubMed RAG) 코드예요. 지금 화면에서는 쓰지 않아요.
