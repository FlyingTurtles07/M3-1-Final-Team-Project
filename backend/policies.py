"""레시피 추천 정책 22종 + 레시피 지침 → AI 레시피 지시문에 덧붙이는 글.

- 원본: docs/레시피_추천_정책_22종.md, docs/recipe_guideline.md
  고치면 `python upload_policies.py` 로 data/recipe_policies.json 을 다시 만들고 Firestore(recipe_policies)에 올려요.
- 서버는 Firestore에서 읽고(10분 캐시), 못 읽으면 data/recipe_policies.json 을 써요.
- AI에는 가족 이름·나이를 보내지 않고, 가족 전체에 해당하는 알레르기·식사 조건과 그 정책 글만 보내요.
"""
import json
import logging
import time
from pathlib import Path

log = logging.getLogger("hansang.policies")

BUNDLE = Path(__file__).resolve().parent / "data" / "recipe_policies.json"
CACHE_SECONDS = 600
_cache: dict = {"at": 0.0, "data": None}

# 가족 프로필 선택지(직접 입력 포함) → 정책 코드. 넓은 분류는 보수적으로 모두 적용해요.
ALLERGY_MAP = {
    "달걀": ["AL-01"], "계란": ["AL-01"], "알류": ["AL-01"],
    "우유": ["AL-02"],
    "견과류": ["AL-03", "AL-09"], "땅콩": ["AL-03"], "호두": ["AL-09"], "잣": ["AL-09"],
    "대두": ["AL-04"], "콩": ["AL-04"],
    "밀": ["AL-05"],
    "메밀": ["AL-06"],
    "갑각류": ["AL-07"], "새우": ["AL-07"], "게": ["AL-07"],
    "고등어": ["AL-08"], "생선": ["AL-08"],
    "조개류": ["AL-10"], "조개": ["AL-10"], "굴": ["AL-10"], "전복": ["AL-10"], "홍합": ["AL-10"], "오징어": ["AL-10"],
}
CONDITION_MAP = {
    "당뇨식": ["DM-01", "DM-02", "DM-03", "DM-04"],
    "저염식": ["NA-01", "NA-02", "NA-03", "NA-04"],
}
ALWAYS = ["QT-01"]
NONE_VALUES = {"알레르기 없음", "없음", "일반식", "해당사항없음"}


def _load_bundle() -> dict:
    try:
        return json.loads(BUNDLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.exception("정책 파일을 읽지 못했어요: %s", BUNDLE)
        return {}


def load() -> dict:
    """{"common": 글, "guideline": 글, "policies": {코드: {"text", "active", ...}}}"""
    if _cache["data"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    data = None
    try:
        import fstore
        data = fstore.get_policies()
    except Exception:
        log.exception("Firestore 정책을 읽지 못해서 내장 파일을 써요")
    if not data or not data.get("policies"):
        data = _load_bundle()
    _cache.update(at=time.time(), data=data)
    return data


def codes_for(members: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """(적용할 정책 코드, 가족 알레르기 목록, 가족 식사 조건 목록)"""
    codes, allergies, conds = list(ALWAYS), [], []
    for m in members:
        for a in m.get("allergies") or []:
            a = str(a).strip()
            if not a or a in NONE_VALUES:
                continue
            if a not in allergies:
                allergies.append(a)
            for c in ALLERGY_MAP.get(a, []):
                if c not in codes:
                    codes.append(c)
        for c in m.get("conditions") or []:
            c = str(c).strip()
            if not c or c in NONE_VALUES:
                continue
            if c not in conds:
                conds.append(c)
            for code in CONDITION_MAP.get(c, []):
                if code not in codes:
                    codes.append(code)
    return codes, allergies, conds


def prompt_block(members: list[dict]) -> str:
    """AI 지시문에 덧붙일 정책 글. 정책을 못 읽으면 빈 글이에요 (기존 지시문만으로 추천)."""
    data = load()
    pol = data.get("policies") or {}
    if not pol:
        return ""
    codes, allergies, conds = codes_for(members)
    parts = ["아래 규칙을 지켜서 레시피를 만들어. 규칙과 위 지시가 부딪히면 규칙을 따르되, 답의 JSON 형식은 아래 형식 그대로 써."]
    fam = []
    if allergies:
        fam.append("알레르기·회피 재료: " + ", ".join(allergies))
    if conds:
        fam.append("식사 조건: " + ", ".join(conds))
    parts.append("[우리 가족 조건 (구성원 전체)]\n" + ("\n".join("- " + x for x in fam) if fam else "- 없음"))
    for key in ("common", "guideline"):
        if data.get(key):
            parts.append(data[key])
    for code in codes:
        p = pol.get(code)
        if p and p.get("active", True) and p.get("text"):
            parts.append(p["text"])
    return "\n\n".join(parts)
