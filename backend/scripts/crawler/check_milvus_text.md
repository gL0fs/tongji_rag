# 查看 Milvus 文本内容工具

##  简介

`check_milvus_text.py` 是一个用于直接查看 Milvus 向量数据库中存储的文本内容的工具脚本。它可以实时查询 Milvus 中的数据，比 Web UI 更及时，方便验证爬取数据是否正确。

##  功能

-  查看 Milvus 集合中的文本内容
-  显示集合统计信息（实体数量）
-  支持按条件过滤查询
-  支持指定输出字段
-  支持显示完整文本或预览（前400字符）
-  自动检测文本是否包含中文

##  使用方法

### 基本用法

```bash
# 在容器内执行
python scripts/crawler/check_milvus_text.py
```

**默认行为**：
- 查询 `rag_standard` 集合
- 显示前 10 条记录
- 显示 `text` 和 `source` 字段
- 只显示文本前 400 字符

### 查看指定集合

```bash
python scripts/crawler/check_milvus_text.py --collection rag_faq
```

### 查看更多记录

```bash
python scripts/crawler/check_milvus_text.py --limit 20
```

### 按来源过滤

```bash
python scripts/crawler/check_milvus_text.py --filter 'source == "同济大学官网"'
```

### 按ID查询

```bash
python scripts/crawler/check_milvus_text.py --filter 'id == 123'
```

### 显示完整文本

```bash
python scripts/crawler/check_milvus_text.py --full-text
```

### 指定输出字段

```bash
python scripts/crawler/check_milvus_text.py --fields text source dept_id
```

##  参数说明

| 参数 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `--collection` | 集合名称 | `rag_standard` | `--collection rag_faq` |
| `--limit` | 显示记录数量 | `10` | `--limit 20` |
| `--filter` | 过滤表达式 | 无 | `--filter 'source == "xxx"'` |
| `--fields` | 输出字段列表 | `text, source` | `--fields text source dept_id` |
| `--full-text` | 显示完整文本 | `False` | `--full-text` |

##  使用场景

### 1. 验证爬取数据是否正确

```bash
# 查看最近爬取的数据
python scripts/crawler/check_milvus_text.py --collection rag_standard --limit 5
```

### 2. 检查特定来源的数据

```bash
# 查看来自特定URL的数据
python scripts/crawler/check_milvus_text.py --filter 'source == "https://www.tongji.edu.cn/"'
```

### 3. 查看完整文本内容

```bash
# 查看某条记录的完整文本
python scripts/crawler/check_milvus_text.py --filter 'id == 123' --full-text
```

### 4. 检查数据质量

脚本会自动检测文本是否包含中文，如果检测到不包含中文，会提示"可能是乱码"。

##  输出示例

```
================================================================================
 检查 Milvus 中的完整文本（集合: rag_standard）
================================================================================
 集合 rag_standard 存在
 集合中的实体数量: 1234

 查询前 10 条记录...
 找到 10 条记录

【记录 1】
  source: https://www.tongji.edu.cn/
  ID: 123456789
  文本长度: 456 字符
  文本内容（前400字符）:
  ────────────────────────────────────────────────────────────────────────────
  同济大学是一所综合性大学，位于上海市...
  ────────────────────────────────────────────────────────────────────────────
   包含中文
  前500字符中中文数量: 89
  ────────────────────────────────────────────────────────────────────────────
```

##  注意事项

1. **确保 Milvus 服务运行**：脚本需要连接到 Milvus 服务
2. **集合必须存在**：如果集合不存在，脚本会提示错误
3. **过滤表达式语法**：使用 Milvus 的过滤表达式语法，如 `'source == "xxx"'` 或 `'id == 123'`

##  在 Docker 中运行

```bash
# 方式一：在运行中的容器中执行
docker-compose exec rag-backend python scripts/crawler/check_milvus_text.py

# 方式二：进入容器后执行
docker exec -it rag-backend bash
python scripts/crawler/check_milvus_text.py
```

##  相关文件

- `check_milvus_text.py` - 脚本文件
- `crawler.py` - 爬虫主脚本
- `README.md` - 爬虫使用指南

