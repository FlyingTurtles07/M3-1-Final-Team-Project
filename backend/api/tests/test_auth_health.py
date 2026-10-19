"""로그인 확인(Supabase Auth 호출)과 /health 시험. 가짜 Supabase 서버를 app.state.http 로 끼워 넣어요."""
import httpx
from fastapi.testclient import TestClient

from ..deps import get_store
from ..main import app
from .fakes import MemoryStore


def with_supabase(handler, store=None):
    app.dependency_overrides[get_store] = lambda: (store or MemoryStore())
    c = TestClient(app)
    c.__enter__()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def teardown_function():
    app.dependency_overrides.clear()


def test_유효한_토큰이면_사용자로_인정하고_토큰을_그대로_전달한다():
    seen = {}

    def handler(req):
        seen.update(path=req.url.path, auth=req.headers["authorization"], apikey=req.headers["apikey"])
        return httpx.Response(200, json={"id": "uid-1", "email": "a@test.local"})

    store = MemoryStore()
    c = with_supabase(handler, store)
    r = c.get("/api/consents", headers={"Authorization": "Bearer GOOD"})
    assert r.status_code == 200
    assert seen == {"path": "/auth/v1/user", "auth": "Bearer GOOD", "apikey": "anon-key"}
    c.post("/api/consents", headers={"Authorization": "Bearer GOOD"}, json={"items": [{"consent_type": "terms", "granted": True}]})
    assert store.consents[0]["user_id"] == "uid-1"   # 토큰이 아니라 Supabase가 알려준 사용자 id 로 저장


def test_토큰이_없거나_틀리면_401():
    c = with_supabase(lambda req: httpx.Response(401, json={"msg": "bad"}))
    assert c.get("/api/members").status_code == 401
    assert c.get("/api/members", headers={"Authorization": "Bearer BAD"}).status_code == 401
    assert c.get("/api/members", headers={"Authorization": "Basic abc"}).status_code == 401


def test_인증_서버가_죽으면_503():
    def handler(req):
        raise httpx.ConnectError("down")

    c = with_supabase(handler)
    assert c.get("/api/members", headers={"Authorization": "Bearer X"}).status_code == 503


def test_설정이_비어_있으면_503(monkeypatch):
    from .. import config

    monkeypatch.setenv("SUPABASE_URL", "")
    config.get_settings.cache_clear()
    c = with_supabase(lambda req: httpx.Response(200, json={}))
    assert c.get("/api/members", headers={"Authorization": "Bearer X"}).status_code == 503


def test_health는_가볍게_ok와_설정_여부만_알려준다():
    c = with_supabase(lambda req: httpx.Response(500))   # Supabase가 죽어 있어도 기본 health는 성공
    for path in ("/health", "/api/health"):
        body = c.get(path).json()
        assert body["ok"] is True and body["supabase_configured"] is True and body["encryption_configured"] is True
    assert "anon-key" not in c.get("/health").text   # 키 값은 절대 보여주지 않는다


def test_deep_health는_Supabase_연결까지_확인한다():
    c = with_supabase(lambda req: httpx.Response(200, json={"name": "GoTrue"}))
    assert c.get("/health?deep=true").json()["supabase"] == "ok"
    c = with_supabase(lambda req: httpx.Response(500))
    r = c.get("/health?deep=true")
    assert r.status_code == 503 and r.json()["ok"] is False
