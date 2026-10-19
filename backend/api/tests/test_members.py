import json

from .. import crypto
from .conftest import ALL_CONSENTS, MEMBER, auth


def _ready(client, who="alice"):
    client.post("/api/consents", json=ALL_CONSENTS, headers=auth(who))
    return auth(who)


def test_동의_없이는_조회도_저장도_403(client):
    h = auth("alice")
    for r in (client.get("/api/members", headers=h), client.post("/api/members", json=MEMBER, headers=h)):
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "consent_required"
        assert set(r.json()["detail"]["missing"]) == {"terms", "privacy", "health"}


def test_구성원을_추가_조회_수정_삭제한다(client):
    h = _ready(client)
    created = client.post("/api/members", json=MEMBER, headers=h)
    assert created.status_code == 201
    m = created.json()
    assert m["nickname"] == "엄마" and m["allergies"] == ["땅콩", "우유"] and m["allergy_custom"] == "복숭아"

    assert [x["id"] for x in client.get("/api/members", headers=h).json()] == [m["id"]]   # 새로고침해도 그대로

    changed = {**MEMBER, "allergies": ["없음"], "allergy_custom": "", "conditions": ["저염식"], "notes": "바뀜"}
    u = client.put(f"/api/members/{m['id']}", json=changed, headers=h)
    assert u.status_code == 200 and u.json()["conditions"] == ["저염식"] and u.json()["notes"] == "바뀜"

    assert client.delete(f"/api/members/{m['id']}", headers=h).status_code == 204
    assert client.get("/api/members", headers=h).json() == []
    assert client.delete(f"/api/members/{m['id']}", headers=h).status_code == 404


def test_구성원_세명_이상을_저장할_수_있다(client):
    h = _ready(client)
    for name in ("엄마", "아빠", "민준"):
        assert client.post("/api/members", json={**MEMBER, "nickname": name}, headers=h).status_code == 201
    assert len(client.get("/api/members", headers=h).json()) == 3


def test_건강정보는_DB에_암호화되어_저장된다(client, store):
    h = _ready(client)
    client.post("/api/members", json=MEMBER, headers=h)
    stored = json.dumps(store.members[0], ensure_ascii=False, default=str)
    for secret in ("땅콩", "복숭아", "당뇨식", "가지", "체중 관리", "성인"):
        assert secret not in stored
    assert store.members[0]["nickname"] == "엄마"   # 별칭은 평문
    assert crypto.decrypt_json(store.members[0]["health_enc"])["allergies"] == ["땅콩", "우유"]


def test_다른_계정은_내_구성원을_볼_수도_고칠_수도_지울_수도_없다(client):
    ha, hb = _ready(client, "alice"), _ready(client, "bob")
    mid = client.post("/api/members", json=MEMBER, headers=ha).json()["id"]
    assert client.get("/api/members", headers=hb).json() == []
    assert client.put(f"/api/members/{mid}", json=MEMBER, headers=hb).status_code == 404
    assert client.delete(f"/api/members/{mid}", headers=hb).status_code == 404
    assert len(client.get("/api/members", headers=ha).json()) == 1


def test_같은_별칭은_중복_저장할_수_없다(client):
    h = _ready(client)
    client.post("/api/members", json=MEMBER, headers=h)
    r = client.post("/api/members", json=MEMBER, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_nickname"
    other = client.post("/api/members", json={**MEMBER, "nickname": "아빠"}, headers=h).json()
    r = client.put(f"/api/members/{other['id']}", json=MEMBER, headers=h)   # 아빠를 '엄마'로 바꾸려 함
    assert r.status_code == 409


def test_구성원은_최대_10명까지(client):
    h = _ready(client)
    for i in range(10):
        assert client.post("/api/members", json={**MEMBER, "nickname": f"가족{i}"}, headers=h).status_code == 201
    r = client.post("/api/members", json={**MEMBER, "nickname": "열한번째"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "member_limit"


def test_건강정보_동의를_철회하면_조회와_저장이_막히고_삭제는_된다(client):
    h = _ready(client)
    mid = client.post("/api/members", json=MEMBER, headers=h).json()["id"]
    client.post("/api/consents", json={"items": [{"consent_type": "health", "granted": False}]}, headers=h)

    assert client.get("/api/members", headers=h).status_code == 403
    assert client.post("/api/members", json={**MEMBER, "nickname": "아빠"}, headers=h).status_code == 403
    assert client.put(f"/api/members/{mid}", json=MEMBER, headers=h).status_code == 403
    assert client.delete(f"/api/members/{mid}", headers=h).status_code == 204   # 삭제는 언제든


def test_표준_목록에_없는_알레르기와_잘못된_값은_422(client):
    h = _ready(client)
    bad = [
        {**MEMBER, "allergies": ["마법가루"]},
        {**MEMBER, "age": "외계인"},
        {**MEMBER, "conditions": ["아무식"]},
        {**MEMBER, "allergies": ["없음", "땅콩"]},
        {**MEMBER, "allergies": ["없음"], "allergy_custom": "복숭아"},
        {**MEMBER, "conditions": ["일반식", "당뇨식"]},
        {**MEMBER, "nickname": ""},
        {**MEMBER, "nickname": "열한글자이름이에요요요"},
        {**MEMBER, "이상한필드": 1},
    ]
    for body in bad:
        assert client.post("/api/members", json=body, headers=h).status_code == 422, body


def test_조건을_비우면_일반식이_된다_그리고_중복은_정리된다(client):
    h = _ready(client)
    body = {**MEMBER, "conditions": [], "allergies": ["땅콩", "땅콩"], "avoid_ingredients": [" 가지 ", "가지", ""]}
    r = client.post("/api/members", json=body, headers=h)
    assert r.status_code == 201
    assert r.json()["conditions"] == ["일반식"]
    assert r.json()["allergies"] == ["땅콩"]
    assert r.json()["avoid_ingredients"] == ["가지"]


def test_구성원_id가_UUID가_아니면_422(client):
    h = _ready(client)
    assert client.put("/api/members/not-a-uuid", json=MEMBER, headers=h).status_code == 422
    assert client.delete("/api/members/1;drop table", headers=h).status_code == 422


def test_복호화_키가_바뀌면_500이고_내용은_노출되지_않는다(client, monkeypatch):
    from cryptography.fernet import Fernet

    from .. import config

    h = _ready(client)
    client.post("/api/members", json=MEMBER, headers=h)
    monkeypatch.setenv("HEALTH_DATA_KEY", Fernet.generate_key().decode())
    config.get_settings.cache_clear()
    r = client.get("/api/members", headers=h)
    assert r.status_code == 500 and "땅콩" not in r.text
