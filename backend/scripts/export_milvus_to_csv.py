"""
将本地 Milvus 向量数据库的数据导出为 CSV 文件

用法:
    python export_milvus_to_csv.py
    python export_milvus_to_csv.py --output-dir ./exports
    python export_milvus_to_csv.py --collections rag_standard rag_faq
    python export_milvus_to_csv.py --include-vector  # 包含向量字段
"""
import sys
import argparse
import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# tqdm 可选（用于进度条）
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    # 如果没有 tqdm，创建一个简单的占位符
    class tqdm:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def update(self, n=1):
            pass

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings
from pymilvus import MilvusClient


class MilvusExporter:
    """Milvus 数据导出类"""
    
    def __init__(self, local_host: str = None, local_port: str = None):
        """
        初始化导出器
        
        Args:
            local_host: 本地 Milvus 主机地址
            local_port: 本地 Milvus 端口
        """
        # 本地配置
        self.local_host = local_host or settings.MILVUS_HOST
        self.local_port = local_port or settings.MILVUS_PORT
        self.local_client = None
        
        # 集合配置
        self.rag_collections = [
            settings.COLLECTION_STANDARD,
            settings.COLLECTION_KNOWLEDGE,
            settings.COLLECTION_INTERNAL,
            settings.COLLECTION_PERSONAL
        ]
        self.faq_collection = settings.COLLECTION_FAQ
    
    def connect(self):
        """连接到本地 Milvus"""
        print(f"\n{'='*80}")
        print(" 正在连接 Milvus...")
        print(f"{'='*80}")
        
        # 连接本地
        try:
            local_uri = f"http://{self.local_host}:{self.local_port}"
            print(f" 连接本地 Milvus: {local_uri}")
            self.local_client = MilvusClient(uri=local_uri)
            local_cols = self.local_client.list_collections()
            print(f" 本地连接成功，找到 {len(local_cols)} 个集合: {local_cols}")
        except Exception as e:
            print(f" 本地连接失败: {e}")
            raise
    
    def get_collection_stats(self, collection_name: str) -> int:
        """获取集合中的记录数量，失败时返回 0"""
        try:
            # 优先尝试官方统计接口（部分版本没有）
            if hasattr(self.local_client, "get_collection_stats"):
                stats = self.local_client.get_collection_stats(collection_name)
                return stats.get("row_count", 0) or stats.get("rowCount", 0) or 0
            if hasattr(self.local_client, "get_collection_statistics"):
                stats = self.local_client.get_collection_statistics(collection_name)
                return stats.get("row_count", 0) or stats.get("rowCount", 0) or 0
            # 兼容旧版本：使用 count(*) 查询
            res = self.local_client.query(
                collection_name=collection_name,
                filter="",
                output_fields=["count(*)"],
            )
            if res and isinstance(res, list) and "count(*)" in res[0]:
                return int(res[0]["count(*)"])
            print("    当前客户端不支持统计接口，count(*) 也未返回，继续尝试直接读取数据")
            return 0
        except Exception as e:
            print(f"    无法获取统计信息: {e}")
            return 0
    
    def read_collection_data(self, collection_name: str, batch_size: int = 1000) -> List[Dict[str, Any]]:
        """
        从本地集合读取所有数据
        
        Args:
            collection_name: 集合名称
            batch_size: 每批读取的数量
            
        Returns:
            所有数据的列表
        """
        print(f"\n 正在读取集合 {collection_name} 的数据...")
        
        # 判断集合类型
        is_faq = collection_name == self.faq_collection
        
        # 确定输出字段
        if is_faq:
            output_fields = ["id", "vector", "question", "answer", "source"]
        else:
            output_fields = ["id", "vector", "text", "source", "dept_id", "user_id"]
        
        # 获取总数（可能失败返回 0）
        total_count = self.get_collection_stats(collection_name)
        if total_count > 0:
            print(f"   总记录数: {total_count}")
        else:
            print("    无法获取总数或总数为 0，直接尝试读取数据")
        
        # 分批读取数据
        all_data = []
        max_limit = 16384  # Milvus 默认最大 limit
        
        try:
            # 先尝试一次性读取（最多 16384 条），当前数据量足够
            primary_limit = max_limit if total_count == 0 else min(total_count, max_limit)
            results = self.local_client.query(
                collection_name=collection_name,
                filter="",
                limit=primary_limit,
                output_fields=output_fields
            )
            all_data = results or []
            if not all_data:
                print(f"    集合 {collection_name} 中没有数据")
                return []
            print(f"   成功读取 {len(all_data)} 条记录")
            
            # 如果估计的总数大于 max_limit，则继续分批读取剩余数据
            if total_count > max_limit:
                print(f"   数据量较大，继续分批读取（每批最多 {batch_size} 条）...")
                last_max_id = max(r["id"] for r in all_data)
                read_count = len(all_data)
                
                with tqdm(total=total_count, desc=f"  读取 {collection_name}") if HAS_TQDM else tqdm() as pbar:
                    while read_count < total_count:
                        filter_expr = f"id > {last_max_id}"
                        batch_limit = min(batch_size, max_limit)
                        results = self.local_client.query(
                            collection_name=collection_name,
                            filter=filter_expr,
                            limit=batch_limit,
                            output_fields=output_fields
                        )
                        
                        if not results:
                            break
                        
                        all_data.extend(results)
                        read_count += len(results)
                        
                        if HAS_TQDM:
                            pbar.update(len(results))
                        
                        last_max_id = max(r["id"] for r in results)
                        
                        if len(results) < batch_limit:
                            break
                
                print(f"   分批读取完成，共 {len(all_data)} 条记录")
        except Exception as e:
            print(f"   读取数据时出错: {e}")
            import traceback
            traceback.print_exc()
            return []
        
        return all_data
    
    def format_vector(self, vector: List[float]) -> str:
        """将向量格式化为字符串"""
        if not vector:
            return ""
        # 将向量转换为 JSON 字符串，确保可序列化为 float
        try:
            vector_as_float = [float(x) for x in vector]
        except Exception:
            vector_as_float = [float(x.item()) if hasattr(x, "item") else float(x) for x in vector]
        return json.dumps(vector_as_float)

    def _sanitize_value(self, value: Any) -> Any:
        """将值转换为可 JSON 序列化的基本类型"""
        if value is None:
            return ""
        if isinstance(value, (str, int, float)):
            return value
        if hasattr(value, "item"):  # numpy 类型
            try:
                return value.item()
            except Exception:
                return float(value)
        if isinstance(value, list):
            return [self._sanitize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._sanitize_value(v) for k, v in value.items()}
        return str(value)
    
    def prepare_data_for_csv(
        self,
        data: List[Dict[str, Any]],
        include_vector: bool = False,
        for_import: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        准备数据用于 CSV 导出
        
        Args:
            data: 原始数据列表
            include_vector: 是否包含向量字段
            
        Returns:
            处理后的数据列表
        """
        prepared = []
        for item in data:
            new_item = {}
            for key, value in item.items():
                if key == "id" and for_import:
                    # 导入模式下去掉自增主键
                    continue
                if key == "vector":
                    if include_vector:
                        # 包含向量：转换为 JSON 字符串
                        new_item["vector"] = self.format_vector(value)
                    else:
                        # 不包含向量：跳过
                        continue
                elif isinstance(value, (list, dict)):
                    # 其他复杂类型也转换为 JSON 字符串
                    sanitized = self._sanitize_value(value)
                    new_item[key] = json.dumps(sanitized, ensure_ascii=False) if sanitized != "" else ""
                elif value is None:
                    new_item[key] = ""
                else:
                    new_item[key] = self._sanitize_value(value)
            prepared.append(new_item)
        return prepared
    
    def export_to_csv(
        self,
        collection_name: str,
        output_dir: Path,
        include_vector: bool = False,
        for_import: bool = False,
    ):
        """
        将集合数据导出为 CSV 文件
        
        Args:
            collection_name: 集合名称
            output_dir: 输出目录
            include_vector: 是否包含向量字段
        """
        # 读取数据
        data = self.read_collection_data(collection_name)
        if not data:
            print(f"    集合 {collection_name} 没有数据，跳过导出")
            return
        
        # 准备数据
        print(f"\n 正在准备数据...")
        prepared_data = self.prepare_data_for_csv(
            data,
            include_vector=include_vector,
            for_import=for_import,
        )
        
        if not prepared_data:
            print(f"    没有数据需要导出")
            return
        
        # 确定输出文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"{collection_name}_{timestamp}.csv"
        
        # 获取字段名（排除 vector 如果不包含）
        if collection_name == self.faq_collection:
            field_order = ["question", "answer", "source"]
        else:
            field_order = ["text", "source", "dept_id", "user_id"]
        if include_vector:
            field_order.insert(0, "vector")
        # 保留未知字段（安全兜底）
        extra_fields = [f for f in prepared_data[0].keys() if f not in field_order]
        fieldnames = field_order + extra_fields
        
        # 写入 CSV
        print(f"\n 正在导出到 {output_file}...")
        try:
            with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                with tqdm(total=len(prepared_data), desc=f"  写入 {collection_name}") if HAS_TQDM else tqdm() as pbar:
                    for row in prepared_data:
                        writer.writerow(row)
                        if HAS_TQDM:
                            pbar.update(1)
            
            file_size = output_file.stat().st_size / 1024 / 1024  # MB
            print(f"   导出成功！")
            print(f"   文件: {output_file}")
            print(f"   记录数: {len(prepared_data)}")
            print(f"   文件大小: {file_size:.2f} MB")
        except Exception as e:
            print(f"   导出失败: {e}")
            import traceback
            traceback.print_exc()
    
    def export_all(
        self,
        output_dir: Path,
        collections: Optional[List[str]] = None,
        include_vector: bool = False,
        for_import: bool = False,
    ):
        """
        导出所有或指定的集合
        
        Args:
            output_dir: 输出目录
            collections: 要导出的集合列表，如果为 None 则导出所有集合
            include_vector: 是否包含向量字段
        """
        # 确保输出目录存在
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 确定要导出的集合
        if collections is None:
            # 导出所有集合
            all_collections = self.rag_collections + [self.faq_collection]
            existing_collections = self.local_client.list_collections()
            collections = [col for col in all_collections if col in existing_collections]
        
        if not collections:
            print("    没有找到要导出的集合")
            return
        
        print(f"\n{'='*80}")
        print(f" 开始导出 {len(collections)} 个集合到 {output_dir}")
        print(f"{'='*80}")
        
        for i, collection_name in enumerate(collections, 1):
            print(f"\n[{i}/{len(collections)}] 处理集合: {collection_name}")
            try:
                self.export_to_csv(
                    collection_name,
                    output_dir,
                    include_vector=include_vector,
                    for_import=for_import,
                )
            except Exception as e:
                print(f"   导出集合 {collection_name} 时出错: {e}")
                continue
        
        print(f"\n{'='*80}")
        print(" 导出完成！")
        print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(
        description="将本地 Milvus 向量数据库的数据导出为 CSV 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 导出所有集合到默认目录
  python export_milvus_to_csv.py
  
  # 导出到指定目录
  python export_milvus_to_csv.py --output-dir ./exports
  
  # 只导出指定集合
  python export_milvus_to_csv.py --collections rag_standard rag_faq
  
  # 包含向量字段（文件会很大）
  python export_milvus_to_csv.py --include-vector
  
  # 指定本地 Milvus 地址
  python export_milvus_to_csv.py --local-host localhost --local-port 19530
        """
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./milvus_exports",
        help="CSV 文件输出目录（默认: ./milvus_exports）"
    )
    
    parser.add_argument(
        "--collections",
        nargs="+",
        help="要导出的集合名称（默认: 导出所有集合）"
    )
    
    parser.add_argument(
        "--include-vector",
        action="store_true",
        help="包含向量字段（适合直接导入 Attu，文件会更大，默认关闭）"
    )
    
    parser.add_argument(
        "--for-import",
        action="store_true",
        help="导入模式：去掉自增主键 id，字段顺序按 schema 输出"
    )
    
    parser.add_argument(
        "--local-host",
        type=str,
        help=f"本地 Milvus 主机地址（默认: {settings.MILVUS_HOST}）"
    )
    
    parser.add_argument(
        "--local-port",
        type=str,
        help=f"本地 Milvus 端口（默认: {settings.MILVUS_PORT}）"
    )
    
    args = parser.parse_args()
    
    # 创建导出器
    exporter = MilvusExporter(
        local_host=args.local_host,
        local_port=args.local_port
    )
    
    try:
        # 连接
        exporter.connect()
        
        # 导出
        output_dir = Path(args.output_dir)
        exporter.export_all(
            output_dir=output_dir,
            collections=args.collections,
            include_vector=args.include_vector,
            for_import=args.for_import,
        )
    except KeyboardInterrupt:
        print("\n\n  用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"\n 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

