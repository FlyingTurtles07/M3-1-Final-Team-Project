"""DB 대신 쓰는 메모리 가짜. 실제 DB 규칙(내 것만 보임, 동의 철회 시 쓰기 차단, 별칭 중복 금지)을 같게 흉내 내요."""
import itertools
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ..store import CurrentUser, DuplicateNickname, RlsDenied


class MemoryStore:
    def __init__(self):
        self.consents: list[dict] = []
        self.members: list[dict] = []
        self.deleted_accounts: list[str] = []
        self._seq = itertools.count(1)

    def _now(self):
        return datetime.now(timezone.utc)

    def _health_ok(self, user):
        mine = [c for c in self.consents if c["user_id"] == user.id and c["consent_type"] == "health"]
        return bool(mine) and mine[-1]["granted"]

    async def current_consents(self, user: CurrentUser):
        latest: dict[str, dict] = {}
        for c in self.consents:
            if c["user_id"] == user.id:
                latest[c["consent_type"]] = c
        return list(latest.values())

    async def consent_history(self, user):
        return [c for c in reversed(self.consents) if c["user_id"] == user.id]

    async def add_consents(self, user, rows):
        for r in rows:
            self.consents.append({**r, "id": next(self._seq), "user_id": user.id, "created_at": self._now()})

    async def list_members(self, user):
        return [m for m in self.members if m["user_id"] == user.id]

    async def create_member(self, user, row):
        if not self._health_ok(user):
            raise RlsDenied("x")
        if any(m["user_id"] == user.id and m["nickname"] == row["nickname"] for m in self.members):
            raise DuplicateNickname("x")
        rec = {**row, "id": str(uuid4()), "user_id": user.id, "created_at": self._now(), "updated_at": self._now()}
        self.members.append(rec)
        return rec

    async def update_member(self, user, member_id: UUID, row):
        target = next((m for m in self.members if m["id"] == str(member_id) and m["user_id"] == user.id), None)
        if target is None:
            return None
        if not self._health_ok(user):
            raise RlsDenied("x")
        if any(m is not target and m["user_id"] == user.id and m["nickname"] == row["nickname"] for m in self.members):
            raise DuplicateNickname("x")
        target.update(row, updated_at=self._now())
        return target

    async def delete_member(self, user, member_id):
        before = len(self.members)
        self.members = [m for m in self.members if not (m["id"] == str(member_id) and m["user_id"] == user.id)]
        return len(self.members) < before

    async def delete_account(self, user):
        self.deleted_accounts.append(user.id)
        self.members = [m for m in self.members if m["user_id"] != user.id]
        self.consents = [c for c in self.consents if c["user_id"] != user.id]
