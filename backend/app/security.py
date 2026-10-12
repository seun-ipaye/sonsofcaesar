from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Argon2: a deliberately slow, salted hash, so stolen hashes are useless
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
