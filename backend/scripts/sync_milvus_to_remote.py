"""
将本地 Milvus 向量数据库的数据同步到远程服务器

用法:
    python sync_milvus_to_remote.py
    python sync_milvus_to_remote.py --remote-host 124.221.26.181 --remote-port 19530
    python sync_milvus_to_remote.py --collections rag_standard rag_faq
"""
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

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


class MilvusSync:
    """Milvus 数据同步类"""
    
    def __init__(self, local_host: str = None, local_port: str = None,
                 remote_host: str = None, remote_port: str = None):
        """
        初始化同步器
        
        Args:
            local_host: 本地 Milvus 主机地址
            local_port: 本地 Milvus 端口
            remote_host: 远程 Milvus 主机地址
            remote_port: 远程 Milvus 端口
        """
        # 本地配置
        self.local_host = local_host or settings.MILVUS_HOST
        self.local_port = local_port or settings.MILVUS_PORT
        self.local_client = None
        
        # 远程配置
        self.remote_host = remote_host or "124.221.26.181"
        self.remote_port = remote_port or "19530"
        self.remote_client = None
        
        # 集合配置
        self.rag_collections = [
            settings.COLLECTION_STANDARD,
            settings.COLLECTION_KNOWLEDGE,
            settings.COLLECTION_INTERNAL,
            settings.COLLECTION_PERSONAL
        ]
        self.faq_collection = settings.COLLECTION_FAQ
    
    def connect(self):
        """连接到本地和远程 Milvus"""
        print(f"\n{'='*80}")
        print("🔌 正在连接 Milvus...")
        print(f"{'='*80}")
        
        # 连接本地
        try:
            local_uri = f"http://{self.local_host}:{self.local_port}"
            print(f"📡 连接本地 Milvus: {local_uri}")
            self.local_client = MilvusClient(uri=local_uri)
            local_cols = self.local_client.list_collections()
            print(f"✅ 本地连接成功，找到 {len(local_cols)} 个集合: {local_cols}")
        except Exception as e:
            print(f"❌ 本地连接失败: {e}")
            raise
        
        # 连接远程
        try:
            remote_uri = f"http://{self.remote_host}:{self.remote_port}"
            print(f"📡 连接远程 Milvus: {remote_uri}")
            self.remote_client = MilvusClient(uri=remote_uri)
            remote_cols = self.remote_client.list_collections()
            print(f"✅ 远程连接成功，现有 {len(remote_cols)} 个集合: {remote_cols}")
        except Exception as e:
            print(f"❌ 远程连接失败: {e}")
            print(f"   请检查:")
            print(f"   1. 远程服务器地址是否正确: {self.remote_host}:{self.remote_port}")
            print(f"   2. 远程 Milvus 服务是否运行")
            print(f"   3. 防火墙是否允许连接")
            raise
    
    def ensure_collection_exists(self, collection_name: str, is_faq: bool = False):
        """
        确保远程集合存在，如果不存在则创建
        
        Args:
            collection_name: 集合名称
            is_faq: 是否为 FAQ 集合
        """
        existing_cols = self.remote_client.list_collections()
        
        if collection_name in existing_cols:
            print(f"  ✅ 远程集合 {collection_name} 已存在")
            return
        
        print(f"  📦 创建远程集合 {collection_name}...")
        try:
            self.remote_client.create_collection(
                collection_name=collection_name,
                dimension=1024,  # 向量维度
                metric_type="COSINE",  # 相似度度量方式
                auto_id=True  # 自动生成 ID
            )
            print(f"  ✅ 远程集合 {collection_name} 创建成功")
        except Exception as e:
            print(f"  ❌ 创建远程集合失败: {e}")
            raise
    
    def get_collection_stats(self, client: MilvusClient, collection_name: str) -> int:
        """获取集合中的记录数量"""
        try:
            stats = client.get_collection_stats(collection_name)
            return stats.get("row_count", 0)
        except Exception as e:
            print(f"  ⚠️  无法获取统计信息: {e}")
            return 0
    
    def read_collection_data(self, collection_name: str, batch_size: int = 1000) -> List[Dict[str, Any]]:
        """
        从本地集合读取所有数据
        
        Args:
            collection_name: 集合名称
            batch_size: 每批读取的数量（用于进度显示）
            
        Returns:
            所有数据的列表
        """
        print(f"\n📖 正在读取本地集合 {collection_name} 的数据...")
        
        # 判断集合类型
        is_faq = collection_name == self.faq_collection
        
        # 确定输出字段
        if is_faq:
            output_fields = ["id", "vector", "question", "answer", "source"]
        else:
            output_fields = ["id", "vector", "text", "source", "dept_id", "user_id"]
        
        # 获取总数
        total_count = self.get_collection_stats(self.local_client, collection_name)
        if total_count == 0:
            print(f"  ⚠️  集合 {collection_name} 中没有数据")
            return []
        
        print(f"  📊 总记录数: {total_count}")
        
        # 直接读取所有数据（MilvusClient 支持一次性读取）
        all_data = []
        try:
            # 尝试一次性读取所有数据
            # Milvus 的 limit 可能有上限（通常是 16384），所以需要分批
            max_limit = 16384  # Milvus 默认最大 limit
            
            if total_count <= max_limit:
                # 数据量不大，一次性读取
                results = self.local_client.query(
                    collection_name=collection_name,
                    filter="",  # 空过滤表示查询所有
                    limit=total_count,
                    output_fields=output_fields
                )
                all_data = results
                print(f"  ✅ 成功读取 {len(all_data)} 条记录")
            else:
                # 数据量大，需要分批读取
                print(f"  📦 数据量较大，分批读取（每批最多 {batch_size} 条）...")
                all_data = []
                last_max_id = None
                read_count = 0
                
                with tqdm(total=total_count, desc=f"  读取 {collection_name}") if HAS_TQDM else tqdm() as pbar:
                    while read_count < total_count:
                        # 构建过滤条件：使用 ID 范围
                        if last_max_id is not None:
                            filter_expr = f"id > {last_max_id}"
                        else:
                            filter_expr = ""
                        
                        # 读取一批数据
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
                        
                        # 更新 last_max_id 为当前批次的最大 ID
                        if results:
                            last_max_id = max(r["id"] for r in results)
                        else:
                            break
                        
                        # 如果读取的数据少于 batch_size，说明已经读完了
                        if len(results) < batch_limit:
                            break
                
                print(f"  ✅ 分批读取完成，共 {len(all_data)} 条记录")
        except Exception as e:
            print(f"  ❌ 读取数据时出错: {e}")
            # 如果一次性读取失败，尝试分批读取
            print(f"  🔄 尝试分批读取...")
            try:
                # 使用迭代方式：每次读取一批，直到没有更多数据
                all_data = []
                last_id = None
                max_iterations = (total_count // batch_size) + 10  # 防止无限循环
                iteration = 0
                
                while iteration < max_iterations:
                    # 构建过滤条件
                    if last_id is not None:
                        filter_expr = f"id > {last_id}"
                    else:
                        filter_expr = ""
                    
                    results = self.local_client.query(
                        collection_name=collection_name,
                        filter=filter_expr,
                        limit=batch_size,
                        output_fields=output_fields
                    )
                    
                    if not results:
                        break
                    
                    all_data.extend(results)
                    last_id = max(r["id"] for r in results)
                    iteration += 1
                    
                    if len(all_data) >= total_count:
                        break
                
                print(f"  ✅ 分批读取成功，共 {len(all_data)} 条记录")
            except Exception as e2:
                print(f"  ❌ 分批读取也失败: {e2}")
                import traceback
                traceback.print_exc()
                return []
        
        return all_data
    
    def upload_collection_data(self, collection_name: str, data: List[Dict[str, Any]], 
                              batch_size: int = 100):
        """
        将数据上传到远程集合
        
        Args:
            collection_name: 集合名称
            data: 要上传的数据列表
            batch_size: 每批插入的数量
        """
        if not data:
            print(f"  ⚠️  没有数据需要上传")
            return
        
        print(f"\n📤 正在上传数据到远程集合 {collection_name}...")
        print(f"  📊 总记录数: {len(data)}")
        
        # 判断集合类型
        is_faq = collection_name == self.faq_collection
        
        # 准备数据：移除 id 字段（因为远程使用 auto_id）
        prepared_data = []
        for item in data:
            new_item = {}
            for key, value in item.items():
                if key != "id":  # 移除 id，让远程自动生成
                    new_item[key] = value
            prepared_data.append(new_item)
        
        # 分批插入
        total_inserted = 0
        total_batches = (len(prepared_data) + batch_size - 1) // batch_size
        
        with tqdm(total=len(prepared_data), desc=f"  上传 {collection_name}") if HAS_TQDM else tqdm() as pbar:
            for i in range(0, len(prepared_data), batch_size):
                batch = prepared_data[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                
                if not HAS_TQDM:
                    print(f"  上传批次 {batch_num}/{total_batches} ({len(batch)} 条)...", end=" ")
                
                try:
                    result = self.remote_client.insert(
                        collection_name=collection_name,
                        data=batch
                    )
                    total_inserted += len(batch)
                    
                    if HAS_TQDM:
                        pbar.update(len(batch))
                    else:
                        print("✅")
                except Exception as e:
                    if not HAS_TQDM:
                        print("❌")
                    print(f"  ❌ 插入批次失败 (索引 {i}-{i+len(batch)-1}): {e}")
                    # 继续处理下一批
                    continue
        
        print(f"  ✅ 成功上传 {total_inserted}/{len(prepared_data)} 条记录")
        return total_inserted
    
    def sync_collection(self, collection_name: str, skip_existing: bool = False):
        """
        同步单个集合
        
        Args:
            collection_name: 集合名称
            skip_existing: 如果远程集合已存在数据，是否跳过
        """
        print(f"\n{'='*80}")
        print(f"🔄 同步集合: {collection_name}")
        print(f"{'='*80}")
        
        # 检查本地集合是否存在
        local_cols = self.local_client.list_collections()
        if collection_name not in local_cols:
            print(f"❌ 本地集合 {collection_name} 不存在，跳过")
            return
        
        # 检查本地是否有数据
        local_count = self.get_collection_stats(self.local_client, collection_name)
        if local_count == 0:
            print(f"⚠️  本地集合 {collection_name} 没有数据，跳过")
            return
        
        # 判断集合类型
        is_faq = collection_name == self.faq_collection
        
        # 确保远程集合存在
        self.ensure_collection_exists(collection_name, is_faq)
        
        # 检查远程是否已有数据
        remote_count = self.get_collection_stats(self.remote_client, collection_name)
        if remote_count > 0:
            if skip_existing:
                print(f"⚠️  远程集合 {collection_name} 已有 {remote_count} 条数据，跳过")
                return
            else:
                print(f"⚠️  远程集合 {collection_name} 已有 {remote_count} 条数据，将继续添加")
        
        # 读取本地数据
        local_data = self.read_collection_data(collection_name)
        
        if not local_data:
            print(f"⚠️  没有数据需要同步")
            return
        
        # 上传到远程
        self.upload_collection_data(collection_name, local_data)
        
        # 验证
        final_remote_count = self.get_collection_stats(self.remote_client, collection_name)
        print(f"\n✅ 同步完成！")
        print(f"   本地记录数: {local_count}")
        print(f"   远程记录数: {final_remote_count}")
    
    def sync_all(self, collections: Optional[List[str]] = None, skip_existing: bool = False):
        """
        同步所有集合
        
        Args:
            collections: 要同步的集合列表，None 表示同步所有
            skip_existing: 如果远程集合已存在数据，是否跳过
        """
        # 连接
        self.connect()
        
        # 确定要同步的集合
        if collections is None:
            all_collections = self.rag_collections + [self.faq_collection]
        else:
            all_collections = collections
        
        # 过滤出存在的集合
        local_cols = self.local_client.list_collections()
        collections_to_sync = [col for col in all_collections if col in local_cols]
        
        if not collections_to_sync:
            print("❌ 没有找到需要同步的集合")
            return
        
        print(f"\n📋 将同步以下集合: {collections_to_sync}")
        
        # 逐个同步
        for collection_name in collections_to_sync:
            try:
                self.sync_collection(collection_name, skip_existing)
            except Exception as e:
                print(f"❌ 同步集合 {collection_name} 时出错: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\n{'='*80}")
        print("🎉 所有集合同步完成！")
        print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(
        description="将本地 Milvus 数据同步到远程服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认远程地址同步所有集合
  python sync_milvus_to_remote.py
  
  # 指定远程地址和端口
  python sync_milvus_to_remote.py --remote-host 124.221.26.181 --remote-port 19530
  
  # 只同步指定集合
  python sync_milvus_to_remote.py --collections rag_standard rag_faq
  
  # 如果远程集合已有数据则跳过
  python sync_milvus_to_remote.py --skip-existing
        """
    )
    
    parser.add_argument("--local-host", type=str, default=None,
                       help="本地 Milvus 主机地址 (默认: 从配置读取)")
    parser.add_argument("--local-port", type=str, default=None,
                       help="本地 Milvus 端口 (默认: 从配置读取)")
    parser.add_argument("--remote-host", type=str, default="124.221.26.181",
                       help="远程 Milvus 主机地址 (默认: 124.221.26.181)")
    parser.add_argument("--remote-port", type=str, default="19530",
                       help="远程 Milvus 端口 (默认: 19530)")
    parser.add_argument("--collections", type=str, nargs="+", default=None,
                       help="要同步的集合列表，不指定则同步所有")
    parser.add_argument("--skip-existing", action="store_true",
                       help="如果远程集合已有数据则跳过")
    parser.add_argument("--batch-size", type=int, default=100,
                       help="批量插入大小 (默认: 100)")
    
    args = parser.parse_args()
    
    # 创建同步器
    syncer = MilvusSync(
        local_host=args.local_host,
        local_port=args.local_port,
        remote_host=args.remote_host,
        remote_port=args.remote_port
    )
    
    # 执行同步
    try:
        syncer.sync_all(
            collections=args.collections,
            skip_existing=args.skip_existing
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断操作")
    except Exception as e:
        print(f"\n❌ 同步过程中出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

