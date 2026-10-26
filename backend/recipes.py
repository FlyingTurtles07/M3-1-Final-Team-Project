"""레시피 추천.

- 추천은 '냉장고 재료'로 3개를 골라요. AI 추천에는 가족 전체의 알레르기·식사 조건과 해당 정책(policies.py)을 함께 넣어요.
  (이름·나이는 보내지 않아요. 구성원별 차이는 화면에서 고른 레시피의 '분기점'으로 안내해요)
- OPENAI_API_KEY가 있으면 AI가 레시피를 만들고, 없거나 실패하면 기본 레시피(data/recipes.json)에서 골라요.
- 레시피 형식: ing(재료 [이름, 양, 무게]) / sauce(양념) / steps(만드는법) / adds(단계별로 들어가는 재료) / saltAt(간하는 단계)
"""
import hashlib
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("hansang.recipes")
DATA = Path(__file__).with_name("data")
POOL: list[dict] = json.loads((DATA / "recipes.json").read_text(encoding="utf-8"))
ING_ALLERGEN: dict[str, list[str]] = json.loads((DATA / "ing_allergen.json").read_text(encoding="utf-8"))
ING_ALLERGEN.update({
    "계란": ["달걀"], "메추리알": ["달걀"], "마요네즈": ["달걀"], "버터": ["우유"], "생크림": ["우유"], "요거트": ["우유"],
    "게": ["갑각류"], "꽃게": ["갑각류"], "고등어": ["생선"], "멸치": ["생선"], "참치": ["생선"], "대구": ["생선"],
    "빵": ["밀"], "부침가루": ["밀"], "튀김가루": ["밀"], "아몬드": ["견과류"], "잣": ["견과류"], "캐슈넛": ["견과류"],
    "두유": ["대두"], "콩": ["대두"], "유부": ["대두"], "고추장": ["대두", "밀"], "국간장": ["대두", "밀"], "진간장": ["대두", "밀"],
})
# 가공식품·양념은 냉장고 재고(추천 기준 재료)에서 빼요
PROCESSED = {"간장", "국간장", "진간장", "된장", "고추장", "소금", "설탕", "식용유", "참기름", "들기름", "식초", "후추", "맛술",
             "물엿", "올리고당", "케첩", "마요네즈", "굴소스", "햄", "스팸", "소시지", "베이컨", "어묵", "라면", "치즈", "만두",
             "간마늘", "통깨", "고춧가루", "정수물", "물"}
# AI가 만든 레시피에 붙일 예시 사진 (화면 쪽 food/ 폴더)
PHOTO_HINTS = [("죽", "food/chicken-porridge.jpg"), ("뭇국", "food/beef-radish-soup.jpg"), ("무국", "food/beef-radish-soup.jpg"),
               ("된장", "food/zucchini-tofu-soup.jpg"), ("국", "food/zucchini-tofu-soup.jpg"), ("찌개", "food/zucchini-tofu-soup.jpg"),
               ("조림", "food/braised-tofu.jpg"), ("비빔", "food/tofu-bibimbap.jpg"), ("덮밥", "food/salmon-brown-rice.jpg"),
               ("연어", "food/salmon-brown-rice.jpg"), ("오믈렛", "food/veggie-omelet.jpg"), ("말이", "food/carrot-omelet-roll.jpg"),
               ("찜", "food/tofu-zucchini-egg.jpg"), ("볶음", "food/chicken-veggie-stirfry.jpg"), ("닭", "food/chicken-veggie-stirfry.jpg"),
               ("두부", "food/braised-tofu.jpg"), ("달걀", "food/zucchini-egg-stirfry.jpg")]
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def recipe_allergens(r: dict) -> list[str]:
    out: list[str] = []
    for step in r.get("adds") or []:
        for ing in step:
            for a in ING_ALLERGEN.get(ing, []):
                if a not in out:
                    out.append(a)
    return out


for _r in POOL:
    _r["allergens"] = recipe_allergens(_r)
    _r["source"] = "sample"


def rank_pool(ingredients: list[str], exclude: list[str], count: int = 3) -> list[dict]:
    """냉장고 재료가 모두 있는 레시피 → 겹치는 재료가 많은 레시피 순서"""
    def score(item):
        i, r = item
        have = sum(1 for u in r["uses"] if u in ingredients)
        return (-(1 if have == len(r["uses"]) else 0), -have, i)
    cand = [(i, r) for i, r in enumerate(POOL) if r["id"] not in exclude]
    return [dict(r) for _, r in sorted(cand, key=score)[:count]]


def _guess_photo(title: str) -> str | None:
    for word, path in PHOTO_HINTS:
        if word in title:
            return path
    return None


def _item(x) -> list[str] | None:
    """재료 한 줄을 [이름, 양, 무게]로 맞춰요. AI가 [이름, 무게]처럼 두 칸만 줘도 받아요."""
    if isinstance(x, dict):
        x = [x.get("name"), x.get("amount") or x.get("weight"), x.get("weight") or x.get("amount")]
    if not isinstance(x, (list, tuple)) or not x or not str(x[0]).strip():
        return None
    name = str(x[0]).strip()
    if len(x) >= 3:
        return [name, str(x[1]), str(x[2])]
    if len(x) == 2:
        return [name, str(x[1]), str(x[1])]
    return [name, "적당량", ""]


def _clean_recipe(raw: dict, ingredients: list[str]) -> dict | None:
    """AI 응답을 화면이 쓰는 형식으로 다듬고, 형식이 틀리면 버려요"""
    try:
        title = str(raw["title"]).strip()[:40]
        steps = [str(s).strip() for s in raw["steps"] if str(s).strip()][:10]
        adds = [[str(x).strip() for x in a] for a in raw.get("adds", [])][: len(steps)]
        while len(adds) < len(steps):
            adds.append([])
        ing = [_item(x) for x in raw["ing"]]
        ing = [x for x in ing if x]
        sauce_raw = raw.get("sauce") or {}
        sauce = {"label": str(sauce_raw.get("label") or "양념"),
                 "items": [x for x in (_item(y) for y in sauce_raw.get("items", [])) if x]}
        salt_at = int(raw.get("saltAt", len(steps) - 1))
        salt_at = max(0, min(salt_at, len(steps) - 1))
        minutes = int(raw.get("minutes") or 30)
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not title or len(steps) < 2 or not ing:
        return None
    # 재료 목록에 냉장고 재료가 하나도 없으면(주재료를 빠뜨린 답) 버려요
    names = [x[0].replace(" ", "") for x in ing]
    uses = [f for f in ingredients if any(f in n for n in names)]
    if ingredients and not uses:
        return None
    uses = uses or [x[0] for x in ing if x[0] not in PROCESSED][:4]
    rid = "ai-" + hashlib.sha1(title.encode()).hexdigest()[:10]
    r = {"id": rid, "title": title, "photo": _guess_photo(title), "minutes": minutes, "servings": 4, "uses": uses,
         "ing": ing, "sauce": sauce if sauce["items"] else None, "steps": steps, "adds": adds, "saltAt": salt_at,
         "source": "ai", "aiImage": True}
    r["allergens"] = recipe_allergens(r)
    return r


PROMPT = """너는 한국 가정식 레시피를 만드는 도우미야.
냉장고 재료: {ingredients}
이미 보여준 메뉴(겹치지 않게): {exclude}
지난 식사 가족 반응(맛 취향 참고용, 비어 있으면 무시): {notes}

위 재료를 최대한 활용해서 가족이 함께 먹을 수 있는 한식 레시피 {count}개를 만들어.
- 모두 4인분(성인 1인분×4) 기준. ing·sauce의 각 줄은 꼭 [이름, 양, 무게] 세 칸으로 (예: ["무","약 1/5개","300g"]). 계량: 1컵 200mL, 1큰술 15mL, 1작은술 5mL.
- 냉장고에 없는 재료는 최소한으로(소금·간장 같은 기본 양념은 써도 돼).
- ing에는 주재료를 빠짐없이 모두 적어 (예: 소고기 무조림이면 소고기와 무를 꼭 ing에).
- 만드는법은 3~6단계, 쉬운 말투(~해요)로.
- adds: 만드는법 각 단계에서 '새로 들어가는 재료 이름' 목록 (steps와 길이가 같아야 해). 이름은 ing/sauce에 쓴 이름과 같게.
- saltAt: 간(소금·간장·된장 등)을 하는 단계 번호(0부터).
- 건강 효과를 단정하는 표현은 쓰지 마.
- 가족 반응이 있으면 맛 취향(간, 식감, 남긴 재료)을 참고해서 간을 맞추거나 재료를 바꿔도 좋아. 같은 메뉴를 다시 낼 땐 반응을 반영한 변형으로.

JSON만 답해:
{{"recipes":[{{"title":"소고기 뭇국","minutes":35,
 "ing":[["소고기 국거리","1컵","200g"],["무","약 1/5개","300g"]],
 "sauce":{{"label":"양념","items":[["소금","½작은술","3g"]]}},
 "steps":["…","…"],"adds":[["소고기"],["무"]],"saltAt":1}}]}}"""


def parse_json(text: str) -> dict:
    """AI 답에서 JSON만 꺼내요 (```json … ``` 같은 감싼 글이 있어도 괜찮게)"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return {}


async def ai_recommend(ingredients: list[str], exclude_titles: list[str], count: int = 3, notes: str = "", rules: str = "") -> list[dict]:
    if not os.getenv("OPENAI_API_KEY"):
        return []
    from openai import AsyncOpenAI
    client = AsyncOpenAI(timeout=float(os.getenv("OPENAI_TIMEOUT", "40")), max_retries=0)
    prompt = PROMPT.format(ingredients=", ".join(ingredients) or "(없음)", exclude=", ".join(exclude_titles) or "(없음)", count=count,
                           notes=("\n" + notes) if notes else "(없음)")
    if rules:   # 레시피 추천 정책(policies.py)은 JSON 형식 안내 바로 앞에 넣어요
        prompt = prompt.replace("\n\nJSON만 답해:", "\n\n" + rules + "\n\nJSON만 답해:", 1)
    # 첫 모델이 실패하거나 쓸 만한 레시피를 못 주면 다음 모델로 한 번 더 시도해요
    models = [OPENAI_MODEL] + [m.strip() for m in os.getenv("OPENAI_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",") if m.strip() and m.strip() != OPENAI_MODEL]
    for model in models:
        try:
            # temperature·JSON 모드는 쓰지 않아요 (코디세이 등 일부 OpenAI 호환 서버가 지원하지 않아요)
            res = await client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
            data = parse_json(res.choices[0].message.content or "")
            out = []
            for raw in data.get("recipes", []):
                r = _clean_recipe(raw, ingredients)
                if r and r["title"] not in exclude_titles and all(r["title"] != x["title"] for x in out):
                    out.append(r)
            if out:
                return out[:count]
            log.warning("AI(%s)가 쓸 수 있는 레시피를 주지 않았어요", model)
        except Exception as e:  # AI가 실패해도 다음 모델 → 기본 레시피로 이어서 보여줘요
            log.warning("AI 레시피 추천 실패(%s): %s", model, str(e)[:200])
    return []


def stock_only(names: list[str]) -> list[str]:
    """가공식품·양념을 뺀 냉장고 재료"""
    out = []
    for n in names:
        n = re.sub(r"\s+", "", str(n))[:20]
        if n and n not in PROCESSED and n not in out:
            out.append(n)
    return out
