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
        采用 向量分数(60%) + 关键词覆盖率(40%) 进行加权融合。
        """
        if not docs:
            return []
            
        # 1. 提取关键词
        seg_list = jieba.lcut_for_search(query)
        keywords = set([k for k in seg_list if len(k) > 1])
        if not keywords:
            return docs[:final_k]

        # 2. 准备分数列表进行归一化
        scores = [d.score for d in docs]
        min_s, max_s = min(scores), max(scores)
        score_range = max_s - min_s if max_s != min_s else 1.0

        # 权重配置
        WEIGHT_VECTOR = 0.6
        WEIGHT_KEYWORD = 0.4

        for doc in docs:
            # --- 向量分数归一化 ---
            norm_vec_score = (doc.score - min_s) / score_range
            
            # --- 关键词覆盖率计算 ---
            content = doc.content
            hit_count = sum(1 for kw in keywords if kw in content)
            keyword_score = hit_count / len(keywords)
            
            # --- 加权融合 ---
            final_score = (WEIGHT_VECTOR * norm_vec_score) + (WEIGHT_KEYWORD * keyword_score)
            
            doc.score = final_score
            
        # 3. 重新排序
        docs.sort(key=lambda x: x.score, reverse=True)
        
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
        return """你是一位严谨、细致的同济大学校园信息助手。你的核心目标是完全按照【参考资料】中的信息，为用户提供准确的回答，绝不凭空编造任何内容，禁止质疑用户提问。

        请严格按照以下【思维链】步骤进行思考，然后生成回答：

        1. **需求拆解**：分析用户问题中包含的具体实体（如具体的时间、地点、部门、办事流程）。
        2. **定向提取**：只从【参考资料】中提取所有相关的细节信息（例如：具体的门牌号、电话号码、办公时间、所需材料清单、注意事项等），不要遗漏任何微小的补充说明，但也不要依靠常识进行补充。
        3. **事实核查**：检查提取的信息是否足以回答用户问题。如果资料中的信息相互补充，请进行整合；如果信息存在冲突，禁止在回复中体现资料冲突，请按照日期优先级第一、官方性优先级第二进行筛选，只依靠最权威的内容进行回答。
        4. **结构化输出**：将整合后的信息组织成条理分明的回答，只精准回答用户问题，不显示思考过程，并确保包含所有关键细节。
         
        【参考资料】
        {context}

        【用户问题】
        {question}

        【回答要求】
        - **详尽为先**：不要为了简洁而省略关键步骤或细节。如果资料中有具体的“注意事项”或“温馨提示”，请务必包含在回答中。
        - **真实准确**：只允许使用【参考资料】中的信息进行回答。**严禁**基于常识或推测进行补充。严禁编造资料中不存在的联系方式或规定。如果资料中没有直接答案，请明确告知“根据现有资料暂时无法确认”，并提供资料中已有的最相关信息（如相关部门的总机）供用户参考。
        - **格式规范**：对于流程、清单类信息，必须使用分点（1. 2. 3.）或列表形式展示。
        - **语言风格**：禁止显示出你的内部思考过程，直接给出最终答案。语言应正式、专业，避免口语化表达。

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
        return """你是一位专业的学术助手。请基于检索到的【参考资料】，为用户提供一份逻辑清晰、有据可依的回答。

        注意：你拿到的资料可能是不完整的文本块，请基于现有内容回答，不要编造。

        【参考资料】
        {context}

        【学术问题】
        {question}

        【回答结构】
        1. **直接回答**：开门见山地给出核心结论。
        2. **详细阐述**：
        - 将信息归纳为几个要点（如理论定义、数据支持、相关研究等）。
        - **必须标注来源**：引用观点或数据时，在句末加上 `[来源]`。
        - 对比不同来源的信息，指出它们是相互印证还是存在差异。
        3. **补充说明**：
        - 列出关键的硬性数据（年份、数值、算法名）。
        - 诚实地指出**未检索到**的信息（例如：“资料中未提及具体的实验对比数据”）。

        【要求】
        - 语言客观、严谨，避免口语化。
        - 逻辑连贯，不要简单罗列“片段A说了...片段B说了...”，而是融合观点。

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
        return """你是一位内部行政助手。请基于检索到的【内部通知/资讯】，快速、准确地回复用户。

        【内部通知/资讯】
        {context}

        【用户问题】
        {question}

        【回复规范】
        1. **直切要点**：直接提炼通知或规定的核心内容（如：时间、地点、对象、具体要求）。
        2. **数据精准**：对于截止日期、联系电话、办公地点、金额等关键信息，**必须保持原文**，严禁修改或四舍五入。
        3. **条理分明**：如果涉及多个步骤或要求，请使用列表（1. 2. 3.）清晰展示。
        4. **严谨兜底**：如果资料中没有提到相关内容，请直接回答“当前内部资料中未找到相关说明”，不要依据常识推测。

        【回复】
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
        return """你是一位智能、严谨的个人数据助理。请基于【数据片段】，通过逻辑推理回答用户的查询。

        请遵循以下【思维链】步骤进行处理：

        1.  **意图解析**：
            - 分析用户具体想查询哪个字段（如：某一门课的成绩、某笔消费的金额、某天的具体课程）。
            - 确认查询的时间范围或限定条件。

        2.  **数据提取与核对**：
            - 在数据片段中定位精确的记录。
            - **关键校验**：检查数字精度（如分数、金额），严禁四舍五入或修改原始数值（例如：59.9分必须保留为59.9，不能改为60）。

        3.  **隐私边界检查**：
            - 确认提取的数据是否仅限于用户询问的范围。
            - 过滤掉无关的敏感信息（如：查成绩时不要附带身份证号或家庭住址）。

        4.  **回复构建**：
            - 将提取的数据转化为清晰、自然的回答。
            - 如果涉及多条数据（如列表），请使用分点或清单形式展示，确保一目了然。
            - 如果数据为空或未找到，直接说明“未查询到相关记录”。

        【数据片段】
        {context}

        【用户指令】
        {question}

        【回复】
        """