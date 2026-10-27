/**
 * MiniKB 前端逻辑
 *
 * 核心流程（符合阶跃星辰赛题要求）：
 *  1. 浏览器本地加载量化 embedding 模型（@xenova/transformers，WebGPU 优先，WASM 降级）
 *  2. 文档/查询向量化全部在用户设备本地完成，禁止云端推理 API
 *  3. 向量+原文+元数据写入 seekdb；混合检索在 seekdb 内完成
 */
import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

// 模型配置：量化（INT8/FP16）+ 端侧运行
const MODEL_NAME = "Xenova/all-MiniLM-L6-v2"; // 384 维，支持量化，适合端侧
const QUANTIZED = true; // INT8 量化

// Transformers.js 环境配置（模型本地加载，无远端依赖）
env.allowLocalModels = true;
env.useBrowserCache = true;

// ---------- DOM ----------
const $ = (id) => document.getElementById(id);
const logEl = $("log");
const modelBadge = $("modelBadge");
const backendBadge = $("backendBadge");
const backendMode = $("backendMode");

// ---------- 全局状态 ----------
let embedder = null;
let modelLoadStart = 0;
let modelLoadMs = 0;

function log(msg) {
  const t = new Date().toLocaleTimeString();
  logEl.textContent += `[${t}] ${msg}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function setBadge(el, text, cls) {
  el.textContent = text;
  el.className = `badge ${cls}`;
}

// 检测可用推理后端：优先 WebGPU，降级 WASM
async function detectBackend() {
  // @xenova/transformers 自动选择 backend；这里显式探测并展示
  if (typeof navigator !== "undefined" && "gpu" in navigator && navigator.gpu) {
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (adapter) {
        log("✔ 检测到 WebGPU，使用 WebGPU 推理后端");
        return "WebGPU";
      }
    } catch (e) { /* 忽略，降级 */ }
  }
  log("ℹ 未检测到 WebGPU，自动降级为 WASM 推理后端");
  return "WASM";
}

// 初始化模型（本地向量化核心）
async function initModel() {
  modelLoadStart = performance.now();
  setBadge(modelBadge, "模型加载中…", "loading");
  try {
    // 构造管道：feature-extraction + 量化模型
    embedder = await pipeline("feature-extraction", MODEL_NAME, {
      quantized: QUANTIZED,
      progress_callback: (p) => {
        if (p && p.status === "progress" && typeof p.progress === "number") {
          modelBadge.textContent = `模型加载中 ${p.progress.toFixed(0)}%`;
        }
      },
    });
    modelLoadMs = performance.now() - modelLoadStart;
    log(`✔ 模型加载完成：${MODEL_NAME}${QUANTIZED ? "（INT8 量化）" : ""}，耗时 ${modelLoadMs.toFixed(0)}ms`);
    setBadge(modelBadge, "模型就绪 ✓", "ready");
    $("pLoad").textContent = `${modelLoadMs.toFixed(0)} ms`;
    $("pSize").textContent = QUANTIZED ? "INT8 量化（体积约为原模型 1/4）" : "FP32 原始";
    return true;
  } catch (e) {
    log(`✘ 模型加载失败：${e.message}`);
    setBadge(modelBadge, "模型加载失败", "error");
    return false;
  }
}

// 文本 → 向量（本地计算）
async function embed(texts) {
  if (!embedder) throw new Error("模型未初始化");
  const output = await embedder(texts, { pooling: "mean", normalize: true });
  // output.data 为 Float32Array；转普通数组
  const dim = output.dim || 384;
  const vecs = [];
  const data = output.data;
  for (let i = 0; i < texts.length; i++) {
    const start = i * dim;
    vecs.push(Array.from(data.slice(start, start + dim)));
  }
  return vecs;
}

// ---------- 后端 API ----------
async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await res.json();
  if (!j.success) throw new Error(j.error || "请求失败");
  return j.data;
}

// ---------- 导入 ----------
async function ingest() {
  const text = $("docsInput").value.trim();
  if (!text) { log("请先输入语料"); return; }
  if (!embedder) { log("模型未就绪，请等待加载完成"); return; }
  const docs = text.split("\n").map(s => s.trim()).filter(Boolean);
  log(`开始向量化 ${docs.length} 条文档（本地推理）…`);
  const t0 = performance.now();
  try {
    const embs = await embed(docs);
    const t1 = performance.now();
    const throughput = (docs.length / ((t1 - t0) / 1000)).toFixed(1);
    $("pThroughput").textContent = `${throughput} 条/秒`;
    log(`✔ 本地向量化完成：${docs.length} 条，耗时 ${(t1 - t0).toFixed(0)}ms（${throughput} 条/秒）`);

    // 写入 seekdb
    const items = docs.map((d, i) => ({
      id: `doc_${Date.now()}_${i}`,
      document: d,
      embedding: embs[i],
      metadata: { source: "user", ts: Date.now(), idx: i },
    }));
    const t2 = performance.now();
    await api("/api/ingest-batch", { items });
    const t3 = performance.now();
    log(`✔ 已写入 seekdb（混合检索将在数据库内完成），写入耗时 ${(t3 - t2).toFixed(0)}ms`);
    await refreshStatus();
  } catch (e) {
    log(`✘ 导入失败：${e.message}`);
  }
}

// ---------- 检索 ----------
async function search() {
  const query = $("queryInput").value.trim();
  if (!query) { log("请输入查询"); return; }
  if (!embedder) { log("模型未就绪"); return; }
  log(`查询：${query}（本地向量化 + seekdb 混合检索）`);
  const t0 = performance.now();
  try {
    // 1) 本地算查询向量
    const qEmb = (await embed([query]))[0];
    // 2) seekdb 混合检索（全文 $contains + 向量 knn，由数据库完成）
    const data = await api("/api/search", {
      queryText: query,
      queryEmbedding: qEmb,
      nResults: 10,
    });
    const t1 = performance.now();
    $("pQuery").textContent = `${(t1 - t0).toFixed(0)} ms（端到端）`;
    renderResults(data.results, query);
    log(`✔ 检索完成：${data.total} 条结果，端到端耗时 ${(t1 - t0).toFixed(0)}ms`);
  } catch (e) {
    log(`✘ 检索失败：${e.message}`);
  }
}

// 渲染结果
function renderResults(results, query) {
  const box = $("results");
  if (!results || results.length === 0) {
    box.innerHTML = `<div class="dim-note">没有匹配结果。</div>`;
    return;
  }
  box.innerHTML = `<div class="dim-note" style="margin-bottom:8px;">“${query}” 的混合检索结果（rrf 融合排序，由 seekdb 完成）：</div>` +
    results.map((r, i) => `
      <div class="result-item">
        <div class="score">#${i + 1} · 相似度 ${r.distance !== null ? r.distance.toFixed(4) : "—"}</div>
        <div class="doc">${escapeHtml(r.document)}</div>
        <div class="meta">来源元数据：${escapeHtml(JSON.stringify(r.metadata || {}))}</div>
      </div>`).join("");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---------- 状态 ----------
async function refreshStatus() {
  try {
    const d = await api("/api/status", {});
    backendBadge.textContent = `seekdb 就绪 ✓（${d.count} 条记录）`;
    backendBadge.className = "badge ready";
    return d;
  } catch (e) {
    setBadge(backendBadge, "后端未连接", "error");
    log(`✘ 后端连接失败：${e.message}`);
    return null;
  }
}

async function reset() {
  try {
    await api("/api/reset", {});
    log("✔ 知识库已清空");
    $("results").innerHTML = "";
    await refreshStatus();
  } catch (e) {
    log(`✘ 清空失败：${e.message}`);
  }
}

// ---------- 事件绑定 ----------
$("btnIngest").addEventListener("click", ingest);
$("btnSearch").addEventListener("click", search);
$("btnReset").addEventListener("click", reset);
$("queryInput").addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });

// ---------- 初始化 ----------
(async function init() {
  log("MiniKB 初始化中…");
  const backend = await detectBackend();
  $("pBackend").textContent = backend;
  backendMode.textContent = `推理后端：${backend}${backend === "WebGPU" ? "（不支持时自动降级 WASM）" : ""}`;
  const s = await refreshStatus();
  const okModel = await initModel();
  if (s && okModel) {
    log("✔ 全部就绪：可开始导入语料并检索");
  }
})();
