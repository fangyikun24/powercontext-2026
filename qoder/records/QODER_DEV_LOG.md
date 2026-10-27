# Qoder 开发记录（QODER DEV LOG）— StudyMate 学习提效助手

> 用途：赛题验收「Qoder 开发可核对」—— 记录项目在 Qoder 中的完整开发过程。

## 项目概览

- 项目名：StudyMate · 学习提效助手
- 解决的问题：学习薄弱点记忆与复习召回
- 核心技术：PowerContext（记忆复用）+ 轻量资料库
- 发布：Qoder Sites（site/ 目录内容）

## 开发过程（Qoder 中完成）

### 阶段 1：需求与设计（Qoder 对话规划）

在 Qoder 中向 AI 助手描述需求："做一个学习提效工具，核心是记录薄弱点并能在复习时召回；用 PowerContext 做记忆层，尽量少依赖第三方包，任何环境都能跑。"

Qoder 帮助梳理出：
- 记忆层三接口：remember / search / report
- 降级策略：PowerContext 不可用 → 本地 SQLite
- CLI 命令集：note / weakness / review / status

### 阶段 2：核心代码开发（Qoder 生成 + 人工核对）

| 文件 | 内容 | Qoder 参与 |
|---|---|---|
| `core/memory.py` | PowerContext HTTP 记忆层 + SQLite 降级 | Qoder 生成框架，人工补充端点容错 |
| `core/kb.py` | 笔记存储与全文检索 | Qoder 生成，人工加计分逻辑 |
| `cli/main.py` | CLI 命令分发 | Qoder 生成 argparse 骨架 |

### 阶段 3：闭环验证（Qoder 运行测试）

在 Qoder 中运行：
```bash
python -m studymate.cli.main weakness add "机器学习-过拟合" "训练好验证差，对策：正则化+早停"
python -m studymate.cli.main weakness list
python -m studymate.cli.main note add "SQL 索引原理" --tags 数据库 SQL --content "B+树索引按序存储"
python -m studymate.cli.main review "过拟合"
```
验证结果：记忆写入、检索复用、重启后数据仍在（见 `records/VALIDATION.md`）。

### 阶段 4：Qoder Sites 发布

- 网站内容位于 `site/`（项目简介、解决的问题、核心功能、截图/录屏、仓库链接、体验入口）。
- 使用 Qoder Sites 发布，可见范围设置为"任何人都可访问"。
- 发布后网址记录于 `site/README.md`。

## Qoder Credits 使用

- 本次开发使用 Qoder CN Credits（2000 额度中的一部分），用于模型对话与代码生成。
- 额度来源：大赛提供的 Qoder CN Credits 权益。

## 证据

- 本项目 `records/VALIDATION.md` 为可核对验证记录
- 代码仓库链接（fork 后填入）：
- Qoder Sites 网址（发布后填入）：
