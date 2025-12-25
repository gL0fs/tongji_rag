import uvicorn
import json
import redis
import jwt
import datetime
import uuid
from jwt.exceptions import PyJWTError, ExpiredSignatureError
from fastapi import FastAPI, Header, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from typing import Set

from app.config import settings
from app.dto import RequestPayload, UserContext, LoginRequest, LoginResponse, RefreshRequest
from app.database import get_db
from app.models_db import User
from app.pipelines import PublicPipeline, ScholarPipeline, InternalPipeline, PersonalPipeline

app = FastAPI(title="Tongji RAG System")

# --- 基础设施初始化 ---
redis_client = redis.Redis(
    host=settings.REDIS_HOST, 
    port=settings.REDIS_PORT, 
    password=settings.REDIS_PASSWORD,
    decode_responses=True
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 权限常量定义 ---
ROLE_GUEST = "guest"
ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"
ROLE_SCHOLAR = "scholar"

# 路由权限表
ROUTE_PERMISSIONS = {
    "public": {ROLE_GUEST, ROLE_STUDENT, ROLE_TEACHER, ROLE_SCHOLAR},
    "academic": {ROLE_STUDENT, ROLE_TEACHER, ROLE_SCHOLAR},
    "internal": {ROLE_STUDENT, ROLE_TEACHER},
    "personal": {ROLE_STUDENT, ROLE_TEACHER}
}

# Pipeline 工厂
pipelines = {
    "public": PublicPipeline(),
    "academic": ScholarPipeline(),
    "internal": InternalPipeline(),
    "personal": PersonalPipeline()
}

# --- 辅助函数 ---
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def create_tokens(user_id: str, role: str, dept: str = None):
    # 1. Access Token (短期)
    access_expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_payload = {
        "sub": user_id,
        "role": role,
        "dept": dept,
        "type": "access",
        "exp": access_expire
    }
    access_token = jwt.encode(access_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # 2. Refresh Token (长期)
    refresh_expire = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": refresh_expire
    }
    refresh_token = jwt.encode(refresh_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return access_token, refresh_token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

# --- 鉴权依赖 (Dependency) ---
async def get_current_user(authorization: str = Header(None)) -> UserContext:
    if not authorization:
        return UserContext(user_id="guest", user_role=ROLE_GUEST)
    
    token = authorization.replace("Bearer ", "")
    
    try:
        # 只做 CPU 校验，不查 DB/Redis，速度极快
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        return UserContext(
            user_id=str(payload.get("sub")),
            user_role=payload.get("role", ROLE_GUEST),
            dept_id=payload.get("dept")
        )
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- API 接口 ---

@app.post("/api/v1/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    # 1. 查库
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalars().first()

    # 2. 校验
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    # 3. 发证
    at, rt, expires_in = create_tokens(str(user.id), user.role, user.dept_id)
    
    # 4. 存 Refresh Token 到 Redis (白名单)
    redis_key = f"{settings.REDIS_REFRESH_PREFIX}{rt}"
    # 存 user_id 作为 value
    redis_client.set(redis_key, str(user.id), ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600)
    
    return LoginResponse(
        access_token=at, 
        refresh_token=rt, 
        expires_in=expires_in,
        user_info={"name": user.full_name, "role": user.role}
    )

@app.post("/api/v1/refresh")
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    rt = request.refresh_token
    redis_key = f"{settings.REDIS_REFRESH_PREFIX}{rt}"
    
    # 1. 查 Redis 是否存在
    user_id = redis_client.get(redis_key)
    if not user_id:
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")
    
    # 2. 查最新的用户信息 (防止期间角色变更)
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # 3. 签发新的 Access Token
    new_at, _, expires_in = create_tokens(str(user.id), user.role, user.dept_id)
    
    # Refresh Token 不变，除非你想实现滚动刷新
    return {"access_token": new_at, "refresh_token": rt, "expires_in": expires_in, "user_info": {"name": user.full_name}}

@app.post("/api/v1/logout")
async def logout(request: RefreshRequest):
    redis_key = f"{settings.REDIS_REFRESH_PREFIX}{request.refresh_token}"
    redis_client.delete(redis_key)
    return {"message": "Logged out successfully"}

@app.post("/api/v1/chat/{type}")
async def chat_endpoint(
    type: str, 
    payload: RequestPayload, 
    user: UserContext = Depends(get_current_user)
):
    # 1. 路由是否存在
    if type not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    
    # 2. 权限校验
    allowed_roles = ROUTE_PERMISSIONS.get(type, set())
    if user.user_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"Access Denied for role: {user.user_role}"
        )

    # 3. 执行流式生成
    pipeline = pipelines[type]

    async def event_generator():
        try:
            for chunk in pipeline.execute(payload, user):
                data = json.dumps({"chunk": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            err_msg = json.dumps({"error": str(e)})
            yield f"data: {err_msg}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)