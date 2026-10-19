"""FR-01 가족 프로필. 건강 정보는 서버가 암호화해서 저장하고, 내려줄 때 복호화해요."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from ..constants import MAX_MEMBERS, SERVICE_CONSENTS
from ..crypto import decrypt_json, encrypt_json
from ..deps import get_current_user, get_store, require_consents
from ..schemas import HEALTH_FIELDS, MemberIn, MemberOut
from ..store import CurrentUser, DuplicateNickname, RlsDenied, Store

router = APIRouter(prefix="/api/members", tags=["가족 프로필 (FR-01)"])

_need_consent = require_consents(*SERVICE_CONSENTS)

_CONSENT_REQUIRED = {"code": "consent_required", "missing": ["health"], "message": "건강 정보 수집·이용에 동의해야 해요."}
_DUPLICATE = {"code": "duplicate_nickname", "message": "같은 이름의 구성원이 있어요."}


def _to_row(body: MemberIn) -> dict:
    health = body.model_dump(include=set(HEALTH_FIELDS))
    return {
        "nickname": body.nickname,
        "avatar": body.avatar,
        "proxy_consent": body.proxy_consent,
        "health_enc": encrypt_json(health),
    }


def _to_out(row: dict) -> MemberOut:
    health = decrypt_json(row["health_enc"])
    return MemberOut(
        id=row["id"], nickname=row["nickname"], avatar=row.get("avatar"), proxy_consent=row["proxy_consent"],
        created_at=row["created_at"], updated_at=row["updated_at"], **health,
    )


@router.get("", response_model=list[MemberOut], summary="가족 구성원 목록")
async def list_members(user: CurrentUser = Depends(_need_consent), store: Store = Depends(get_store)):
    return [_to_out(r) for r in await store.list_members(user)]


@router.post("", response_model=MemberOut, status_code=201, summary="구성원 추가")
async def create_member(body: MemberIn, user: CurrentUser = Depends(_need_consent), store: Store = Depends(get_store)):
    if len(await store.list_members(user)) >= MAX_MEMBERS:
        raise HTTPException(409, {"code": "member_limit", "message": f"구성원은 최대 {MAX_MEMBERS}명까지 저장할 수 있어요."})
    try:
        row = await store.create_member(user, _to_row(body))
    except DuplicateNickname:
        raise HTTPException(409, _DUPLICATE) from None
    except RlsDenied:
        raise HTTPException(403, _CONSENT_REQUIRED) from None
    return _to_out(row)


@router.put("/{member_id}", response_model=MemberOut, summary="구성원 수정 (전체 교체)")
async def update_member(member_id: UUID, body: MemberIn, user: CurrentUser = Depends(_need_consent), store: Store = Depends(get_store)):
    try:
        row = await store.update_member(user, member_id, _to_row(body))
    except DuplicateNickname:
        raise HTTPException(409, _DUPLICATE) from None
    except RlsDenied:
        raise HTTPException(403, _CONSENT_REQUIRED) from None
    if row is None:
        raise HTTPException(404, {"code": "not_found", "message": "구성원을 찾을 수 없어요."})
    return _to_out(row)


@router.delete("/{member_id}", status_code=204, summary="구성원과 건강 정보 삭제 (동의 철회 후에도 가능)")
async def delete_member(member_id: UUID, user: CurrentUser = Depends(get_current_user), store: Store = Depends(get_store)):
    if not await store.delete_member(user, member_id):
        raise HTTPException(404, {"code": "not_found", "message": "구성원을 찾을 수 없어요."})
    return Response(status_code=204)
