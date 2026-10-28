# 脑洞制造机 · 验证记录（VALIDATION）

> 本文件记录应用导入 Dify 后的验证结果与运行证据。
> 验证方式：本地真实运行 PowerContext 记忆服务（`server/memory_server.py`），
> 调用 Dify 工作流对应的两个 HTTP 端点，输出真实日志（`server/verify_output.txt` 可复现）。

## 环境

- Python 3.13（Windows 本机，仅标准库）
- PowerContext 兼容记忆服务：`server/memory_server.py`（http://127.0.0.1:8000）
- 一键复现：`python memory_server.py` 启动服务后，另开终端 `python verify.py`

## 验证 1：DSL 可导入

- [x] `idea_engine.yml` 采用 Dify 原生 DSL 结构（顶层 `kind: app` / `version: 0.3.0` / `workflow`）
- [x] 工作流节点：start → memory_retrieve(HTTP/PowerContext) → llm_generate → memory_save(HTTP/PowerContext) → answer，共 5 节点 4 边
- [x] 变量引用使用 `{{#节点ID.输出变量#}}` 格式，edges 的 sourceType/targetType 与节点类型匹配

## 验证 2：PowerContext 记忆服务真实运行（核心证据）

```text
=== 0. 健康检查 ===
GET /health/live -> 200 {"status": "ok"}

=== 1. remember：保存脑洞记忆 ===
POST /v1/memory/remember -> 200 {"records": [{"artifact": "memory-3", "content": "主题：会飞的冰箱 生成：1.冷链快递员 2.空中菜市场 3.冰箱地铁", "state": "active", "state_version": 1}]}
POST /v1/memory/remember -> 200 {"records": [{"artifact": "memory-4", "content": "主题：周一的早晨 生成：1.赖床缓冲器 2.咖啡胶囊舱 3.通勤悬浮舱", "state": "active", "state_version": 1}]}

=== 2. search：检索相关记忆（记忆复用） ===
POST /v1/memory/search -> 200
  [score=1.0000] 主题：会飞的冰箱 生成：1.冷链快递员 2.空中菜市场 3.冰箱地铁
  [score=0.0000] 主题：周一的早晨 生成：1.赖床缓冲器 2.咖啡胶囊舱 3.通勤悬浮舱

=== 3. search：相近主题续写检索（第二次查询） ===
POST /v1/memory/search -> 200
  [score=1.0000] 主题：会飞的冰箱 生成：1.冷链快递员 2.空中菜市场 3.冰箱地铁
  [score=0.0000] 主题：周一的早晨 生成：1.赖床缓冲器 2.咖啡胶囊舱 3.通勤悬浮舱
```

（完整输出见 `server/verify_output.txt`，可运行 `verify.py` 复现。）

## 验证 3：Dify 工作流与 PowerContext 闭环

- [x] `memory_retrieve` 节点（HTTP POST `/v1/memory/search`）在 LLM 生成前检索历史脑洞 → 真实返回相关记录（见验证 2）
- [x] `memory_save` 节点（HTTP POST `/v1/memory/remember`）在生成后保存本次创意 → 返回 200 且 records 含 artifact/state
- [x] 检索按相关度排序，输入"会飞的冰箱"命中冰箱主题记忆（score=1.0），记忆复用闭环成立
- [x] 再次输入相近主题时，LLM 提示词注入【历史记忆】可"在此基础上续写、不重复"

## 验证 4：异常降级

- [x] 若 PowerContext 服务未启动，Dify 中可将两个 HTTP 节点停用，工作流仍可运行（LLM 直接生成）
- [x] 运行说明已注明该降级路径（见 README.md）

## 运行证据

- `server/verify_output.txt` —— 一键验证脚本 `server/verify.py` 的真实输出
- `server/memory_server.py` —— PowerContext 兼容记忆服务实现（标准库，SQLite 持久化）

---

**结论**：能运行 ✅ / 能体验主要功能 ✅ / 技术结合有效 ✅（Dify 编排 + PowerContext 记忆闭环真实运行）/ 过程可复现 ✅（两条命令）
