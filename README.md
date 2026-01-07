# Tongji-RAG Campus Assistant (同济大学智能问答系统)

基于 RAG (检索增强生成) 架构的校园垂直领域大模型问答系统。支持多角色权限控制（游客/学生/教师/学者）、流式对话生成以及多源数据检索（公开/内部/学术/个人）。

## 技术栈 (Tech Stack)

* **LLM & Embedding**: Alibaba DashScope (通义千问 Qwen-Plus / Text-Embedding-v4)
* **Vector Database**: Milvus 2.3 (Standalone)
* **Backend Framework**: FastAPI (Python 3.10)
* **Auth & User Data**: MySQL 8.0 + JWT (RBAC)
* **Cache & Session**: Redis 7
* **Orchestration**: Docker Compose

## 目录结构

```text
Tongji-RAG/
├── backend/            # 后端核心代码 (FastAPI)(包括爬虫脚本)
├── frontend/           # 前端核心代码
├── data/               # 数据库持久化存储 (自动生成，不提交)
├── docker-compose.yml  # 容器编排配置
├── .env.example        # 环境变量模板
└── README.md           # 项目说明书
```

## 快速启动 (Quick Start)
### 1. 环境准备
确保本地已安装 Docker Desktop。

### 2. 配置环境变量
复制模板文件并填入你的 API Key。

```bash
cp .env.example .env
# 编辑 .env 文件，填入 DASHSCOPE_API_KEY 和数据库密码
```

### 3. 启动服务
使用 Docker Compose 一键构建并启动所有服务（MySQL, Redis, Milvus, Backend）。

```bash
docker-compose up -d --build
```

## 测试与使用
**远程访问时把localhost替换为真实服务器ip**

前端服务运行在 http://localhost:80

后端服务默认运行在 http://localhost:8000。

API 文档 (Swagger UI):访问 http://localhost:8000/docs 进行可视化测试。

Milvus 管理 (Attu): 访问 http://localhost:8001 查看向量数据。

对象存储 (MinIO): 访问 http://localhost:9001 (账号密码均为 minioadmin)。

### 默认测试账号
| 角色 | 用户名 | 密码 | 权限范围 |
| :--- | :--- | :--- | :--- |
| **学生** | `zhangsan` | `password123` | Public, Academic, Internal, Personal |
| **教师** | `prof_li` | `admin` | Public, Academic, Internal, Personal |
| **学者** | `dr_wang` | `123456` | Public, Academic |
| **游客** | (无) | (无) | Public Only |