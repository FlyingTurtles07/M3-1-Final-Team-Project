"""환경 변수 읽기.

키·비밀번호는 코드에 넣지 않아요. 내 컴퓨터에서는 backend/api/.env, 배포(Render)에서는 Environment 설정에만 넣습니다.
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str          # 공개 가능한 키 (로그인한 사용자의 토큰과 함께 DB를 호출할 때 사용)
    supabase_service_role_key: str  # 비밀 키: 계정 삭제에만 사용. 프론트·GitHub에 절대 노출 금지
    health_data_key: str            # 건강 정보 암호화 키 (쉼표로 여러 개 넣으면 앞의 것으로 암호화, 나머지는 옛 데이터 복호화용)
    cors_origins: tuple[str, ...]
    policy_version: str             # 동의 문구(약관) 버전. 문구를 바꾸면 이 값도 함께 바꿔요


@lru_cache
def get_settings() -> Settings:
    return Settings(
        supabase_url=os.getenv("SUPABASE_URL", "").strip().rstrip("/"),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", "").strip(),
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        health_data_key=os.getenv("HEALTH_DATA_KEY", "").strip(),
        cors_origins=tuple(o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()),
        policy_version=os.getenv("POLICY_VERSION", "2026-10-19").strip(),
    )
