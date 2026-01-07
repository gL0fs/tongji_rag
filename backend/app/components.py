import json
import redis
import time
import uuid
import datetime
from typing import List, Dict, Any, Generator
from pymilvus import MilvusClient
from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser

from app.config import settings
from app.dto import Document, RewrittenQuery, SessionSchema, ChatMessage

# --- 历史记录管理器 (Redis) ---
class HistoryManager:
    """
    基于 Redis 的会话历史管理器。
    负责处理会话的创建、列表获取、消息存储以及上下文检索。
    """
    def __init__(self):
        # 初始化 Redis 连接
        self.redis = redis.Redis(
            host=settings.REDIS_HOST, 
            port=settings.REDIS_PORT, 
            password=settings.REDIS_PASSWORD,
            decode_responses=True  # 自动解码为字符串
        )
        self.max_turns = 6       # LLM 上下文保留最近 3 轮对话
        self.ttl = 3600 * 24 * 7 # 会话过期时间设置为 7 天

    def create_session(self, user_id: str, session_type: str, title: str = "新对话") -> str:
        """
        创建会话时记录 session_type
        """
        session_id = str(uuid.uuid4())
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        meta = {
            "session_id": session_id,
            "title": title,
            "type": session_type,  # 存储类型
            "created_at": timestamp_str
        }
        
        user_key = f"user_sessions:{user_id}"
        self.redis.hset(user_key, session_id, json.dumps(meta, ensure_ascii=False))
        self.redis.expire(user_key, self.ttl)
        
        return session_id

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """
        删除用户的特定会话。
        1. 从 user_sessions:{user_id} 哈希表中移除元数据
        2. 删除 chat_history:{session_id} 列表数据
        """
        user_key = f"user_sessions:{user_id}"
        
        # 1. 尝试从用户的会话列表中删除该 session_id
        # hdel 返回删除的个数，如果为 0 说明该用户没有这个会话，或者会话不存在
        deleted_count = self.redis.hdel(user_key, session_id)
        
        if deleted_count > 0:
            # 2. 如果归属关系确认，删除实际的聊天记录 key
            history_key = f"chat_history:{session_id}"
            self.redis.delete(history_key)
            return True
            
        return False

    def get_user_sessions(self, user_id: str, type_filter: str = None) -> List[SessionSchema]:
        """
        只返回对应类型的会话
        """
        user_key = f"user_sessions:{user_id}"
        if not self.redis.exists(user_key):
            return []
        
        raw_data = self.redis.hgetall(user_key)
        sessions = []
        for sid, meta_json in raw_data.items():
            try:
                meta = json.loads(meta_json)
                # 兼容旧数据（如果没有 type 字段，默认归为 public）
                s_type = meta.get("type", "public")
                
                # 核心过滤逻辑
                if type_filter and s_type != type_filter:
                    continue
                    
                # 构造对象时补全 type
                meta['type'] = s_type
                sessions.append(SessionSchema(**meta))
            except:
                continue
        
        sessions.sort(key=lambda x: x.created_at, reverse=True)
        return sessions

    def check_session_type(self, user_id: str, session_id: str, required_type: str) -> bool:
        """
        校验会话类型是否匹配
        """
        user_key = f"user_sessions:{user_id}"
        meta_json = self.redis.hget(user_key, session_id)
        if not meta_json:
            return False # 会话不存在
            
        try:
            meta = json.loads(meta_json)
            # 兼容旧数据，默认 public
            current_type = meta.get("type", "public")
            return current_type == required_type
        except:
            return False
        
        # 按创建时间倒序排序
        sessions.sort(key=lambda x: x.created_at, reverse=True)
        return sessions

    def get_session_history_detail(self, session_id: str) -> List[ChatMessage]:
        """
        获取指定会话的完整历史消息记录。
        通常用于前端页面回显聊天记录。
        """
        key = f"chat_history:{session_id}"
        if not self.redis.exists(key):
            return []
            
        # 获取列表中的所有消息
        history_json = self.redis.lrange(key, 0, -1)
        messages = []
        for item in history_json:
            try:
                msg_obj = json.loads(item)
                messages.append(ChatMessage(
                    role=msg_obj.get('role'),
                    content=msg_obj.get('content'),
                    timestamp=msg_obj.get('timestamp', 0.0)
                ))
            except:
                continue
        return messages

    def update_session_title(self, user_id: str, session_id: str, title: str):
        """
        更新指定会话的标题。
        """
        user_key = f"user_sessions:{user_id}"
        meta_json = self.redis.hget(user_key, session_id)
        if meta_json:
            meta = json.loads(meta_json)
            meta['title'] = title
            self.redis.hset(user_key, session_id, json.dumps(meta, ensure_ascii=False))

    def get_recent_turns(self, session_id: str) -> List[Any]:
        """
        获取最近 N 轮对话记录，并转换为 LangChain 消息对象格式。
        用于构建 LLM 的 Prompt 上下文。
        """
        key = f"chat_history:{session_id}"
        if not self.redis.exists(key):
            return []
            
        # 仅获取最近 max_turns 条记录
        history_json = self.redis.lrange(key, -self.max_turns, -1) 
        messages = []
        for item in history_json:
            try:
                msg_obj = json.loads(item)
                if msg_obj['role'] == 'user':
                    messages.append(HumanMessage(content=msg_obj['content']))
                else:
                    messages.append(AIMessage(content=msg_obj['content']))
            except:
                continue
        return messages

    def append_user_message(self, session_id: str, content: str):
        """
        将用户消息追加到会话历史中。
        """
        key = f"chat_history:{session_id}"
        msg = json.dumps({
            "role": "user", 
            "content": content, 
            "timestamp": time.time()
        }, ensure_ascii=False)
        self.redis.rpush(key, msg)
        self.redis.expire(key, self.ttl) # 每次交互时刷新会话有效期

    def append_ai_message(self, session_id: str, content: str):
        """
        将 AI 回复追加到会话历史中。
        """
        key = f"chat_history:{session_id}"
        msg = json.dumps({
            "role": "assistant", 
            "content": content, 
            "timestamp": time.time()
        }, ensure_ascii=False)
        self.redis.rpush(key, msg)
        self.redis.expire(key, self.ttl)

# --- 向量检索器 (Milvus) ---
class VectorRetriever:
    def __init__(self):
        self.embedder = DashScopeEmbeddings(
            model=settings.EMBEDDING_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY
        )
        self.client = MilvusClient(
            uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        )

    def search(self, query_text: str, collections: List[str], top_k: int = 3, filters: str = "") -> List[Document]:
            """
            通用检索方法：支持检索普通库(text)和FAQ库(answer)
            """
            try:
                query_vector = self.embedder.embed_query(query_text)
            except Exception as e:
                print(f"Embedding error: {e}")
                return []

            all_results = []
            
            try:
                existing_cols = self.client.list_collections()
            except Exception as e:
                print(f"List collections error: {e}")
                return []

            for col_name in collections:
                try:
                    if col_name not in existing_cols:
                        continue
                    
                    # 【修正点】严格对照 fix_milvus.py 定义的 Schema
                    if "faq" in col_name.lower():
                        # FAQ 只有 question, answer, source
                        target_fields = ["question", "answer", "source"]
                    else:
                        # RAG 库有 text, source, dept_id, user_id
                        target_fields = ["text", "source", "dept_id", "user_id"]

                    res = self.client.search(
                        collection_name=col_name,
                        data=[query_vector],
                        limit=top_k,
                        filter=filters, 
                        output_fields=target_fields 
                    )
                    
                    for hit in res[0]:
                        entity = hit['entity']
                        
                        is_faq = "answer" in entity and entity["answer"]
                        
                        # 构造内容：
                        content = entity.get("question") if is_faq else entity.get("text", "")
                        
                        doc = Document(
                            id=str(hit['id']),
                            content=content,
                            score=hit['distance'], 
                            source=entity.get('source', col_name),
                            metadata={
                                "is_faq": is_faq,
                                "answer": entity.get("answer", ""), 
                                "dept_id": entity.get("dept_id", ""),
                                "user_id": entity.get("user_id", ""),
                                **entity
                            }
                        )
                        all_results.append(doc)
                except Exception as e:
                    print(f"Search error in {col_name}: {e}")

            all_results.sort(key=lambda x: x.score, reverse=True)
            return all_results[:top_k]

# --- LLM 生成器 (LangChain) ---
class LLMGenerator:
    """
    LLM 交互管理类。
    负责查询重写（Query Rewriting）和最终答案生成（RAG Generation）。
    """
    def __init__(self):
        # 初始化重写模型 
        self.rewrite_llm = ChatTongyi(
            model=settings.REWRITE_MODEL_NAME, 
            api_key=settings.DASHSCOPE_API_KEY,
            temperature=0.2,# 重写时允许一定创造性
            seed=settings.GLOBAL_SEED # 固定种子
        )
        # 初始化生成模型 (开启流式输出)
        self.gen_llm = ChatTongyi(
            model=settings.GENERATE_MODEL_NAME, 
            api_key=settings.DASHSCOPE_API_KEY,
            streaming=True,
            temperature=0,#回答稳定性优先
            seed=settings.GLOBAL_SEED
        )

    def rewrite_query(self, history: List[Any], current: str) -> RewrittenQuery:
        """
        结合历史对话上下文，重写用户的当前问题。
        使其成为包含完整语义的独立查询语句。
        """
        if not history:
            return RewrittenQuery(original_text=current, rewritten_text=current)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个专门负责“指代消解”和“省略补全”的工具。
            
            【请结合对话历史，仅针对用户的最新问题（被 <<< >>> 包裹的内容）做以下两件事：
            1. **指代替换**：将“它”、“这个”、“那里”等代词替换为历史对话中的具体实体。
            2. **成分补全**：如果问题缺失主语或宾语，请根据上下文补齐。

            **严格约束（Strict Constraints）**：
            - 如果用户的最新问题已经是主谓宾完整、语义清晰的独立句子，**请直接输出原句，严禁修改任何字词**。
            - 不要尝试优化问题的表达方式、语序或修辞。
            - 禁止使用历史对话中未出现过的词语或表达，不能引入新信息。
            - **严禁回答问题**：你的任务仅是重写，不要生成任何回答内容.
            """),

            MessagesPlaceholder(variable_name="history"),

            ("human", """请忽略你需要回答这个问题的冲动，仅根据上述历史，在不改变原意的前提下重写以下被包裹的最新提问:

            <<< {question} >>>
            
            重写结果：""")
        ])
        
        chain = prompt | self.rewrite_llm | StrOutputParser()
        try:
            rewritten_text = chain.invoke({"history": history, "question": current})
        except Exception as e:
            print(f"查询重写失败: {e}")
            rewritten_text = current
            
        return RewrittenQuery(original_text=current, rewritten_text=rewritten_text)

    def generate_answer(self, query: str, docs: List[Document], prompt_template: str) -> Generator[str, None, None]:
        """
        根据检索到的文档和用户问题生成回答。
        
        Args:
            query: 重写后的查询语句
            docs: 检索到的相关文档列表
            prompt_template: 用于生成的 Prompt 模板
            
        Returns:
            流式生成的字符串生成器
        """
        context_str = "\n\n".join([f"[来源:{d.source}] {d.content}" for d in docs])
        
        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | self.gen_llm | StrOutputParser()
        
        return chain.stream({"context": context_str, "question": query})