# Tongji-RAG Backend

这是系统的后端核心，基于 FastAPI 和 LangChain 构建。

## 🧠 核心架构

后端采用 **Pipeline 设计模式**，根据用户角色和请求类型路由到不同的处理流水线：

1.  **PublicPipeline**: 检索公开库 (`rag_standard`)，无门槛。
2.  **ScholarPipeline**: 检索公开库 + 学术库 (`rag_knowledge`)。
3.  **InternalPipeline**: 检索全量库，包含内部通知 (`rag_internal`)，需 JWT 鉴权。
4.  **PersonalPipeline**: 仅检索个人画像 (`rag_person_info`)，严格过滤 UserID。

### 关键组件
* `app/server.py`: 入口文件，处理 HTTP 请求、JWT 鉴权、SSE 流式响应。
* `app/pipelines.py`: 业务逻辑层，定义了 Prompt 模板和检索策略。
* `app/components.py`: 基础设施层，封装了 LangChain (LLM), Milvus (Retriever), Redis (History)。

## 💻 本地开发指南

虽然推荐使用 Docker 开发，但如果你需要本地调试代码（为了 IDE 代码补全等）：

1.  **创建虚拟环境**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # Windows: venv\Scripts\activate
    ```

2.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **本地运行 (不推荐)**:
    由于代码依赖 Docker 网络中的主机名 (如 `mysql`, `redis`)，本地直接运行 `python app/server.py` 会连接失败。
    * **建议**: 始终使用 `docker-compose up` 运行服务。
    * **调试**: 使用 Swagger UI (`http://localhost:8000/docs`) 或 Postman 进行接口测试。

## 📜 常用命令

### 数据库迁移/初始化
所有初始化脚本位于 `scripts/` 目录下。

* `init_sql.py`: 使用 SQLAlchemy 建立 MySQL 表结构，并插入 `zhangsan`, `prof_li` 等测试用户。
* `init_milvus.py`: 重置 Milvus 集合，并调用 DashScope Embedding API 将 Mock 文本向量化后存入。

### 添加新的 Python 依赖
如果你安装了新的包，请务必更新 `requirements.txt`：
```bash
pip freeze > requirements.txt
# 或者手动添加
```

并在根目录重新构建镜像：
```bash
docker-compose up -d --build
```