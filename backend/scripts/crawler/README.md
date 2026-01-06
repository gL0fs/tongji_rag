# 爬虫使用指南

##  简介

本爬虫脚本用于爬取同济大学官网等公开信息，经过文本处理和向量化后存储到 Milvus 向量数据库，供 RAG 系统检索使用。

### 爬取方法

爬虫采用**语义块提取**的方式，能够：

1. **按HTML语义结构提取**：识别 `<section>`, `<article>`, `<div class="content">` 等标签，每个语义标签作为一个独立的信息块
2. **按标题分割**：遇到 `<h1>`, `<h2>`, `<h3>`, `<h4>` 时创建新的信息块，标题后的内容属于该块
3. **自动分类**：根据关键词自动分类为：
   - 时间信息（开放时间、办公时间等）
   - 位置信息（地址、地图、校区等）
   - 联系方式（电话、邮箱等）
   - 基本信息（简介、历史等）
   - 新闻公告
   - 招生信息
   - 学术信息
   - 其他

**优势**：相比按固定字符数机械分割，语义块提取能够区分不同主题的信息，提高检索精度。

### 数据存储流程

```
1. 爬取网页 → 提取文本（语义块）
2. 文本清理 → 去除HTML标签、特殊字符
3. 文本分块 → 将长文本分割为指定大小的块（chunk）
4. 向量化 → 使用 DashScope Embedding API 生成1024维向量
5. 插入Milvus → 批量插入到对应集合（rag_standard 或 rag_knowledge）
6. 保存元数据 → 记录到 MySQL 数据库（crawl_tasks 和 crawl_blocks 表）
```

---

##  快速开始

### 1. 创建配置文件

复制配置示例文件：

```bash
cd backend/scripts/crawler
cp crawl_config_example.py crawl_config.py
```

### 2. 编辑配置文件

打开 `crawl_config.py`，修改以下内容：

#### 2.1 公开标准信息URL列表（`STANDARD_URLS`）

```python
STANDARD_URLS = [
    "https://www.tongji.edu.cn/",  # 官网首页
    "https://www.tongji.edu.cn/xxgk/xxjj.htm",  # 学校简介
    # 添加更多URL...
]
```

**说明**：
- 这些URL会被爬取并存储到 `rag_standard` 集合
- 如果列表为空 `[]`，则不会执行公开信息爬取任务

#### 2.2 学术科研信息URL列表（`ACADEMIC_URLS`）

```python
ACADEMIC_URLS = [
    "https://www.tongji.edu.cn/kxyj/",  # 科学研究
    # 添加更多学术相关URL...
]
```

**说明**：
- 这些URL会被爬取并存储到 `rag_knowledge` 集合
- 如果列表为空 `[]`，则不会执行学术信息爬取任务

#### 2.3 常见问题FAQ（`MANUAL_FAQS`）

```python
MANUAL_FAQS = [
    {
        "q": "同济大学校训是什么？",
        "a": "同济大学的校训是：同舟共济。",
        "source": "校训办"
    },
    # 添加更多FAQ...
]
```

**说明**：
- FAQ 会直接存储到 `rag_faq` 集合
- 如果列表为空 `[]`，则不会执行FAQ添加任务

#### 2.4 爬取配置参数（`CRAWL_CONFIG`）

```python
CRAWL_CONFIG = {
    "max_pages_standard": 50,  # 公开信息最大爬取页数
    "max_pages_academic": 30,  # 学术信息最大爬取页数
    "delay_seconds": 1,  # 每次请求延迟（秒）
    "chunk_size_standard": 500,  # 公开信息文本块大小（字符数）
    "chunk_size_academic": 600,  # 学术信息文本块大小（字符数）
    "chunk_overlap": 50,  # 文本块重叠大小（字符数）
}
```

**参数说明**：

| 参数 | 说明 | 默认值 | 建议值 |
|------|------|--------|--------|
| `max_pages_standard` | 公开信息最大爬取页数 | 50 | 10-100 |
| `max_pages_academic` | 学术信息最大爬取页数 | 30 | 10-50 |
| `delay_seconds` | 每次请求之间的延迟（秒） | 1 | 1-3（避免被封） |
| `chunk_size_standard` | 公开信息文本块大小（字符数） | 500 | 300-800 |
| `chunk_size_academic` | 学术信息文本块大小（字符数） | 600 | 400-1000 |
| `chunk_overlap` | 文本块重叠大小（字符数） | 50 | 50-100 |

**调整建议**：
- 如果网站响应慢，可以增加 `delay_seconds`
- 如果文本较长，可以增加 `chunk_size`
- 如果只想测试，可以减小 `max_pages`

---

##  使用方法

### 方式一：在 Docker 容器中运行（推荐）

```bash
# 在项目根目录执行
docker-compose exec rag-backend python scripts/crawler/crawler.py
```

### 方式二：进入容器后运行

```bash
# 进入容器
docker exec -it rag-backend bash

# 运行脚本
python scripts/crawler/crawler.py
```

### 方式三：本地运行（需要安装依赖）

```bash
cd backend/scripts/crawler
python crawler.py
```

---

##  参数调整指南

### 调整文本块大小

**场景**：如果网页内容较长，希望每个块包含更多信息

```python
CRAWL_CONFIG = {
    "chunk_size_standard": 800,  # 从500增加到800
    "chunk_size_academic": 1000,  # 从600增加到1000
    "chunk_overlap": 100,  # 增加重叠以保持上下文
    # ...
}
```

**影响**：
-  优点：每个块包含更多上下文信息，检索时可能更准确
-  缺点：块太大可能导致检索到不相关的内容

### 限制爬取页数（测试用）

**场景**：只想测试爬虫功能，不想爬取太多数据

```python
CRAWL_CONFIG = {
    "max_pages_standard": 3,  # 只爬取3页
    "max_pages_academic": 2,  # 只爬取2页
    # ...
}
```

### 调整请求延迟

**场景**：网站响应慢，或者担心被封IP

```python
CRAWL_CONFIG = {
    "delay_seconds": 2,  # 从1秒增加到2秒
    # ...
}
```

**建议**：
- 不要设置太小（< 0.5秒），可能被网站封禁
- 不要设置太大（> 5秒），爬取速度会非常慢

### 只爬取一种类型的数据

**场景**：只想爬取公开信息，不爬取学术信息

```python
STANDARD_URLS = [
    "https://www.tongji.edu.cn/",
    # ...
]

ACADEMIC_URLS = []  # 设为空列表，不会爬取学术信息

MANUAL_FAQS = []  # 设为空列表，不会添加FAQ
```

**说明**：如果某个列表为空，对应的爬取任务就不会执行。

---

##  数据存储位置

### Milvus 向量数据库

- `rag_standard`：公开标准信息
- `rag_knowledge`：学术科研信息
- `rag_faq`：常见问题FAQ

### MySQL 数据库

- `crawl_tasks`：爬取任务记录（URL、状态、时间等）
- `crawl_blocks`：文本块元数据（来源URL、标题、分类、Milvus ID等）

---

##  修复缺失的 Milvus ID

如果某些记录的 `milvus_id` 为 `NULL`，说明这些记录没有成功插入到 Milvus。可以使用修复脚本：

```bash
# 在容器内执行
python scripts/crawler/fix_missing_milvus_ids.py
```

详细说明请查看 `fix_missing_milvus_ids.py` 的注释。

---

##  注意事项

1. **URL格式**：确保URL以 `http://` 或 `https://` 开头
2. **网络连接**：确保能访问目标网站
3. **API密钥**：确保 `.env` 文件中配置了 `DASHSCOPE_API_KEY`
4. **数据库连接**：确保 MySQL 和 Milvus 服务正在运行
5. **礼貌爬取**：不要设置过小的 `delay_seconds`，避免对目标网站造成压力
6. **遵守robots.txt**：爬取前检查网站的 `robots.txt` 文件

---

##  常见问题

### Q: 提示 "未找到 crawl_config.py 文件"
A: 请先复制 `crawl_config_example.py` 为 `crawl_config.py`

### Q: 爬取失败，提示连接错误
A: 检查网络连接和URL是否正确，确保能访问目标网站

### Q: 数据没有插入到数据库
A: 检查 MySQL 和 Milvus 服务是否正常运行，检查 `.env` 配置

### Q: 爬取速度很慢
A: 可以减小 `max_pages` 或增加 `delay_seconds`，但不要设置太小避免被封

### Q: Milvus 插入失败
A: 请查看 `插入失败排查.md`（如果存在）或运行 `init_milvus.py` 初始化集合

---

##  相关文件

- `crawler.py` - 主爬虫脚本
- `crawl_config_example.py` - 配置示例文件
- `crawl_config.py` - 你的配置文件（需要自己创建）
- `fix_missing_milvus_ids.py` - 修复缺失 Milvus ID 的脚本
- `check_milvus_text.py` - 查看 Milvus 中存储的文本内容
