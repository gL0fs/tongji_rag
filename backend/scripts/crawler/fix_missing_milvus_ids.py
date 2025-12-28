"""
修复脚本：重新处理 milvus_id 为 NULL 的记录
功能：重新爬取并插入到 Milvus，更新 milvus_id
"""

import sys
import os
from typing import List, Dict, Set
from datetime import datetime

# 确保能找到 app 模块和 crawler 模块
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(backend_dir)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))  # 添加 crawler 目录到路径

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from app.models_db import CrawlBlock, CrawlTask
from crawler import WebCrawler, DataIngester, get_sync_db_session


def get_null_milvus_id_blocks(db_session: Session) -> List[CrawlBlock]:
    """获取所有 milvus_id 为 NULL 的记录"""
    blocks = db_session.query(CrawlBlock).filter(
        CrawlBlock.milvus_id.is_(None)
    ).all()
    return blocks


def get_unique_urls_from_blocks(blocks: List[CrawlBlock]) -> Set[str]:
    """从 blocks 中提取唯一的 URL"""
    return set(block.url for block in blocks)


def insert_using_preview(
    db_session: Session,
    blocks: List[CrawlBlock],
    collection_name: str = None
) -> Dict[int, str]:
    """
    使用 text_preview 直接插入到 Milvus（快速修复，但文本不完整）
    
    Returns:
        Dict[block_id, milvus_id]: 成功插入的块ID和对应的Milvus ID
    """
    if not blocks:
        return {}
    
    # 确定集合名称
    if collection_name is None:
        if blocks[0].task_id:
            task = db_session.query(CrawlTask).filter(CrawlTask.id == blocks[0].task_id).first()
            if task:
                collection_name = task.collection_name
        if not collection_name:
            collection_name = settings.COLLECTION_STANDARD
    
    print(f"使用集合: {collection_name}")
    print(f"使用 text_preview 快速修复 {len(blocks)} 个块...")
    
    ingester = DataIngester()
    result = {}
    
    # 准备插入数据
    blocks_to_insert = []
    for block in blocks:
        if not block.text_preview:
            print(f"  ⚠️  块 #{block.id} 没有 text_preview，跳过")
            continue
        
        blocks_to_insert.append({
            "db_block": block,
            "block_data": {
                "text": block.text_preview,  # 使用预览文本（不完整）
                "title": block.title or "未命名区块",
                "section": block.section or "其他",
                "url": block.url
            }
        })
    
    if not blocks_to_insert:
        print("  ⚠️  没有可插入的块")
        return {}
    
    # 插入到 Milvus
    block_data_list = [item["block_data"] for item in blocks_to_insert]
    milvus_ids = ingester.ingest_blocks(
        block_data_list,
        collection_name=collection_name
    )
    
    # 更新数据库
    for item, milvus_id in zip(blocks_to_insert, milvus_ids):
        if milvus_id:
            db_block = item["db_block"]
            db_block.milvus_id = milvus_id
            result[db_block.id] = milvus_id
    
    db_session.commit()
    return result


def re_crawl_and_insert(
    db_session: Session,
    blocks: List[CrawlBlock],
    collection_name: str = None
) -> Dict[int, str]:
    """
    重新爬取并插入到 Milvus
    
    Returns:
        Dict[block_id, milvus_id]: 成功插入的块ID和对应的Milvus ID
    """
    if not blocks:
        print("没有需要修复的记录")
        return {}
    
    # 按 URL 分组 blocks
    url_to_blocks = {}
    for block in blocks:
        if block.url not in url_to_blocks:
            url_to_blocks[block.url] = []
        url_to_blocks[block.url].append(block)
    
    print(f"需要修复 {len(blocks)} 个块，涉及 {len(url_to_blocks)} 个URL")
    
    # 确定集合名称（从第一个 block 的 task 中获取，或使用默认值）
    if collection_name is None:
        if blocks[0].task_id:
            task = db_session.query(CrawlTask).filter(CrawlTask.id == blocks[0].task_id).first()
            if task:
                collection_name = task.collection_name
        if not collection_name:
            collection_name = settings.COLLECTION_STANDARD
    
    print(f"使用集合: {collection_name}")
    
    # 初始化爬虫和数据处理器
    crawler = WebCrawler(base_url="")
    ingester = DataIngester()
    
    result = {}  # {block_id: milvus_id}
    
    # 逐个 URL 处理
    for url, url_blocks in url_to_blocks.items():
        print(f"\n处理 URL: {url} ({len(url_blocks)} 个块)")
        
        try:
            # 重新爬取
            html = crawler.fetch_page(url)
            if not html:
                print(f"  ⚠️  无法获取页面内容，跳过")
                continue
            
            # 提取语义块
            semantic_blocks = crawler.extract_semantic_blocks(html, url)
            
            if not semantic_blocks:
                print(f"  ⚠️  未提取到语义块，尝试提取普通文本")
                text = crawler.extract_text(html)
                if text:
                    semantic_blocks = [{
                        "text": text,
                        "title": "页面内容",
                        "section": "其他",
                        "url": url
                    }]
                else:
                    print(f"  ⚠️  无法提取文本，跳过")
                    continue
            
            # 匹配 blocks：根据 title 和 section 匹配
            # 如果无法精确匹配，则按顺序匹配
            matched_blocks = []
            for db_block in url_blocks:
                # 尝试找到匹配的语义块
                matched = False
                for sem_block in semantic_blocks:
                    # 简单的匹配逻辑：title 或 section 相似
                    if (db_block.title and db_block.title in sem_block.get("title", "")) or \
                       (db_block.section and db_block.section in sem_block.get("section", "")):
                        matched_blocks.append({
                            "db_block": db_block,
                            "sem_block": sem_block
                        })
                        matched = True
                        break
                
                # 如果无法匹配，使用第一个未使用的语义块
                if not matched and semantic_blocks:
                    matched_blocks.append({
                        "db_block": db_block,
                        "sem_block": semantic_blocks[0]  # 使用第一个
                    })
            
            # 如果没有匹配到，使用所有语义块
            if not matched_blocks and semantic_blocks:
                for i, db_block in enumerate(url_blocks):
                    if i < len(semantic_blocks):
                        matched_blocks.append({
                            "db_block": db_block,
                            "sem_block": semantic_blocks[i]
                        })
            
            # 准备插入数据
            blocks_to_insert = []
            for match in matched_blocks:
                db_block = match["db_block"]
                sem_block = match["sem_block"]
                
                # 如果文本太长，需要分割
                text = sem_block["text"]
                if len(text) > 1000:
                    # 简单分割（实际应该用 TextProcessor）
                    chunks = [text[i:i+1000] for i in range(0, len(text), 900)]
                else:
                    chunks = [text]
                
                for chunk in chunks:
                    blocks_to_insert.append({
                        "db_block": db_block,
                        "block_data": {
                            "text": chunk,
                            "title": sem_block.get("title", db_block.title or "未命名区块"),
                            "section": sem_block.get("section", db_block.section or "其他"),
                            "url": url
                        }
                    })
            
            # 插入到 Milvus
            if blocks_to_insert:
                block_data_list = [item["block_data"] for item in blocks_to_insert]
                milvus_ids = ingester.ingest_blocks(
                    block_data_list,
                    collection_name=collection_name
                )
                
                # 更新数据库
                for i, (item, milvus_id) in enumerate(zip(blocks_to_insert, milvus_ids)):
                    if milvus_id:
                        db_block = item["db_block"]
                        db_block.milvus_id = milvus_id
                        result[db_block.id] = milvus_id
                        print(f"  ✅ 块 #{db_block.id} -> Milvus ID: {milvus_id}")
                
                db_session.commit()
                print(f"  ✅ 成功处理 {len([r for r in result.values() if r])} 个块")
        
        except Exception as e:
            print(f"  ❌ 处理失败: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    return result


def main():
    """主函数"""
    print("=" * 60)
    print("修复 milvus_id 为 NULL 的记录")
    print("=" * 60)
    
    db_session = get_sync_db_session()
    
    try:
        # 1. 获取所有 milvus_id 为 NULL 的记录
        print("\n1. 查找 milvus_id 为 NULL 的记录...")
        null_blocks = get_null_milvus_id_blocks(db_session)
        
        if not null_blocks:
            print("✅ 没有需要修复的记录！")
            return
        
        print(f"找到 {len(null_blocks)} 条记录需要修复")
        
        # 2. 按任务分组（可选）
        task_groups = {}
        for block in null_blocks:
            task_id = block.task_id
            if task_id not in task_groups:
                task_groups[task_id] = []
            task_groups[task_id].append(block)
        
        print(f"涉及 {len(task_groups)} 个任务")
        
        # 3. 选择修复方式
        print("\n2. 选择修复方式：")
        print("  1. 快速修复（使用 text_preview，文本不完整但速度快）")
        print("  2. 完整修复（重新爬取，文本完整但速度慢）")
        
        choice = input("请选择 (1/2，默认1): ").strip() or "1"
        
        total_fixed = 0
        
        if choice == "1":
            print("\n使用快速修复模式...")
            for task_id, blocks in task_groups.items():
                print(f"\n处理任务 #{task_id} ({len(blocks)} 个块)")
                result = insert_using_preview(db_session, blocks)
                total_fixed += len(result)
        else:
            print("\n使用完整修复模式（重新爬取）...")
            for task_id, blocks in task_groups.items():
                print(f"\n处理任务 #{task_id} ({len(blocks)} 个块)")
                result = re_crawl_and_insert(db_session, blocks)
                total_fixed += len(result)
        
        # 4. 统计结果
        print("\n" + "=" * 60)
        print("修复完成！")
        print(f"成功修复: {total_fixed}/{len(null_blocks)} 条记录")
        print("=" * 60)
        
        # 5. 再次检查
        remaining = get_null_milvus_id_blocks(db_session)
        if remaining:
            print(f"\n⚠️  仍有 {len(remaining)} 条记录未修复")
            print("可能原因：")
            print("  - URL 无法访问")
            print("  - 页面内容已变化")
            print("  - 向量化失败")
        else:
            print("\n✅ 所有记录已成功修复！")
    
    except Exception as e:
        print(f"\n❌ 修复过程出错: {e}")
        import traceback
        traceback.print_exc()
        db_session.rollback()
    finally:
        db_session.close()


if __name__ == "__main__":
    main()

