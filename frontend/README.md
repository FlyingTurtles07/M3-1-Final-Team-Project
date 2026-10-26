# 온가족 한상 · 화면 (정적 사이트)

빌드 없이 HTML 파일을 그대로 올리는 화면이에요. Render에서는 저장소 맨 위의 `render.yaml` 설정으로 이 폴더를 올려요.

## 화면 순서
회원가입(`signup.html`) / 로그인(`login.html`) → 가족 프로필(`family-profile.html`) → 홈·재료 사진(`home.html`) → 재료 확인(`ingredient-check.html`)
→ 오늘의 한상(`today-meal.html`, 레시피 3개 + 분기점) → 식사 후 의견(`feedback.html`, 마음에 들면 보관함 저장) → 식사 사진 기록(`meal-record.html`, 레시피 함께 공유·인스타·카톡)
→ 다른 집 한상(`browse.html`) · 저장한 요리(`saved-recipes.html`)

- `index.html`: 첫 주소로 들어오면 회원가입(로그인한 적이 있으면 홈)으로 보내요.
- `nav.js`: 화면마다 하단 탭 이동을 연결해요.
- 지금은 서버 없이 브라우저 저장소(localStorage)에 저장하는 시제품이에요. 레시피·사진 인식은 예시 데이터예요.

## 내 컴퓨터에서 보기
```bash
cd frontend
python -m http.server 8000   # http://localhost:8000
```
