"""Auth routes: login/logout."""

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from app.api.schemas import LoginRequest, UserResponse
from app.auth import create_session_token, verify_password
from app.models import User

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login", response_model=UserResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    """Authenticate and set session cookie."""
    session_factory = request.app.state.session_factory
    settings = request.app.state.settings

    async with session_factory() as db:
        result = await db.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_session_token(user.id, settings.session_secret)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
    )
    return UserResponse(id=user.id, email=user.email, name=user.name, role=user.role)


@auth_router.post("/logout")
async def logout(response: Response):
    """Clear session cookie."""
    response.delete_cookie("session")
    return {"ok": True}
