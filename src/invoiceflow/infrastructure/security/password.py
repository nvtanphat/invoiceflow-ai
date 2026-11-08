from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash password using OWASP-recommended Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify plain password against Argon2 hash with timing attack resistance."""
    if not hashed_password or not password:
        return False
    try:
        return _hasher.verify(hashed_password, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False
