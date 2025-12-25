import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import MilvusClient
from langchain_community.embeddings import DashScopeEmbeddings
from app.config import settings

def init_milvus():
    print("--- Initializing Milvus Collections ---")
    
    client = MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
    embedder = DashScopeEmbeddings(
        model=settings.EMBEDDING_MODEL,
        dashscope_api_key=settings.DASHSCOPE_API_KEY
    )
    
    cols = [
        settings.COLLECTION_STANDARD,
        settings.COLLECTION_KNOWLEDGE,
        settings.COLLECTION_INTERNAL,
        settings.COLLECTION_PERSONAL
    ]

    # 1. 重建集合
    for col in cols:
        if client.has_collection(col):
            client.drop_collection(col)
        
        # 这里的维度需与 DashScope 模型一致。text-embedding-v2=1536
        client.create_collection(
            collection_name=col,
            dimension=1536, 
            metric_type="COSINE", 
            auto_id=True
        )
        print(f"Re-created collection: {col}")

    # 2. 准备数据
    mock_data = {
        settings.COLLECTION_STANDARD: [
            {"text": "同济大学校训是：同舟共济。", "source": "官网"},
            {"text": "嘉定校区地址：曹安公路4800号。", "source": "官网"},
        ],
        settings.COLLECTION_KNOWLEDGE: [
            {"text": "RAG技术结合了检索和生成能力。", "source": "arXiv:2005.11401"},
            {"text": "Transformer架构由Self-Attention机制组成。", "source": "Google Brain"},
        ],
        settings.COLLECTION_INTERNAL: [
            {"text": "计算机系本周五下午召开全体教职工大会。", "dept_id": "CS", "source": "OA"},
            {"text": "软件学院2025届毕设答辩安排已发布。", "dept_id": "SE", "source": "OA"},
        ],
        settings.COLLECTION_PERSONAL: [
            # 注意：这里的 user_id 对应 init_sql.py 里插入的用户ID
            # 假设 MySQL 自增ID 从 1 开始，zhangsan 是 1
            {"text": "你的GPA为3.85，排名专业第5。", "user_id": "1", "source": "教务系统"},
            {"text": "你已选修《高级机器学习》课程。", "user_id": "1", "source": "教务系统"},
        ]
    }

    # 3. 向量化并插入
    for col, items in mock_data.items():
        rows = []
        for item in items:
            text = item["text"]
            vector = embedder.embed_query(text)
            
            row = {
                "vector": vector,
                "text": text,
                "source": item.get("source", "mock"),
                "dept_id": item.get("dept_id", ""),
                "user_id": item.get("user_id", "")
            }
            rows.append(row)
            
        client.insert(collection_name=col, data=rows)
        print(f"Inserted {len(rows)} items into {col}")

if __name__ == "__main__":
    init_milvus()