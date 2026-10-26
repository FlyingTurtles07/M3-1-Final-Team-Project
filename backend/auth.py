"""회원 인증: 비밀번호 해시(PBKDF2) + 로그인 토큰(JWT)."""
import hashlib
import hmac
import logging
import os
import secrets
import time

import jwt
from fastapi import Header, HTTPException

log = logging.getLogger("hansang.auth")

SECRET = os.getenv("JWT_SECRET", "")
if not SECRET:
    SECRET = "dev-only-secret"   # 내 컴퓨터 테스트용. Render에서는 JWT_SECRET 환경변수를 꼭 넣어요
    log.warning("JWT_SECRET이 없어서 개발용 비밀값을 써요. 배포 환경에서는 꼭 설정하세요.")
TOKEN_DAYS = 30
ITERATIONS = 200_000


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, TypeError):
        return False


def make_token(user_id: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + TOKEN_DAYS * 86400}, SECRET, algorithm="HS256")


def _user_id(authorization: str | None) -> int | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        data = jwt.decode(authorization[7:].strip(), SECRET, algorithms=["HS256"])
        return int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def optional_user(authorization: str | None = Header(default=None)) -> int | None:
    """로그인했으면 회원 번호, 아니면 None"""
    return _user_id(authorization)


def require_user(authorization: str | None = Header(default=None)) -> int:
    uid = _user_id(authorization)
    if uid is None:
        raise HTTPException(status_code=401, detail="로그인이 필요해요")
    return uid
