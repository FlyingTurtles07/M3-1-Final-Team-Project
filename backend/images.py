"""AI 레시피 요리 사진 만들기 (gpt-image-2).

- AI가 만든 레시피에만 그려요. 같은 요리 이름은 DB에 저장해 두고 다시 그리지 않아요 (크레딧 절약).
- 코디세이 그림 API: POST {서버}/api/v1/images
  응답의 url은 웹 로그인 전용이라, response_format=b64_json으로 그림 자체를 받아요.
- 받은 그림은 640px JPEG로 줄여서 저장해요.
- IMAGE_ENABLED=false 이거나 키가 없으면 그리지 않아요 (화면은 예시 사진을 그대로 써요).
"""
import asyncio
import base64
import io
import logging
import os
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger("hansang.images")

IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
MAX_PER_HOUR = int(os.getenv("IMAGE_MAX_PER_HOUR", "40"))   # 한 시간에 새로 그리는 최대 장수 (비용 안전장치)
_recent: list[float] = []
_locks: dict[str, asyncio.Lock] = {}


def enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("IMAGE_ENABLED", "true").lower() != "false"


def _api_url() -> str:
    url = os.getenv("IMAGE_API_URL", "").strip()
    if url:
        return url
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    u = urlparse(base)
    if "openai.com" in u.netloc:
        return "https://api.openai.com/v1/images/generations"
    return f"{u.scheme}://{u.netloc}/api/v1/images"     # 코디세이 미디어 API


def title_key(title: str) -> str:
    return "".join(title.split())[:60]


def lock_for(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _find_b64(data) -> str | None:
    """응답 어디에 있든 그림(base64)을 찾아요"""
    if isinstance(data, dict):
        for k in ("b64_json", "b64", "base64", "imageBase64"):
            if isinstance(data.get(k), str) and len(data[k]) > 100:
                return data[k]
        for v in data.values():
            found = _find_b64(v)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _find_b64(v)
            if found:
                return found
    elif isinstance(data, str) and data.startswith("data:image") and "," in data:
        return data.split(",", 1)[1]
    return None


def _shrink(raw: bytes) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((640, 640))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()


def _prompt(title: str, ingredients: list[str]) -> str:
    ing = ", ".join(ingredients[:6])
    return (f"Korean home-cooked dish '{title}'" + (f" made with {ing}" if ing else "") +
            ", served for a family of four on a warm wooden dining table, natural window light, "
            "realistic appetizing food photography, top-down 45 degree angle, no people, no text, no watermark")


async def generate(title: str, ingredients: list[str]) -> bytes | None:
    if not enabled():
        return None
    now = time.time()
    while _recent and now - _recent[0] > 3600:
        _recent.pop(0)
    if len(_recent) >= MAX_PER_HOUR:
        log.warning("이번 시간에 그릴 수 있는 사진 수(%d)를 다 썼어요", MAX_PER_HOUR)
        return None
    _recent.append(now)
    body = {"model": IMAGE_MODEL, "prompt": _prompt(title, ingredients), "size": "1024x1024", "n": 1, "response_format": "b64_json"}
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("IMAGE_TIMEOUT", "120"))) as c:
            r = await c.post(_api_url(), json=body, headers={"Authorization": "Bearer " + os.getenv("OPENAI_API_KEY", "")})
        if r.status_code != 200:
            log.warning("요리 사진 만들기 실패 %s: %s", r.status_code, r.text[:200])
            return None
        b64 = _find_b64(r.json())
        if not b64:
            log.warning("요리 사진 응답에 그림이 없어요: %s", r.text[:200])
            return None
        return await asyncio.to_thread(_shrink, base64.b64decode(b64))
    except Exception:
        log.exception("요리 사진 만들기 실패")
        return None
