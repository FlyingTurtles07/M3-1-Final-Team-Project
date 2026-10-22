"""온가족 한상 백엔드 (FastAPI + Firebase Firestore).

실행:  uvicorn main:app --reload        (backend 폴더에서)
문서:  http://localhost:8000/docs

1) 회원: 가입·로그인(토큰), 가족 프로필·재료·보관함 저장           /api/auth/*, /api/me, /api/me/data/{key}
2) 공유: 다른 집 한상 글(사진·레시피) 저장·조회·좋아요·신고·삭제    /api/posts*
3) AI:   사진 재료 인식, 레시피 3개 추천, 요리 사진                  /api/ingredients/analyze, /api/recipes/*
4) 안전: 알레르기·당뇨식·저염식 검사                                /api/safety/check (추천 결과에도 함께 들어가요)
5) 나만의 레시피북                                                  /api/records*

데이터는 Firebase Firestore에 저장해요 (fstore.py).
"""
import json
import logging
import os
import re
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))   # 다른 모듈이 환경변수를 읽기 전에 불러와요

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import fstore  # noqa: E402
import images  # noqa: E402
import recipes  # noqa: E402
import safety  # noqa: E402
import vision  # noqa: E402
from auth import check_password, hash_password, make_token, optional_user, require_user  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hansang")

app = FastAPI(title="온가족 한상 API", version="2.0")
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

DOC_KEYS = {"family", "pantry", "saved", "collections"}
MAX_DOC_BYTES = 300_000
MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
HIDE_AFTER_REPORTS = 3


@app.on_event("startup")
def startup() -> None:
    try:
        _seed_posts()
    except Exception:
        log.exception("예시 게시물을 넣지 못했어요 (Firestore 연결을 확인하세요)")


def _seed_posts() -> None:
    """처음 시작할 때 예시 게시물을 넣어 둬요 (게시물이 하나도 없을 때만)"""
    if fstore.count_posts():
        return
    data = json.loads((Path(__file__).with_name("data") / "sample_posts.json").read_text(encoding="utf-8"))
    for p in data:
        fstore.add_post(title=p["title"], comment=p.get("comment", ""), auto_tags=p.get("autoTags", []),
                        user_tags=p.get("userTags", []), recipe=p.get("recipe"), photo_url=p.get("photoUrl"),
                        ai_image=bool(p.get("aiImage")), verified=bool(p.get("verified")), likes=int(p.get("likes", 0)))
    log.info("예시 게시물 %d개를 넣었어요", len(data))


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


async def _read_photo(f: UploadFile) -> tuple[bytes, str]:
    if f.content_type not in PHOTO_TYPES:
        raise HTTPException(400, "사진 파일(JPEG·PNG·WEBP)만 올릴 수 있어요")
    data = await f.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "사진은 5MB 이하만 올릴 수 있어요")
    return await run_in_threadpool(fstore.shrink_photo, data)


def _photo_response(found, cache: str) -> Response:
    if not found:
        raise HTTPException(404, "사진이 없어요")
    data, mime = found
    return Response(data, media_type=mime, headers={"Cache-Control": cache})


# ---------------------------------------------------------------- 상태
@app.get("/api/health")
def health():
    ok = fstore.ping()
    return {"ok": ok, "db": ok, "store": "firestore", "ai": bool(os.getenv("OPENAI_API_KEY")), "images": images.enabled(),
            "vision": vision.enabled(), "mfds": bool(safety.MFDS_API_KEY)}


# ---------------------------------------------------------------- 1) 회원
class SignupReq(BaseModel):
    name: str = Field(min_length=2, max_length=12)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=100)
    consents: dict = Field(default_factory=dict)   # {terms, privacy, health, marketing, age14}


class LoginReq(BaseModel):
    email: str
    password: str


def _user_out(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"]}


@app.post("/api/auth/signup")
def signup(req: SignupReq):
    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 형식을 확인해 주세요")
    if not re.search(r"[A-Za-z]", req.password) or not re.search(r"\d", req.password):
        raise HTTPException(400, "비밀번호는 영문과 숫자를 모두 넣어 주세요")
    need = ["terms", "privacy", "health", "age14"]
    if not all(req.consents.get(k) for k in need):
        raise HTTPException(400, "필수 약관에 모두 동의해 주세요")
    consents = {k: bool(v) for k, v in req.consents.items()}
    consents["agreedAt"] = fstore.now().isoformat()
    try:
        u = fstore.create_user(email, req.name.strip(), hash_password(req.password), consents)
    except fstore.Duplicate:
        raise HTTPException(409, "이미 가입된 이메일이에요")
    return {"token": make_token(u["id"]), "user": _user_out(u)}


@app.post("/api/auth/login")
def login(req: LoginReq):
    u = fstore.get_user_by_email(req.email.strip().lower())
    if not u or not check_password(req.password, u["pw_hash"]):
        raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요")
    return {"token": make_token(u["id"]), "user": _user_out(u)}


@app.get("/api/me")
def me(uid: int = Depends(require_user)):
    u = fstore.get_user(uid)
    if not u:
        raise HTTPException(401, "로그인이 필요해요")
    return _user_out(u)


@app.delete("/api/me")
def withdraw(uid: int = Depends(require_user)):
    """탈퇴: 계정·가족·건강 정보·게시물·레시피북을 모두 지워요"""
    fstore.delete_user(uid)
    return {"ok": True}


class DocReq(BaseModel):
    data: object


@app.get("/api/me/data/{key}")
def get_doc(key: str, uid: int = Depends(require_user)):
    if key not in DOC_KEYS:
        raise HTTPException(404, "없는 항목이에요")
    return {"data": fstore.get_doc(uid, key)}


@app.put("/api/me/data/{key}")
def put_doc(key: str, req: DocReq, uid: int = Depends(require_user)):
    if key not in DOC_KEYS:
        raise HTTPException(404, "없는 항목이에요")
    if len(json.dumps(req.data, ensure_ascii=False).encode()) > MAX_DOC_BYTES:
        raise HTTPException(413, "저장할 내용이 너무 커요")
    fstore.put_doc(uid, key, req.data)
    return {"ok": True}


# ---------------------------------------------------------------- 2) 다른 집 한상
def _post_out(p: dict, base: str, uid: int | None, liked: set[int]) -> dict:
    photo = f"{base}/api/posts/{p['id']}/photo" if p.get("has_photo") else p.get("photo_url")
    created = p.get("created_at")
    return {"id": p["id"], "title": p["title"], "comment": p.get("comment", ""), "autoTags": p.get("auto_tags") or [],
            "userTags": p.get("user_tags") or [], "likes": int(p.get("likes", 0)), "liked": p["id"] in liked,
            "verified": bool(p.get("verified")), "photoUrl": photo, "aiImage": bool(p.get("ai_image")), "recipe": p.get("recipe"),
            "mine": uid is not None and p.get("user_id") == uid, "createdAt": created.isoformat() if created else None}


@app.get("/api/posts")
def list_posts(request: Request, text: str = "", tags: str = "", offset: int = 0, limit: int = 4,
               uid: int | None = Depends(optional_user)):
    tag_list = [t for t in tags.split(",") if t]
    need_safe = any(t.endswith("제외") for t in tag_list)   # 알레르기 제외 검색은 안전 확인된 글만
    q = text.strip().lower()
    rows = fstore.list_posts()
    reported = fstore.reported_by(uid) if uid else set()
    liked = fstore.liked_by(uid) if uid else set()
    out = []
    for p in rows:
        if p["id"] in reported or (need_safe and not p.get("verified")):
            continue
        ok = True
        for t in tag_list:
            if t.startswith("#"):
                w = t[1:].lower()
                ok = any(u.lower() == w for u in (p.get("user_tags") or [])) or w in (p.get("comment") or "").lower()
            else:
                ok = t in (p.get("auto_tags") or [])
            if not ok:
                break
        if not ok:
            continue
        if q:
            rec = p.get("recipe") or {}
            ings = " ".join(rec.get("ingredients") or [x[0] for x in rec.get("ing") or []])
            hay = " ".join([p["title"], p.get("comment") or "", " ".join(p.get("user_tags") or []),
                            " ".join(p.get("auto_tags") or []), ings]).lower()
            if q not in hay:
                continue
        out.append(p)
    out.sort(key=lambda p: (0 if (uid and p.get("user_id") == uid) else 1, -int(p.get("likes", 0)), -p["id"]))   # 내 글 → 좋아요 많은 순
    limit = max(1, min(limit, 20))
    base = _base(request)
    return {"posts": [_post_out(p, base, uid, liked) for p in out[offset:offset + limit]], "total": len(out)}


@app.post("/api/posts")
async def create_post(request: Request, data: str = Form(...), photo: UploadFile = File(...),
                      uid: int = Depends(require_user)):
    try:
        d = json.loads(data)
    except ValueError:
        raise HTTPException(400, "글 내용을 읽지 못했어요")
    if d.get("visibility") != "share" or not d.get("consent"):
        raise HTTPException(400, "공유하려면 공유 동의가 필요해요")
    img, mime = await _read_photo(photo)
    recipe = d.get("recipe")
    if recipe:   # 공통 레시피만 남겨요 (가족 이름·건강 정보는 받지 않아요)
        recipe = {k: recipe.get(k) for k in ("title", "minutes", "servings", "ingredients", "ing", "sauce", "steps")}
    p = await run_in_threadpool(lambda: fstore.add_post(
        user_id=uid, title=str(d.get("recipeTitle") or "우리 집 한상")[:60], comment=str(d.get("comment") or "")[:100],
        auto_tags=[str(t)[:20] for t in (d.get("autoTags") or [])][:6], user_tags=[str(t)[:12] for t in (d.get("myTags") or [])][:5],
        recipe=recipe, photo=img, photo_type=mime, verified=False))
    return _post_out(p, _base(request), uid, set())


@app.get("/api/posts/{post_id}")
def get_post(request: Request, post_id: int, uid: int | None = Depends(optional_user)):
    """공유한 요리 페이지(QR로 들어오는 화면). 로그인하지 않아도 볼 수 있어요."""
    p = fstore.get_post(post_id)
    if not p or p.get("hidden"):
        raise HTTPException(404, "글이 없거나 내려간 글이에요")
    return _post_out(p, _base(request), uid, fstore.liked_by(uid) if uid else set())


@app.get("/api/posts/{post_id}/photo")
def post_photo(post_id: int):
    p = fstore.get_post(post_id)
    if not p or p.get("hidden"):
        raise HTTPException(404, "사진이 없어요")
    return _photo_response(fstore.get_photo(f"post-{post_id}"), "public, max-age=86400")


class LikeReq(BaseModel):
    liked: bool


@app.post("/api/posts/{post_id}/like")
def like_post(post_id: int, req: LikeReq, uid: int = Depends(require_user)):
    try:
        likes = fstore.set_like(post_id, uid, req.liked)
    except KeyError:
        raise HTTPException(404, "게시물이 없어요")
    return {"likes": likes, "liked": req.liked}


class ReportReq(BaseModel):
    reason: str = Field(min_length=1, max_length=100)


@app.post("/api/posts/{post_id}/report")
def report_post(post_id: int, req: ReportReq, uid: int | None = Depends(optional_user)):
    if not fstore.get_post(post_id):
        raise HTTPException(404, "게시물이 없어요")
    fstore.add_report(post_id, uid, req.reason, HIDE_AFTER_REPORTS)
    return {"ok": True}


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, uid: int = Depends(require_user)):
    p = fstore.get_post(post_id)
    if not p:
        raise HTTPException(404, "게시물이 없어요")
    if p.get("user_id") != uid:
        raise HTTPException(403, "내가 올린 글만 지울 수 있어요")
    fstore.delete_post(post_id)
    return {"ok": True}


# ---------------------------------------------------------------- 식사 후 의견
class FeedbackReq(BaseModel):
    recipeId: str = ""
    recipeTitle: str = ""
    answers: dict = Field(default_factory=dict)
    comment: str = Field(default="", max_length=200)


@app.post("/api/feedback")
def feedback(req: FeedbackReq, uid: int | None = Depends(optional_user)):
    fstore.add_feedback(user_id=uid, recipe_id=req.recipeId[:80], recipe_title=req.recipeTitle[:80],
                        answers=req.answers, comment=req.comment)
    return {"ok": True}


# ---------------------------------------------------------------- 가족 의견 링크 (카카오톡 단톡방에 보내는 링크)
# 받은 사람은 가입 없이 링크만 열어서 의견을 남겨요. 화면에는 메뉴 이름·사진·가족 별칭만 보여요 (건강 정보 없음).
SHARE_MAX_RESPONSES = 30


class ShareReq(BaseModel):
    postId: int
    recordId: int | None = None
    members: list[str] = Field(default_factory=list)


class ShareFeedbackReq(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)   # {가족 별칭: 'ate' | 'left'}
    comment: str = Field(default="", max_length=200)


class ShareActiveReq(BaseModel):
    active: bool


def _share_out(s: dict, base: str) -> dict:
    p = fstore.get_post(s["post_id"])
    photo = None
    if p and not p.get("hidden"):
        photo = f"{base}/api/posts/{p['id']}/photo" if p.get("has_photo") else p.get("photo_url")
    return {"token": s["token"], "title": s["title"], "members": s.get("members") or [], "active": bool(s.get("active")),
            "postId": s["post_id"], "photoUrl": photo}


@app.post("/api/shares")
def create_share(request: Request, req: ShareReq, uid: int = Depends(require_user)):
    p = fstore.get_post(req.postId)
    if not p or p.get("user_id") != uid:
        raise HTTPException(404, "내가 올린 글만 링크로 보낼 수 있어요")
    s = fstore.find_share(uid, req.postId)   # 같은 글이면 같은 링크를 다시 써요
    if s:
        if not s.get("active"):
            fstore.set_share_active(s["token"], True)
            s["active"] = True
    else:
        names = []
        for n in req.members:
            n = str(n).strip()[:12]
            if n and n not in names:
                names.append(n)
        s = fstore.add_share(secrets.token_urlsafe(9), user_id=uid, post_id=req.postId, record_id=req.recordId,
                             title=p["title"], members=names[:10])
    return _share_out(s, _base(request))


@app.get("/api/shares/{token}")
def get_share(request: Request, token: str):
    s = fstore.get_share(token)
    if not s:
        raise HTTPException(404, "없는 링크예요")
    return _share_out(s, _base(request))


@app.put("/api/shares/{token}")
def set_share(token: str, req: ShareActiveReq, uid: int = Depends(require_user)):
    s = fstore.get_share(token)
    if not s or s.get("user_id") != uid:
        raise HTTPException(404, "없는 링크예요")
    fstore.set_share_active(token, req.active)
    return {"ok": True, "active": req.active}


@app.post("/api/shares/{token}/feedback")
def share_feedback(token: str, req: ShareFeedbackReq):
    s = fstore.get_share(token)
    if not s:
        raise HTTPException(404, "없는 링크예요")
    if not s.get("active"):
        raise HTTPException(410, "보낸 사람이 링크를 꺼서 의견을 남길 수 없어요")
    members = s.get("members") or []
    answers = {k: v for k, v in req.answers.items() if v in ("ate", "left") and (k in members or not members)}
    comment = req.comment.strip()
    if not answers and not comment:
        raise HTTPException(400, "먹은 정도를 고르거나 남기고 싶은 말을 적어 주세요")
    if not fstore.add_share_feedback(token, s["user_id"], s["title"], answers, comment, SHARE_MAX_RESPONSES):
        raise HTTPException(429, "이 링크로 받을 수 있는 의견이 가득 찼어요")
    return {"ok": True}


# ---------------------------------------------------------------- 3) AI: 사진 재료 인식 · 레시피 추천
@app.post("/api/ingredients/analyze")
async def analyze(fridge: UploadFile | None = File(default=None), receipt: UploadFile | None = File(default=None)):
    photos = []
    for kind, f in (("fridge", fridge), ("receipt", receipt)):
        if f is None:
            continue
        if f.content_type not in PHOTO_TYPES:
            raise HTTPException(400, "사진 파일만 올릴 수 있어요")
        data = await f.read()
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "사진은 5MB 이하만 올릴 수 있어요")
        photos.append((kind, data, f.content_type))
    if not photos:
        raise HTTPException(400, "사진을 한 장 이상 넣어 주세요")
    result = await vision.analyze(photos)   # 사진은 저장하지 않고 재료 이름만 돌려줘요
    del photos
    return result


class Member(BaseModel):
    name: str = ""
    age: str | None = None
    allergies: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class RecommendReq(BaseModel):
    ingredients: list[str] = Field(default_factory=list)
    excludeIds: list[str] = Field(default_factory=list)
    excludeTitles: list[str] = Field(default_factory=list)
    members: list[Member] = Field(default_factory=list)   # 추천에는 쓰지 않고 안전 검사에만 써요
    count: int = 3


@app.post("/api/recipes/recommend")
async def recommend(req: RecommendReq):
    count = max(1, min(req.count, 3))
    ingredients = recipes.stock_only(req.ingredients)
    # 추천은 재료만으로: AI가 먼저 만들고, 모자라면 기본 레시피에서 채워요
    picked = await recipes.ai_recommend(ingredients, req.excludeTitles, count)
    if len(picked) < count:
        exclude = list(req.excludeIds) + [r["id"] for r in picked]
        for r in recipes.rank_pool(ingredients, exclude, count):
            if len(picked) < count and r["title"] not in req.excludeTitles:
                picked.append(r)
    members = [m.model_dump() for m in req.members]
    for r in picked:
        r["safety"] = await safety.check_recipe(r, members)
    return {"recipes": picked}


class SafetyReq(BaseModel):
    recipe: dict
    members: list[Member] = Field(default_factory=list)


@app.post("/api/safety/check")
async def safety_check(req: SafetyReq):
    return await safety.check_recipe(req.recipe, [m.model_dump() for m in req.members])


# ---------------------------------------------------------------- AI 레시피 요리 사진 (gpt-image-2)
class RecipeImageReq(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    ingredients: list[str] = Field(default_factory=list)


def _image_url(request: Request, image_id: int) -> str:
    return f"{_base(request)}/api/recipe-images/{image_id}"


@app.post("/api/recipes/image")
async def recipe_image(req: RecipeImageReq, request: Request):
    """요리 사진을 돌려줘요. 이미 그린 요리면 저장된 사진을, 처음이면 새로 그려요."""
    key = images.title_key(req.title)
    found = await run_in_threadpool(fstore.find_recipe_image, key)
    if found:
        return {"url": _image_url(request, found), "cached": True}
    if not images.enabled():
        raise HTTPException(503, "요리 사진을 만들 수 없어요")
    async with images.lock_for(key):      # 같은 요리를 동시에 두 번 그리지 않게
        found = await run_in_threadpool(fstore.find_recipe_image, key)
        if found:
            return {"url": _image_url(request, found), "cached": True}
        data = await images.generate(req.title, [str(x)[:20] for x in req.ingredients][:8])
        if not data:
            raise HTTPException(502, "요리 사진을 만들지 못했어요")
        iid = await run_in_threadpool(fstore.add_recipe_image, key, req.title[:80], data)
        return {"url": _image_url(request, iid), "cached": False}


@app.get("/api/recipe-images/{image_id}")
def get_recipe_image(image_id: int):
    return _photo_response(fstore.get_photo(f"img-{image_id}"), "public, max-age=604800")


# ---------------------------------------------------------------- 나만의 레시피북 (내 식사 기록)
def _record_out(r: dict, base: str, share: dict | None = None, responses: list[dict] | None = None) -> dict:
    created = r.get("created_at")
    out = {"id": r["id"], "title": r["title"], "comment": r.get("comment", ""), "autoTags": r.get("auto_tags") or [],
           "userTags": r.get("user_tags") or [], "recipe": r.get("recipe"), "visibility": r.get("visibility", "private"),
           "photoUrl": f"{base}/api/records/photo/{r['photo_key']}" if r.get("has_photo") else None,
           "createdAt": created.isoformat() if created else None}
    if share:
        out["share"] = {"token": share["token"], "active": bool(share.get("active")), "postId": share["post_id"]}
        out["responses"] = [{"answers": x["answers"], "comment": x["comment"],
                             "createdAt": x["created_at"].isoformat() if x["created_at"] else None} for x in responses or []]
    return out


@app.get("/api/records")
def list_records(request: Request, uid: int = Depends(require_user)):
    base = _base(request)
    shares = {s.get("record_id"): s for s in fstore.shares_of(uid) if s.get("record_id")}
    responses = fstore.share_responses(uid) if shares else {}
    out = []
    for r in fstore.list_records(uid):
        s = shares.get(r["id"])
        out.append(_record_out(r, base, s, responses.get(s["token"]) if s else None))
    return {"records": out}


@app.post("/api/records")
async def create_record(request: Request, data: str = Form(...), photo: UploadFile | None = File(default=None),
                        uid: int = Depends(require_user)):
    try:
        d = json.loads(data)
    except ValueError:
        raise HTTPException(400, "기록 내용을 읽지 못했어요")
    img, mime = (await _read_photo(photo)) if photo is not None else (None, None)
    recipe = d.get("recipe")
    if recipe:
        recipe = {k: recipe.get(k) for k in ("title", "minutes", "servings", "ingredients", "ing", "sauce", "steps")}
    r = await run_in_threadpool(lambda: fstore.add_record(
        user_id=uid, title=str(d.get("recipeTitle") or "우리 집 한상")[:60], comment=str(d.get("comment") or "")[:100],
        auto_tags=[str(t)[:20] for t in (d.get("autoTags") or [])][:6], user_tags=[str(t)[:12] for t in (d.get("myTags") or [])][:5],
        recipe=recipe, visibility="share" if d.get("visibility") == "share" else "private",
        photo=img, photo_type=mime, photo_key=secrets.token_urlsafe(24)))
    return _record_out(r, _base(request))


@app.get("/api/records/photo/{key}")
def record_photo(key: str):
    return _photo_response(fstore.get_photo(key), "private, max-age=86400")


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int, uid: int = Depends(require_user)):
    r = fstore.get_record(record_id)
    if not r or r.get("user_id") != uid:
        raise HTTPException(404, "기록이 없어요")
    fstore.delete_record(record_id)
    return {"ok": True}
