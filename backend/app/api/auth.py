import os

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.users import create_user, get_user_by_email, set_user_role
from app.models.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    RoleRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_SIGNUP_CODE_REQUIRED_MSG = (
    "Registration requires an invite code. Ask the person who invited you for the code."
)
_SIGNUP_CODE_WRONG_MSG = (
    "That invite code is not valid. Check it and try again, or ask for a new invite."
)


def _user_out(user: dict) -> UserOut:
    return UserOut(id=user["id"], email=user["email"], role=user.get("role"))


def _required_signup_code() -> str:
    """When SIGNUP_CODE is set (non-empty), registration requires a matching code."""
    return (os.getenv("SIGNUP_CODE") or "").strip()


@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest):
    expected = _required_signup_code()
    if expected:
        got = (body.signup_code or "").strip()
        if not got:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_SIGNUP_CODE_REQUIRED_MSG,
            )
        if got != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_SIGNUP_CODE_WRONG_MSG,
            )
    if get_user_by_email(body.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    user = create_user(body.email, hash_password(body.password))
    token = create_access_token(user["id"], user["email"])
    return AuthResponse(access_token=token, user=_user_out(user))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest):
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(user["id"], user["email"])
    return AuthResponse(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(current_user: dict = Depends(get_current_user)):
    return UserOut(**current_user)


@router.post("/role", response_model=UserOut)
def choose_role(body: RoleRequest, current_user: dict = Depends(get_current_user)):
    updated = set_user_role(current_user["id"], body.role)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_out(updated)
