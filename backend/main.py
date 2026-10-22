"""온가족 한상 백엔드 (FastAPI).

실행:  uvicorn main:app --reload        (backend 폴더에서)
문서:  http://localhost:8000/docs

1) 회원: 가입·로그인(토큰), 가족 프로필·재료·보관함 저장           /api/auth/*, /api/me, /api/me/data/{key}
2) 공유: 다른 집 한상 글(사진·레시피) 저장·조회·좋아요·신고·삭제    /api/posts*
3) AI:   사진 재료 인식, 레시피 3개 추천                            /api/ingredients/analyze, /api/recipes/recommend
4) 안전: 알레르기·당뇨식·저염식 검사                                /api/safety/check (추천 결과에도 함께 들어가요)
"""
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))   # 다른 모듈이 환경변수를 읽기 전에 불러와요

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

import images  # noqa: E402
import recipes  # noqa: E402
import safety  # noqa: E402
import vision  # noqa: E402
from auth import check_password, hash_password, make_token, optional_user, require_user  # noqa: E402
from db import Feedback, Post, PostLike, RecipeImage, Report, SessionLocal, User, UserDoc, init_db, now  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hansang")

app = FastAPI(title="온가족 한상 API", version="1.0")
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
    init_db()
    _seed_posts()


def _seed_posts() -> None:
    """처음 시작할 때 예시 게시물을 넣어 둬요 (게시물이 하나도 없을 때만)"""
    with SessionLocal() as s:
        if s.scalar(select(func.count()).select_from(Post)):
            return
        data = json.loads((Path(__file__).with_name("data") / "sample_posts.json").read_text(encoding="utf-8"))
        for p in data:
            s.add(Post(title=p["title"], comment=p.get("comment", ""), auto_tags=p.get("autoTags", []),
                       user_tags=p.get("userTags", []), recipe=p.get("recipe"), photo_url=p.get("photoUrl"),
                       ai_image=bool(p.get("aiImage")), verified=bool(p.get("verified")), likes=int(p.get("likes", 0))))
        s.commit()
        log.info("예시 게시물 %d개를 넣었어요", len(data))


# ---------------------------------------------------------------- 상태
@app.get("/api/health")
def health():
    ok = True
    try:
        with SessionLocal() as s:
            s.execute(select(1))
    except Exception:
        ok = False
    return {"ok": ok, "db": ok, "ai": bool(os.getenv("OPENAI_API_KEY")), "images": images.enabled(), "mfds": bool(safety.MFDS_API_KEY)}


# ---------------------------------------------------------------- 1) 회원
class SignupReq(BaseModel):
    name: str = Field(min_length=2, max_length=12)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=100)
    consents: dict = Field(default_factory=dict)   # {terms, privacy, health, marketing, age14}


class LoginReq(BaseModel):
    email: str
    password: str


def _user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email}


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
    consents["agreedAt"] = now().isoformat()
    with SessionLocal() as s:
        u = User(email=email, name=req.name.strip(), pw_hash=hash_password(req.password), consents=consents)
        s.add(u)
        try:
            s.commit()
        except IntegrityError:
            raise HTTPException(409, "이미 가입된 이메일이에요")
        return {"token": make_token(u.id), "user": _user_out(u)}


@app.post("/api/auth/login")
def login(req: LoginReq):
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == req.email.strip().lower()))
        if not u or not check_password(req.password, u.pw_hash):
            raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요")
        return {"token": make_token(u.id), "user": _user_out(u)}


@app.get("/api/me")
def me(uid: int = Depends(require_user)):
    with SessionLocal() as s:
        u = s.get(User, uid)
        if not u:
            raise HTTPException(401, "로그인이 필요해요")
        return _user_out(u)


@app.delete("/api/me")
def withdraw(uid: int = Depends(require_user)):
    """탈퇴: 계정·가족·건강 정보·게시물을 모두 지워요"""
    with SessionLocal() as s:
        u = s.get(User, uid)
        if u:
            for model in (UserDoc, PostLike, Feedback):
                s.query(model).filter(model.user_id == uid).delete()
            s.query(Post).filter(Post.user_id == uid).delete()
            s.delete(u)
            s.commit()
    return {"ok": True}


class DocReq(BaseModel):
    data: object


@app.get("/api/me/data/{key}")
def get_doc(key: str, uid: int = Depends(require_user)):
    if key not in DOC_KEYS:
        raise HTTPException(404, "없는 항목이에요")
    with SessionLocal() as s:
        d = s.get(UserDoc, (uid, key))
        return {"data": d.data if d else None}


@app.put("/api/me/data/{key}")
def put_doc(key: str, req: DocReq, uid: int = Depends(require_user)):
    if key not in DOC_KEYS:
        raise HTTPException(404, "없는 항목이에요")
    if len(json.dumps(req.data, ensure_ascii=False).encode()) > MAX_DOC_BYTES:
        raise HTTPException(413, "저장할 내용이 너무 커요")
    with SessionLocal() as s:
        d = s.get(UserDoc, (uid, key))
        if d:
            d.data = req.data
            d.updated_at = now()
        else:
            s.add(UserDoc(user_id=uid, key=key, data=req.data))
        s.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 2) 다른 집 한상
def _post_out(p: Post, base: str, uid: int | None, liked: set[int]) -> dict:
    photo = f"{base}/api/posts/{p.id}/photo" if p.photo else p.photo_url
    return {"id": p.id, "title": p.title, "comment": p.comment, "autoTags": p.auto_tags or [], "userTags": p.user_tags or [],
            "likes": p.likes, "liked": p.id in liked, "verified": p.verified, "photoUrl": photo, "aiImage": p.ai_image,
            "recipe": p.recipe, "mine": uid is not None and p.user_id == uid, "createdAt": p.created_at.isoformat() if p.created_at else None}


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.get("/api/posts")
def list_posts(request: Request, text: str = "", tags: str = "", offset: int = 0, limit: int = 4,
               uid: int | None = Depends(optional_user)):
    tag_list = [t for t in tags.split(",") if t]
    need_safe = any(t.endswith("제외") for t in tag_list)   # 알레르기 제외 검색은 안전 확인된 글만
    q = text.strip().lower()
    with SessionLocal() as s:
        rows = s.scalars(select(Post).where(Post.hidden.is_(False))).all()
        reported = set(s.scalars(select(Report.post_id).where(Report.user_id == uid)).all()) if uid else set()
        liked = set(s.scalars(select(PostLike.post_id).where(PostLike.user_id == uid)).all()) if uid else set()
    out = []
    for p in rows:
        if p.id in reported or (need_safe and not p.verified):
            continue
        ok = True
        for t in tag_list:
            if t.startswith("#"):
                w = t[1:].lower()
                ok = any(u.lower() == w for u in (p.user_tags or [])) or w in (p.comment or "").lower()
            else:
                ok = t in (p.auto_tags or [])
            if not ok:
                break
        if not ok:
            continue
        if q:
            ings = " ".join((p.recipe or {}).get("ingredients") or [x[0] for x in (p.recipe or {}).get("ing") or []])
            hay = " ".join([p.title, p.comment or "", " ".join(p.user_tags or []), " ".join(p.auto_tags or []), ings]).lower()
            if q not in hay:
                continue
        out.append(p)
    out.sort(key=lambda p: (0 if (uid and p.user_id == uid) else 1, -p.likes, -p.id))   # 내 글 → 좋아요 많은 순
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
    if photo.content_type not in PHOTO_TYPES:
        raise HTTPException(400, "사진 파일(JPEG·PNG·WEBP)만 올릴 수 있어요")
    img = await photo.read()
    if len(img) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "사진은 5MB 이하만 올릴 수 있어요")
    recipe = d.get("recipe")
    if recipe:   # 공통 레시피만 남겨요 (가족 이름·건강 정보는 받지 않아요)
        recipe = {k: recipe.get(k) for k in ("title", "minutes", "servings", "ingredients", "ing", "sauce", "steps")}
    user_tags = [str(t)[:12] for t in (d.get("myTags") or [])][:5]
    with SessionLocal() as s:
        p = Post(user_id=uid, title=str(d.get("recipeTitle") or "우리 집 한상")[:60], comment=str(d.get("comment") or "")[:100],
                 auto_tags=[str(t)[:20] for t in (d.get("autoTags") or [])][:6], user_tags=user_tags, recipe=recipe,
                 photo=img, photo_type=photo.content_type, verified=False)
        s.add(p)
        s.commit()
        return _post_out(p, _base(request), uid, set())


@app.get("/api/posts/{post_id}/photo")
def post_photo(post_id: int):
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if not p or not p.photo or p.hidden:
            raise HTTPException(404, "사진이 없어요")
        return Response(p.photo, media_type=p.photo_type or "image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


class LikeReq(BaseModel):
    liked: bool


@app.post("/api/posts/{post_id}/like")
def like_post(post_id: int, req: LikeReq, uid: int = Depends(require_user)):
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if not p:
            raise HTTPException(404, "게시물이 없어요")
        has = s.get(PostLike, (post_id, uid))
        if req.liked and not has:
            s.add(PostLike(post_id=post_id, user_id=uid))
            p.likes += 1
        elif not req.liked and has:
            s.delete(has)
            p.likes = max(0, p.likes - 1)
        s.commit()
        return {"likes": p.likes, "liked": req.liked}


class ReportReq(BaseModel):
    reason: str = Field(min_length=1, max_length=100)


@app.post("/api/posts/{post_id}/report")
def report_post(post_id: int, req: ReportReq, uid: int | None = Depends(optional_user)):
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if not p:
            raise HTTPException(404, "게시물이 없어요")
        s.add(Report(post_id=post_id, user_id=uid, reason=req.reason))
        s.flush()
        if s.scalar(select(func.count()).select_from(Report).where(Report.post_id == post_id)) >= HIDE_AFTER_REPORTS:
            p.hidden = True   # 신고가 쌓이면 운영자가 확인할 때까지 숨겨요
        s.commit()
    return {"ok": True}


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, uid: int = Depends(require_user)):
    with SessionLocal() as s:
        p = s.get(Post, post_id)
        if not p:
            raise HTTPException(404, "게시물이 없어요")
        if p.user_id != uid:
            raise HTTPException(403, "내가 올린 글만 지울 수 있어요")
        s.delete(p)
        s.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 식사 후 의견
class FeedbackReq(BaseModel):
    recipeId: str = ""
    recipeTitle: str = ""
    answers: dict = Field(default_factory=dict)
    comment: str = Field(default="", max_length=200)


@app.post("/api/feedback")
def feedback(req: FeedbackReq, uid: int | None = Depends(optional_user)):
    with SessionLocal() as s:
        s.add(Feedback(user_id=uid, recipe_id=req.recipeId[:80], recipe_title=req.recipeTitle[:80],
                       answers=req.answers, comment=req.comment))
        s.commit()
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
    with SessionLocal() as s:
        found = s.scalar(select(RecipeImage).where(RecipeImage.key == key))
        if found:
            return {"url": _image_url(request, found.id), "cached": True}
    if not images.enabled():
        raise HTTPException(503, "요리 사진을 만들 수 없어요")
    async with images.lock_for(key):      # 같은 요리를 동시에 두 번 그리지 않게
        with SessionLocal() as s:
            found = s.scalar(select(RecipeImage).where(RecipeImage.key == key))
            if found:
                return {"url": _image_url(request, found.id), "cached": True}
        data = await images.generate(req.title, [str(x)[:20] for x in req.ingredients][:8])
        if not data:
            raise HTTPException(502, "요리 사진을 만들지 못했어요")
        with SessionLocal() as s:
            row = RecipeImage(key=key, title=req.title[:80], image=data)
            s.add(row)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                row = s.scalar(select(RecipeImage).where(RecipeImage.key == key))
            return {"url": _image_url(request, row.id), "cached": False}


@app.get("/api/recipe-images/{image_id}")
def get_recipe_image(image_id: int):
    with SessionLocal() as s:
        row = s.get(RecipeImage, image_id)
        if not row:
            raise HTTPException(404, "사진이 없어요")
        return Response(row.image, media_type=row.mime, headers={"Cache-Control": "public, max-age=604800"})
