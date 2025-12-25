import json
import redis
from typing import List, Dict, Any, Generator
from pymilvus import MilvusClient
from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser

from app.config import settings
from app.dto import Document, RewrittenQuery

# --- History Manager (Redis) ---
class HistoryManager:
    def __init__(self):
        self.redis = redis.Redis(
            host=settings.REDIS_HOST, 
            port=settings.REDIS_PORT, 
            password=settings.REDIS_PASSWORD,
            decode_responses=True
        )
        self.max_turns = 3  # 保留最近3轮
        self.ttl = 3600     # 会话过期时间 1小时

    def get_recent_turns(self, session_id: str) -> List[Any]:
        key = f"chat_history:{session_id}"
        if not self.redis.exists(key):
            return []
            
        history_json = self.redis.lrange(key, 0, -1)
        messages = []
        for item in history_json:
            try:
                msg_obj = json.loads(item)
                if msg_obj['role'] == 'user':
                    messages.append(HumanMessage(content=msg_obj['content']))
                else:
                    messages.append(AIMessage(content=msg_obj['content']))
            except json.JSONDecodeError:
                continue
        return messages

    def append_user_message(self, session_id: str, content: str):
        key = f"chat_history:{session_id}"
        msg = json.dumps({"role": "user", "content": content}, ensure_ascii=False)
        self.redis.rpush(key, msg)
        self.redis.ltrim(key, -self.max_turns, -1)
        self.redis.expire(key, self.ttl)

    def append_ai_message(self, session_id: str, content: str):
        key = f"chat_history:{session_id}"
        msg = json.dumps({"role": "assistant", "content": content}, ensure_ascii=False)
        self.redis.rpush(key, msg)
        self.redis.ltrim(key, -self.max_turns, -1)
        self.redis.expire(key, self.ttl)

# --- Vector Retriever (Milvus) ---
class VectorRetriever:
    def __init__(self):
        self.embedder = DashScopeEmbeddings(
            model=settings.EMBEDDING_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY
        )
        # 初始化 Milvus 连接
        self.client = MilvusClient(
            uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        )

    def search(self, query_text: str, collections: List[str], top_k: int = 3, filters: str = "") -> List[Document]:
        """多库联合检索"""
        try:
            query_vector = self.embedder.embed_query(query_text)
        except Exception as e:
            print(f"Embedding error: {e}")
            return []

        all_results = []
        
        for col_name in collections:
            try:
                if not self.client.has_collection(col_name):
                    print(f"Warning: Collection {col_name} not found.")
                    continue
                
                res = self.client.search(
                    collection_name=col_name,
                    data=[query_vector],
                    limit=top_k,
                    filter=filters, 
                    output_fields=["text", "source", "dept_id", "user_id"]
                )
                
                for hit in res[0]:
                    doc = Document(
                        id=str(hit['id']),
                        content=hit['entity'].get('text', ''),
                        score=hit['distance'], 
                        source=hit['entity'].get('source', col_name),
                        metadata=hit['entity']
                    )
                    all_results.append(doc)
            except Exception as e:
                print(f"Search error in {col_name}: {e}")

        # 统一排序
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:top_k]

# --- LLM Generator (LangChain) ---
class LLMGenerator:
    def __init__(self):
        self.rewrite_llm = ChatTongyi(
            model=settings.REWRITE_MODEL_NAME, 
            api_key=settings.DASHSCOPE_API_KEY,
            temperature=0.1
        )
        self.gen_llm = ChatTongyi(
            model=settings.GENERATE_MODEL_NAME, 
            api_key=settings.DASHSCOPE_API_KEY,
            streaming=True
        )

    def rewrite_query(self, history: List[Any], current: str) -> RewrittenQuery:
        if not history:
            return RewrittenQuery(original_text=current, rewritten_text=current)

        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个搜索查询优化专家。请根据以下对话历史，将用户的最新问题改写为一个独立、完整、包含所有必要上下文的搜索查询语句。如果不需要改写，直接输出原句。不要输出任何解释。"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])
        
        chain = prompt | self.rewrite_llm | StrOutputParser()
        try:
            rewritten_text = chain.invoke({"history": history, "question": current})
        except Exception as e:
            print(f"Rewrite failed: {e}")
            rewritten_text = current
            
        return RewrittenQuery(original_text=current, rewritten_text=rewritten_text)

    def generate_answer(self, query: str, docs: List[Document], prompt_template: str) -> Generator[str, None, None]:
        context_str = "\n\n".join([f"[来源:{d.source}] {d.content}" for d in docs])
        
        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self.gen_llm | StrOutputParser()
        
        return chain.stream({"context": context_str, "question": query})