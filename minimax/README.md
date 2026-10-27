# MiniMax 赛道 · 上下文管理系统

**任务**：订单折扣计算器（sample_project）的边界校验修复，由上下文系统驱动 MiniMax 完成真实代码修改。

## 安装

```bash
pip install -r requirements.txt
```

依赖：`requests`、`seekdb`（Python SDK）、`pytest`；可选 `powercontext[client]`（状态持久化用 PowerContext，未安装时自动降级本地 JSON）。

## 前置环境

| 项 | 要求 |
|---|---|
| seekdb | 需可连接的 seekdb server（Windows 推荐 Docker：`docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest`）；环境变量 `SEEKDB_HOST/SEEKDB_PORT/SEEKDB_DB/SEEKDB_USER/SEEKDB_PASSWORD` 可覆盖 |
| MiniMax API | 环境变量 `MINIMAX_API_KEY`（必填）；`MINIMAX_MODEL`/`MINIMAX_BASE_URL` 可覆盖 |
| PowerContext | 可选：`POWERCONTEXT_URL` 指向已部署的 PowerContext server；未部署时自动降级本地 `records/state.json` |

## 使用

```bash
# 1) 初始化：把 SPEC/CODE/TEST 工程资料写入 seekdb
python -m context_module.cli init

# 2) 执行闭环：检索资料 → 组装上下文 → 调 MiniMax 生成补丁 → 应用 → 跑测试 → 保存状态
python -m context_module.cli run

# 3) 恢复状态：读取上次保存的任务状态（证明状态可复用）
python -m context_module.cli resume
```

## 六项必做落点

1. **能运行**：init → run → resume 完整闭环。
2. **MiniMax 实际参与**：`context_module/minimax_client.py` 真实调用 MiniMax API；调用记录写入 `records/DEVELOPMENT_LOG.md`；补丁保存 `records/patch.txt`。
3. **上下文正确**：上下文由 `ContextAssembler` 从 seekdb 检索组装，包含规格/代码/测试的来源（kind/title/id）；`materials/SPEC.md` 更新并重新 `init` 后，`run` 输出随之更新。
4. **数据库实际参与**：seekdb 存储工程资料，检索结果直接构成上下文（非静态模板）。
5. **状态能复用**：`state.py` 用 PowerContext（或本地 JSON）保存任务状态；`resume` 读取上次进度。
6. **修改有效**：基线 2 个目标测试失败（quantity 边界缺失）；应用补丁后目标测试通过、5 个回归测试不受影响。
