# 阶跃星辰赛道 · 一页技术说明

**项目**：seekdb × 阶跃星辰 —— 端侧 AI 推理性能优化与 seekdb 混合检索（迷你知识库 MiniKB）

## 1. 总体架构

```
用户浏览器（用户设备本地推理）                后端 Node 服务                 数据层
┌─────────────────────────────┐      ┌─────────────────────┐      ┌──────────────────┐
│ Transformers.js 加载量化模型 │      │ express API 服务     │      │ seekdb (server)   │
│ 文档/查询 → 本地 embedding   │ ───► │ /api/ingest 写入     │ ───► │ 向量 + 原文 + 元数据│
│ WebGPU 优先，WASM 自动降级    │ ◄─── │ /api/search 混搜     │ ◄─── │ 向量索引 + 全文索引 │
└─────────────────────────────┘      └─────────────────────┘      └──────────────────┘
```

- **端侧推理**：向量化全部在用户浏览器本地完成，不调用任何云端推理 API，不在服务端预计算向量。
- **seekdb 存储与检索**：向量、原文、元数据写入 seekdb；向量与全文的混合检索由 seekdb 的 `hybridSearch()`（RRF 融合）完成，客户端不做结果拼合。

## 2. 模型与量化

| 项 | 配置 |
|---|---|
| 模型 | `Xenova/all-MiniLM-L6-v2`（开源，384 维，Apache 兼容） |
| 量化 | `quantized: true`（INT8 动态量化） |
| 推理运行时 | `@xenova/transformers`（Transformers.js，纯浏览器端） |
| 推理后端 | 优先 WebGPU（`navigator.gpu` 探测），不支持时自动降级 WASM，并在界面明确提示当前后端 |
| 量化效果 | INT8 体积约为 FP32 原始模型的 1/4（量化前后体积与质量对比见测试记录） |

## 3. seekdb 使用

| 项 | 说明 |
|---|---|
| 部署方式 | server 模式（Windows 推荐 Docker：`docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest`） |
| 集合 | `mini_kb`，向量维度 384，距离度量 cosine |
| 存储内容 | 向量（前端算好传入）+ 原文 + 元数据（来源、时间戳） |
| 混合检索 | `hybridSearch()`：全文分支 `whereDocument.$contains` + 向量分支 `knn.queryEmbeddings`，RRF 融合排序 |
| 增量写入 | `upsert` / `add` 支持增量导入；索引在 seekdb 内部随写入维护，刷新后新文档可检索 |
| 状态管理 | 集合/会话状态由 seekdb 管理，多次导入与切换后检索结果与知识库一致 |

## 4. 关键接口

| 接口 | 方法 | 作用 |
|---|---|---|
| `/api/ingest` | POST | 单条写入（id + 原文 + 前端向量 + 元数据） |
| `/api/ingest-batch` | POST | 批量写入（导入语料） |
| `/api/search` | POST | 混合检索（queryText + queryEmbedding → seekdb 结果） |
| `/api/status` | GET | 集合统计（记录数） |
| `/api/reset` | POST | 清空知识库 |

## 5. 运行方式

```bash
npm install        # 安装依赖（pnpm install 亦可；seekdb-js 依赖 @seekdb/js-bindings，需按官方说明触发原生绑定下载）
npm start          # 启动后端，默认 http://localhost:3000
```

启动前确保 seekdb server 可连（默认 127.0.0.1:2881，可用环境变量 SEEKDB_HOST/SEEKDB_PORT 覆盖）。
浏览器打开 `http://localhost:3000`：导入语料 → 本地向量化 → 混合检索。

## 6. 性能与质量测试方法（待评测环境补齐数据）

在固定设备、浏览器版本、语料与查询集下，记录：

1. 模型体积：量化前后大小与压缩比（实测）；
2. 向量化吞吐：文档向量化条数/秒（分首次加载与预热后）；
3. 检索质量：量化前后 Recall@K / nDCG@K 对比（同一评测集）；
4. 端到端延迟：用户提交查询 → 结果展示，区分 WebGPU 与 WASM 两档；
5. 降级路径：WebGPU 不可用环境下验证 WASM 提示与检索可用性。

## 7. 合规说明

- 禁止云端推理 API：本应用向量化全程在浏览器本地完成；
- 禁止服务端预计算回放：不存在服务端预存向量/结果回放逻辑；
- 存储与检索必须使用 seekdb：本应用仅使用 seekdb 存储与检索。
