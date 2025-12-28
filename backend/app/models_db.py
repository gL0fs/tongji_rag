from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)
    full_name = Column(String(50))
    role = Column(String(20), default="student") # student, teacher, scholar, guest
    dept_id = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)


class CrawlTask(Base):
    """爬取任务元数据表"""
    __tablename__ = "crawl_tasks"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(500), nullable=False, index=True)
    collection_name = Column(String(50), nullable=False)  # rag_standard, rag_knowledge等
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    pages_crawled = Column(Integer, default=0)
    blocks_inserted = Column(Integer, default=0)  # 插入的文本块/语义块数量
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class CrawlBlock(Base):
    """爬取的文本块元数据表（可选，用于追踪和管理）"""
    __tablename__ = "crawl_blocks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)  # 关联到 crawl_tasks.id
    url = Column(String(500), nullable=False, index=True)
    title = Column(String(200), nullable=True)  # 语义块标题
    section = Column(String(50), nullable=True)  # 语义块分类（时间信息、位置信息等）
    text_preview = Column(String(500), nullable=True)  # 文本预览（前500字符）
    milvus_id = Column(String(100), nullable=True, index=True)  # Milvus中的ID（如果可获取）
    created_at = Column(DateTime, server_default=func.now())