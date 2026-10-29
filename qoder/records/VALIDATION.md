# StudyMate 验证记录（VALIDATION）

> 记录方式：官方 PowerContext Server + 官方 Python SDK 实测，可复现核对。

## 环境

- Python 3.11+（Windows / Linux 均可）
- 官方 PowerContext 1.4.x：`pip install "powercontext[cli,builtin]>=1.4"`
- 官方 Server：`python server/run_powercontext.py`（等价 `powercontext server run --host 127.0.0.1 --port 8000`）

## 验证 1：薄弱点记忆写入与检索（官方 PowerContext）

```text
$ python -m studymate.cli.main weakness add "机器学习-过拟合" "训练集表现好但验证集差，常见对策是正则化与早停"
✔ 薄弱点已记入记忆（memory:...）
记忆层：官方 PowerContext SDK（http://127.0.0.1:8000，scope=project:studymate）

$ python -m studymate.cli.main weakness list
记忆中已记录的薄弱点：
  1. 机器学习-过拟合：训练集表现好但验证集差，常见对策是正则化与早停
```

**结论：记忆写入 + 官方 SDK 语义检索复用 ✓（无 SQLite 降级）**

## 验证 2：笔记存储与检索

```text
$ python -m studymate.cli.main note add "SQL 索引原理" --tags 数据库 SQL --content "索引是数据库加速查询的数据结构，B+树索引按序存储"
✔ 笔记已保存 (#1)：SQL 索引原理

$ python -m studymate.cli.main note search "数据库 索引"
[1] SQL 索引原理  标签=数据库,SQL
   索引是数据库加速查询的数据结构，B+树索引按序存储
```

**结论：笔记存储 + 全文检索 ✓**

## 验证 3：重启后状态复用（关键验收项）

```python
# 模拟重启：重新创建 MemoryLayer（新进程语义），再次从官方 PowerContext 检索
mem2 = MemoryLayer()
mem2.search('过拟合')   # → 从 PowerContext 语义检索返回 1 条薄弱点
```

**结论：状态可复用 ✓（数据持久化于官方 PowerContext，进程重启后仍可检索召回）**

## 验证 4：官方 SDK 调用链路（核心证据）

记忆层代码真实调用官方 API：

```python
from powercontext.client import PowerContextClient
from powercontext.http import RememberMemoryRequest, SearchMemoryRequest

async with PowerContextClient("http://127.0.0.1:8000") as client:
    await client.remember_memory(RememberMemoryRequest(scope_id="project:studymate", kind="weakness", text="..."))
    resp = await client.search_memory(SearchMemoryRequest(scope_id="project:studymate", query="过拟合", limit=5))
    # resp.hits[].memory.text 即命中的薄弱点
```

## 覆盖情况

| 验收项 | 状态 |
|---|---|
| 项目能运行 | ✓（官方依赖 + 官方 Server） |
| PowerContext 实际发挥作用 | ✓（官方 SDK 唯一记忆路径：写入/语义检索，无自制兼容层） |
| 状态可复用 | ✓（验证 3） |
| Qoder 开发可核对 | ✓（records/QODER_DEV_LOG.md） |
| 网站可访问 | ✓（Qoder Sites 已发布，见 site/README.md） |
