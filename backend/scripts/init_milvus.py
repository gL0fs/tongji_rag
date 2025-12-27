import sys
import os
import time

# 确保能找到 app 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import MilvusClient
from langchain_community.embeddings import DashScopeEmbeddings
from app.config import settings

def init_milvus():
    print("--- Initializing Milvus Collections ---")
    
    # 连接 Milvus
    client = MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
    
    # 初始化 Embedding 模型
    embedder = DashScopeEmbeddings(
        model=settings.EMBEDDING_MODEL,
        dashscope_api_key=settings.DASHSCOPE_API_KEY
    )
    
    # 获取当前已存在的集合列表 (解决 has_collection 报错问题)
    existing_cols = client.list_collections()
    print(f"Existing collections: {existing_cols}")

    # ==========================================
    # 1. 定义集合列表
    # ==========================================
    
    # A. 普通文本检索库 (Schema: id, vector, text, source, dept_id, user_id)
    rag_cols = [
        settings.COLLECTION_STANDARD,
        settings.COLLECTION_KNOWLEDGE,
        settings.COLLECTION_INTERNAL,
        settings.COLLECTION_PERSONAL
    ]
    
    # B. 问答库 (Schema: id, vector, question, answer, source)
    faq_col = settings.COLLECTION_FAQ

    # ==========================================
    # 2. 重建集合 (Drop & Create)
    # ==========================================
    
    # 处理 RAG 集合
    for col in rag_cols:
        if col in existing_cols:
            client.drop_collection(col)
            print(f"Dropped old collection: {col}")
        
        client.create_collection(
            collection_name=col,
            dimension=1024,
            metric_type="COSINE",
            auto_id=True
        )
        print(f"Created RAG collection: {col}")

    # 处理 FAQ 集合
    if faq_col in existing_cols:
        client.drop_collection(faq_col)
        print(f"Dropped old collection: {faq_col}")

    client.create_collection(
        collection_name=faq_col,
        dimension=1024,
        metric_type="COSINE",
        auto_id=True
    )
    print(f"Created FAQ collection: {faq_col}")

    # ==========================================
    # 3. 准备数据
    # ==========================================
    
    # A. RAG 数据 (文本 Chunk)
    rag_data_source = {
        settings.COLLECTION_STANDARD: [
            {"text": "同济大学历史悠久，创建于1907年。", "source": "官网"},
            {"text": "同济大学主要校区位于上海市，四平路校区地址为四平路1239号。", "source": "官网"},
        ],
        settings.COLLECTION_KNOWLEDGE: [
            {"text": "RAG技术结合了检索(Retrieval)和生成(Generation)能力。", "source": "CS_Paper"},
            {"text": "Transformer架构的核心是Self-Attention机制。", "source": "AI_Intro"},
        ],
        settings.COLLECTION_INTERNAL: [
            # dept_id="CS" 对应张三
            {"text": "计算机系通知：本周五下午召开全体教职工大模型培训。", "dept_id": "CS", "source": "OA通知"},
            # dept_id="SE" 对应李教授
            {"text": "软件学院公告：2025届毕业设计答辩将在嘉定校区举行。", "dept_id": "SE", "source": "OA通知"},
        ],
        settings.COLLECTION_PERSONAL: [
            # user_id="1" 对应张三 (根据 init_sql.py 的插入顺序，第一个用户ID通常是1)
            {"text": "张三的GPA为3.85，专业排名第5。", "user_id": "1", "source": "教务系统"},
            {"text": "张三已选修《高级机器学习》和《云计算》课程。", "user_id": "1", "source": "教务系统"},
            # user_id="2" 对应李教授
            {"text": "李教授本月工资单详情：基本工资...", "user_id": "2", "source": "财务系统"},
        ]
    }

    # B. FAQ 数据 (QA 对)
    faq_data_source = [
        {"q": "同济大学校训是什么？", "a": "同济大学的校训是：同舟共济。", "source": "校训办"},
        {"q": "嘉定校区地址在哪里？", "a": "嘉定校区位于上海市嘉定区曹安公路4800号。", "source": "保卫处"},
        {"q": "如何申请访客入校？", "a": "请通过同济大学官方微信公众号进行访客预约。", "source": "保卫处"},
    ]

    # ==========================================
    # 4. 向量化并插入
    # ==========================================

    # --- 插入 RAG 数据 ---
    for col, items in rag_data_source.items():
        rows = []
        for item in items:
            try:
                text = item["text"]
                vector = embedder.embed_query(text)
                
                # 为了防止 Filter 报错，所有字段最好都给个默认值
                row = {
                    "vector": vector,
                    "text": text,
                    "source": item.get("source", "unknown"),
                    "dept_id": item.get("dept_id", ""),  # 默认为空字符串
                    "user_id": item.get("user_id", "")   # 默认为空字符串
                }
                rows.append(row)
            except Exception as e:
                print(f"Error embedding item: {e}")

        if rows:
            client.insert(collection_name=col, data=rows)
            print(f"Inserted {len(rows)} items into {col}")

    # --- 插入 FAQ 数据 ---
    faq_rows = []
    for item in faq_data_source:
        try:
            # FAQ 是对 'question' 进行向量化
            q_text = item["q"]
            vector = embedder.embed_query(q_text)
            
            row = {
                "vector": vector,
                "question": q_text, # 存问题原文
                "answer": item["a"],# 存答案
                "source": item.get("source", "faq")
            }
            faq_rows.append(row)
        except Exception as e:
            print(f"Error embedding FAQ: {e}")

    if faq_rows:
        client.insert(collection_name=faq_col, data=faq_rows)
        print(f"Inserted {len(faq_rows)} items into {faq_col} (FAQ)")

    print("--- Milvus Initialization Complete ---")

if __name__ == "__main__":
    init_milvus()