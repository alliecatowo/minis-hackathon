import base64
import hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings


def _derive_key() -> bytes:
    if settings.encryption_key:
        derived = HKDF(
            algorithm=SHA256(),
            length=32,
            salt=None,
            info=b"minis-encryption-key",
        ).derive(settings.encryption_key.encode())
        return base64.urlsafe_b64encode(derived)

    # Fallback: derive from JWT secret for backward compat
    key = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(key)


_fernet = Fernet(_derive_key())


def encrypt_value(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
