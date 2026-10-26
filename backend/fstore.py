"""Firebase Firestore 저장소.

컬렉션 구조
- counters/{이름}            : 숫자 번호 발급용 (회원·게시물·기록·요리 사진은 숫자 번호를 써요)
- users/{번호}               : email, name, pw_hash, consents, created_at
- user_emails/{이메일}        : {uid}  (같은 이메일로 두 번 가입하지 못하게)
- user_docs/{번호}_{key}      : 가족·재료·보관함 (JSON 글자로 저장)
- posts/{번호}               : 다른 집 한상 게시물
- post_likes/{게시물}_{회원}   : 좋아요
- reports/{자동}             : 신고 이력
- feedback/{자동}            : 식사 후 의견
- shares/{링크}              : 가족 의견 링크 (메뉴·사진·가족 별칭, 하루 뒤 만료)
- share_responses/{링크}_{n} : 링크로 받은 가족 한 명의 의견 (별점·느낌·불편 신고)
- records/{번호}             : 나만의 레시피북
- recipe_images/{번호}        : AI 요리 사진 정보 (key = 띄어쓰기 뺀 요리 이름)
- photos/{key}               : 사진 파일 (게시물 post-번호 / 기록 photo_key / 요리 사진 img-번호)

Firestore는 '목록 안의 목록'을 저장하지 못해서 레시피·회원 데이터는 JSON 글자로 저장해요.
사진은 문서 한 개 1MB 제한이 있어서 1280px JPEG로 줄여서 넣어요.

인증 정보: FIREBASE_CREDENTIALS(JSON 내용) 또는 FIREBASE_CREDENTIALS_FILE(파일 경로)
"""
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

log = logging.getLogger("hansang.fstore")
_db = None


class Duplicate(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _cred():
    raw = os.getenv("FIREBASE_CREDENTIALS", "").strip()
    if raw:
        return credentials.Certificate(json.loads(raw))
    path = os.getenv("FIREBASE_CREDENTIALS_FILE", "").strip()
    if not path:   # 내 컴퓨터: 프로젝트 폴더에 둔 서비스 계정 키 파일을 찾아요
        found = sorted(Path(__file__).resolve().parent.parent.glob("*firebase-adminsdk*.json"))
        path = str(found[0]) if found else ""
    if not path:
        raise RuntimeError("Firebase 인증 정보가 없어요 (FIREBASE_CREDENTIALS 또는 FIREBASE_CREDENTIALS_FILE)")
    return credentials.Certificate(path)


def db():
    global _db
    if _db is None:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(_cred())
        _db = firestore.client()
    return _db


def ping() -> bool:
    try:
        db().collection("counters").document("_ping").get()
        return True
    except Exception:
        log.exception("Firestore 연결 실패")
        return False


def next_id(name: str) -> int:
    ref = db().collection("counters").document(name)

    @firestore.transactional
    def bump(tx):
        snap = ref.get(transaction=tx)
        n = (snap.to_dict() or {}).get("n", 0) + 1 if snap.exists else 1
        tx.set(ref, {"n": n})
        return n
    return bump(db().transaction())


def _j(v):
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _uj(s):
    return json.loads(s) if s else None


def shrink_photo(data: bytes, max_side: int = 1280) -> tuple[bytes, str]:
    """Firestore 문서 1MB 제한에 맞게 줄여요 (JPEG)"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((max_side, max_side))
        q = 82
        while True:
            out = io.BytesIO()
            img.save(out, "JPEG", quality=q, optimize=True)
            if out.tell() < 900_000 or q <= 50:
                return out.getvalue(), "image/jpeg"
            q -= 10
    except Exception:
        if len(data) < 900_000:
            return data, "image/jpeg"
        raise


# ---------------------------------------------------------------- 사진
def put_photo(key: str, data: bytes, mime: str) -> None:
    db().collection("photos").document(key).set({"data": data, "mime": mime, "created_at": now()})


def get_photo(key: str) -> tuple[bytes, str] | None:
    snap = db().collection("photos").document(key).get()
    if not snap.exists:
        return None
    d = snap.to_dict()
    return d["data"], d.get("mime") or "image/jpeg"


def del_photo(key: str) -> None:
    db().collection("photos").document(key).delete()


# ---------------------------------------------------------------- 회원
def create_user(email: str, name: str, pw_hash: str, consents: dict) -> dict:
    email_ref = db().collection("user_emails").document(email)
    uid = next_id("users")

    @firestore.transactional
    def claim(tx):
        if email_ref.get(transaction=tx).exists:
            raise Duplicate(email)
        tx.set(email_ref, {"uid": uid})
        tx.set(db().collection("users").document(str(uid)),
               {"email": email, "name": name, "pw_hash": pw_hash, "consents": consents, "created_at": now()})
    claim(db().transaction())
    return {"id": uid, "name": name, "email": email}


def get_user(uid: int) -> dict | None:
    snap = db().collection("users").document(str(uid)).get()
    return dict(snap.to_dict(), id=uid) if snap.exists else None


def get_user_by_email(email: str) -> dict | None:
    snap = db().collection("user_emails").document(email).get()
    if not snap.exists:
        return None
    return get_user(int(snap.to_dict()["uid"]))


def _delete_where(col: str, field: str, value) -> int:
    n = 0
    for doc in db().collection(col).where(filter=FieldFilter(field, "==", value)).stream():
        doc.reference.delete()
        n += 1
    return n


def delete_user(uid: int) -> None:
    u = get_user(uid)
    if not u:
        return
    for key in ("family", "pantry", "saved", "collections"):
        db().collection("user_docs").document(f"{uid}_{key}").delete()
    _delete_where("post_likes", "user_id", uid)
    _delete_where("feedback", "user_id", uid)
    _delete_where("shares", "user_id", uid)
    _delete_where("share_responses", "owner_id", uid)
    for doc in db().collection("records").where(filter=FieldFilter("user_id", "==", uid)).stream():
        d = doc.to_dict()
        if d.get("photo_key"):
            del_photo(d["photo_key"])
        doc.reference.delete()
    for doc in db().collection("posts").where(filter=FieldFilter("user_id", "==", uid)).stream():
        del_photo(f"post-{doc.id}")
        doc.reference.delete()
    db().collection("user_emails").document(u["email"]).delete()
    db().collection("users").document(str(uid)).delete()


# ---------------------------------------------------------------- 회원별 데이터
def get_doc(uid: int, key: str):
    snap = db().collection("user_docs").document(f"{uid}_{key}").get()
    return _uj(snap.to_dict().get("json")) if snap.exists else None


def put_doc(uid: int, key: str, data) -> None:
    db().collection("user_docs").document(f"{uid}_{key}").set(
        {"user_id": uid, "key": key, "json": _j(data), "updated_at": now()})


# ---------------------------------------------------------------- 게시물
def _post(doc) -> dict:
    d = doc.to_dict()
    d["id"] = int(doc.id)
    d["recipe"] = _uj(d.pop("recipe_json", None))
    return d


def count_posts() -> int:
    return len(list(db().collection("posts").limit(1).stream()))


def add_post(**fields) -> dict:
    pid = fields.pop("id", None) or next_id("posts")
    photo = fields.pop("photo", None)
    photo_type = fields.pop("photo_type", None)
    doc = {"user_id": None, "title": "", "comment": "", "auto_tags": [], "user_tags": [], "photo_url": None,
           "ai_image": False, "verified": False, "likes": 0, "hidden": False, "report_count": 0, "has_photo": False,
           "created_at": now()}
    doc.update(fields)
    doc["recipe_json"] = _j(doc.pop("recipe", None))
    if photo:
        put_photo(f"post-{pid}", photo, photo_type or "image/jpeg")
        doc["has_photo"] = True
    db().collection("posts").document(str(pid)).set(doc)
    return dict(doc, id=pid, recipe=_uj(doc["recipe_json"]))


def list_posts() -> list[dict]:
    return [_post(d) for d in db().collection("posts").where(filter=FieldFilter("hidden", "==", False)).stream()]


def get_post(pid: int) -> dict | None:
    snap = db().collection("posts").document(str(pid)).get()
    return _post(snap) if snap.exists else None


def delete_post(pid: int) -> None:
    for doc in db().collection("shares").where(filter=FieldFilter("post_id", "==", pid)).stream():
        doc.reference.update({"active": False})   # 글을 지우면 그 글로 만든 의견 링크도 꺼요
    del_photo(f"post-{pid}")
    db().collection("posts").document(str(pid)).delete()


def liked_by(uid: int) -> set[int]:
    return {int(d.to_dict()["post_id"]) for d in db().collection("post_likes").where(filter=FieldFilter("user_id", "==", uid)).stream()}


def reported_by(uid: int) -> set[int]:
    return {int(d.to_dict()["post_id"]) for d in db().collection("reports").where(filter=FieldFilter("user_id", "==", uid)).stream()}


def set_like(pid: int, uid: int, liked: bool) -> int:
    post_ref = db().collection("posts").document(str(pid))
    like_ref = db().collection("post_likes").document(f"{pid}_{uid}")

    @firestore.transactional
    def run(tx):
        p = post_ref.get(transaction=tx)
        if not p.exists:
            raise KeyError(pid)
        likes = int(p.to_dict().get("likes", 0))
        has = like_ref.get(transaction=tx).exists
        if liked and not has:
            tx.set(like_ref, {"post_id": pid, "user_id": uid})
            likes += 1
        elif not liked and has:
            tx.delete(like_ref)
            likes = max(0, likes - 1)
        tx.update(post_ref, {"likes": likes})
        return likes
    return run(db().transaction())


def add_report(pid: int, uid: int | None, reason: str, hide_after: int) -> None:
    db().collection("reports").add({"post_id": pid, "user_id": uid, "reason": reason, "status": "접수", "created_at": now()})
    ref = db().collection("posts").document(str(pid))
    ref.update({"report_count": firestore.Increment(1)})
    if int(ref.get().to_dict().get("report_count", 0)) >= hide_after:
        ref.update({"hidden": True})   # 신고가 쌓이면 운영자가 확인할 때까지 숨겨요


# ---------------------------------------------------------------- 식사 후 의견
def add_feedback(**fields) -> None:
    fields["created_at"] = now()
    fields["answers"] = _j(fields.get("answers") or {})
    db().collection("feedback").add(fields)


# ---------------------------------------------------------------- 레시피 추천 정책 (upload_policies.py 가 올려요)
POLICY_META = ("COMMON", "GUIDELINE")


def put_policies(data: dict) -> int:
    col = db().collection("recipe_policies")
    t = now()
    batch = db().batch()
    batch.set(col.document("COMMON"), {"text": data["common"], "version": data["version"], "updated_at": t})
    batch.set(col.document("GUIDELINE"), {"text": data["guideline"], "version": data["version"], "updated_at": t})
    for code, p in data["policies"].items():
        batch.set(col.document(code), {**p, "version": data["version"], "updated_at": t})
    for doc in col.stream():   # 문서에서 빠진 정책은 지워요
        if doc.id not in POLICY_META and doc.id not in data["policies"]:
            batch.delete(doc.reference)
    batch.commit()
    return len(data["policies"]) + len(POLICY_META)


def get_policies() -> dict:
    out = {"common": "", "guideline": "", "version": "", "policies": {}}
    for doc in db().collection("recipe_policies").stream():
        d = doc.to_dict()
        if doc.id == "COMMON":
            out["common"], out["version"] = d.get("text", ""), d.get("version", "")
        elif doc.id == "GUIDELINE":
            out["guideline"] = d.get("text", "")
        else:
            out["policies"][doc.id] = {k: d.get(k) for k in ("code", "category", "title", "text", "active")}
    return out


# ---------------------------------------------------------------- 가족 의견 링크 (카카오톡으로 보내는 링크)
SHARE_HOURS = 24   # 링크는 하루 동안 열려요 (다시 켜면 하루 연장)


def add_share(token: str, **fields) -> dict:
    t = now()
    fields.update(active=True, reflect=True, created_at=t, expires_at=t + timedelta(hours=SHARE_HOURS))
    db().collection("shares").document(token).set(fields)
    return dict(fields, token=token)


def get_share(token: str) -> dict | None:
    snap = db().collection("shares").document(token).get()
    return dict(snap.to_dict(), token=token) if snap.exists else None


def find_share(uid: int, post_id: int) -> dict | None:
    for doc in db().collection("shares").where(filter=FieldFilter("post_id", "==", post_id)).stream():
        d = doc.to_dict()
        if d.get("user_id") == uid:
            return dict(d, token=doc.id)
    return None


def update_share(token: str, renew: bool = False, **fields) -> None:
    if renew:
        fields.update(active=True, expires_at=now() + timedelta(hours=SHARE_HOURS))
    db().collection("shares").document(token).update(fields)


def share_open(s: dict) -> bool:
    return bool(s.get("active")) and s.get("expires_at") is not None and s["expires_at"] > now()


def shares_of(uid: int) -> list[dict]:
    return [dict(d.to_dict(), token=d.id) for d in db().collection("shares").where(filter=FieldFilter("user_id", "==", uid)).stream()]


# 가족 한 명당 의견 한 개 (다시 보내면 고쳐져요): share_responses/{링크}_{가족 순번}
def _resp(doc) -> dict:
    d = doc.to_dict()
    d["symptom"] = _uj(d.pop("symptom_json", None))
    return d


def put_response(token: str, idx: int, **fields) -> dict:
    ref = db().collection("share_responses").document(f"{token}_{idx}")
    old = ref.get()
    t = now()
    fields["symptom_json"] = _j(fields.pop("symptom", None))
    fields.update(token=token, idx=idx, updated_at=t, ack=False, suspects=[])   # 고치면 다시 확인할 수 있게 표시를 풀어요
    fields["created_at"] = old.to_dict().get("created_at", t) if old.exists else t
    ref.set(fields)
    return dict(fields, symptom=_uj(fields["symptom_json"]))


def update_response(token: str, idx: int, **fields) -> bool:
    ref = db().collection("share_responses").document(f"{token}_{idx}")
    if not ref.get().exists:
        return False
    ref.update(fields)
    return True


def delete_response(token: str, idx: int) -> None:
    db().collection("share_responses").document(f"{token}_{idx}").delete()


def responses_of(token: str) -> list[dict]:
    rows = [_resp(d) for d in db().collection("share_responses").where(filter=FieldFilter("token", "==", token)).stream()]
    return sorted(rows, key=lambda r: r["idx"])


def responses_by_share(uid: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in db().collection("share_responses").where(filter=FieldFilter("owner_id", "==", uid)).stream():
        r = _resp(d)
        out.setdefault(r["token"], []).append(r)
    return out


# ---------------------------------------------------------------- 나만의 레시피북
def _record(doc) -> dict:
    d = doc.to_dict()
    d["id"] = int(doc.id)
    d["recipe"] = _uj(d.pop("recipe_json", None))
    return d


def add_record(**fields) -> dict:
    rid = fields.pop("id", None) or next_id("records")
    photo = fields.pop("photo", None)
    photo_type = fields.pop("photo_type", None)
    fields.setdefault("created_at", now())
    fields["recipe_json"] = _j(fields.pop("recipe", None))
    fields["has_photo"] = bool(photo)
    if photo:
        put_photo(fields["photo_key"], photo, photo_type or "image/jpeg")
    db().collection("records").document(str(rid)).set(fields)
    return dict(fields, id=rid, recipe=_uj(fields["recipe_json"]))


def list_records(uid: int) -> list[dict]:
    rows = [_record(d) for d in db().collection("records").where(filter=FieldFilter("user_id", "==", uid)).stream()]
    return sorted(rows, key=lambda r: -r["id"])


def get_record(rid: int) -> dict | None:
    snap = db().collection("records").document(str(rid)).get()
    return _record(snap) if snap.exists else None


def record_by_photo_key(key: str) -> dict | None:
    for doc in db().collection("records").where(filter=FieldFilter("photo_key", "==", key)).limit(1).stream():
        return _record(doc)
    return None


def delete_record(rid: int) -> None:
    r = get_record(rid)
    if r and r.get("photo_key"):
        del_photo(r["photo_key"])
    db().collection("records").document(str(rid)).delete()


# ---------------------------------------------------------------- AI 요리 사진
def find_recipe_image(key: str) -> int | None:
    for doc in db().collection("recipe_images").where(filter=FieldFilter("key", "==", key)).limit(1).stream():
        return int(doc.id)
    return None


def add_recipe_image(key: str, title: str, data: bytes, mime: str = "image/jpeg", iid: int | None = None) -> int:
    iid = iid or next_id("recipe_images")
    put_photo(f"img-{iid}", data, mime)
    db().collection("recipe_images").document(str(iid)).set({"key": key, "title": title, "created_at": now()})
    return iid
