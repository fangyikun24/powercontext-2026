# StudyMate · 学习提效助手（Qoder 赛道作品）

> **赛道**：Qoder —— Build with Qoder（20 分）
> **核心思想**：围绕学习科研提效，用 Qoder 开发一个"学习薄弱点记忆助手"，PowerContext 承担记忆复用（官方 SDK 接入），Qoder Sites 发布项目网站。

## 解决的问题

学生/科研人员在长期学习中普遍面临：
1. **学了就忘** —— 薄弱点散落在笔记/文档里，难以按需召回；
2. **复习无重点** —— 不知道哪些知识点薄弱、何时该复习；
3. **资料难检索** —— 笔记写了不少，用关键词搜索效果差。

StudyMate 用**记忆层（官方 PowerContext）**把"薄弱点"持续保存，随时语义检索复用，让每次学习都有上下文延续。

## 核心功能

| 功能 | 命令 | 说明 |
|---|---|---|
| 记笔记 | `studymate note add "标题" --tags 标签 --content 内容` | 本地资料库存储 |
| 检索笔记 | `studymate note search "关键词"` | 全文检索 |
| 记录薄弱点 | `studymate weakness add "知识点" "薄弱描述"` | **写入官方 PowerContext 记忆** |
| 查看薄弱点 | `studymate weakness list` | 记忆语义检索复用 |
| 一键复习 | `studymate review "主题"` | 合并笔记 + 薄弱点输出复习清单 |
| 状态查看 | `studymate status` | 记忆层/资料库状态 |

## 技术结合（赛题必用技术实际发挥作用）

- **PowerContext（必用，官方接入）**：`core/memory.py` 使用 **OceanBase 官方 PowerContext 1.4.x Python SDK**
  （`from powercontext.client import PowerContextClient`），真实调用 `remember_memory` / `search_memory`，
  无任何自制兼容层或 SQLite 降级。
  - 官方 Server：`powercontext server run --host 127.0.0.1 --port 8000`（见 `server/run_powercontext.py`）
  - CLI 首次调用 `weakness` / `review` 时会探测 `http://127.0.0.1:8000`，未启动则自动拉起官方 Server
  - 实际发挥作用：`weakness add` 写入记忆，`weakness list` / `review` 语义检索复用
- **Qoder**：全部开发在 Qoder 中完成（开发记录见 `records/QODER_DEV_LOG.md`）；Qoder Sites 发布项目网站（见 `site/`）。

## 运行

> 以下命令均在 `qoder/` 目录下执行（先 `cd qoder`）。

```bash
cd qoder

# 0) 安装官方依赖
pip install -r studymate/requirements.txt        # powercontext[cli,builtin]>=1.4

# 1) 一键自检（推荐）：自动拉起官方 Server，跑通写入/检索/复习
python run_demo.py                               # 全部步骤成功时输出 PASS

# 2) 手动使用（CLI 同样会在首次调用时自动拉起官方 Server）
python -m studymate.cli.main note add "Transformer 自注意力" --tags AI 深度学习 --content "QKV 权重计算，多头并行"
python -m studymate.cli.main weakness add "过拟合" "训练好验证差，对策：正则化+早停"
python -m studymate.cli.main review "过拟合"
python -m studymate.cli.main status
```

## 验证样例（官方 PowerContext 模式，已实测）

```
$ python -m studymate.cli.main weakness add "机器学习-过拟合" "训练集表现好但验证集差，常见对策是正则化与早停"
✔ 薄弱点已记入记忆（memory:...）
记忆层：官方 PowerContext SDK（http://127.0.0.1:8000，scope=project:studymate）

$ python -m studymate.cli.main weakness list
记忆中已记录的薄弱点：
  1. 机器学习-过拟合：训练集表现好但验证集差，常见对策是正则化与早停

$ python -m studymate.cli.main status
笔记总数：2
记忆层：官方 PowerContext SDK（http://127.0.0.1:8000，scope=project:studymate）
```

重启后（新建进程）再次 `weakness list` / `review`，数据仍从 PowerContext 语义检索返回 —— **状态可复用**已验证。

## 目录结构

```
qoder/
├── studymate/
│   ├── core/
│   │   ├── memory.py     # 官方 PowerContext SDK 记忆层（PowerContextClient）
│   │   └── kb.py         # 学习资料库（笔记 + 全文检索）
│   ├── cli/main.py       # CLI 入口
│   └── requirements.txt  # 官方依赖 powercontext[cli,builtin]
├── server/run_powercontext.py  # 官方 PowerContext Server 启动封装
├── run_demo.py           # 一键自检（写入/检索/复习，自动拉起官方 Server）
├── site/                 # Qoder Sites 网站内容（见 site/README.md）
├── records/              # Qoder 开发记录、验证记录
└── docs/                 # 文档
```
