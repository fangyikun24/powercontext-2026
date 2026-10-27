# StudyMate · 学习提效助手（Qoder 赛道作品）

> **赛道**：Qoder —— Build with Qoder（20 分）
> **核心思想**：围绕学习科研提效，用 Qoder 开发一个"学习薄弱点记忆助手"，PowerContext 承担记忆复用（数据持久化 + 语义检索），Qoder Sites 发布项目网站。

## 解决的问题

学生/科研人员在长期学习中普遍面临：
1. **学了就忘** —— 薄弱点散落在笔记/文档里，难以按需召回；
2. **复习无重点** —— 不知道哪些知识点薄弱、何时该复习；
3. **资料难检索** —— 笔记写了不少，用关键词搜索效果差。

StudyMate 用**记忆层（PowerContext）**把"薄弱点"持续保存，随时检索复用，让每次学习都有上下文延续。

## 核心功能

| 功能 | 命令 | 说明 |
|---|---|---|
| 记笔记 | `studymate note add "标题" --tags 标签 --content 内容` | 本地资料库存储 |
| 检索笔记 | `studymate note search "关键词"` | 全文检索 |
| 记录薄弱点 | `studymate weakness add "知识点" "薄弱描述"` | **写入 PowerContext 记忆** |
| 查看薄弱点 | `studymate weakness list` | 记忆复用 |
| 一键复习 | `studymate review "主题"` | 合并笔记 + 薄弱点输出复习清单 |
| 状态查看 | `studymate status` | 记忆层/资料库状态 |

## 技术结合（赛题必用技术实际发挥作用）

- **PowerContext（必用）**：`core/memory.py` 通过 PowerContext HTTP 保存/检索记忆；
  无 PowerContext server 时**自动降级本地 SQLite**（std 库 sqlite3），保证任何环境可运行。
  - 接入方式：HTTP（`POWERCONTEXT_URL` 环境变量，默认 `http://127.0.0.1:8000`）
  - 实际发挥作用：`weakness add` 写入记忆，`weakness list` / `review` 检索复用
- **seekdb（可选增强）**：`core/kb.py` 预留向量混合检索接入位（配置 SEEKDB_HOST 后启用）。
- **Qoder**：全部开发在 Qoder 中完成（开发记录见 `records/QODER_DEV_LOG.md`）。

## 运行

```bash
# 0) 依赖：仅标准库，无需安装第三方包（PowerContext 经 HTTP 直连）
# 1) 可选：部署 PowerContext server（不部署自动用 SQLite，功能完整）
#    export POWERCONTEXT_URL=http://127.0.0.1:8000   # 或 Windows: $env:POWERCONTEXT_URL=...

# 2) 使用
python -m studymate.cli.main note add "Transformer 自注意力" --tags AI 深度学习 --content "QKV 权重计算，多头并行"
python -m studymate.cli.main weakness add "过拟合" "训练好验证差，对策：正则化+早停"
python -m studymate.cli.main review "过拟合"
python -m studymate.cli.main status
```

## 验证样例（已实测）

```
$ python -m studymate.cli.main weakness add "机器学习-过拟合" "训练集表现好但验证集差，常见对策是正则化与早停"
✔ 薄弱点已记入记忆（sqlite:1）
记忆层模式：sqlite（本地 SQLite ...）

$ python -m studymate.cli.main weakness list
记忆中已记录的薄弱点：
  1. 机器学习-过拟合：训练集表现好但验证集差，常见对策是正则化与早停

$ python -m studymate.cli.main status
笔记总数：2
记忆层模式：sqlite（本地 SQLite ...）
```

重启后（新建进程）再次 `weakness list` / `review`，数据仍可读取 —— **状态可复用**已验证。

## 目录结构

```
qoder/
├── studymate/
│   ├── core/
│   │   ├── memory.py     # PowerContext 记忆层（HTTP + SQLite 降级）
│   │   └── kb.py         # 学习资料库（笔记 + 全文检索）
│   ├── cli/main.py       # CLI 入口
│   └── requirements.txt  # 无第三方必装依赖
├── site/                 # Qoder Sites 网站内容（见 site/README.md）
├── records/              # Qoder 开发记录、验证记录
└── docs/                 # 文档
```
