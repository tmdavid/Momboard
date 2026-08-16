"""Authentication utilities: password hashing, session management, dependencies."""


from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.models import User

ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password with argon2."""
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_session_token(user_id: int, secret: str) -> str:
    """Create a signed session token."""
    s = URLSafeTimedSerializer(secret)
    return s.dumps({"user_id": user_id})


def decode_session_token(token: str, secret: str, max_age: int = 86400 * 7) -> int | None:
    """Decode a session token, returning user_id or None."""
    s = URLSafeTimedSerializer(secret)
    try:
        data = s.loads(token, max_age=max_age)
        user_id: int | None = data.get("user_id")  # type: ignore[union-attr]
        return user_id
    except (BadSignature, Exception):
        return None


async def get_current_user(request: Request) -> User:
    """Dependency: extract user from session cookie."""
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    settings = request.app.state.settings
    user_id = decode_session_token(session_token, settings.session_secret)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        user: User | None = await db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency: require admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
