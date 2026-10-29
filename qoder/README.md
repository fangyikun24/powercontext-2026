# StudyMate · 学习提效助手（Qoder × OceanBase 赛道作品）

StudyMate 是一个面向大学生/考研人群的学习提效工具：把笔记和错题真正存进 **seekdb**，
用中文全文检索 + 科目过滤找回它们，并把每次复习结果写回数据库，形成可追踪的薄弱点。

- **项目网站（Qoder Sites，任何人可访问）**：https://studymate-6ni50nl82vr.qoder.website
- **代码仓库**：https://github.com/fangyikun24/powercontext-2026（分支 `2026-competition-ecosystem`，本目录 `qoder/`）
- **技术结合**：seekdb 嵌入式数据库（`pylibseekdb` + MySQL 协议），中文 `ngram` 全文索引、
  科目结构化过滤、复习写回与分科目统计，均为真实 SQL 查询，不是前端假数据。

## 解决的问题

1. **学了就忘**：笔记散落、错题不归档 → 统一存入 seekdb，按关键词/科目随时找回；
2. **复习没重点**：不知道哪些知识点薄弱 → 每次复习写回 `review_log`，统计分科目正确率；
3. **检索不精准**：普通关键词搜索匹配差 → seekdb `FULLTEXT ... WITH PARSER ngram` 中文分词 + 科目过滤。

## 目录结构

```
qoder/
├── backend/
│   ├── server.py          # HTTP API + 静态页面（标准库，无 Web 框架）
│   ├── verify_seekdb.py   # 7 项接口级验收（需先启动 server.py）
│   └── static/index.html  # 可交互的检索/复习演示页
├── run_demo.py            # 一键验收（直接调用后端函数，无需启动服务）
├── requirements.txt       # pylibseekdb + pymysql
├── records/               # Qoder 开发记录、验证记录
├── site/                  # Qoder Sites 发布的网站源文件
└── README.md
```

## 运行环境

- Python 3.11+
- Windows / Linux / macOS
- 依赖：`pylibseekdb>=1.4.0.post1`（seekdb 嵌入式运行时）、`pymysql>=1.1`

数据目录默认值（可用环境变量 `STUDYMATE_SEEKDB_DIR` 覆盖，必须是纯 ASCII 路径）：

- Windows：`C:\Users\Public\StudyMateData\seekdb`
- Linux/macOS：`/tmp/studymate-seekdb`

## 安装与运行（评审按此复现）

```bash
cd qoder
pip install -r requirements.txt

# 1) 一键验收：建表 + 写入 8 条笔记/6 道错题 + 6 项检查
python run_demo.py
# 期望末尾输出：PASS：seekdb 检索 / 过滤 / 复习写回 / 统计全部可用

# 2) 启动可交互演示页（另开终端）
python backend/server.py
# 浏览器打开 http://127.0.0.1:8787
```

可覆盖端口与数据目录：

```bash
STUDYMATE_PORT=8899 STUDYMATE_SEEKDB_DIR=/tmp/sm-db python backend/server.py   # Linux/macOS
$env:STUDYMATE_PORT=8899; $env:STUDYMATE_SEEKDB_DIR="D:\sm-db"; python backend\server.py  # Windows
```

> 启动 `server.py` 后，可另开终端运行 `python backend/verify_seekdb.py`，
> 它会依次验证 7 项接口级行为（engine、两次检索的 score/took_ms、科目过滤、复习写回、review_log、正确率）。

## 验证样例

### 样例 1：中文全文检索（笔记）

```bash
python run_demo.py
```

实际输出（节选）：

```
[PASS] seekdb 中文全文检索（笔记） · 命中 1 条，首条《边际效用递减》 score=1.6995664355304099
[PASS] seekdb 中文全文检索（错题） · 命中 1 条，首条「求函数 f(x) = x²e^x 的导数」
[PASS] 科目过滤下推到 seekdb · subject=数学 1 条 / subject=英语 0 条
[PASS] 复习动作写回数据库 · attempts 3 → 4
[PASS] review_log 增加 1 条 · reviews 0 → 1
[PASS] 分科目正确率统计 · 数学 6次 66.7% / 英语 3次 33.3% / …
共 6 项，失败 0 项
PASS：seekdb 检索 / 过滤 / 复习写回 / 统计全部可用
```

### 样例 2：接口级验收（启动 server 后）

```bash
python backend/server.py            # 终端 A
python backend/verify_seekdb.py     # 终端 B
```

实际输出（节选）：

```
PASS · engine 声明为 seekdb
PASS · 笔记检索「边际效用」返回 score 与 took_ms
PASS · 错题检索「导数」返回 score 与 took_ms
PASS · 科目过滤下推到 seekdb 执行
PASS · 复习写回返回 attempts/correct_count
PASS · review_log 增加 1 条
PASS · 对应科目正确率随写回变化
共 7 项，失败 0 项
```

### 样例 3：浏览器交互

打开 <http://127.0.0.1:8787/?q=边际效用>，页面显示“seekdb 命中 1 条，耗时 x ms”，
在错题页点“这次答对了”，提示“已写入 seekdb：第 N 次练习”，统计区正确率同步变化。

## 表结构（seekdb / MySQL 协议）

```sql
CREATE TABLE notes (
  id INT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(200), content TEXT, subject VARCHAR(50), tags VARCHAR(200),
  FULLTEXT INDEX ft_notes (content) WITH PARSER ngram
) ORGANIZATION = HEAP;

CREATE TABLE questions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  subject VARCHAR(50), question TEXT,
  wrong_answer VARCHAR(500), correct_answer VARCHAR(500), knowledge_point VARCHAR(200),
  attempts INT DEFAULT 0, correct_count INT DEFAULT 0,
  FULLTEXT INDEX ft_questions (question) WITH PARSER ngram
) ORGANIZATION = HEAP;

CREATE TABLE review_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  question_id INT, correct TINYINT, reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ORGANIZATION = HEAP;
```

## Qoder 开发记录

- 开发过程见 `records/QODER_DEV_LOG.md`，验证输出见 `records/VALIDATION.md`。
- Qoder 账号 UID：`01a1834d-987e-7381-81d7-81305fd2bbe8`（站点归属与开发记录核对用）。

## 已知边界

- 线上站点是纯静态展示页，不会请求 `127.0.0.1`；真实检索/复习在本地按上文运行。
- seekdb 数据目录必须为纯 ASCII 路径（含中文的路径会导致 `seekdb_open failed`）。
