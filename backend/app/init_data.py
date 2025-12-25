from pymilvus import MilvusClient, DataType
from langchain_community.embeddings import DashScopeEmbeddings
from config import settings
import os

def init_milvus():
    client = MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
    embedder = DashScopeEmbeddings(model=settings.EMBEDDING_MODEL)
    
    collections = [
        settings.COLLECTION_STANDARD,
        settings.COLLECTION_KNOWLEDGE,
        settings.COLLECTION_INTERNAL,
        settings.COLLECTION_PERSONAL
    ]

    # 1. 清理旧数据并建表
    for col in collections:
        if client.has_collection(col):
            client.drop_collection(col)

        client.create_collection(
            collection_name=col,
            dimension=1536 if "v3" in settings.EMBEDDING_MODEL else 1536, # text-embedding-v3 是 1024 还是 1536 需确认，百炼 v2是1536
            metric_type="COSINE", 
            auto_id=True
        )
        print(f"Created collection: {col}")

    # 2. 准备 Mock 数据
    data_map = {
        settings.COLLECTION_STANDARD: [
            "同济大学校训是：同舟共济。",
            "同济大学位于上海，是一所历史悠久的名校。",
            "嘉定校区地址是曹安公路4800号。"
        ],
        settings.COLLECTION_KNOWLEDGE: [
            "DeepSeek是一种新型的大语言模型架构。",
            "Attention Is All You Need 提出了 Transformer 结构。",
            "RAG (Retrieval-Augmented Generation) 结合了检索和生成。"
        ],
        settings.COLLECTION_INTERNAL: [
            {"text": "本周五下午2点在A楼会议室开全院大会。", "dept_id": "CS"},
            {"text": "软件工程专业2025届毕业设计答辩安排。", "dept_id": "SE"},
        ],
        settings.COLLECTION_PERSONAL: [
            {"text": "张三的GPA是3.8，排名专业前10%。", "user_id": "u1001"},
            {"text": "张三选修了《高级算法设计》课程。", "user_id": "u1001"},
        ]
    }

    # 3. 插入数据
    for col, items in data_map.items():
        insert_data = []
        for item in items:
            text = item["text"] if isinstance(item, dict) else item
            vector = embedder.embed_query(text)
            
            entry = {
                "vector": vector,
                "text": text,
                "source": "mock_data",
                "dept_id": item.get("dept_id", "") if isinstance(item, dict) else "",
                "user_id": item.get("user_id", "") if isinstance(item, dict) else ""
            }
            insert_data.append(entry)
            
        client.insert(collection_name=col, data=insert_data)
        print(f"Inserted {len(insert_data)} rows into {col}")

if __name__ == "__main__":
    init_milvus()