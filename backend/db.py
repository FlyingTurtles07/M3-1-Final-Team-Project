"""데이터베이스 (SQLAlchemy).

- Render에서는 DATABASE_URL(Postgres)을 쓰고, 내 컴퓨터에서는 설정이 없으면 SQLite 파일(local.db)을 써요.
- 회원별 데이터(가족 프로필·재료·보관함)는 user_docs 에 JSON 한 덩어리로 저장해요.
- 공유 글 사진은 작게 줄인 JPEG를 posts.photo 에 그대로 저장해요 (시제품 단계라 별도 저장소 없이).
"""
import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip() or "sqlite:///./local.db"
    # Render는 postgres:// 또는 postgresql:// 주소를 줘요 → psycopg(v3) 드라이버로 바꿔요
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(40))
    pw_hash: Mapped[str] = mapped_column(String(200))          # 비밀번호는 해시만 저장해요
    consents: Mapped[dict] = mapped_column(JSON, default=dict)  # 약관 동의 기록 (동의 시각 포함)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UserDoc(Base):
    """회원별 데이터 묶음: family(가족 프로필) / pantry(확인한 재료) / saved(보관함) / collections(묶음)"""
    __tablename__ = "user_docs"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(30), primary_key=True)
    data: Mapped[object] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Post(Base):
    """다른 집 한상 게시물"""
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(60))
    comment: Mapped[str] = mapped_column(Text, default="")
    auto_tags: Mapped[list] = mapped_column(JSON, default=list)
    user_tags: Mapped[list] = mapped_column(JSON, default=list)
    recipe: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # 함께 공유한 공통 레시피
    photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # 올린 사진 (위치정보 지운 JPEG)
    photo_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(300), nullable=True)  # 예시 글은 화면 쪽 사진 경로
    ai_image: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # 알레르기 안전 확인을 통과했는지
    likes: Mapped[int] = mapped_column(Integer, default=0)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)    # 신고가 쌓이면 숨겨요
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PostLike(Base):
    __tablename__ = "post_likes"
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Report(Base):
    """신고 접수 → 운영자 확인·처리 이력"""
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="접수")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Feedback(Base):
    """식사 후 의견 (다음 추천에 반영할 자료)"""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    recipe_id: Mapped[str] = mapped_column(String(80), default="")
    recipe_title: Mapped[str] = mapped_column(String(80), default="")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def init_db() -> None:
    Base.metadata.create_all(engine)
