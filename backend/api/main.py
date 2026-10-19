"""온가족 한상 백엔드 API (FastAPI) — 로그인·동의·가족 프로필 담당.

실행 (저장소 맨 위 폴더에서):
    uvicorn backend.api.main:app --reload
API 문서(자동 생성): http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .crypto import CryptoError
from .routers import account, consents, members
from .store import StoreError

log = logging.getLogger("hansang")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        app.state.http = client
        yield


app = FastAPI(title="온가족 한상 API", version="0.1.0", lifespan=lifespan)

# 로그인은 쿠키가 아니라 Authorization 헤더(Bearer 토큰)로 하므로 credentials 는 허용하지 않아요.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(consents.router)
app.include_router(members.router)
app.include_router(account.router)


@app.exception_handler(StoreError)
async def store_error_handler(request: Request, exc: StoreError):
    return JSONResponse(status_code=502, content={"detail": {"code": "db_error", "message": "저장소에 문제가 있어요. 잠시 후 다시 시도해 주세요."}})


@app.exception_handler(CryptoError)
async def crypto_error_handler(request: Request, exc: CryptoError):
    log.error("암호화 오류: %s", exc)
    return JSONResponse(status_code=500, content={"detail": {"code": "crypto_error", "message": "서버 설정에 문제가 있어요."}})


@app.get("/health", tags=["상태"], summary="서버 상태 (Render 상태 확인용)")
@app.get("/api/health", include_in_schema=False)
async def health(request: Request, deep: bool = False):
    """기본은 가볍게 서버가 떠 있는지만 확인해요. ?deep=true 를 붙이면 Supabase 연결까지 확인해요."""
    s = get_settings()
    body = {
        "ok": True,
        "supabase_configured": bool(s.supabase_url and s.supabase_anon_key),
        "encryption_configured": bool(s.health_data_key),
        "policy_version": s.policy_version,
    }
    if deep:
        try:
            r = await request.app.state.http.get(f"{s.supabase_url}/auth/v1/health", headers={"apikey": s.supabase_anon_key})
            body["supabase"] = "ok" if r.status_code == 200 else f"error({r.status_code})"
        except (httpx.HTTPError, httpx.InvalidURL):
            body["supabase"] = "unreachable"
        if body["supabase"] != "ok":
            body["ok"] = False
            return JSONResponse(status_code=503, content=body)
    return body
