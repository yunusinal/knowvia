from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

# Argon2 kullanır; her hash'e rastgele bir salt ekler.
_password_hash = PasswordHash.recommended()

# Var olmayan kullanıcı için de parola kontrolü yapılır; böylece cevap süresi
# e-postanın kayıtlı olup olmadığını ele vermez (timing attack).
DUMMY_PASSWORD_HASH = _password_hash.hash("dummy-password")

_JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(user_id: str) -> str:
    """Kullanıcı kimliğini (sub) ve son geçerlilik zamanını (exp) içeren imzalı JWT üretir."""
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """İmzası ve süresi geçerliyse kullanıcı kimliğini döndürür; aksi halde None."""
    try:
        # Algoritma açıkça sabitlenir; token'ın kendi "alg" alanına güvenilmez.
        payload = jwt.decode(
            token, get_settings().jwt_secret_key.get_secret_value(), algorithms=[_JWT_ALGORITHM]
        )
    except jwt.InvalidTokenError:
        return None
    user_id = payload.get("sub")
    return user_id if isinstance(user_id, str) else None
