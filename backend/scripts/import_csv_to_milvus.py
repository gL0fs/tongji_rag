"""
将 backend/scripts/milvus_exports 目录中的 CSV 文件导入到本地 Milvus。

约定：
- 每个 CSV 文件对应一个集合，集合名 = 文件名（不含扩展名），例如：
    rag_standard.csv  ->  集合名 "rag_standard"
- CSV 第一行为表头，后续行为数据。
- 如果存在 "id" 字段，会在导入前移除（因为集合使用 auto_id）。
- 如果存在 "vector" 字段，则认为是 JSON/列表字符串，会被反序列化为 float 列表后直接写入 Milvus；
  否则不处理向量（假定集合已存在且会自行填充，或你另有脚本负责向量化）。

使用方式：
    # 导入默认目录（backend/scripts/milvus_exports）下的所有 CSV
    python import_csv_to_milvus.py

    # 只导入指定集合
    python import_csv_to_milvus.py --collections rag_standard rag_faq

    # 指定 Milvus 地址
    python import_csv_to_milvus.py --local-host localhost --local-port 19530
"""

import sys
import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from pymilvus import MilvusClient

# 同步 MySQL 相关
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# 保证能找到 app 模块（与 crawler.py 保持一致，从 scripts 子目录向上两级到 backend）
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings  # noqa: E402
from app.models_db import CrawlTask, CrawlBlock  # noqa: E402


class MilvusImporter:
    """从 CSV 导入数据到本地 Milvus，并同步记录到 MySQL 的 CrawlTask/CrawlBlock"""

    def __init__(self, local_host: Optional[str] = None, local_port: Optional[str] = None):
        # 默认使用 localhost，方便在宿主机直接连接 Docker 暴露出来的 Milvus 端口
        # 如果你在容器内部运行脚本，可以显式传入 --local-host milvus-standalone
        self.local_host = local_host or "localhost"
        self.local_port = local_port or settings.MILVUS_PORT
        self.client: Optional[MilvusClient] = None

        # --- MySQL (同步) ---
        # 这里复用 crawler.py 中的同步连接方式，方便脚本直接运行
        # 在宿主机（Windows）上直接运行脚本时，MySQL 是通过 Docker 映射到本机 3306 端口的，
        # 这里显式使用 localhost，避免使用容器内部的主机名（如 "mysql"）导致解析失败。
        sync_db_url = (
            f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
            f"@localhost:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}"
        )
        self.sync_engine = create_engine(sync_db_url, echo=False, pool_pre_ping=True)
        self.SyncSessionLocal = sessionmaker(
            bind=self.sync_engine, expire_on_commit=False, autoflush=False
        )

        # 已知的 RAG / FAQ 集合名，方便做一点点特殊处理
        self.rag_collections = {
            settings.COLLECTION_STANDARD,
            settings.COLLECTION_KNOWLEDGE,
            settings.COLLECTION_INTERNAL,
            settings.COLLECTION_PERSONAL,
        }
        self.faq_collection = settings.COLLECTION_FAQ

    # ------------------------------------------------------------------ #
    # 连接
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        uri = f"http://{self.local_host}:{self.local_port}"
        print("=" * 80)
        print(f"🔌 正在连接本地 Milvus: {uri}")
        print("=" * 80)
        self.client = MilvusClient(uri=uri)
        cols = self.client.list_collections()
        print(f"✅ 连接成功，当前已有集合: {cols}")

    # ------------------------------------------------------------------ #
    # CSV 读取与预处理
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # MySQL Session 辅助
    # ------------------------------------------------------------------ #
    def _get_db(self) -> Session:
        """获取同步数据库 Session"""
        return self.SyncSessionLocal()

    # ------------------------------------------------------------------ #
    # CSV 读取与预处理
    # ------------------------------------------------------------------ #
    def _parse_vector(self, value: str) -> Optional[List[float]]:
        """将 CSV 中的向量字段解析为 float 列表"""
        if not value:
            return None
        try:
            # 兼容两种情况：
            # 1. JSON 字符串 "[0.1, 0.2, ...]"
            # 2. 逗号分隔的简单列表 "0.1,0.2,..."
            v = value.strip()
            if v.startswith("[") and v.endswith("]"):
                arr = json.loads(v)
            else:
                arr = [float(x) for x in v.split(",") if x.strip()]
            return [float(x) for x in arr]
        except Exception as e:
            print(f"   无法解析向量字段，原始值已被丢弃: {e}")
            return None

    def _prepare_row(self, raw: Dict[str, Any], collection_name: str) -> Dict[str, Any]:
        """根据集合类型，把一行 CSV 转成可以插入 Milvus 的字典"""
        row = dict(raw)  # 浅拷贝，避免修改原始 dict

        # 去掉 id（集合使用 auto_id）
        row.pop("id", None)

        # 解析 vector
        if "vector" in row:
            vec = self._parse_vector(row["vector"])
            if vec is not None:
                row["vector"] = vec
            else:
                row.pop("vector", None)

        # 去掉空字符串，避免不必要的脏数据
        for k, v in list(row.items()):
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    row[k] = ""
                else:
                    row[k] = v

        # 针对已知 schema 做一点兜底填充（可选）
        if collection_name in self.rag_collections:
            # 确保 RAG 文本库的几个字段都有
            row.setdefault("text", "")
            row.setdefault("source", "")
            row.setdefault("dept_id", "")
            row.setdefault("user_id", "")
        elif collection_name == self.faq_collection:
            # FAQ 库
            row.setdefault("question", "")
            row.setdefault("answer", "")
            row.setdefault("source", "")

        return row

    def _create_import_task(
        self, db: Session, collection_name: str, csv_path: Path
    ) -> CrawlTask:
        """
        为当前 CSV 导入创建一个 CrawlTask 记录，方便后续统计和关联 CrawlBlock。
        """
        task = CrawlTask(
            url=f"import://{collection_name}/{csv_path.name}",
            collection_name=collection_name,
            status="running",
            pages_crawled=0,
            blocks_inserted=0,
            error_message=None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        print(f" 创建导入任务 #{task.id}: {task.url}")
        return task

    def _build_crawl_block_from_row(
        self,
        task_id: int,
        collection_name: str,
        prepared_row: Dict[str, Any],
        raw_row: Dict[str, Any],
    ) -> CrawlBlock:
        """
        根据集合类型和行内容，构造一个 CrawlBlock 记录。

        由于导入的数据来自 CSV 而不是真实网页，这里约定：
        - url: 使用 import:// 前缀标记来源
        - title/section: 根据集合和字段做一个大致归类
        - text_preview: 截取 text 或 question/answer 作为预览
        """
        # 构造“伪 URL”，方便区分不同集合和来源
        base_url = f"import://{collection_name}"
        source = prepared_row.get("source") or raw_row.get("source") or ""
        if source:
            url = f"{base_url}/{source}"
        else:
            url = base_url

        # 生成预览文本
        text_for_preview = (
            prepared_row.get("text")
            or prepared_row.get("question")
            or prepared_row.get("answer")
            or ""
        )
        text_preview = text_for_preview[:500] if len(text_for_preview) > 500 else text_for_preview

        # 简单的 title/section 约定
        if collection_name == self.faq_collection:
            title = "FAQ 问答"
            section = "FAQ"
        elif collection_name in self.rag_collections:
            title = "RAG 文本块"
            section = collection_name
        else:
            title = "导入文本块"
            section = collection_name

        crawl_block = CrawlBlock(
            task_id=task_id,
            url=url,
            title=title,
            section=section,
            text_preview=text_preview,
        )
        return crawl_block

    def import_csv_to_collection(
        self, csv_path: Path, collection_name: str, batch_size: int = 1000
    ) -> None:
        """将单个 CSV 文件导入指定集合，并同步写入 MySQL 中的 CrawlBlock"""
        assert self.client is not None, "Milvus client 未连接，请先调用 connect()"
        print("\n" + "-" * 80)
        print(f" 正在导入 CSV: {csv_path}")
        print(f" 目标集合: {collection_name}")

        if not csv_path.exists():
            print(f"   文件不存在，跳过: {csv_path}")
            return

        # 简单检查集合是否存在
        existing_cols = self.client.list_collections()
        if collection_name not in existing_cols:
            print(f"   集合 {collection_name} 不存在，将跳过导入。")
            print("     请先通过 init_milvus.py 或其它脚本创建对应集合。")
            return

        # --- 打开数据库 Session，并创建一个导入任务 ---
        db = self._get_db()
        task = self._create_import_task(db, collection_name, csv_path)

        total = 0
        # 按 crawler.DataIngester.ingest_blocks 的风格：
        # - 使用批次 rows_batch 做插入
        # - 使用 pending_blocks_batch 记录本批次对应的 CrawlBlock
        # - 全量 crawl_blocks 仅用于统计
        rows_batch: List[Dict[str, Any]] = []
        pending_blocks_batch: List[CrawlBlock] = []
        crawl_blocks: List[CrawlBlock] = []  # 用于统计和日志

        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                print(f"   检测到字段: {fieldnames}")

                for raw_row in reader:
                    prepared = self._prepare_row(raw_row, collection_name)
                    if not prepared:
                        continue

                    rows_batch.append(prepared)

                    # 为本条记录创建一个 CrawlBlock（先不填 milvus_id）
                    crawl_block = self._build_crawl_block_from_row(
                        task_id=task.id,
                        collection_name=collection_name,
                        prepared_row=prepared,
                        raw_row=raw_row,
                    )
                    crawl_blocks.append(crawl_block)
                    pending_blocks_batch.append(crawl_block)
                    db.add(crawl_block)

                    if len(rows_batch) >= batch_size:
                        # 先提交 MySQL，让本批次 CrawlBlock 获得 ID
                        db.commit()

                        # 插入到 Milvus
                        insert_result = self.client.insert(
                            collection_name=collection_name, data=rows_batch
                        )
                        # insert_result 包含 insert_count/ids 等信息，尝试拿回 ID
                        milvus_ids = (
                            insert_result.get("ids")
                            if isinstance(insert_result, dict)
                            else None
                        )

                        if milvus_ids:
                            # 按批次顺序回填本批次对应的 CrawlBlock.milvus_id
                            for cb, mid in zip(pending_blocks_batch, milvus_ids):
                                cb.milvus_id = str(mid)
                            db.commit()

                        total += len(rows_batch)
                        print(f"   已插入 {total} 条记录...")
                        rows_batch = []
                        pending_blocks_batch = []

            # 处理最后一批
            if rows_batch:
                db.commit()
                insert_result = self.client.insert(
                    collection_name=collection_name, data=rows_batch
                )
                milvus_ids = (
                    insert_result.get("ids") if isinstance(insert_result, dict) else None
                )
                if milvus_ids:
                    for cb, mid in zip(pending_blocks_batch, milvus_ids):
                        cb.milvus_id = str(mid)
                    db.commit()
                total += len(rows_batch)

            # 更新任务状态
            task.status = "completed"
            task.pages_crawled = 1  # 这里没有真实页面概念，简单记为 1
            task.blocks_inserted = total
            task.completed_at = datetime.now()
            db.commit()

            print(f"   导入完成，合计插入 {total} 条记录到集合 {collection_name}")
            print(f"   同步写入 MySQL: CrawlTask #{task.id}, CrawlBlock 数量 {len(crawl_blocks)}")

        except Exception as e:  # noqa: BLE001
            print(f"   导入 {csv_path} 过程中发生错误: {e}")
            try:
                task.status = "failed"
                task.error_message = str(e)
                task.completed_at = datetime.now()
                db.commit()
            except Exception:
                pass
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # 批量导入
    # ------------------------------------------------------------------ #
    def import_from_dir(
        self,
        input_dir: Path,
        collections: Optional[List[str]] = None,
        batch_size: int = 1000,
    ) -> None:
        """从目录中批量导入 CSV，文件名（不含扩展名）即集合名"""
        assert self.client is not None, "Milvus client 未连接，请先调用 connect()"

        input_dir.mkdir(parents=True, exist_ok=True)

        if collections:
            targets = []
            for name in collections:
                path = input_dir / f"{name}.csv"
                targets.append((path, name))
        else:
            # 扫描目录下所有 .csv
            targets = []
            for csv_path in sorted(input_dir.glob("*.csv")):
                collection_name = csv_path.stem
                targets.append((csv_path, collection_name))

        if not targets:
            print(f" 目录 {input_dir} 下没有找到任何 CSV 文件")
            return

        print("\n" + "=" * 80)
        print(f" 即将导入 {len(targets)} 个 CSV 到 Milvus：")
        for path, col in targets:
            print(f"  - {path.name}  ->  {col}")
        print("=" * 80)

        for idx, (csv_path, collection_name) in enumerate(targets, start=1):
            print(f"\n[{idx}/{len(targets)}] 处理文件: {csv_path.name}")
            self.import_csv_to_collection(csv_path, collection_name, batch_size=batch_size)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将 backend/scripts/milvus_exports 下的 CSV 导入到本地 Milvus 集合中",
    )

    default_dir = Path(__file__).parent / "milvus_exports"
    parser.add_argument(
        "--input-dir",
        type=str,
        default=str(default_dir),
        help=f"CSV 输入目录（默认: {default_dir}）",
    )

    parser.add_argument(
        "--collections",
        nargs="+",
        help="要导入的集合名称（默认为目录下所有 CSV 文件名）",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="批量插入大小（默认: 1000）",
    )

    parser.add_argument(
        "--local-host",
        type=str,
        help=f"本地 Milvus 主机地址（默认: {settings.MILVUS_HOST}）",
    )

    parser.add_argument(
        "--local-port",
        type=str,
        help=f"本地 Milvus 端口（默认: {settings.MILVUS_PORT}）",
    )

    args = parser.parse_args()

    importer = MilvusImporter(
        local_host=args.local_host,
        local_port=args.local_port,
    )

    try:
        importer.connect()
        input_dir = Path(args.input_dir)
        importer.import_from_dir(
            input_dir=input_dir,
            collections=args.collections,
            batch_size=args.batch_size,
        )
    except KeyboardInterrupt:
        print("\n 用户中断操作")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"\n 导入过程中发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


