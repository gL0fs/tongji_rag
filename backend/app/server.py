import uvicorn
import json
import redis
import jwt
import datetime
import uuid
from jwt.exceptions import PyJWTError, ExpiredSignatureError
from fastapi import FastAPI, Header, HTTPException, Depends, status, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware 
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from typing import Set

from app.config import settings
from app.dto import (
    RequestPayload, UserContext, LoginRequest, LoginResponse, RefreshRequest,
    SessionSchema, SessionListResponse, SessionHistoryResponse, CreateSessionRequest
)
from app.database import get_db
from app.models_db import User 
from app.pipelines import PublicPipeline, ScholarPipeline, InternalPipeline, PersonalPipeline
from app.components import HistoryManager

VALID_SESSION_TYPES = {"public", "academic", "internal", "personal"}

app = FastAPI(title="Tongji RAG System")

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 基础设施初始化 ---
redis_client = redis.Redis(
    host=settings.REDIS_HOST, 
    port=settings.REDIS_PORT, 
    password=settings.REDIS_PASSWORD,
    decode_responses=True
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
history_manager = HistoryManager()

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

security = HTTPBearer(auto_error=False)

# --- 辅助函数 ---
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def create_tokens(user_id: str, role: str, dept: str = None):
    access_expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_payload = {
        "sub": user_id,
        "role": role,
        "dept": dept,
        "type": "access",
        "exp": access_expire
    }
    access_token = jwt.encode(access_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    refresh_expire = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": refresh_expire
    }
    refresh_token = jwt.encode(refresh_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return access_token, refresh_token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

# --- 鉴权依赖 ---
async def get_current_user(auth: HTTPAuthorizationCredentials = Depends(security)) -> UserContext:
    # 1. 如果没有携带 Authorization 头，auth 会是 None -> 降级为游客
    if not auth:
        return UserContext(user_id="guest", user_role=ROLE_GUEST)
    
    # 2. 提取 Token
    token = auth.credentials 

    try:
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
    # 兼容处理：init_sql.py 里插入的是 id=1, id=2...
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalars().first()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    at, rt, expires_in = create_tokens(str(user.id), user.role, user.dept_id)
    
    redis_key = f"{settings.REDIS_REFRESH_PREFIX}{rt}"
    redis_client.set(redis_key, str(user.id), ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600)
    
    return LoginResponse(
        access_token=at, 
        refresh_token=rt, 
        expires_in=expires_in,
        user_info={"name": user.full_name, "role": user.role}
    )

# 游客登录接口
@app.post("/api/v1/guest-login", response_model=LoginResponse)
async def guest_login():
    guest_id = f"guest_{uuid.uuid4()}"
    at, rt, expires_in = create_tokens(user_id=guest_id, role=ROLE_GUEST, dept=None)
    
    redis_key = f"{settings.REDIS_REFRESH_PREFIX}{rt}"
    redis_client.set(redis_key, guest_id, ex=86400)
    
    return LoginResponse(
        access_token=at, 
        refresh_token=rt, 
        expires_in=expires_in,
        user_info={
            "name": "访客", 
            "role": ROLE_GUEST,
            "id": guest_id
        }
    )

@app.post("/api/v1/refresh")
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    old_rt = request.refresh_token
    redis_key_old = f"{settings.REDIS_REFRESH_PREFIX}{old_rt}"
    
    user_id = redis_client.get(redis_key_old)
    if not user_id:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    
    user_role = ROLE_GUEST
    user_name = "访客"
    user_dept = None

    if str(user_id).startswith("guest_"):
        user_role = ROLE_GUEST
    else:
        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user_role = user.role
        user_name = user.full_name
        user_dept = user.dept_id

    new_at, new_rt, expires_in = create_tokens(str(user_id), user_role, user_dept)
    
    pipe = redis_client.pipeline()
    try:
        pipe.delete(redis_key_old)
        redis_key_new = f"{settings.REDIS_REFRESH_PREFIX}{new_rt}"
        ttl = 86400 if user_role == ROLE_GUEST else settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
        pipe.set(redis_key_new, str(user_id), ex=ttl)
        pipe.execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail="Token rotation failed")
    
    return {
        "access_token": new_at, 
        "refresh_token": new_rt, 
        "expires_in": expires_in, 
        "user_info": {"name": user_name}
    }

@app.post("/api/v1/logout")
async def logout(request: RefreshRequest):
    redis_key = f"{settings.REDIS_REFRESH_PREFIX}{request.refresh_token}"
    redis_client.delete(redis_key)
    return {"message": "Logged out successfully"}

# 会话管理
@app.post("/api/v1/session/new", response_model=SessionSchema)
async def create_new_session(
    request: CreateSessionRequest,  # 改为接收 JSON Body
    user: UserContext = Depends(get_current_user)
):
    # 权限与类型校验
    if request.type not in VALID_SESSION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid session type")

    # 权限检查：比如 guest 不能创建 internal
    allowed_roles = ROUTE_PERMISSIONS.get(request.type, set())
    if user.user_role not in allowed_roles:
         raise HTTPException(status_code=403, detail=f"Permission denied for {request.type}")

    if user.user_role == ROLE_GUEST:
        pass 
    elif not user.is_authenticated():
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # 传入 type
    session_id = history_manager.create_session(
        user.user_id, 
        session_type=request.type, 
        title="新对话"
    )
    
    return SessionSchema(
        session_id=session_id,
        title="新对话",
        type=request.type,
        created_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

@app.delete("/api/v1/session/{session_id}")
async def delete_session_endpoint(
    session_id: str,
    user: UserContext = Depends(get_current_user)
):
    """
    删除指定会话
    """
    # 1. 权限校验：访客或登录用户均可删除自己的会话
    if not user.user_id:
        raise HTTPException(status_code=401, detail="User identity missing")

    # 2. 调用管理器执行删除
    success = history_manager.delete_session(user.user_id, session_id)

    if not success:
        # 如果删除失败，通常意味着 session_id 不存在或者不属于该用户
        raise HTTPException(
            status_code=404, 
            detail="Session not found or permission denied"
        )
    
    return {"message": "Session deleted successfully", "session_id": session_id}

@app.get("/api/v1/session/list", response_model=SessionListResponse)
async def get_session_list(
    type: str = "public",  # 接收 Query 参数 ?type=xxx
    user: UserContext = Depends(get_current_user)
):
    if not user.is_authenticated() and user.user_role != ROLE_GUEST:
        return SessionListResponse(data=[])
    
    # 传入 type 进行筛选
    sessions = history_manager.get_user_sessions(user.user_id, type_filter=type)
    return SessionListResponse(data=sessions)

@app.get("/api/v1/session/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_detail(session_id: str, user: UserContext = Depends(get_current_user)):
    if not user.is_authenticated() and user.user_role != ROLE_GUEST:
        raise HTTPException(status_code=401, detail="Login required")
    
    messages = history_manager.get_session_history_detail(session_id)
    return SessionHistoryResponse(session_id=session_id, messages=messages)

# --- 聊天接口 ---
@app.post("/api/v1/chat/{type}")
async def chat_endpoint(
    type: str, 
    payload: RequestPayload, 
    user: UserContext = Depends(get_current_user),
):
    if type not in pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    
    # 1. 角色权限校验
    allowed_roles = ROUTE_PERMISSIONS.get(type, set())
    if user.user_role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail=f"Access Denied for role: {user.user_role}"
        )

    # 2. 会话绑定校验
    is_valid_session = history_manager.check_session_type(
        user.user_id, 
        payload.session_id, 
        required_type=type
    )
    
    if not is_valid_session:
        # 如果校验失败，可能是 session_id 错误，或者是跨模块调用
        raise HTTPException(
            status_code=400, 
            detail=f"Session {payload.session_id} does not belong to module '{type}' or does not exist."
        )

    # 游客限流
    if user.user_role == ROLE_GUEST:
        limit_key = f"rate_limit:{user.user_id}"
        request_count = redis_client.incr(limit_key)
        if request_count == 1:
            redis_client.expire(limit_key, 60)
        if request_count > 10:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Guest rate limit exceeded. Please wait a moment."
            )

    # 生成标题
    if user.user_id:
        current_history = history_manager.get_recent_turns(payload.session_id)
        if not current_history:
            new_title = payload.query[:15]
            history_manager.update_session_title(user.user_id, payload.session_id, new_title)

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