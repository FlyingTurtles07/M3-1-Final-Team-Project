"""FR-08 동의·철회. 동의 이력은 쌓기만 하고(수정·삭제 없음), 현재 상태는 항목별 가장 최근 기록이에요."""
from fastapi import APIRouter, Depends

from ..config import get_settings
from ..constants import CONSENT_TYPES, SERVICE_CONSENTS
from ..deps import get_current_user, get_store
from ..schemas import ConsentEvent, ConsentState, ConsentStatus, ConsentUpdate
from ..store import CurrentUser, Store

router = APIRouter(prefix="/api/consents", tags=["동의 (FR-08)"])


async def _status(user: CurrentUser, store: Store) -> ConsentStatus:
    current = {r["consent_type"]: r for r in await store.current_consents(user)}
    states = {
        t: ConsentState(
            granted=bool(current[t]["granted"]) if t in current else False,
            updated_at=current[t]["created_at"] if t in current else None,
            policy_version=current[t]["policy_version"] if t in current else None,
        )
        for t in CONSENT_TYPES
    }
    return ConsentStatus(
        policy_version=get_settings().policy_version,
        consents=states,
        can_use_service=all(states[t].granted for t in SERVICE_CONSENTS),
    )


@router.get("", response_model=ConsentStatus, summary="내 동의 현황")
async def get_consents(user: CurrentUser = Depends(get_current_user), store: Store = Depends(get_store)):
    return await _status(user, store)


@router.post("", response_model=ConsentStatus, summary="동의 또는 철회 기록하기")
async def update_consents(body: ConsentUpdate, user: CurrentUser = Depends(get_current_user), store: Store = Depends(get_store)):
    """items 의 granted=true 는 동의, false 는 철회예요. 이력에 새 줄이 추가되고 현재 상태가 바뀌어요.

    철회하면 해당 정보의 입력·조회가 막혀요. (건강정보 철회 → 가족 프로필 저장·조회 불가, 삭제는 가능)
    """
    version = get_settings().policy_version
    rows = [{"consent_type": i.consent_type, "granted": i.granted, "policy_version": version} for i in body.items]
    await store.add_consents(user, rows)
    return await _status(user, store)


@router.get("/history", response_model=list[ConsentEvent], summary="동의·철회 이력 (최근 200건)")
async def consent_history(user: CurrentUser = Depends(get_current_user), store: Store = Depends(get_store)):
    return await store.consent_history(user)
