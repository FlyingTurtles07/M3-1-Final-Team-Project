from .conftest import ALL_CONSENTS, MEMBER, auth


def test_confirm_없이는_삭제되지_않는다(client, store):
    assert client.delete("/api/account", headers=auth("alice")).status_code == 400
    assert store.deleted_accounts == []


def test_로그인_없이는_삭제할_수_없다(client):
    assert client.delete("/api/account?confirm=true").status_code == 401


def test_계정을_삭제하면_내_데이터만_모두_사라진다(client, store):
    for who in ("alice", "bob"):
        client.post("/api/consents", json=ALL_CONSENTS, headers=auth(who))
        client.post("/api/members", json=MEMBER, headers=auth(who))
    assert client.delete("/api/account?confirm=true", headers=auth("alice")).status_code == 204
    assert store.deleted_accounts == ["alice"]
    assert all(m["user_id"] == "bob" for m in store.members) and len(store.members) == 1
    assert all(c["user_id"] == "bob" for c in store.consents)
