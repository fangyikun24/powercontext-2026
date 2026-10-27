/**
 * 阶跃星辰赛道 · 迷你知识库应用 · 后端服务
 *
 * 架构（符合赛题要求）：
 *  - 浏览器端用 Transformers.js 在用户设备本地完成 embedding（禁止云端推理 API）
 *  - 本服务基于 seekdb（server 模式）提供数据存储 + 向量/全文混合检索
 *  - 混合检索由 seekdb 完成（hybridSearch），不在客户端拼合
 *
 * 运行：npm install && npm start  → http://localhost:3000
 */
import express from "express";
import multer from "multer";
import path from "path";
import { fileURLToPath } from "url";
import { SeekdbClient } from "seekdb";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;
const COLLECTION = "mini_kb";

// ---------- seekdb 连接（server 模式；Windows 推荐用 Docker 部署 seekdb 后连接） ----------
// 环境变量说明：
//   SEEKDB_HOST   seekdb 服务地址（默认 127.0.0.1）
//   SEEKDB_PORT   seekdb MySQL 协议端口（默认 2881）
//   SEEKDB_DB     数据库名（默认 test）
// 部署方式（任选其一）：
//   1) Docker：docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
//   2) 官方安装包部署 seekdb server
const client = new SeekdbClient({
  host: process.env.SEEKDB_HOST || "127.0.0.1",
  port: parseInt(process.env.SEEKDB_PORT || "2881", 10),
  database: process.env.SEEKDB_DB || "test",
  user: process.env.SEEKDB_USER || "root",
  password: process.env.SEEKDB_PASSWORD || "",
});

// ---------- 中间件 ----------
app.use(express.json({ limit: "50mb" }));
app.use(express.static(path.join(__dirname, "..", "public")));

// ---------- 工具 ----------
function ok(data) {
  return { success: true, data };
}
function fail(msg) {
  return { success: false, error: msg };
}

// ---------- 初始化集合 ----------
async function initCollection() {
  if (await client.hasCollection(COLLECTION)) {
    return client.getCollection({ name: COLLECTION });
  }
  // 向量索引 + 全文索引。
  // 注意：向量由前端 Transformers.js 本地计算后传入，因此后端 embeddingFunction 置 null，
  //      不依赖 @seekdb/default-embed（避免额外模型下载）。
  const collection = await client.createCollection({
    name: COLLECTION,
    configuration: {
      dimension: 384, // 与 all-MiniLM-L6-v2 输出维度一致（量化后不变）
      distance: "cosine",
      embeddingFunction: null,
    },
  });
  return collection;
}

// ---------- API ----------

// 写入一条文档（前端已算好向量）
app.post("/api/ingest", async (req, res) => {
  try {
    const { id, document, embedding, metadata } = req.body || {};
    if (!id || !document || !embedding || !Array.isArray(embedding)) {
      return res.status(400).json(fail("需要 id / document / embedding"));
    }
    const collection = await initCollection();
    await collection.upsert({
      ids: id,
      documents: document,
      embeddings: [embedding],
      metadatas: metadata || { source: "user" },
    });
    res.json(ok({ id }));
  } catch (e) {
    console.error("ingest error:", e);
    res.status(500).json(fail(String(e.message || e)));
  }
});

// 批量写入
app.post("/api/ingest-batch", async (req, res) => {
  try {
    const items = req.body?.items;
    if (!Array.isArray(items) || items.length === 0) {
      return res.status(400).json(fail("items 为空"));
    }
    const collection = await initCollection();
    const ids = [], docs = [], embs = [], metas = [];
    for (const it of items) {
      if (!it.id || !it.document || !Array.isArray(it.embedding)) continue;
      ids.push(it.id);
      docs.push(it.document);
      embs.push(it.embedding);
      metas.push(it.metadata || { source: "user" });
    }
    if (ids.length === 0) return res.status(400).json(fail("没有合法数据"));
    await collection.add({ ids, documents: docs, embeddings: embs, metadatas: metas });
    res.json(ok({ count: ids.length }));
  } catch (e) {
    console.error("ingest-batch error:", e);
    res.status(500).json(fail(String(e.message || e)));
  }
});

// 混合检索（向量 + 全文，由 seekdb 完成）
app.post("/api/search", async (req, res) => {
  try {
    const { queryText, queryEmbedding, nResults = 10, where } = req.body || {};
    if (!queryText && !queryEmbedding) {
      return res.status(400).json(fail("需要 queryText 或 queryEmbedding"));
    }
    const collection = await initCollection();
    const hybrid = await collection.hybridSearch({
      query: {
        whereDocument: { $contains: queryText || "" },
        ...(where ? { where } : {}),
        nResults,
      },
      knn: {
        queryEmbeddings: queryEmbedding ? [queryEmbedding] : undefined,
        ...(queryText && !queryEmbedding ? { queryTexts: [queryText] } : {}),
        nResults,
      },
      rank: { rrf: {} },
      nResults,
      include: ["documents", "metadatas"],
    });
    const ids = hybrid.ids?.[0] || [];
    const docs = hybrid.documents?.[0] || [];
    const metas = hybrid.metadatas?.[0] || [];
    const dists = hybrid.distances?.[0] || [];
    const results = ids.map((id, i) => ({
      id,
      document: docs[i] || "",
      metadata: metas[i] || {},
      distance: dists[i] ?? null,
    }));
    res.json(ok({ results, total: results.length }));
  } catch (e) {
    console.error("search error:", e);
    res.status(500).json(fail(String(e.message || e)));
  }
});

// 集合统计 / 状态
app.get("/api/status", async (req, res) => {
  try {
    const collection = await initCollection();
    const count = await collection.count();
    res.json(ok({ collection: COLLECTION, count, backend: "seekdb-embedded" }));
  } catch (e) {
    console.error("status error:", e);
    res.status(500).json(fail(String(e.message || e)));
  }
});

// 清空（重置知识库）
app.post("/api/reset", async (req, res) => {
  try {
    await client.deleteCollection(COLLECTION);
    res.json(ok({ reset: true }));
  } catch (e) {
    // 集合不存在也视为成功
    res.json(ok({ reset: true }));
  }
});

// ---------- 启动 ----------
app.listen(PORT, async () => {
  try {
    await initCollection();
    const count = await (await client.getCollection({ name: COLLECTION })).count().catch(() => 0);
    console.log(`✔ 迷你知识库已启动: http://localhost:${PORT} (当前 ${count} 条记录)`);
  } catch (e) {
    console.error("启动时初始化集合失败:", e.message);
    console.log(`✔ 服务仍已启动: http://localhost:${PORT}`);
  }
});
