from sqlalchemy import Column, Integer, String, Boolean
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