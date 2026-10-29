# 验证记录（VALIDATION）

> 记录时间：2026-10-29
> 环境：Windows 11 · Python 3.12 · `pylibseekdb 1.4.0.post2` · `pymysql 1.2.3`
> 数据目录：`C:\Users\Public\StudyMateData\seekdb`（ASCII 路径）

## 验证 1：一键验收（无需启动 HTTP 服务）

```bash
cd qoder
pip install -r requirements.txt
python run_demo.py
```

实际输出：

```
数据目录：C:\Users\Public\StudyMateData\seekdb
初始化：建表并写入 8 条笔记 / 6 道错题
[PASS] seekdb 中文全文检索（笔记） · 命中 1 条，首条《边际效用递减》 score=1.6995664355304099
[PASS] seekdb 中文全文检索（错题） · 命中 1 条，首条「求函数 f(x) = x²e^x 的导数」
[PASS] 科目过滤下推到 seekdb · subject=数学 1 条 / subject=英语 0 条
[PASS] 复习动作写回数据库 · attempts 3 → 4
[PASS] review_log 增加 1 条 · reviews 0 → 1
[PASS] 分科目正确率统计 · 数学 6次 66.7% / 英语 3次 33.3% / 经济学 2次 100.0% / 方法 2次 100.0% / 政治 1次 0.0%

共 6 项，失败 0 项
PASS：seekdb 检索 / 过滤 / 复习写回 / 统计全部可用
```

## 验证 2：接口级验收（启动 server 后）

```bash
python backend/server.py
# 另开终端：
python backend/verify_seekdb.py
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

## 验证 3：HTTP 接口

```text
GET /api/search?q=边际效用   → 200，count=1，took_ms≈20，首条 score≈1.6996
GET /api/stats               → 200，notes=8，questions=6，reviews 随复习递增
POST /api/review             → 200，attempts 3→4，correct_count 2→3
```

## 技术作用说明

| 环节 | seekdb 的实际作用 |
|---|---|
| 笔记检索 | `MATCH(content) AGAINST('边际效用')` 命中《边际效用递减》，返回真实 score |
| 错题检索 | `MATCH(question) AGAINST('导数')` 命中导数题，返回题干、错因与复习次数 |
| 科目过滤 | `AND subject = '数学'` 由 seekdb 执行；换成“英语”返回 0 条 |
| 复习写回 | `UPDATE questions ...` + `INSERT INTO review_log`，统计页正确率同步变化 |
| 中文分词 | `FULLTEXT INDEX ... WITH PARSER ngram`，默认分词器对中文不分词 |

## 复现注意

- `pylibseekdb` 会启动嵌入式 `seekdb.exe` 并锁定数据目录；同一目录不要同时开多个实例，
  否则会出现 `seekdb_open failed` 或连接异常。首次运行请使用全新数据目录。
- 数据目录必须是纯 ASCII 路径；含中文的用户目录会导致 `seekdb_open failed: code=-1`。
- 端口可用 `STUDYMATE_PORT` 覆盖（默认 8787）；启动前确认端口未被占用。
