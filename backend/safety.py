"""레시피 안전 검사: 알레르기 · 당뇨식 · 저염식.

판정
- pass(통과): 가족 알레르기 성분이 없고, 당뇨식·저염식 가족이 있으면 1인분 당류·나트륨이 기준 이하
- hold(확인 필요): 알레르기 성분이 들어 있거나(분기점에서 따로 덜어야 해요), 기준을 넘거나, 수치를 확인할 수 없음
  * 유동식·이유식은 자동 검증 범위 밖이라 전문가 확인 전까지 hold
화면에는 판정 결과에 맞는 문구만 보여주고, 자세한 사유(reasons)는 운영 기록용이에요.

수치 출처
- MFDS_API_KEY(공공데이터포털 식품영양성분DB)가 있으면 그 값을, 없으면 아래 기본 수치(임시값)를 써요.
- [검토] 기준값(LIMITS)과 기본 수치는 전문가 확정 전 임시값이에요.
- [검토] 식약처 API 요청 주소와 응답 필드 이름은 활용신청 후 받는 참고문서로 확인해서 환경변수로 맞춰 주세요.
"""
import logging
import os
import re

import httpx

from recipes import ING_ALLERGEN, recipe_allergens

log = logging.getLogger("hansang.safety")

# 100g당 (나트륨 mg, 당류 g) — 임시값 [검토]
BASE_NUTRITION = {
    "두부": (7, 0.6), "달걀": (140, 0.4), "애호박": (1, 2.1), "양파": (2, 4.6), "당근": (40, 4.7), "대파": (3, 2.3),
    "무": (15, 2.5), "브로콜리": (20, 1.5), "시금치": (55, 0.4), "버섯": (5, 1.0), "표고버섯": (5, 1.0), "감자": (3, 0.8),
    "닭가슴살": (50, 0), "소고기": (55, 0), "소고기 국거리": (55, 0), "간소고기": (55, 0), "연어": (60, 0), "새우": (190, 0),
    "쌀": (2, 0.1), "현미": (3, 0.7), "고구마": (15, 6), "배추": (9, 1.4), "콩나물": (6, 0.5), "청양고추": (3, 3),
    "정수물": (0, 0), "물": (0, 0), "소금": (39000, 0), "간장": (5700, 3), "진간장": (5700, 3), "국간장": (6900, 2),
    "된장": (4400, 6), "고추장": (2500, 20), "참기름": (0, 0), "식용유": (0, 0), "간마늘": (3, 1), "마늘": (3, 1),
    "통깨": (10, 0.3), "굵은고춧가루": (20, 10), "고춧가루": (20, 10), "설탕": (0, 100), "올리고당": (10, 70), "케첩": (1000, 22),
}
LIMITS = {
    "sodium_mg_per_serving": float(os.getenv("LIMIT_SODIUM_MG", "800")),   # 저염식 1인분 나트륨 한도 (임시)
    "sugar_g_per_serving": float(os.getenv("LIMIT_SUGAR_G", "10")),        # 당뇨식 1인분 당류 한도 (임시)
}
MFDS_API_KEY = os.getenv("MFDS_API_KEY", "")
MFDS_API_URL = os.getenv("MFDS_API_URL", "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo02/getFoodNtrCpntDbInq02")
MFDS_NAME_FIELD = os.getenv("MFDS_NAME_FIELD", "FOOD_NM_KR")
MFDS_SODIUM_FIELD = os.getenv("MFDS_SODIUM_FIELD", "AMT_NUM13")
MFDS_SUGAR_FIELD = os.getenv("MFDS_SUGAR_FIELD", "AMT_NUM7")
_cache: dict[str, tuple[float, float] | None] = {}


def grams(text: str) -> float | None:
    m = re.search(r"([\d,.]+)\s*(g|mL|ml)", str(text))
    return float(m.group(1).replace(",", "")) if m else None


async def _mfds(name: str) -> tuple[float, float] | None:
    """식약처 식품영양성분DB에서 이름이 정확히 같은 항목만 써요 (호출 결과는 캐시)"""
    if name in _cache:
        return _cache[name]
    val = None
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(MFDS_API_URL, params={"serviceKey": MFDS_API_KEY, "FOOD_NM_KR": name, "type": "json", "numOfRows": 10, "pageNo": 1})
            items = (((r.json() or {}).get("body") or {}).get("items")) or []
            for it in items:
                if str(it.get(MFDS_NAME_FIELD, "")).strip() == name:
                    val = (float(it.get(MFDS_SODIUM_FIELD) or 0), float(it.get(MFDS_SUGAR_FIELD) or 0))
                    break
    except Exception:
        log.warning("식약처 API 조회 실패: %s", name)
    _cache[name] = val
    return val


async def nutrition(name: str) -> tuple[float, float] | None:
    if MFDS_API_KEY:
        v = await _mfds(name)
        if v is not None:
            return v
    return BASE_NUTRITION.get(name)


def _allergy_hits(recipe: dict, members: list[dict]) -> list[str]:
    allergens = recipe.get("allergens") or recipe_allergens(recipe)
    names = [x[0] for x in (recipe.get("ing") or [])] + [x[0] for x in ((recipe.get("sauce") or {}).get("items") or [])]
    hits = []
    for m in members:
        for a in m.get("allergies") or []:
            if a in ("알레르기 없음", "없음"):
                continue
            if a in allergens or a in names or any(a in ING_ALLERGEN.get(n, []) for n in names):
                if a not in hits:
                    hits.append(a)
    return hits


async def check_recipe(recipe: dict, members: list[dict]) -> dict:
    reasons: list[str] = []
    result = "pass"

    def hold(why: str):
        nonlocal result
        reasons.append(why)
        result = "hold"

    hits = _allergy_hits(recipe, members)
    if hits:
        hold("가족 알레르기 성분 포함: " + ", ".join(hits))

    conds = {c for m in members for c in (m.get("conditions") or [])}
    if conds & {"유동식", "이유식"}:
        hold("유동식·이유식은 전문가 기준 확인 전")

    if conds & {"당뇨식", "저염식"}:
        servings = recipe.get("servings") or 4
        items = (recipe.get("ing") or []) + ((recipe.get("sauce") or {}).get("items") or [])
        sodium = sugar = 0.0
        missing = []
        for name, _amount, weight in items:
            g = grams(weight)
            n = await nutrition(name)
            if g is None or n is None:
                missing.append(name)
                continue
            sodium += n[0] * g / 100
            sugar += n[1] * g / 100
        if not items:
            hold("분량 정보 없음")
        if missing:
            hold("수치 없음: " + ", ".join(missing))
        if "저염식" in conds and sodium / servings > LIMITS["sodium_mg_per_serving"]:
            hold(f"1인분 나트륨 {sodium / servings:.0f}mg")
        if "당뇨식" in conds and sugar / servings > LIMITS["sugar_g_per_serving"]:
            hold(f"1인분 당류 {sugar / servings:.1f}g")
    return {"result": result, "allergyHits": hits, "reasons": reasons}
