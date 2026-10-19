"""DB 접근 계층. Supabase(PostgREST)를 '로그인한 사용자의 토큰'으로 호출해서 RLS가 항상 적용되게 해요.

- 서버가 DB 관리자 권한으로 사용자 데이터를 읽고 쓰지 않아요. 예외는 계정 삭제(관리자 API)뿐이에요.
- 테스트에서는 같은 모양의 메모리용 가짜(tests/fakes.py)로 바꿔 끼워요.
"""
import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import httpx

from .config import Settings

log = logging.getLogger("hansang.store")


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    token: str   # 이 사용자의 Supabase 액세스 토큰 (로그에 남기지 않아요)


class StoreError(RuntimeError):
    """DB 쪽 문제 (연결 실패, 예상 못한 응답 등)"""


class DuplicateNickname(StoreError):
    pass


class RlsDenied(StoreError):
    """행 단위 접근 제한에 걸림 (예: 건강 정보 동의를 철회한 상태에서 저장)"""


class Store(Protocol):
    async def current_consents(self, user: CurrentUser) -> list[dict]: ...
    async def consent_history(self, user: CurrentUser) -> list[dict]: ...
    async def add_consents(self, user: CurrentUser, rows: list[dict]) -> None: ...
    async def list_members(self, user: CurrentUser) -> list[dict]: ...
    async def create_member(self, user: CurrentUser, row: dict) -> dict: ...
    async def update_member(self, user: CurrentUser, member_id: UUID, row: dict) -> dict | None: ...
    async def delete_member(self, user: CurrentUser, member_id: UUID) -> bool: ...
    async def delete_account(self, user: CurrentUser) -> None: ...


class SupabaseStore:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http = http
        self.s = settings

    # ── 내부 도우미 ──
    def _user_headers(self, user: CurrentUser) -> dict[str, str]:
        return {"apikey": self.s.supabase_anon_key, "Authorization": f"Bearer {user.token}"}

    async def _rest(self, method: str, path: str, user: CurrentUser, *, params: dict | None = None, body: Any = None) -> Any:
        headers = {**self._user_headers(user), "Prefer": "return=representation"}
        try:
            r = await self.http.request(method, f"{self.s.supabase_url}/rest/v1/{path}", params=params, json=body, headers=headers)
        except httpx.HTTPError as e:
            log.error("Supabase REST 연결 실패: %s", type(e).__name__)
            raise StoreError("DB에 연결하지 못했어요.") from e
        if r.status_code >= 400:
            code = ""
            try:
                code = str(r.json().get("code", ""))
            except ValueError:
                pass
            log.error("Supabase REST 오류 status=%s code=%s path=%s", r.status_code, code, path)   # 본문(개인정보 가능성)은 남기지 않아요
            if code == "23505":
                raise DuplicateNickname("같은 별칭이 이미 있어요.")
            if code == "42501":
                raise RlsDenied("접근 권한이 없어요.")
            raise StoreError(f"DB 오류 ({r.status_code})")
        return r.json() if r.content else None

    # ── 동의 ──
    async def current_consents(self, user: CurrentUser) -> list[dict]:
        return await self._rest("GET", "current_consents", user, params={"select": "consent_type,granted,policy_version,created_at"})

    async def consent_history(self, user: CurrentUser) -> list[dict]:
        return await self._rest(
            "GET", "consents", user,
            params={"select": "consent_type,granted,policy_version,created_at", "order": "id.desc", "limit": "200"},
        )

    async def add_consents(self, user: CurrentUser, rows: list[dict]) -> None:
        await self._rest("POST", "consents", user, body=rows)   # user_id 는 DB가 로그인 사용자로 채워요

    # ── 가족 구성원 ──
    async def list_members(self, user: CurrentUser) -> list[dict]:
        return await self._rest("GET", "family_members", user, params={"select": "*", "order": "created_at.asc"})

    async def create_member(self, user: CurrentUser, row: dict) -> dict:
        rows = await self._rest("POST", "family_members", user, body=row)
        return rows[0]

    async def update_member(self, user: CurrentUser, member_id: UUID, row: dict) -> dict | None:
        rows = await self._rest("PATCH", "family_members", user, params={"id": f"eq.{member_id}"}, body=row)
        return rows[0] if rows else None   # 없거나 남의 것이면 빈 목록

    async def delete_member(self, user: CurrentUser, member_id: UUID) -> bool:
        rows = await self._rest("DELETE", "family_members", user, params={"id": f"eq.{member_id}"})
        return bool(rows)

    # ── 계정 삭제 (관리자 API, 서비스 키 사용) ──
    async def delete_account(self, user: CurrentUser) -> None:
        key = self.s.supabase_service_role_key
        if not key:
            raise StoreError("SUPABASE_SERVICE_ROLE_KEY 가 설정되지 않았어요.")
        headers = {"apikey": key}
        if key.startswith("eyJ"):   # 예전 방식(JWT) 키만 Authorization 에도 넣어요. 새 sb_secret_ 키는 apikey 만 사용
            headers["Authorization"] = f"Bearer {key}"
        try:
            r = await self.http.delete(f"{self.s.supabase_url}/auth/v1/admin/users/{user.id}", headers=headers)
        except httpx.HTTPError as e:
            log.error("계정 삭제 호출 실패: %s", type(e).__name__)
            raise StoreError("계정을 삭제하지 못했어요.") from e
        if r.status_code not in (200, 204, 404):   # 404 = 이미 삭제됨
            log.error("계정 삭제 오류 status=%s", r.status_code)
            raise StoreError(f"계정 삭제 오류 ({r.status_code})")
