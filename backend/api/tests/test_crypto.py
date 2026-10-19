import pytest
from cryptography.fernet import Fernet

from .. import config, crypto


def test_암호화했다_복호화하면_원래대로(monkeypatch):
    token = crypto.encrypt_json({"allergies": ["땅콩"], "notes": "한글 ✓"})
    assert "땅콩" not in token
    assert crypto.decrypt_json(token) == {"allergies": ["땅콩"], "notes": "한글 ✓"}


def test_같은_내용도_매번_다른_문장이_된다():
    assert crypto.encrypt_json({"a": 1}) != crypto.encrypt_json({"a": 1})


def test_키를_교체해도_옛_데이터를_읽을_수_있다(monkeypatch):
    old = Fernet.generate_key().decode()
    monkeypatch.setenv("HEALTH_DATA_KEY", old)
    config.get_settings.cache_clear()
    token = crypto.encrypt_json({"x": 1})
    new = Fernet.generate_key().decode()
    monkeypatch.setenv("HEALTH_DATA_KEY", f"{new},{old}")
    config.get_settings.cache_clear()
    assert crypto.decrypt_json(token) == {"x": 1}
    assert crypto.decrypt_json(crypto.encrypt_json({"y": 2})) == {"y": 2}


def test_다른_키로는_복호화할_수_없다(monkeypatch):
    token = crypto.encrypt_json({"x": 1})
    monkeypatch.setenv("HEALTH_DATA_KEY", Fernet.generate_key().decode())
    config.get_settings.cache_clear()
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_json(token)


@pytest.mark.parametrize("value", ["", "짧은키"])
def test_키가_없거나_잘못되면_분명한_오류(monkeypatch, value):
    monkeypatch.setenv("HEALTH_DATA_KEY", value)
    config.get_settings.cache_clear()
    with pytest.raises(crypto.CryptoError):
        crypto.encrypt_json({"x": 1})
