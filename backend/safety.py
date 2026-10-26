"""레시피 안전 검사: 알레르기 · 당뇨식 · 저염식.

판정
- pass(통과): 가족 알레르기 성분이 없고, 저염식 가족이 있으면 1인분 나트륨이 기준 이하
  * 당뇨식 가족이 있으면 기준값 확정 전이라 항상 hold (레시피 추천 정책 DM-01·DM-04)
- hold(확인 필요): 알레르기 성분이 들어 있거나(분기점에서 따로 덜어야 해요), 기준을 넘거나, 수치를 확인할 수 없음
  * 유동식·이유식은 자동 검증 범위 밖이라 전문가 확인 전까지 hold
화면에는 판정 결과에 맞는 문구만 보여주고, 자세한 사유(reasons)는 운영 기록용이에요.

수치 출처
- MFDS_API_KEY(공공데이터포털 식품영양성분DB)가 있으면 그 값을, 없으면 아래 기본 수치(임시값)를 써요.
- [검토] 기준값(LIMITS)과 기본 수치는 전문가 확정 전 임시값이에요.
- 식약처 API는 FoodNtrCpntDbInfo03 (2026-10 확인: AMT_NUM13=나트륨 mg, AMT_NUM7=당류 g, 100g당).
  원재료 '생것' 항목만 쓰고, 간장·두부처럼 생것이 없는 재료는 기본 수치를 써요.
"""
import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

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
    "후추": (40, 0.6), "깨": (10, 0.3), "들기름": (0, 0), "맛술": (300, 20), "식초": (5, 0.5), "물엿": (20, 70),
    "양조간장": (5700, 3), "생강": (13, 1.7), "청주": (5, 3), "애호박전용부침가루": (800, 2), "밀가루": (2, 0.3), "부침가루": (900, 2),
    "버섯": (5, 1.0), "느타리버섯": (5, 1.0), "팽이버섯": (5, 0.2), "새송이버섯": (5, 1.0), "고추": (3, 3), "홍고추": (3, 4),
    "닭다리살": (90, 0), "돼지고기": (60, 0), "멸치육수": (300, 0), "다시마": (2500, 0), "멸치": (2000, 0),
}
# 이름이 조금 달라도 같은 재료로 찾아요 (예: "다진 마늘" → 마늘, "소고기 국거리" → 소고기)
PREFIXES = ("다진", "간", "굵은", "채썬", "송송썬", "얇게썬", "깍둑썬", "데친", "삶은", "볶은")
ALIASES = {"쇠고기": "소고기", "계란": "달걀", "파": "대파", "쪽파": "대파", "물": "정수물", "참깨": "통깨"}
# 우리 재료 이름 → 식약처 원재료 항목 이름 (생것 항목이 없거나 이름이 다른 재료)
# [검토] 종류가 여러 개인 양념은 나트륨이 더 높은 쪽(저염식 판정에 더 안전한 쪽)으로 골랐어요. 팀 확정 필요.
MFDS_NAMES = {
    "소금": "소금, 정제염",                 # 36,025mg (천일염 33,811 · 구운소금 37,556)
    "간장": "간장, 개량, 산분해",            # 5,476mg
    "진간장": "간장, 개량, 산분해",          # 5,476mg (양조 4,783)
    "양조간장": "간장, 개량, 양조",          # 4,783mg
    "국간장": "간장, 재래",                 # 7,999mg
    "된장": "된장, 재래",                   # 5,152mg (개량 4,339)
    "닭가슴살": "닭고기, 가슴, 생것",
    "닭다리살": "닭고기, 다리(넓적다리), 생것",
    "소고기 국거리": "소고기, 한우, 양지, 생것",
    "통깨": "참깨, 흰색, 볶은것",
    "깨": "참깨, 흰색, 볶은것",
    "쌀": "멥쌀, 백미, 생것",
    "현미": "멥쌀, 현미, 생것",
    "연어": "연어, 생것",
}
# 식약처에 당류 값이 비어 있지만 0으로 봐도 되는 항목 (고기·생선) [검토]
MFDS_SUGAR_ZERO = {"연어, 생것"}
LIMITS = {
    "sodium_mg_per_serving": float(os.getenv("LIMIT_SODIUM_MG", "770")),   # 저염식 1인분(한 끼) 나트륨 한도: 하루 2,300mg의 1/3 (NA-02, 임시값)
    # 당뇨식 당류·탄수화물 기준값은 전문가 확정 전이라 두지 않아요 (DM-01: 수치로 통과 판정하지 않고 확인 필요)
}
MFDS_API_KEY = os.getenv("MFDS_API_KEY", "")
MFDS_API_URL = os.getenv("MFDS_API_URL", "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03")
MFDS_NAME_FIELD = os.getenv("MFDS_NAME_FIELD", "FOOD_NM_KR")
MFDS_SODIUM_FIELD = os.getenv("MFDS_SODIUM_FIELD", "AMT_NUM13")
MFDS_SUGAR_FIELD = os.getenv("MFDS_SUGAR_FIELD", "AMT_NUM7")
MFDS_RECHECK_SEC = 600                     # 연결 안 됐을 때 상태를 다시 확인하는 간격
MFDS_FILE = Path(__file__).with_name("data") / "mfds_nutrition.json"   # 미리 받아 둔 수치 (python safety.py 로 갱신)
_cache: dict[str, tuple[float, float] | None] = {
    k: (tuple(v) if v else None) for k, v in
    (json.loads(MFDS_FILE.read_text(encoding="utf-8")) if MFDS_FILE.exists() else {}).items()
    if v or k not in MFDS_NAMES}           # 매핑을 새로 넣은 재료는 '없음'으로 저장돼 있어도 다시 찾아요
_limit = asyncio.Semaphore(4)              # 동시에 너무 많이 부르면 시간 초과가 나요
# 식약처 API 실제 연결 상태 — /api/health 에서 보여줘요
# state: unset(키 없음) · unchecked(아직 안 불러봄) · ok · error
_status: dict = {"state": "unchecked" if MFDS_API_KEY else "unset", "error": None, "checked": 0.0}


def grams(text: str) -> float | None:
    m = re.search(r"([\d,.]+)\s*(g|mL|ml)", str(text))
    return float(m.group(1).replace(",", "")) if m else None


def _set_status(error: str | None) -> None:
    """상태가 바뀔 때만 로그를 남겨요 (같은 오류를 매번 찍지 않게)"""
    state = "error" if error else "ok"
    if (state, error) != (_status["state"], _status["error"]):
        if error:
            log.warning("식약처 API 연결 안 됨 — 기본 수치(임시값)로 대신해요: %s", error)
        else:
            log.info("식약처 API 연결됨")
    _status.update(state=state, error=error, checked=time.time())


async def _request(name: str, rows: int = 100) -> list[dict]:
    """식약처 API를 불러 items를 돌려줘요 (FOOD_NM_KR은 부분 일치). 키 오류·서비스 오류면 MfdsError"""
    async with httpx.AsyncClient(timeout=20) as c:     # 응답에 보통 5초 안팎 걸려요
        r = await c.get(MFDS_API_URL, params={"serviceKey": MFDS_API_KEY, "FOOD_NM_KR": name, "type": "json", "numOfRows": rows, "pageNo": 1})
    try:
        data = r.json() or {}
    except ValueError:
        raise MfdsError(f"HTTP {r.status_code}, JSON 아닌 응답: {r.text[:120]}")
    # 키·서비스 오류는 {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {...}}} 형태로 와요
    err = (data.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader")
    if err:
        raise MfdsError(f"{err.get('errMsg')} ({err.get('returnAuthMsg')})")
    head = data.get("header") or {}
    if head.get("resultCode") not in (None, "00"):
        raise MfdsError(f"{head.get('resultCode')} {head.get('resultMsg')}")
    if r.status_code != 200:
        raise MfdsError(f"HTTP {r.status_code}")
    return ((data.get("body") or {}).get("items")) or []


class MfdsError(Exception):
    pass


def _num(v) -> float | None:
    """'7,999.000' 같은 값을 숫자로. 빈 값은 None (0으로 치지 않아요)"""
    try:
        return float(str(v).replace(",", "")) if str(v or "").strip() else None
    except ValueError:
        return None


def _pick(name: str, items: list[dict]) -> tuple[float, float] | None:
    """원재료성(DB_GRP_CM R…) 항목 중 재료명이 맨 앞에 오고 '생것'인 것, 그중 가장 단순한 이름을 골라요.
    예: 양파 → '양파, 생것' · 대파 → '파, 대파, 생것'(상위 분류 바로 뒤도 인정).
    '수제비면, 감자, 생것'처럼 다른 식품은 빼요. 생것이 없으면(간장·두부 등) 기본 수치로 넘겨요."""
    best = None
    for it in items:
        if not str(it.get("DB_GRP_CM", "")).startswith("R"):
            continue
        parts = [p.strip() for p in str(it.get(MFDS_NAME_FIELD, "")).split(",")]
        head = parts[0] == name or (len(parts) > 1 and parts[1] == name and name.endswith(parts[0]))
        if not head or "생것" not in parts:
            continue
        na, sugar = _num(it.get(MFDS_SODIUM_FIELD)), _num(it.get(MFDS_SUGAR_FIELD))
        if na is None or sugar is None:
            continue
        if best is None or len(parts) < best[0]:
            best = (len(parts), (na, sugar))
    return best[1] if best else None


def _pick_exact(target: str, items: list[dict]) -> tuple[float, float] | None:
    """MFDS_NAMES로 정해 둔 항목을 이름 그대로 찾아요"""
    for it in items:
        if str(it.get(MFDS_NAME_FIELD, "")).strip() == target and str(it.get("DB_GRP_CM", "")).startswith("R"):
            na, sugar = _num(it.get(MFDS_SODIUM_FIELD)), _num(it.get(MFDS_SUGAR_FIELD))
            if sugar is None and target in MFDS_SUGAR_ZERO:
                sugar = 0.0
            return (na, sugar) if na is not None and sugar is not None else None
    return None


async def _mfds(name: str) -> tuple[float, float] | None:
    """식약처 식품영양성분DB 원재료 항목에서 100g당 (나트륨, 당류)를 찾아요 (정상 응답만 캐시)"""
    if name in _cache:
        return _cache[name]
    if _status["state"] == "error" and time.time() - _status["checked"] < MFDS_RECHECK_SEC:
        return None                        # 연결 안 된 동안은 재료마다 부르지 않아요
    target = MFDS_NAMES.get(name)
    try:
        async with _limit:
            # 원재료 이름은 '양파, 생것' 형식이라 쉼표까지 붙여 찾아요 (FOOD_NM_KR은 부분 일치)
            items = await _request(target or name + ",", rows=20 if target else 100)
    except MfdsError as e:
        _set_status(str(e))
        return None                        # 캐시 안 함 — 키가 승인되면 재시작 없이 바로 쓰여요
    except httpx.HTTPError as e:           # 시간 초과 등 일시 오류는 이 재료만 기본 수치로 (상태는 그대로)
        log.warning("식약처 API 조회 실패(%s): %s", type(e).__name__, name)
        return None
    _set_status(None)
    val = _pick_exact(target, items) if target else _pick(name, items)
    if target and val is None:
        log.warning("식약처에서 정해 둔 항목을 찾지 못했어요: %s → %s", name, target)
    _cache[name] = val
    return val


async def mfds_status() -> dict:
    """연결 상태. 확인한 적 없거나 오류 뒤 일정 시간이 지났으면 한 번 불러서 확인해요"""
    if _status["state"] == "unchecked" or (_status["state"] == "error" and time.time() - _status["checked"] > MFDS_RECHECK_SEC):
        try:
            await _request("양파,", rows=1)
            _set_status(None)
        except (MfdsError, httpx.HTTPError) as e:
            _set_status(str(e) or type(e).__name__)
    return {"state": _status["state"], "error": _status["error"]}


def _candidates(name: str) -> list[str]:
    n = name.replace(" ", "")
    out = [name, n]
    for pre in PREFIXES:
        if n.startswith(pre) and len(n) > len(pre):
            out.append(n[len(pre):])
    out += [ALIASES[x] for x in list(out) if x in ALIASES]
    first = name.split()[0] if " " in name else None     # "소고기 국거리" → 소고기
    if first:
        out.append(ALIASES.get(first, first))
    return list(dict.fromkeys(out))


async def nutrition(name: str) -> tuple[float, float] | None:
    """식약처 수치를 먼저 모든 이름 후보로 찾고(간마늘 → 마늘), 없으면 기본 수치(임시값)"""
    cands = _candidates(name)
    if MFDS_API_KEY:
        for cand in cands:
            v = await _mfds(cand)
            if v is not None:
                return v
    for cand in cands:
        if cand in BASE_NUTRITION:
            return BASE_NUTRITION[cand]
    return None


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
        found = await asyncio.gather(*(nutrition(name) for name, _a, _w in items))   # 재료를 동시에 조회해요
        for (name, _amount, weight), n in zip(items, found):
            g = grams(weight)
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
        if "당뇨식" in conds:   # 기준값 보류 중이라 수치와 상관없이 확인 필요 (계산값은 기록용)
            hold(f"당뇨식 기준값 확정 전 (1인분 당류 {sugar / servings:.1f}g)")
    return {"result": result, "allergyHits": hits, "reasons": reasons}


async def _prefetch() -> None:
    """기본 레시피·기본 수치에 나오는 재료를 식약처 API에서 미리 받아 data/mfds_nutrition.json 에 저장해요.
    식약처 서버가 느려서(1건 5초 안팎) 실시간 조회 대신 이 파일을 먼저 써요. 시간 초과는 3번까지 다시 해요."""
    from recipes import POOL
    names = set(BASE_NUTRITION)
    for r in POOL:
        for name, _a, _w in (r.get("ing") or []) + ((r.get("sauce") or {}).get("items") or []):
            names.update(_candidates(name))
    for _ in range(3):                     # 식약처 서버가 느려서 첫 확인이 시간 초과될 때가 있어요
        _status["state"] = "unchecked"
        if (await mfds_status())["state"] == "ok":
            break
    else:
        sys.exit(f"식약처 API 연결 안 됨: {_status['error']}")
    todo = sorted(n for n in names if n not in _cache)
    for attempt in range(3):
        await asyncio.gather(*(_mfds(n) for n in todo))
        todo = [n for n in todo if n not in _cache]
        if not todo:
            break
    data = {k: (list(v) if v else None) for k, v in sorted(_cache.items())}
    MFDS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    found = sum(v is not None for v in data.values())
    print(f"저장: {MFDS_FILE.name} — {len(data)}개 중 식약처 수치 {found}개, 생것 항목 없음(기본 수치 사용) {len(data) - found}개")
    if todo:
        print("조회 실패(다음에 다시 실행하세요):", ", ".join(todo))


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    MFDS_API_KEY = os.getenv("MFDS_API_KEY", "")
    _status["state"] = "unchecked" if MFDS_API_KEY else "unset"
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_prefetch())
