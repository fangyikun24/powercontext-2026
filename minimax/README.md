# 规有所依 — SDD 上下文管理模块（MiniMax × OceanBase 赛题）

面向软件持续演进的 **规格驱动开发（Spec-Driven Development）上下文模块**。

它回答 AI 开发助手在动手改代码前必须搞清楚的四个问题：

1. 这次任务要遵守哪些**规格条目**？
2. 应该改**哪个文件的哪个符号**？
3. 用哪些**测试**验证功能与兼容性？
4. 这次任务**已经做了什么、还要做什么、验证结果如何**？

三件指定技术各自承担明确职责，且都真实参与任务流程：

| 技术 | 在本作品中的实际作用 | 接入方式 |
| --- | --- | --- |
| **MiniMax** | 根据模块给出的开发上下文**生成实际代码修改**（不是只做检索或写方案） | HTTP API（Anthropic 兼容端点），`POST {MINIMAX_BASE_URL}/anthropic/v1/messages` |
| **seekdb**（可选 OceanBase） | 存储**规格 / 代码 / 测试**的原子工程资料与全文索引，检索结果直接用于构造上下文 | 嵌入式 seekdb（`pylibseekdb`）+ `pymysql`；或 OceanBase MySQL 模式 |
| **PowerContext** | 持久化**任务进展与验证结果**，模块重启后从同一 scope 读回并继续使用 | Python 进程内 runtime（`open_builtin_runtime`） |

版本：`powercontext==1.4.1`、`pylibseekdb>=1.4.0.post1`、`pytest==9.2.0`、Python 3.12（≥3.11 均可）。

---

## 1. 它解决什么问题

AI 助手改代码时最容易出的三类错：**漏掉约束**、**用了过时规格**、**重复劳动**。

本模块把「工程资料」与「任务状态」分开处理：

```
              ┌─────────────────────────────────────────────────────────┐
  specs/*.md  │  ingest：按「一条规格 / 一个符号 / 一个测试」切分原子资料   │
  src/**/*.py │            ↓                                            │
  tests/*.py  │  seekdb：sdd_materials 表 + FULLTEXT 索引                │
              └─────────────────────────────────────────────────────────┘
                                     ↓ 检索（FTS）
              ┌─────────────────────────────────────────────────────────┐
   task 文本  │  context：规格条目 + 待改符号 + 功能测试 + 回归测试        │
              └─────────────────────────────────────────────────────────┘
                                     ↓
              ┌─────────────────────────────────────────────────────────┐
              │  MiniMax：拿到上下文 → 产出完整文件内容 → 落盘 → 跑测试     │
              └─────────────────────────────────────────────────────────┘
                                     ↓
              ┌─────────────────────────────────────────────────────────┐
              │  PowerContext：context / todo / 验证结果写入 scope          │
              │  重启模块 → 同一 scope 读回 → 继续任务                     │
              └─────────────────────────────────────────────────────────┘
```

**关键点：模块不返回固定答案。** 上下文的每一个来源都来自数据库里由项目文件构建的行；
把 `specs/orders.md` 改掉重新 `ingest`，输出内容随之改变（见 `scripts/verify_spec_update.py`）。

---

## 2. 目录结构

```
minimax/
├── README.md                    ← 本文件（运行说明）
├── requirements.txt
├── .env.example                 ← 配置模板（占位值）
├── sdd_context/                 ← 上下文模块本体
│   ├── config.py                配置解析（.env / 环境变量）
│   ├── db.py                    seekdb / OceanBase 建表、全文索引、检索
│   ├── textutil.py              中英混合分词（供 FULLTEXT 使用）
│   ├── materials.py             规格 / 代码 / 测试 → 原子资料
│   ├── context.py               检索 + 上下文装配
│   ├── state.py                 PowerContext 任务状态存取
│   ├── llm.py                   MiniMax / DeepSeek HTTP 客户端 + 调用记录
│   ├── taskflow.py              plan → apply → verify 编排
│   └── cli.py                   命令行入口
├── sample-project/              ← 被修改的业务工程（可运行、有测试）
│   ├── src/orderflow/           订单服务（最终态 = 修改后）
│   ├── specs/                   权威规格（SDD 输入）
│   ├── tests/                   测试集（修改前后完全一致）
│   └── snapshots/{before,after} 修改前后代码快照
├── scripts/                     setup / reset / verify / 状态与规格验证脚本
├── artifacts/                   logs（测试日志）、diffs（补丁）、records（模型调用记录）
├── docs/                        验证样例、技术使用记录、一页技术说明
└── tests/                       模块自身的测试
```

---

## 3. 环境准备

```bash
cd minimax
python3 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                               # 填入 MINIMAX_API_KEY
```

或直接：

```bash
bash /scripts/setup.sh          # 建 venv、装依赖、生成 .env、doctor、ingest
```

Windows 上等价命令见 `scripts/verify.ps1`。

**数据初始化**就是 `ingest`：它把 `sample-project` 的规格、源码、测试读入 seekdb。
不需要手工建表——表结构与全文索引由 `db.py` 在首次连接时创建。
状态目录（`state/`）默认在模块目录下，可用 `SDDCTX_HOME` 改到别处。

---

## 4. 调用入口（输入 / 输出）

统一入口：`python -m sdd_context <command>`（在 `minimax/` 目录下执行）。

所有命令都接受 `--json`，输出可机器校验。

### 4.1 `doctor` — 配置自检

```bash
python -m sdd_context doctor
```

输出：解析后的数据库路径、状态后端、模型供应商/模型名、配置问题列表。

### 4.2 `ingest` — 导入工程资料

```bash
python -m sdd_context ingest [--json]
```

| 输入 | 输出 |
| --- | --- |
| `SDDCTX_PROJECT`（默认 `sample-project`）下的 `specs/`、`src/`、`tests/` | 每类资料的行数、涉及文件、规格 ID 列表、`storage`（后端与 upsert/removed 计数） |

切分粒度：`specs/*.md` 中每个 `### SPEC-…` 块 → 一行；`src/**/*.py` 每个模块 + 每个类/函数/方法 → 一行；
`tests/test_*.py` 每个 `def test_*` → 一行。

### 4.3 `context` — 构造开发上下文（核心）

```bash
python -m sdd_context context --task "<任务描述>" [--task-id ID] [--json]
```

| 输入 | 输出 |
| --- | --- |
| 任务文本（含规格 ID 与符号名时命中率最高） | `specs` / `code_targets` / `functional_tests` / `regression_tests`，每项都带**真实来源** |

每一项包含：

```json
{
  "kind": "code",
  "source": "src/orderflow/service.py",   // 真实存在的文件
  "locator": "src/orderflow/service.py:38-53",  // 文件:起止行
  "title": "OrderService.list_orders",
  "content_hash": "<sha256>",             // 便于核对是否使用了最新内容
  "score": 4.23,
  "reason": "called by the functional tests",
  "excerpt": "..."
}
```

### 4.4 `task` — 任务生命周期

```bash
python -m sdd_context task plan   --task-id SDD-ORD-004 --task "<任务描述>"
python -m sdd_context task apply  --task-id SDD-ORD-004
python -m sdd_context task verify --task-id SDD-ORD-004
python -m sdd_context task status --task-id SDD-ORD-004
python -m sdd_context task list
```

| 命令 | 输入 | 输出 / 副作用 |
| --- | --- | --- |
| `task plan` | 任务 ID + 任务文本 | 检索上下文 → 调 MiniMax → 保存 `artifacts/diffs/<id>.plan.json` 与 `.patch` → 写 PowerContext |
| `task apply` | 任务 ID | 按落盘的 plan 写出文件（限制在项目目录内），状态转 `applied` |
| `task verify` | 任务 ID | 跑功能测试 + 回归测试，日志落 `artifacts/logs/`，结果写入 PowerContext |
| `task status` | 任务 ID | 从 PowerContext **重新读取**任务记录（含 scope id、todo、验证结果） |

**状态复用**由 `task status` / `task list` 体现：它们不依赖任何进程内缓存，
每次都是一个新进程从数据库把记录读回来。

---

## 5. 验证样例（摘要）

完整定义见 [`docs/验证样例.md`](docs/验证样例.md)。

- **业务工程**：`sample-project`（订单服务，46 个测试，无需网络/数据库/外部服务）
- **要改什么**：`SPEC-ORD-004` — 给 `OrderService.list_orders` 增加可选 `min_total` 筛选
- **必须保持**：`SPEC-ORD-001/002/003/005`、`SPEC-PRC-001..004`（筛选语义、金额精度、库存联动）
- **目标测试**：`tests/test_min_total_filter.py`（8 个用例，修改前后完全一致）
- **回归测试**：`tests/test_orders.py`、`test_pricing.py`、`test_inventory.py`、`test_service.py`

一键走完所有验收项：

```bash
bash /scripts/verify.sh              # 不含模型调用
bash /scripts/verify.sh --with-model # 含 MiniMax plan/apply/verify
```

---

## 6. 已知限制

1. **`task plan` 需要额度充足的 MiniMax 密钥，且密钥类型要对。** MiniMax 有两套计费：
   `sk-api-…`（API 计费，走积分/钱包）与 `sk-cp-…`（Coding Plan，走 M Plan 订阅）。
   用 `sk-api-` 且余额为 0 时，`/v1/models` 正常但对话接口返回
   `402 insufficient_balance_error (1008)`；本次跑通用的是 `sk-cp-` 密钥。
   详见 [`docs/技术使用记录.md`](docs/技术使用记录.md)。
2. **`MiniMax-M3` 系列强制 adaptive thinking，无法关闭。** 传
   `thinking: {"type": "disabled"}` 会被拒（`400 requires adaptive thinking`）。
   大 prompt 下推理可能吃光 `max_tokens` 导致正文为空，因此模块默认发送
   `reasoning: {"effort": "low"}` 并给到 32768 的输出预算。
3. **嵌入式 seekdb 是单进程独占的。** 同一时刻只应有一个进程打开同一个数据目录；
   模块内已对「刚关闭又立刻打开」的短竞争做了退避重试。
4. **在 Windows 上运行 seekdb 需要允许本地回环端口。** seekdb 引擎通过
   `127.0.0.1:<随机端口>` 暴露 MySQL 协议；如果宿主限制了本地监听，`seekdb_open` 会直接失败。
   Linux / macOS 无此问题。
5. **全文检索使用 `WITH PARSER SPACE`**，因此中文靠模块侧的分词（单字 + 二元组）保证召回，
   不是数据库内建中文分词。
6. **没有向量检索。** 全部走全文（lexical）路径，因此不需要 embedding 模型和额外 API Key。
7. `task verify` 默认的测试目标写死在 `taskflow.py` 中，切换到别的业务工程时需要同步调整。

---

## 7. 重置

```bash
bash /scripts/reset.sh     # 或 Windows: ./scripts/reset.ps1
```

删除 `state/`（seekdb 实例、PowerContext 库）、清空生成物，并把 `sample-project`
还原成「修改后」快照。之后重新 `ingest` 即是干净初始状态。

---

## 8. 复用与来源

- 业务工程 `sample-project` 为本作品原创，无第三方代码。
- PowerContext 为 OceanBase 开源项目（Apache-2.0），本作品以 **PyPI 包**
  `powercontext==1.4.1` 的形式使用，未修改其源码。
- 模块代码全部为本作品原创。
