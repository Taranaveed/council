from pydantic import BaseModel, EmailStr, Field
from typing import Literal, Optional


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RoleRequest(BaseModel):
    role: Literal["business", "buyer"]


class UserOut(BaseModel):
    id: int
    email: str
    role: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
