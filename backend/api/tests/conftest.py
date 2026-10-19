import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient

from .. import config
from ..deps import get_current_user, get_store
from ..main import app
from ..store import CurrentUser
from .fakes import MemoryStore


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("HEALTH_DATA_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("POLICY_VERSION", "test-v1")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def client(store):
    """토큰 문자열이 곧 사용자 이름. 예) Authorization: Bearer alice"""

    bearer = HTTPBearer(auto_error=False)

    async def user_from_token(creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if creds is None:
            raise HTTPException(401, "로그인이 필요해요.")
        return CurrentUser(id=creds.credentials, email=f"{creds.credentials}@test.local", token=creds.credentials)

    app.dependency_overrides[get_current_user] = user_from_token
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth(name: str) -> dict:
    return {"Authorization": f"Bearer {name}"}


ALL_CONSENTS = {"items": [{"consent_type": t, "granted": True} for t in ("terms", "privacy", "health")]}

MEMBER = {
    "nickname": "엄마", "avatar": "엄마1", "age": "성인",
    "allergies": ["땅콩", "우유"], "allergy_custom": "복숭아",
    "conditions": ["당뇨식"], "condition_custom": "", "avoid_ingredients": ["가지"],
    "notes": "체중 관리", "proxy_consent": False,
}
