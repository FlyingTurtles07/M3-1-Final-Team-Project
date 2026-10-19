"""FR-08 계정과 데이터 삭제."""
from fastapi import APIRouter, Depends, HTTPException, Response

from ..deps import get_current_user, get_store
from ..store import CurrentUser, Store

router = APIRouter(prefix="/api/account", tags=["동의 (FR-08)"])


@router.delete("", status_code=204, summary="계정과 모든 데이터 삭제 (되돌릴 수 없어요)")
async def delete_account(confirm: bool = False, user: CurrentUser = Depends(get_current_user), store: Store = Depends(get_store)):
    """?confirm=true 를 붙여야 실행돼요. 실수로 호출되는 것을 막는 장치예요.

    Supabase 사용자 계정을 지우면 동의 이력·가족 구성원 등 내 모든 행이 함께 지워져요(DB의 on delete cascade).
    """
    if not confirm:
        raise HTTPException(400, {"code": "confirm_required", "message": "삭제하려면 confirm=true 가 필요해요."})
    await store.delete_account(user)
    return Response(status_code=204)
