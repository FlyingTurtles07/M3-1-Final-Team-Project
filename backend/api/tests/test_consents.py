from .conftest import ALL_CONSENTS, auth


def test_동의_전에는_서비스를_쓸_수_없다(client):
    r = client.get("/api/consents", headers=auth("alice"))
    assert r.status_code == 200
    body = r.json()
    assert body["can_use_service"] is False
    assert all(not v["granted"] for v in body["consents"].values())
    assert body["policy_version"] == "test-v1"


def test_로그인_없이는_401(client):
    assert client.get("/api/consents").status_code == 401
    assert client.post("/api/consents", json=ALL_CONSENTS).status_code == 401


def test_필수_동의를_모두_하면_서비스를_쓸_수_있고_이력이_남는다(client):
    r = client.post("/api/consents", json=ALL_CONSENTS, headers=auth("alice"))
    assert r.status_code == 200
    assert r.json()["can_use_service"] is True
    hist = client.get("/api/consents/history", headers=auth("alice")).json()
    assert len(hist) == 3
    assert {h["policy_version"] for h in hist} == {"test-v1"}


def test_일부만_동의하면_서비스를_쓸_수_없다(client):
    body = {"items": [{"consent_type": "terms", "granted": True}, {"consent_type": "privacy", "granted": True}]}
    assert client.post("/api/consents", json=body, headers=auth("alice")).json()["can_use_service"] is False


def test_철회하면_이력에_남고_현재상태가_바뀐다(client):
    client.post("/api/consents", json=ALL_CONSENTS, headers=auth("alice"))
    r = client.post("/api/consents", json={"items": [{"consent_type": "health", "granted": False}]}, headers=auth("alice"))
    assert r.json()["consents"]["health"]["granted"] is False
    assert r.json()["can_use_service"] is False
    hist = client.get("/api/consents/history", headers=auth("alice")).json()
    assert len(hist) == 4 and hist[0]["granted"] is False   # 최신이 맨 앞


def test_다른_사용자의_동의는_섞이지_않는다(client):
    client.post("/api/consents", json=ALL_CONSENTS, headers=auth("alice"))
    assert client.get("/api/consents", headers=auth("bob")).json()["can_use_service"] is False
    assert client.get("/api/consents/history", headers=auth("bob")).json() == []


def test_잘못된_요청은_422(client):
    h = auth("alice")
    assert client.post("/api/consents", json={"items": []}, headers=h).status_code == 422
    assert client.post("/api/consents", json={"items": [{"consent_type": "아무거나", "granted": True}]}, headers=h).status_code == 422
    dup = {"items": [{"consent_type": "terms", "granted": True}, {"consent_type": "terms", "granted": False}]}
    assert client.post("/api/consents", json=dup, headers=h).status_code == 422
