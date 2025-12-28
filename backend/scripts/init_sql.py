import asyncio
import sys
import os

# 将项目根目录加入 path，以便导入 app 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from passlib.context import CryptContext
from sqlalchemy import select
from app.database import engine, Base, AsyncSessionLocal
from app.models_db import User, CrawlTask, CrawlBlock  # 导入所有模型以确保表被创建

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_hash(password):
    return pwd_context.hash(password)

async def init_db():
    print("--- Initializing MySQL Database ---")
    
    # 1. 创建表结构
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")

    # 2. 插入初始用户
    async with AsyncSessionLocal() as session:
        # 检查是否已初始化
        res = await session.execute(select(User).limit(1))
        if res.scalars().first():
            print("Users already exist. Done.")
            return

        users = [
            # 学生：张三 (CS系)
            User(username="zhangsan", hashed_password=get_hash("password123"), 
                 full_name="张三", role="student", dept_id="CS"),
            # 老师：李教授 (SE系)
            User(username="prof_li", hashed_password=get_hash("admin"), 
                 full_name="李教授", role="teacher", dept_id="SE"),
            # 学者：王博士 (无系别)
            User(username="dr_wang", hashed_password=get_hash("123456"), 
                 full_name="王学者", role="scholar", dept_id=None),
        ]
        
        session.add_all(users)
        await session.commit()
        print(f"Inserted {len(users)} default users.")

if __name__ == "__main__":
    asyncio.run(init_db())