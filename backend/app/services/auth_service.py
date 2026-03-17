from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db import get_db
from app.models.user import User


bearer_scheme = HTTPBearer(auto_error=False)


class AuthService:
    async def get_user_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        normalized_email = email.strip().lower()
        result = await db.execute(select(User).where(User.email == normalized_email))
        return result.scalar_one_or_none()

    async def register_user(
        self,
        db: AsyncSession,
        *,
        email: str,
        password: str,
        name: str,
    ) -> Dict[str, Any]:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("邮箱不能为空")
        if len(password) < 6:
            raise ValueError("密码长度不能少于 6 位")
        if not name.strip():
            raise ValueError("用户名不能为空")

        existing_user = await self.get_user_by_email(db, normalized_email)
        if existing_user:
            raise ValueError("该邮箱已注册")

        now = datetime.utcnow()
        user = User(
            id=uuid.uuid4().hex,
            email=normalized_email,
            name=name.strip(),
            password_hash=hash_password(password),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        return {
            "user": user.to_dict(),
            "access_token": create_access_token(user.id),
            "token_type": "bearer",
        }

    async def login_user(
        self,
        db: AsyncSession,
        *,
        email: str,
        password: str,
    ) -> Dict[str, Any]:
        user = await self.get_user_by_email(db, email)
        if not user or not verify_password(password, user.password_hash):
            raise ValueError("邮箱或密码错误")
        if not user.is_active:
            raise ValueError("用户已被禁用")

        return {
            "user": user.to_dict(),
            "access_token": create_access_token(user.id),
            "token_type": "bearer",
        }


auth_service = AuthService()


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已失效")

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await auth_service.get_user_by_id(db, str(payload.get("sub")))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已失效")
    return user
