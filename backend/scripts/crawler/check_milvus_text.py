"""
直接查看 Milvus 中存储的文本内容，验证爬取数据是否正确
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings
from pymilvus import MilvusClient


def check_milvus_text(collection_name="rag_faq", limit=10, filter_expr="", 
                      output_fields=None, show_full_text=False):
    """
    检查 Milvus 中存储的完整文本
    
    Args:
        collection_name: 集合名称
        limit: 查询记录数量限制
        filter_expr: 过滤表达式，如 'source == "xxx"' 或 'id == 123'
        output_fields: 要返回的字段列表，None 则使用默认字段
        show_full_text: 是否显示完整文本（而不是只显示前400字符）
    """
    print(f"\n{'='*80}")
    print(f"检查 Milvus 中的完整文本（集合: {collection_name}）")
    print(f"{'='*80}")
    
    try:
        client = MilvusClient(
            uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
        )
        
        # 检查集合是否存在
        existing_cols = client.list_collections()
        if collection_name not in existing_cols:
            print(f" 集合 {collection_name} 不存在")
            print(f"   现有集合: {existing_cols}")
            return
        
        print(f" 集合 {collection_name} 存在")
        
        # 判断是否为 FAQ 集合（根据集合名称或配置）
        is_faq_collection = collection_name == settings.COLLECTION_FAQ
        
        # 默认输出字段：FAQ 集合使用 question/answer，其他使用 text
        if output_fields is None:
            if is_faq_collection:
                output_fields = ["question", "answer", "source"]
            else:
                output_fields = ["text", "source"]
        
        # 获取集合统计信息
        try:
            stats = client.get_collection_stats(collection_name)
            entity_count = stats.get("row_count", 0)
            print(f" 集合中的实体数量: {entity_count}")
        except Exception as e:
            print(f"  无法获取统计信息: {e}")
        
        # 尝试使用 query 方法查询数据
        try:
            if filter_expr:
                print(f"\n 使用过滤条件查询（限制 {limit} 条）...")
                print(f"   过滤条件: {filter_expr}")
            else:
                print(f"\n 查询前 {limit} 条记录...")
            
            results = client.query(
                collection_name=collection_name,
                filter=filter_expr,
                limit=limit,
                output_fields=output_fields
            )
            
            if not results:
                print("  集合中没有数据")
                return
            
            print(f" 找到 {len(results)} 条记录\n")
            
            for i, result in enumerate(results, 1):
                print(f"【记录 {i}】")
                
                # 显示 ID
                if 'id' in result:
                    print(f"  ID: {result['id']}")
                
                # 显示其他元数据字段（除了 text, question, answer, id）
                for key, value in result.items():
                    if key not in ['text', 'question', 'answer', 'id']:
                        print(f"  {key}: {value}")
                
                # 判断是 FAQ 还是普通文本
                if is_faq_collection:
                    # FAQ 格式：显示问题和答案
                    question = result.get('question', '')
                    answer = result.get('answer', '')
                    
                    if question:
                        print(f"   问题长度: {len(question)} 字符")
                        if show_full_text:
                            print(f"  完整问题:")
                            print(f"  {'─'*76}")
                            lines = question.split('\n')
                            for line in lines:
                                if line.strip():
                                    print(f"  {line[:76]}")
                            print(f"  {'─'*76}")
                        else:
                            print(f"  问题内容（前400字符）:")
                            print(f"  {'─'*76}")
                            preview = question[:400]
                            lines = preview.split('\n')
                            for line in lines[:10]:
                                if line.strip():
                                    print(f"  {line[:76]}")
                            if len(question) > 400:
                                print(f"  ... (还有 {len(question) - 400} 字符)")
                            print(f"  {'─'*76}")
                    else:
                        print("   问题: (空)")
                    
                    if answer:
                        print(f"  💡 答案长度: {len(answer)} 字符")
                        if show_full_text:
                            print(f"  完整答案:")
                            print(f"  {'─'*76}")
                            lines = answer.split('\n')
                            for line in lines:
                                if line.strip():
                                    print(f"  {line[:76]}")
                            print(f"  {'─'*76}")
                        else:
                            print(f"  答案内容（前400字符）:")
                            print(f"  {'─'*76}")
                            preview = answer[:400]
                            lines = preview.split('\n')
                            for line in lines[:10]:
                                if line.strip():
                                    print(f"  {line[:76]}")
                            if len(answer) > 400:
                                print(f"  ... (还有 {len(answer) - 400} 字符)")
                            print(f"  {'─'*76}")
                    else:
                        print("   答案: (空)")
                else:
                    # 普通文本格式
                    text = result.get('text', '')
                    if text:
                        print(f"  文本长度: {len(text)} 字符")
                        
                        if show_full_text:
                            print(f"  完整文本内容:")
                            print(f"  {'─'*76}")
                            lines = text.split('\n')
                            for line in lines:
                                if line.strip():
                                    print(f"  {line[:76]}")
                            print(f"  {'─'*76}")
                        else:
                            print(f"  文本内容（前400字符）:")
                            print(f"  {'─'*76}")
                            preview = text[:400]
                            lines = preview.split('\n')
                            for line in lines[:15]:  # 最多显示15行
                                if line.strip():
                                    print(f"  {line[:76]}")
                            if len(lines) > 15 or len(text) > 400:
                                remaining = len(lines) - 15 if len(lines) > 15 else 0
                                if remaining > 0:
                                    print(f"  ... (还有 {remaining} 行)")
                                if len(text) > 400:
                                    print(f"  ... (还有 {len(text) - 400} 字符)")
                            
                            # 检查是否包含中文
                            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text[:500])
                            chinese_count = sum(1 for char in text[:500] if '\u4e00' <= char <= '\u9fff')
                            print(f"  {'─'*76}")
                            print(f"  {' 包含中文' if has_chinese else '❌ 不包含中文（可能是乱码）'}")
                            if has_chinese:
                                print(f"  前500字符中中文数量: {chinese_count}")
                    else:
                        print("  文本: (空)")
                
                print(f"  {'─'*76}\n")
        
        except Exception as e:
            print(f" 查询失败: {e}")
            print(f"\n 提示: 如果查询失败，请使用 Milvus Web UI 查看数据:")
            print(f"   http://localhost:8001")
            import traceback
            traceback.print_exc()
        
    except Exception as e:
        print(f" 连接 Milvus 失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="查看 Milvus 中存储的文本内容（实时查询，比 Web UI 更及时）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看默认集合的前10条记录
  python check_milvus_text.py
  
  # 查看指定集合的前20条记录
  python check_milvus_text.py --collection rag_faq --limit 20
  
  # 按来源过滤
  python check_milvus_text.py --filter 'source == "xxx"'
  
  # 按ID查询
  python check_milvus_text.py --filter 'id == 123'
  
  # 显示完整文本
  python check_milvus_text.py --full-text
  
  # 指定输出字段
  python check_milvus_text.py --fields text source dept_id
  
  # FAQ 集合会自动使用 question 和 answer 字段
  python check_milvus_text.py --collection rag_faq
  
  # 也可以手动指定 FAQ 字段
  python check_milvus_text.py --collection rag_faq --fields question answer source
        """
    )
    parser.add_argument("--collection", type=str, default="rag_standard", 
                       help="集合名称 (默认: rag_standard)")
    parser.add_argument("--limit", type=int, default=10, 
                       help="显示记录数量 (默认: 10)")
    parser.add_argument("--filter", type=str, default="", 
                       help="过滤表达式，如 'source == \"xxx\"' 或 'id == 123'")
    parser.add_argument("--fields", type=str, nargs="+", default=None,
                       help="要返回的字段列表，如: --fields text source dept_id")
    parser.add_argument("--full-text", action="store_true",
                       help="显示完整文本内容（而不是只显示前400字符）")
    
    args = parser.parse_args()
    
    check_milvus_text(
        collection_name=args.collection,
        limit=args.limit,
        filter_expr=args.filter,
        output_fields=args.fields,
        show_full_text=args.full_text
    )

