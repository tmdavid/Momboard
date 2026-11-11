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


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOKEN_ADMIN_PREFIX = "/api/tokens"


async def _user_from_bearer(request: Request, presented: str) -> User:
    """Authenticate an API token (``Authorization: Bearer mb_...``).

    Every failure is the same 401, so nothing reveals whether a token exists, was revoked or expired.
    The token acts with its owner's permissions and nothing more: a read token may only use safe
    methods, and no token may manage tokens (so a leaked one cannot mint others).
    """
    from app.services.api_tokens import has_scope, verify_token

    async with request.app.state.session_factory() as db:
        verified = await verify_token(db, presented)
        if verified is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        await db.commit()  # persists last_used_at when it was refreshed
        token, user = verified.token, verified.user

    if request.url.path.startswith(TOKEN_ADMIN_PREFIX):
        raise HTTPException(status_code=403, detail="API tokens cannot manage tokens. Sign in to MomBoard to do that.")
    if request.method not in SAFE_METHODS and not has_scope(token, "write"):
        raise HTTPException(status_code=403, detail="This token is read-only.")
    request.state.api_token = token
    return user


async def get_current_user(request: Request) -> User:
    """Dependency: the signed-in user, from an API token (bearer) or the session cookie.

    A bearer header that is present but wrong is refused outright; it never falls back to a cookie.
    """
    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer":
        return await _user_from_bearer(request, credential.strip())

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
