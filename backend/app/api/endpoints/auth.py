from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.auth_service import auth_service, get_current_user


router = APIRouter()


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    account: str = Field(default="", min_length=0, max_length=255)
    email: str = Field(default="", min_length=0, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


@router.post("/register")
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await auth_service.register_user(
            db,
            email=request.email,
            password=request.password,
            name=request.name,
        )
        return {
            "success": True,
            "message": "注册成功",
            **result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        identifier = (request.account or request.email).strip()
        result = await auth_service.login_user(
            db,
            identifier=identifier,
            password=request.password,
        )
        return {
            "success": True,
            "message": "登录成功",
            **result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return {
        "success": True,
        "user": current_user.to_dict(),
    }
