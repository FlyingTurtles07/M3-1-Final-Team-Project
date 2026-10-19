"""냉장고·영수증 사진에서 식재료 이름 찾기.

- 사진 원본은 메모리에서만 쓰고 저장하지 않아요. 재료 이름만 돌려줘요.
- 영수증은 신선식품만 뽑고 구매 장소·가격·카드번호는 읽지 않아요.
- OPENAI_API_KEY가 없거나 실패하면 예시 결과를 돌려줘요 (source='sample').
"""
import base64
import json
import logging
import os

from recipes import PROCESSED

log = logging.getLogger("hansang.vision")
MODEL = os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

SAMPLE = {
    "fridge": {"items": ["두부", "애호박", "달걀", "대파", "당근"], "suspect": ["새우"], "dropped": ["케첩"]},
    "receipt": {"items": ["양파", "소고기", "시금치"], "suspect": [], "dropped": ["햄", "간장"]},
}

PROMPT = """사진 속 식재료를 찾아 줘. 사진 종류: {kinds}
- 냉장고 사진: 보이는 신선 식재료 이름을 한국어 일반 명사로 (예: 두부, 애호박, 달걀, 대파).
- 영수증 사진: 구매한 신선식품 이름만. 가게 이름·가격·카드번호·날짜는 절대 적지 마.
- 확실하지 않은 재료는 suspect에, 가공식품·양념(햄, 소시지, 케첩, 간장, 된장, 라면 등)은 dropped에 넣어.
- 사람 얼굴이나 개인정보는 무시해.
JSON만 답해: {{"items":["두부"],"suspect":["새우"],"dropped":["케첩"]}}"""


def _sample(kinds: list[str]) -> dict:
    out = {"items": [], "suspect": [], "dropped": [], "source": "sample"}
    for k in kinds:
        for key in ("items", "suspect", "dropped"):
            for x in SAMPLE.get(k, {}).get(key, []):
                if x not in out[key]:
                    out[key].append(x)
    return out


def _clean(names) -> list[str]:
    out = []
    for n in names or []:
        n = str(n).strip().replace(" ", "")[:12]
        if n and n not in out:
            out.append(n)
    return out[:30]


async def analyze(photos: list[tuple[str, bytes, str]]) -> dict:
    """photos: [(kind: 'fridge'|'receipt', bytes, mime)]"""
    kinds = [k for k, _, _ in photos]
    if not os.getenv("OPENAI_API_KEY"):
        return _sample(kinds)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(timeout=60)
        content = [{"type": "text", "text": PROMPT.format(kinds=", ".join("냉장고" if k == "fridge" else "영수증" for k in kinds))}]
        for _kind, data, mime in photos:
            b64 = base64.b64encode(data).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"}})
        res = await client.chat.completions.create(
            model=MODEL, response_format={"type": "json_object"}, temperature=0,
            messages=[{"role": "user", "content": content}],
        )
        data = json.loads(res.choices[0].message.content or "{}")
        items, suspect, dropped = _clean(data.get("items")), _clean(data.get("suspect")), _clean(data.get("dropped"))
        # 가공식품·양념은 재고에서 빼요
        dropped += [x for x in items + suspect if x in PROCESSED and x not in dropped]
        items = [x for x in items if x not in PROCESSED]
        suspect = [x for x in suspect if x not in PROCESSED and x not in items]
        return {"items": items, "suspect": suspect, "dropped": dropped, "source": "ai"}
    except Exception:
        log.exception("사진 재료 인식 실패")
        out = _sample(kinds)
        out["source"] = "sample-fallback"
        return out
