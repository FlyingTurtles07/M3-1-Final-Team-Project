"""레시피 안전보고서 (RAG 파이프라인).

1) 계획: LLM이 레시피 재료와 가족 건강정보를 보고 확인할 '식재료 × 건강 문제' 조합을 골라 영어 의학 용어로 바꿔요.
2) 검색: 조합마다 PubMed에서 논문을 찾아 초록을 가져와요.          (pubmed.py)
3) 생성: LLM이 가져온 초록'만' 근거로 가족별 주의사항과 조리 순서를 써요.
4) 검증: 응답에 붙은 논문 번호가 실제로 검색된 것인지 서버가 다시 확인해요. 근거 없는 항목은 버려요.

개인정보: 이름은 OpenAI에 보내지 않고 "M1, M2…"로 바꿔서 보내요. PubMed에는 영어 검색어만 가요.
"""
import json
import os

import httpx
from openai import AsyncOpenAI

import pubmed

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_PAIRS = 5
_client: AsyncOpenAI | None = None

DISCLAIMER = ("이 보고서는 공개된 의학 논문을 AI가 요약한 참고 정보예요. 진단이나 치료를 대신하지 않아요. "
              "질환이 있다면 식단을 바꾸기 전에 담당 의사나 영양사와 상의하세요.")

# 화면의 질환·신체 특성 선택지 → 영어 의학 용어 (LLM 번역보다 정확하게 고정)
CONCERN_EN = {
    "당뇨": "diabetes mellitus", "고혈압": "hypertension", "고지혈증": "hyperlipidemias",
    "신장질환": "renal insufficiency, chronic", "통풍": "gout", "위장질환": "gastroesophageal reflux",
    "빈혈": "anemia, iron-deficiency", "골다공증": "osteoporosis",
    "씹기 어려움": "mastication", "삼키기 어려움": "deglutition disorders",
    "임신·수유 중": "pregnancy", "과체중": "overweight",
}


class LLMUnavailable(RuntimeError):
    pass


def _llm() -> AsyncOpenAI:
    global _client
    if not os.getenv("OPENAI_API_KEY"):
        raise LLMUnavailable("OPENAI_API_KEY가 설정되지 않았어요")
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def ask_json(system: str, user: str) -> dict:
    """LLM에게 JSON으로 답하게 해요. (테스트에서는 이 함수를 가짜로 바꿔 끼워요)"""
    res = await _llm().chat.completions.create(
        model=MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return json.loads(res.choices[0].message.content or "{}")


# ---------------------------------------------------------------- 1) 계획
PLAN_SYSTEM = """너는 가정식 레시피의 건강 안전성을 확인하려고 PubMed 검색 계획을 세우는 도우미야.
레시피 재료와 가족 구성원(익명 ID)의 질환·신체 특성을 보고, 실제로 논문으로 확인할 가치가 있는
'식재료 × 건강 문제' 조합을 최대 {max_pairs}개 골라.
- 영향이 클 것 같은 조합을 먼저 골라 (예: 고혈압 × 간장/된장의 나트륨, 당뇨 × 흰쌀, 통풍 × 고기·생선의 퓨린, 신장질환 × 칼륨 많은 채소).
- 식재료가 아니라 그 안의 성분(sodium, purines, potassium 등)으로 찾는 게 나으면 ingredient_en에 성분을 써.
- ingredient_en, concern_en은 PubMed MeSH에 가까운 짧은 영어 용어로 써. 검색 연산자는 쓰지 마.
- concern_en은 주어진 영어 용어를 그대로 써.
- 건강 문제가 없으면 pairs를 빈 배열로 둬.
JSON으로만 답해: {{"pairs":[{{"ingredient_ko":"","ingredient_en":"","concern_ko":"","concern_en":"","member_ids":["M1"]}}]}}"""


async def plan(recipe: dict, members: list[dict]) -> list[dict]:
    concerns = {c for m in members for c in m["concerns"]}
    if not concerns:
        return []
    user = json.dumps({
        "recipe": {"title": recipe.get("title"), "ingredients": recipe.get("ingredients", [])},
        "members": [{"id": m["id"], "age": m.get("age"), "concerns": [
            {"ko": c, "en": CONCERN_EN.get(c, c)} for c in m["concerns"]]} for m in members],
    }, ensure_ascii=False)
    out = await ask_json(PLAN_SYSTEM.format(max_pairs=MAX_PAIRS), user)
    valid_ids = {m["id"] for m in members}
    pairs = []
    for p in out.get("pairs", [])[:MAX_PAIRS]:
        if not (p.get("ingredient_en") and p.get("concern_en")):
            continue
        p["member_ids"] = [i for i in p.get("member_ids", []) if i in valid_ids]
        pairs.append(p)
    return pairs


# ---------------------------------------------------------------- 3) 생성
REPORT_SYSTEM = """너는 가족 식사를 준비하는 사람에게 레시피 안전보고서를 써 주는 도우미야.
반드시 아래 규칙을 지켜.
1. 건강에 관한 주장은 evidence에 있는 논문 초록에 실제로 쓰인 내용만 써. 초록에 없는 내용은 지어내지 마.
2. 각 항목에는 근거가 된 논문의 pmid를 1개 이상 붙여. evidence에 없는 pmid는 절대 쓰지 마.
3. 근거가 약하거나 관련이 적으면 level을 "참고"로 두고, 연구 결과가 엇갈리면 그렇다고 말해.
4. 진단·처방처럼 단정하지 마. "~할 수 있어요", "~를 줄이는 걸 고려해 보세요"처럼 써.
5. 쉬운 한국어 존댓말(해요체)로, 항목마다 2문장 이내로 써.
6. 조리 순서(cooking_plan)는 한 냄비로 같이 만들다가 누구 몫을 언제 덜어 따로 조리할지 순서대로 정리해.
   간·양념은 마지막에 넣고 그 전에 덜어내는 식으로, 따로 냄비를 쓰는 건 꼭 필요할 때만 제안해.
7. 검색했는데 근거를 못 찾은 조합은 no_evidence에 넣어.
JSON으로만 답해:
{"summary":"한두 문장 요약",
 "items":[{"member_ids":["M1"],"ingredient":"재료(한국어)","concern":"건강 문제(한국어)",
           "level":"주의|참고|도움","finding":"논문이 말하는 내용","advice":"조리·섭취 조언","pmids":["123"]}],
 "cooking_plan":[{"text":"조리 단계","member_ids":["M1"]}],
 "no_evidence":["재료 × 건강 문제"]}"""


async def write(recipe: dict, members: list[dict], pairs: list[dict], evidence: dict[str, dict]) -> dict:
    user = json.dumps({
        "recipe": recipe,
        "members": [{"id": m["id"], "age": m.get("age"), "concerns": m["concerns"],
                     "allergies": m.get("allergies", [])} for m in members],
        "searched_pairs": [{"ingredient": p.get("ingredient_ko") or p["ingredient_en"],
                            "concern": p.get("concern_ko") or p["concern_en"],
                            "pmids": p.get("pmids", [])} for p in pairs],
        "evidence": [{k: e[k] for k in ("pmid", "title", "year", "types", "abstract")} for e in evidence.values()],
    }, ensure_ascii=False)
    return await ask_json(REPORT_SYSTEM, user)


# ---------------------------------------------------------------- 전체 흐름
LEVELS = ("주의", "참고", "도움")


async def build_report(recipe: dict, raw_members: list[dict]) -> dict:
    # 이름 → 익명 ID (응답을 돌려줄 때 다시 이름으로 바꿔요)
    members, names = [], {}
    for i, m in enumerate(raw_members, 1):
        mid = f"M{i}"
        names[mid] = (m.get("name") or f"구성원 {i}").strip()[:20]
        members.append({
            "id": mid, "age": m.get("age"),
            "allergies": [a for a in m.get("allergies", []) if a != "알레르기 없음"],
            "concerns": [c for c in (m.get("conditions", []) + m.get("traits", [])) if c],
        })

    pairs = await plan(recipe, members)

    evidence: dict[str, dict] = {}
    if pairs:
        async with httpx.AsyncClient(headers={"User-Agent": pubmed.TOOL}) as client:
            for p in pairs:
                p["pmids"] = await pubmed.search(client, p["ingredient_en"], p["concern_en"])
            all_ids = [i for p in pairs for i in p["pmids"]]
            evidence = await pubmed.fetch(client, all_ids)

    if not pairs:
        draft = {"summary": "가족 프로필에 입력된 질환·신체 특성이 없어서 논문 검색을 하지 않았어요.",
                 "items": [], "cooking_plan": [], "no_evidence": []}
    elif not evidence:
        draft = {"summary": "이 레시피와 가족 건강 상태에 관한 논문을 찾지 못했어요.", "items": [], "cooking_plan": [],
                 "no_evidence": [f'{p.get("ingredient_ko") or p["ingredient_en"]} × {p.get("concern_ko") or p["concern_en"]}' for p in pairs]}
    else:
        draft = await write(recipe, members, pairs, evidence)

    # ---- 4) 검증: 실제로 검색된 논문만 근거로 인정하고, 이름을 되돌려요
    def who(ids):
        return [names[i] for i in ids if i in names]

    items, used = [], set()
    for it in draft.get("items", []):
        pmids = [str(p) for p in it.get("pmids", []) if str(p) in evidence]
        if not pmids:
            continue                                    # 근거 없는 주장은 보여주지 않아요
        used.update(pmids)
        items.append({
            "members": who(it.get("member_ids", [])),
            "ingredient": str(it.get("ingredient", "")),
            "concern": str(it.get("concern", "")),
            "level": it.get("level") if it.get("level") in LEVELS else "참고",
            "finding": str(it.get("finding", "")),
            "advice": str(it.get("advice", "")),
            "pmids": pmids,
        })

    return {
        "recipe": recipe.get("title"),
        "summary": str(draft.get("summary", "")),
        "items": items,
        "cooking_plan": [{"text": str(s.get("text", "")), "members": who(s.get("member_ids", []))}
                         for s in draft.get("cooking_plan", []) if s.get("text")],
        "no_evidence": [str(x) for x in draft.get("no_evidence", [])],
        "searched": [{"ingredient": p.get("ingredient_ko") or p["ingredient_en"],
                      "concern": p.get("concern_ko") or p["concern_en"],
                      "query": pubmed.build_term(p["ingredient_en"], p["concern_en"]),
                      "found": len(p.get("pmids", []))} for p in pairs],
        "references": [evidence[p] for p in evidence if p in used],
        "model": MODEL,
        "ai_generated": True,
        "disclaimer": DISCLAIMER,
    }
