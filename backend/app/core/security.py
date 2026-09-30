import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_hasher = PasswordHasher()
ACCESS_TOKEN_SECONDS = 900


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        if encoded.startswith("scrypt$"):
            _, salt, digest = encoded.split("$", 2)
            return secrets.compare_digest(hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex(), digest)
        return _hasher.verify(encoded, password)
    except (VerificationError, ValueError):
        return False


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: str, role: str, secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "role": role, "exp": now + timedelta(seconds=ACCESS_TOKEN_SECONDS)}, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
