# Qoder 开发记录（QODER DEV LOG）— StudyMate 学习提效助手

> 用途：赛题验收「Qoder 开发可核对」。
> Qoder 账号 UID：`01a1834d-987e-7381-81d7-81305fd2bbe8`
> 项目网站（Qoder Sites）：https://studymate-6ni50nl82vr.qoder.website

## 项目概览

- 项目名：StudyMate · 学习提效助手
- 解决的问题：学习笔记与错题散落、复习无重点、关键词检索不精准
- 指定技术：**seekdb**（嵌入式，`pylibseekdb` + MySQL 协议）
- 核心能力：中文全文检索（ngram 分词）+ 科目过滤 + 复习写回 + 分科目正确率统计
- 交付：Qoder Sites 项目网站 + 可运行代码（本目录）+ 验证样例

## 开发过程（Qoder 中完成）

### 阶段 1：需求拆解与网站

在 Qoder 中创建任务「StudyMate 学习助手项目网站开发」，由 Qoder：

- 拆解出项目简介、解决的问题、核心功能、演示截图、体验入口等页面结构；
- 生成 `site/` 下的页面与样式，并通过 Qoder Sites 创建站点、发布为公开访问；
- 产出 `index.html` / `styles.css` / `app.js` 与两张检索演示截图。

站点地址：https://studymate-6ni50nl82vr.qoder.website

### 阶段 2：seekdb 后端

在同一 Qoder 任务中继续实现 seekdb 后端（`backend/server.py`）：

- 选择 seekdb 嵌入式部署（`pylibseekdb`），避免额外服务与端口依赖；
- 建 `notes` / `questions` / `review_log` 三张表；
- 中文全文索引使用 `FULLTEXT INDEX ... WITH PARSER ngram`（默认分词器对中文不分词，实测 `MATCH` 返回 0）；
- 提供 `/api/search`、`/api/questions`、`/api/review`、`/api/stats` 与静态演示页。

### 阶段 3：调试与验收

Qoder 中实际运行并修复的问题：

1. 中文全文检索无结果 → 改用 ngram 分词器；
2. seekdb 数据目录含中文导致 `seekdb_open failed: code=-1` → 固定为 ASCII 数据目录；
3. 复习写回后统计为小数 → `Decimal` 转 `int/float` 后再序列化；
4. 端口被旧进程占用导致连接异常 → 改为可配置 `STUDYMATE_PORT`，并清理重复实例。

### 阶段 4：发布与材料

- 网站通过 Qoder Sites 「任何人都可访问」发布，并复用原地址重新发布；
- 开发记录、验证记录写入 `records/`；
- 代码与运行说明整理进 `qoder/` 目录，提交到大赛分支。

## 验证与证据

- 一键验收：`cd qoder && pip install -r requirements.txt && python run_demo.py` → 6 项 PASS
- 接口验收：启动 `backend/server.py` 后运行 `backend/verify_seekdb.py` → 7 项 PASS
- 详细输出见 `records/VALIDATION.md`
- 页面截图见 `site/assets/demo-notes.png`、`site/assets/demo-questions.png`

## Qoder 对话截图/录屏

关键对话（需求拆解、seekdb 建表、ngram 修复、发布站点）可在 Qoder 任务
「StudyMate 学习助手项目网站开发」中回看；账号 UID 与站点归属见上。
