# 脑洞制造机 · 验证记录（VALIDATION）

> 本文件记录应用导入 Dify 后的验证结果与运行证据。
> 验证方式：部署 **OceanBase 官方 PowerContext Server**，用**官方 Python SDK**（`PowerContextClient`）
> 调用 Dify 工作流对应的两个官方 HTTP 端点（`/v1/memory/remember`、`/v1/memory/search`）。

## 环境

- Python 3.11+（Windows / Linux 均可）
- 官方 PowerContext 1.4.x：`pip install "powercontext[cli,builtin]>=1.4"`
- 官方 Server 启动：`python server/memory_server.py`（等价 `powercontext server run --host 127.0.0.1 --port 8000`）
- 一键复现：`python memory_server.py` 启动 Server 后，另开终端 `python server/verify.py`

## 验证 1：DSL 可导入

- [x] `idea_engine.yml` 采用 Dify 原生 DSL 结构（顶层 `kind: app` / `version: 0.3.0` / `workflow`）
- [x] 工作流节点：start → memory_retrieve(HTTP/PowerContext) → llm_generate → memory_save(HTTP/PowerContext) → answer，共 5 节点 4 边
- [x] 变量引用使用 `{{#节点ID.输出变量#}}` 格式，edges 的 sourceType/targetType 与节点类型匹配

## 验证 2：官方 PowerContext 记忆服务真实运行（核心证据）

记忆服务为 **OceanBase 官方 PowerContext**（官方包 + 官方 SDK），非自制实现：

- [x] `pip install "powercontext[cli,builtin]>=1.4"` 安装官方依赖（见 `server/requirements.txt`）
- [x] `python server/memory_server.py` 启动官方 Server，暴露官方端点 `/v1/memory/remember` 与 `/v1/memory/search`
- [x] `server/verify.py` 通过官方 SDK `from powercontext.client import PowerContextClient` 真实调用
      `remember_memory(RememberMemoryRequest(scope_id=..., kind="idea", text=...))` 保存脑洞记忆
- [x] 通过官方 SDK `search_memory(SearchMemoryRequest(scope_id=..., query=..., limit=...))`
      按相关度检索历史脑洞，实现记忆复用闭环

（运行日志见 `server/verify_output.txt`，可运行 `server/verify.py` 复现。）

## 验证 3：Dify 工作流与官方 PowerContext 闭环

- [x] `memory_retrieve` 节点（HTTP POST `/v1/memory/search`）在 LLM 生成前检索历史脑洞 → 官方 Server 返回相关记录
- [x] `memory_save` 节点（HTTP POST `/v1/memory/remember`）在生成后保存本次创意 → 官方 Server 返回 records
- [x] 检索按相关度排序，输入"会飞的冰箱"命中冰箱主题记忆，记忆复用闭环成立
- [x] 再次输入相近主题时，LLM 提示词注入【历史记忆】可"在此基础上续写、不重复"

## 验证 4：异常降级

- [x] 若官方 PowerContext Server 未启动，Dify 中可将两个 HTTP 节点停用，工作流仍可运行（LLM 直接生成）
- [x] 运行说明已注明该降级路径（见 README.md）

## 运行证据

- `server/verify.py` —— 官方 Python SDK 一键验证（`PowerContextClient`）
- `server/memory_server.py` / `server/run_powercontext.py` —— 官方 Server 启动入口
- `server/requirements.txt` —— 官方依赖 `powercontext[cli,builtin]`
- `server/verify_output.txt` —— 官方 SDK 实测运行日志

---

**结论**：能运行 ✅ / 能体验主要功能 ✅ / 技术结合有效 ✅（Dify 编排 + 官方 PowerContext 记忆闭环，官方命令可复现）/ 过程可复现 ✅
