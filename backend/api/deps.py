"""요청마다 쓰는 의존성: 로그인 확인, 동의 확인, 저장소."""
import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .store import CurrentUser, Store, SupabaseStore

bearer = HTTPBearer(auto_error=False)


def get_store(request: Request) -> Store:
    return SupabaseStore(request.app.state.http, get_settings())


async def get_current_user(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> CurrentUser:
    """Authorization: Bearer <Supabase 액세스 토큰> 을 Supabase Auth에 물어 확인해요. (서명 방식과 무관하게 항상 정확)"""
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(401, "로그인이 필요해요.", headers={"WWW-Authenticate": "Bearer"})
    s = get_settings()
    if not s.supabase_url or not s.supabase_anon_key:
        raise HTTPException(503, "서버 설정(SUPABASE_URL, SUPABASE_ANON_KEY)이 비어 있어요.")
    try:
        r = await request.app.state.http.get(
            f"{s.supabase_url}/auth/v1/user",
            headers={"apikey": s.supabase_anon_key, "Authorization": f"Bearer {creds.credentials}"},
        )
    except httpx.HTTPError:
        raise HTTPException(503, "인증 서버에 연결하지 못했어요.") from None
    if r.status_code in (401, 403):
        raise HTTPException(401, "로그인이 만료되었거나 올바르지 않아요. 다시 로그인해 주세요.", headers={"WWW-Authenticate": "Bearer"})
    if r.status_code != 200:
        raise HTTPException(503, "인증 서버 응답이 올바르지 않아요.")
    data = r.json()
    return CurrentUser(id=data["id"], email=data.get("email"), token=creds.credentials)


def require_consents(*needed: str):
    """필요한 동의를 모두 한 사용자만 통과시켜요. (없으면 403, 어떤 동의가 빠졌는지 알려 줘요)"""

    async def dependency(user: CurrentUser = Depends(get_current_user), store: Store = Depends(get_store)) -> CurrentUser:
        granted = {r["consent_type"] for r in await store.current_consents(user) if r["granted"]}
        missing = [t for t in needed if t not in granted]
        if missing:
            raise HTTPException(403, {"code": "consent_required", "missing": missing, "message": "필요한 동의가 없어요."})
        return user

    return dependency
