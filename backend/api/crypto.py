"""건강 정보 암호화 (Fernet: AES-128-CBC + HMAC 로 변조까지 검출).

DB에는 암호화된 문장만 저장되고, 키는 HEALTH_DATA_KEY 환경 변수에만 있어요.
키를 새로 만들 때:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
키를 바꿀 때: HEALTH_DATA_KEY="새키,옛키" 로 두면 새 키로 암호화하고 옛 데이터도 읽을 수 있어요.
키를 잃어버리면 저장된 건강 정보는 복구할 수 없어요. 안전한 곳에 따로 보관하세요.
"""
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import get_settings


class CryptoError(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in get_settings().health_data_key.split(",") if k.strip()]
    if not keys:
        raise CryptoError("HEALTH_DATA_KEY 환경 변수가 설정되지 않았어요.")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as e:
        raise CryptoError("HEALTH_DATA_KEY 형식이 올바르지 않아요.") from e


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")


def decrypt_json(token: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode("ascii")).decode("utf-8"))
    except InvalidToken as e:
        raise CryptoError("건강 정보를 복호화하지 못했어요. (키가 바뀌었거나 데이터가 손상됨)") from e
