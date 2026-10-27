"""
seekdb 工程资料存储与检索（MiniMax 赛道 · 上下文管理系统）

用 seekdb 存储规格（SPEC）/ 代码（CODE）/ 测试（TEST）三类工程资料，
在组装上下文时按查询语义检索，返回带来源标注的材料片段。

注意：Windows 不支持 seekdb 嵌入式模式，须先部署 seekdb server：
    docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
连接参数可用环境变量覆盖：SEEKDB_HOST / SEEKDB_PORT / SEEKDB_DB / SEEKDB_USER / SEEKDB_PASSWORD
"""
from __future__ import annotations

import os

import seekdb

DEFAULT_COLLECTION = "materials"


class SeekdbStore:
    """基于 seekdb 的工程资料仓库。"""

    def __init__(self, collection: str = DEFAULT_COLLECTION) -> None:
        host = os.environ.get("SEEKDB_HOST", "127.0.0.1")
        port = int(os.environ.get("SEEKDB_PORT", "2881"))
        database = os.environ.get("SEEKDB_DB", "test")
        user = os.environ.get("SEEKDB_USER", "root")
        password = os.environ.get("SEEKDB_PASSWORD", "")
        self.collection = collection
        # 说明：seekdb Python SDK 连接方式随版本略有差异；
        # 以下为 server 模式标准连接（host/port/database/user/password）。
        self._client = seekdb.SeekdbClient(
            host=host, port=port, database=database,
            user=user, password=password,
        )

    # ---------- 写入 ----------
    def ensure_collection(self, dimension: int = 384) -> None:
        if not self._client.has_collection(self.collection):
            self._client.create_collection(
                name=self.collection,
                configuration={
                    "dimension": dimension,
                    "distance": "cosine",
                    "embeddingFunction": None,  # 向量由调用方计算后传入
                },
            )

    def add_material(self, material_id: str, kind: str, title: str, text: str,
                     embedding: list[float]) -> None:
        """写入一份工程资料（含向量、原文、元数据）。"""
        col = self._client.get_collection(name=self.collection)
        col.add(
            ids=[material_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"kind": kind, "title": title, "id": material_id}],
        )

    # ---------- 检索 ----------
    def search(self, query_embedding: list[float], query_text: str | None = None,
               limit: int = 4) -> list[dict]:
        """混合检索：向量相似度 + 可选关键词，返回带来源的资料条目。

        返回值形如：
        [{"id": "SPEC", "kind": "spec", "title": "规格说明",
          "text": "...", "score": 0.91}, ...]
        """
        col = self._client.get_collection(name=self.collection)
        params: dict = {
            "queryEmbeddings": [query_embedding],
            "nResults": limit,
        }
        if query_text:
            # 向量 + 全文混合（RRF 融合），具体参数名以 seekdb SDK 为准
            params["queryTexts"] = [query_text]
        try:
            result = col.query(**params)
        except TypeError:
            # SDK 版本差异降级：退化为纯向量检索
            result = col.query(queryEmbeddings=[query_embedding], nResults=limit)

        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        distances = result.get("distances", [])
        out = []
        for i in range(len(ids)):
            meta = metas[i] if i < len(metas) else {}
            out.append({
                "id": ids[i],
                "kind": meta.get("kind", ""),
                "title": meta.get("title", ""),
                "text": docs[i] if i < len(docs) else "",
                "score": float(1 - distances[i]) if i < len(distances) else None,
            })
        return out

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
