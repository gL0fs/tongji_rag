from abc import ABC, abstractmethod
from typing import List, Generator
import jieba
from app.dto import RequestPayload, UserContext, Document
from app.components import HistoryManager, VectorRetriever, LLMGenerator
from app.config import settings

class BasePipeline(ABC):
    def __init__(self):
        self.history_mgr = HistoryManager()
        self.retriever = VectorRetriever()
        self.llm_service = LLMGenerator()

    def execute(self, request: RequestPayload, user: UserContext) -> Generator[str, None, None]:
        # 获取历史
        history = self.history_mgr.get_recent_turns(request.session_id)
        
        # 查询重写
        rewritten_query = self.llm_service.rewrite_query(history, request.query)
        print(f"[Pipeline] User: {request.query} -> Rewritten: {rewritten_query.rewritten_text}")
        
        # 记录用户提问
        self.history_mgr.append_user_message(request.session_id, request.query)
        
        # 执行具体检索策略
        docs = self._retrieve_strategy(rewritten_query.rewritten_text, user)

        # --- 调试日志打印开始 ---
        print(f"\n{'='*30} 检索调试信息 {'='*30}")
        print(f"原始问题: {request.query}")
        print(f"重写问题: {rewritten_query.rewritten_text}")
        print(f"命中数量: {len(docs)}")
        
        for i, doc in enumerate(docs):
            # 将换行符替换为空格，避免日志太乱
            clean_content = doc.content.replace('\n', ' ')
            # 打印分数、来源和前 150 个字符的内容
            print(f" [文档 {i+1}] 得分: {doc.score:.4f} | 来源: {doc.source}")
            print(f"    内容预览: {clean_content[:150]}...")
            print("-" * 50)
        print(f"{'='*76}\n")
        # --- 【调试日志打印结束 ---
        
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
            
        # 记录 AI 回答
        self.history_mgr.append_ai_message(request.session_id, full_answer)

    def _keyword_rerank(self, query: str, docs: List[Document], final_k: int = 3) -> List[Document]:
        """
        关键词重排序
        对分数进行 Boost 加权，优先保留包含精确关键词的文档。
        """
        if not docs:
            return []
            
        # 使用 jieba 进行搜索引擎模式分词
        seg_list = jieba.lcut_for_search(query)
        
        keywords = set([k for k in seg_list if len(k) > 1])
        
        for doc in docs:
            content = doc.content
            match_score = 0
            
            # 计算关键词命中加分
            for kw in keywords:
                if kw in content:
                    # 命中一个关键词，分数增加 0.05
                    match_score += 0.05
            
            # 混合分数 = 原始向量分 + 关键词加分
            doc.score = doc.score + match_score
            
        # 重新排序
        docs.sort(key=lambda x: x.score, reverse=True)
        
        # 截取最终需要的数量
        return docs[:final_k]

    @abstractmethod
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        pass

    @abstractmethod
    def _get_prompt_template(self) -> str:
        pass

# --- 具体业务实现 ---

class PublicPipeline(BasePipeline):
    # 官方问答命中阈值
    FAQ_THRESHOLD = 0.8

    def execute(self, request: RequestPayload, user: UserContext) -> Generator[str, None, None]:
        # 记录上下文 查询重写
        history = self.history_mgr.get_recent_turns(request.session_id)
        rewritten_query = self.llm_service.rewrite_query(history, request.query)
        self.history_mgr.append_user_message(request.session_id, request.query)
        
        # 第一步：检索官方 FAQ 库
        faq_results = self.retriever.search(
            rewritten_query.rewritten_text, 
            [settings.COLLECTION_FAQ], # 只搜 rag_faq
            top_k=1
        )
        
        # 判断是否命中
        if faq_results and faq_results[0].score >= self.FAQ_THRESHOLD:
            # 直接从 metadata 里拿出 answer 字段
            direct_answer = faq_results[0].metadata.get("answer")
            
            if direct_answer:
                print(f"[PublicPipeline] FAQ Hit! Score: {faq_results[0].score}")
                
                # 加上前缀
                final_output = f"【官方回答】\n{direct_answer}"
                
                # 直接返回，不调 LLM
                yield final_output
                self.history_mgr.append_ai_message(request.session_id, final_output)
                return 

        # RAG 流程
        docs = self._retrieve_strategy(rewritten_query.rewritten_text, user)
        
        full_answer = ""
        prompt_tmpl = self._get_prompt_template()
        try:
            for chunk in self.llm_service.generate_answer(rewritten_query.rewritten_text, docs, prompt_tmpl):
                full_answer += chunk
                yield chunk
        except Exception as e:
            err = f"Error: {str(e)}"
            yield err
            full_answer += err
        self.history_mgr.append_ai_message(request.session_id, full_answer)

    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        # 策略修改：
        # 先从向量库拿出 15 条 (Recall)
        # 通过关键词重排序取前 4 条 (Precision)
        candidates = self.retriever.search(query, [settings.COLLECTION_STANDARD], top_k=15)
        return self._keyword_rerank(query, candidates, final_k=4)

    def _get_prompt_template(self) -> str:
        return """你是一位专业的校园向导。请基于【参考资料】为用户提供一个完整、准确的解答。

        【回答要求】
        1. **精准引用**：回答必须严格基于参考资料。对于关键信息（如时间、地点、电话、具体规定条款），请尽量使用资料中的原话，不要随意改写以免产生歧义。
        2. **内容完整**：如果资料中包含多个相关点，请将它们整合在一起，不要遗漏。
        3. **逻辑清晰**：请将零散的信息组织成通顺的段落或分点说明，形成一个连贯的回答。
        4. **资料不足**：如果资料不足以回答问题，请明确告知。

        【参考资料】
        {context}

        【用户问题】
        {question}

        【你的回答】
        """

class ScholarPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        # 学术场景：召回更多候选，混合排序
        candidates = self.retriever.search(
            query, 
            [settings.COLLECTION_STANDARD, settings.COLLECTION_KNOWLEDGE], 
            top_k=20
        )
        return self._keyword_rerank(query, candidates, final_k=6)
    
    def _get_prompt_template(self) -> str:
        return """你是一位学术研究助理。请根据【参考文献片段】撰写一份详实的学术回答。

        【撰写指南】
        1. **引用证据**：在阐述观点时，请直接引用文献中的关键语句作为证据。
        2. **综合综述**：不要逐条简单罗列文献。请分析不同文献之间的联系，将它们融合成一篇逻辑连贯、内容完整的综述性回答。
        3. **客观严谨**：保持学术的中立性，只陈述文献中已有的结论，不进行过度推断。
        4. **来源标注**：如果参考资料中包含来源信息（如[来源:xxx]），请在回答中保留这些标注。

        【参考文献片段】
        {context}

        【学术问题】
        {question}

        【回答】
        """

class InternalPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        # 内部场景策略：
        if not user.dept_id:
            filter_expr = "dept_id == 'unknown'" 
        else:
            filter_expr = f"dept_id == '{user.dept_id}'"
        
        # 扩大初筛范围 (Recall Phase)
        docs_public = self.retriever.search(query, [settings.COLLECTION_STANDARD, settings.COLLECTION_KNOWLEDGE], top_k=10)
        docs_internal = self.retriever.search(query, [settings.COLLECTION_INTERNAL], top_k=10, filters=filter_expr)
        
        # 合并
        all_candidates = docs_public + docs_internal
        
        # 2. 统一重排序 (Rerank Phase)
        return self._keyword_rerank(query, all_candidates, final_k=5)

    def _get_prompt_template(self) -> str:
        return """你是一位内部行政助手。请根据【参考资料】准确、全面地回复用户的问题。资料可能包含政策规定、内部通知或行政公告等。

        【回复要求】
        1. **精准引用**：对于关键信息（如时间节点、具体要求、数据指标、联系方式等），必须保留原文措辞，确保准确无误。
        2. **全面覆盖**：请综合所有相关资料，确保不遗漏任何生效的通知细节或补充说明。
        3. **条理清晰**：请使用分点（如 1., 2.）的方式组织内容，使信息一目了然。
        4. **信源甄别**：如果内部资料与公开信息存在差异，请明确以内部资料为准，并提示用户。

        【参考资料】
        {context}

        【用户询问】
        {question}

        【行政回复】
        """

class PersonalPipeline(BasePipeline):
    def _retrieve_strategy(self, query: str, user: UserContext) -> List[Document]:
        if not user.user_id:
            raise ValueError("User ID required")
        
        candidates = self.retriever.search(
            query, 
            [settings.COLLECTION_PERSONAL], 
            top_k=10, 
            filters=f"user_id == '{user.user_id}'"
        )
        return self._keyword_rerank(query, candidates, final_k=5)

    def _get_prompt_template(self) -> str:
        return """你是一位个人数据查询助手。请基于【数据片段】回答用户问题。

        【要求】
        1. **忠实转述**：请直接将数据转化为自然语言陈述。对于数字、日期、ID等关键字段，必须与原数据完全一致，不得修改。
        2. **完整呈现**：如果查询结果包含多条记录，请逐一列出，不要擅自省略。
        3. **不予推测**：如果数据中没有直接体现用户问的内容，请直接回答“未找到相关记录”。

        【数据片段】
        {context}

        【查询意图】
        {question}

        【查询结果】
        """