from pydantic import BaseModel
from typing import List, Dict, Optional, Any

# --- 认证相关 ---
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_info: Dict[str, Any]

class RefreshRequest(BaseModel):
    refresh_token: str

# --- 上下文对象 (内部使用) ---
class UserContext(BaseModel):
    user_id: str
    user_name: str = "Guest"
    user_role: str # guest, student, teacher, scholar
    dept_id: Optional[str] = None
    scopes: List[str] = []

    def is_authenticated(self) -> bool:
        return self.user_role != "guest"

# --- RAG 业务相关 ---
class RequestPayload(BaseModel):
    query: str
    session_id: str
    stream: bool = True
    
class Document(BaseModel):
    id: str
    content: str
    score: float
    source: str
    metadata: Dict[str, Any] = {}

class RewrittenQuery(BaseModel):
    original_text: str
    rewritten_text: str