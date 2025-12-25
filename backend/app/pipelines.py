from abc import ABC, abstractmethod
from typing import List, Generator
from app.dto import RequestPayload, UserContext, Document
from app.components import HistoryManager, VectorRetriever, LLMGenerator
from app.config import settings

class BasePipeline(ABC):
    def __init__(self):
        self.history_mgr = HistoryManager()
        self.retriever = VectorRetriever()
        self.llm_service = LLMGenerator()

    def execute(self, request: RequestPayload, user: UserContext) -> Generator[str, None, None]:
        # 1. 获取历史
        history = self.history_mgr.get_recent_turns(request.session_id)
        
        # 2. 查询重写
        rewritten_query = self.llm_service.rewrite_query(history, request.query)
        print(f"[Pipeline] User: {request.query} -> Rewritten: {rewritten_query.rewritten_text}")
        
        # 3. 记录用户提问
        self.history_mgr.append_user_message(request.session_id, request.query)
        
        # 4. 执行具体检索策略
        docs = self._retrieve_strategy(rewritten_query.rewritten_text, user)
        
        # 5. 生成回答 (流式)
        full_answer = ""
        prompt_tmpl = self._get_prompt_template()
        
        try:
            for chunk in self.llm_service.generate_answer(rewritten_query.rewritten_text, docs, prompt_tmpl):
                full_answer += chunk
                yield chunk
        except Exception as e:
            err = f"生成出错: {str(e)}"
            full_answer += err
            yield err
            
        # 6. 记录 AI 回答
        self.history_mgr.append_ai_message(request.session_id, full_answer)

    @abstractmethod
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        pass

    @abstractmethod
    def _get_prompt_template(self) -> str:
        pass

# --- 具体业务实现 ---

class PublicPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        return self.retriever.search(query, [settings.COLLECTION_STANDARD], top_k=3)

    def _get_prompt_template(self) -> str:
        return """你是一个同济大学的公开问答助手。请基于以下公开信息回答问题。如果信息不足，请礼貌告知。
        参考信息：
        {context}
        问题：{question}
        回答："""

class ScholarPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        # 混合检索：公开 + 学术
        return self.retriever.search(
            query, 
            [settings.COLLECTION_STANDARD, settings.COLLECTION_KNOWLEDGE], 
            top_k=5
        )
    
    def _get_prompt_template(self) -> str:
        return """你是一个学术科研助手。请基于提供的学术文献和公开资料回答问题，回答需专业严谨。
        参考文献：
        {context}
        问题：{question}
        回答："""

class InternalPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        # 全量检索，带部门过滤
        # 注意：这里简化处理，对 Internal 库应用 dept_id 过滤
        filter_expr = f"dept_id == '{user.dept_id}'" if user.dept_id else ""
        
        docs_public = self.retriever.search(query, [settings.COLLECTION_STANDARD, settings.COLLECTION_KNOWLEDGE], top_k=3)
        docs_internal = self.retriever.search(query, [settings.COLLECTION_INTERNAL], top_k=3, filters=filter_expr)
        
        all_docs = docs_public + docs_internal
        all_docs.sort(key=lambda x: x.score, reverse=True)
        return all_docs[:5]

    def _get_prompt_template(self) -> str:
        return """你是一个内部行政助手。你可以访问内部通知。请综合回答，注意区分信息的时效性。
        参考资料：
        {context}
        问题：{question}
        回答："""

class PersonalPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        if not user.user_id:
            raise ValueError("User ID required")
        
        # 强制 user_id 过滤
        return self.retriever.search(
            query, 
            [settings.COLLECTION_PERSONAL], 
            top_k=3, 
            filters=f"user_id == '{user.user_id}'"
        )

    def _get_prompt_template(self) -> str:
        return """你是一个个人数据助理。以下是用户的个人档案信息，请据此回答。
        个人档案：
        {context}
        问题：{question}
        回答："""