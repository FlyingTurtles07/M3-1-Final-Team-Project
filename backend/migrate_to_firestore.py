"""Render Postgres(예전 DB) → Firebase Firestore 로 데이터 옮기기 (한 번만 실행).

사용법:  SOURCE_DATABASE_URL=postgres://… python migrate_to_firestore.py
- 회원·가족 데이터·게시물(사진 포함)·좋아요·신고·의견·레시피북·AI 요리 사진을 같은 번호로 옮겨요.
- 번호가 같아서, 이미 로그인한 사람의 토큰도 그대로 쓸 수 있어요.
- 이미 Firestore에 같은 번호 문서가 있으면 덮어써요 (여러 번 실행해도 결과가 같아요).
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
src = os.getenv("SOURCE_DATABASE_URL", "").strip()
if not src:
    sys.exit("SOURCE_DATABASE_URL 에 예전 DB 주소를 넣어 주세요")
os.environ["DATABASE_URL"] = src

from sqlalchemy import select  # noqa: E402

import fstore  # noqa: E402
from db import Feedback, Post, PostLike, RecipeImage, Record, Report, SessionLocal, User, UserDoc  # noqa: E402

db = fstore.db()
counts = {}
with SessionLocal() as s:
    users = s.scalars(select(User)).all()
    for u in users:
        db.collection("users").document(str(u.id)).set({"email": u.email, "name": u.name, "pw_hash": u.pw_hash,
                                                         "consents": u.consents or {}, "created_at": u.created_at})
        db.collection("user_emails").document(u.email).set({"uid": u.id})
    counts["회원"] = len(users)

    docs = s.scalars(select(UserDoc)).all()
    for d in docs:
        fstore.put_doc(d.user_id, d.key, d.data)
    counts["회원 데이터"] = len(docs)

    db.collection("posts")  # 예시 글이 자동으로 다시 들어가지 않게 게시물을 먼저 옮겨요
    posts = s.scalars(select(Post)).all()
    for p in posts:
        fstore.add_post(id=p.id, user_id=p.user_id, title=p.title, comment=p.comment or "", auto_tags=p.auto_tags or [],
                        user_tags=p.user_tags or [], recipe=p.recipe, photo_url=p.photo_url, ai_image=bool(p.ai_image),
                        verified=bool(p.verified), likes=p.likes or 0, hidden=bool(p.hidden), created_at=p.created_at,
                        photo=fstore.shrink_photo(p.photo)[0] if p.photo else None, photo_type="image/jpeg")
    counts["게시물"] = len(posts)

    likes = s.scalars(select(PostLike)).all()
    for lk in likes:
        db.collection("post_likes").document(f"{lk.post_id}_{lk.user_id}").set({"post_id": lk.post_id, "user_id": lk.user_id})
    counts["좋아요"] = len(likes)

    reps = s.scalars(select(Report)).all()
    for r in reps:
        db.collection("reports").add({"post_id": r.post_id, "user_id": r.user_id, "reason": r.reason, "status": r.status,
                                      "created_at": r.created_at})
    counts["신고"] = len(reps)

    fbs = s.scalars(select(Feedback)).all()
    for f in fbs:
        fstore.add_feedback(user_id=f.user_id, recipe_id=f.recipe_id, recipe_title=f.recipe_title, answers=f.answers, comment=f.comment)
    counts["의견"] = len(fbs)

    recs = s.scalars(select(Record)).all()
    for r in recs:
        fstore.add_record(id=r.id, user_id=r.user_id, title=r.title, comment=r.comment or "", auto_tags=r.auto_tags or [],
                          user_tags=r.user_tags or [], recipe=r.recipe, visibility=r.visibility, photo_key=r.photo_key,
                          created_at=r.created_at, photo=fstore.shrink_photo(r.photo)[0] if r.photo else None, photo_type="image/jpeg")
    counts["레시피북"] = len(recs)

    imgs = s.scalars(select(RecipeImage)).all()
    for im in imgs:
        fstore.add_recipe_image(im.key, im.title, im.image, im.mime, iid=im.id)
    counts["AI 요리 사진"] = len(imgs)

    # 다음 번호가 겹치지 않게 번호 발급기를 맞춰요
    for name, rows in (("users", users), ("posts", posts), ("records", recs), ("recipe_images", imgs)):
        db.collection("counters").document(name).set({"n": max([0] + [x.id for x in rows])})

print("옮긴 개수:", counts)
