# 온가족 한상 백엔드

레시피 재료와 가족의 질환·신체 특성으로 PubMed 논문을 찾고, OpenAI로 요약해서 **레시피 안전보고서**를 만들어요 (RAG).

## 실행

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # 그리고 .env 에 OPENAI_API_KEY 입력
uvicorn main:app --reload
```

서버 상태 확인: http://localhost:8000/api/health (안전보고서 화면은 없애고, 오늘의 한상에는 안전검사 통과 문구만 표시해요)

## API

`POST /api/safety-report`

```json
{
  "recipe":  { "id": "zucchini-tofu-soup", "title": "애호박 두부 된장국",
               "ingredients": ["두부", "애호박", "대파"], "steps": ["..."] },
  "members": [ { "name": "할머니", "age": "어르신", "allergies": [],
                 "conditions": ["고혈압"], "traits": ["씹기 어려움"] } ]
}
```

응답: `summary`, `items`(가족별 주의/참고/도움 + 근거 PMID), `cooking_plan`(조리 순서), `references`(논문), `searched`(검색식), `disclaimer`

`GET /api/health` — 서버 상태와 OpenAI 키 설정 여부

## 동작 방식 (safety.py)

1. **계획**: LLM이 레시피 재료 × 가족 건강 문제 중 확인할 조합을 최대 5개 골라 영어 의학 용어로 바꿔요. 질환명은 서버에 고정된 MeSH 용어를 써요.
2. **검색**: 조합마다 PubMed에서 리뷰·메타분석·임상시험 논문을 먼저 찾고, 없으면 조건을 풀어 다시 찾아요 (pubmed.py).
3. **생성**: LLM이 검색된 초록만 근거로 가족별 주의사항과 조리 순서를 써요.
4. **검증**: 응답의 논문 번호가 실제로 검색된 것인지 서버가 확인하고, 근거 없는 항목은 버려요.

개인정보: OpenAI에는 이름 대신 `M1, M2…`를 보내고, PubMed에는 영어 검색어만 보내요.
