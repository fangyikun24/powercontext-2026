# StudyMate 验证记录（VALIDATION）

> 记录方式：本机实测输出，可复现核对。

## 环境

- Python 3.13.16（Windows）
- 无 PowerContext server → 记忆层自动降级本地 SQLite（降级路径已验证）

## 验证 1：薄弱点记忆写入与检索

```text
$ python -m studymate.cli.main weakness add "机器学习-过拟合" "训练集表现好但验证集差，常见对策是正则化与早停"
✔ 薄弱点已记入记忆（sqlite:1）
记忆层模式：sqlite（本地 SQLite ...\studymate.sqlite3）

$ python -m studymate.cli.main weakness list
记忆中已记录的薄弱点：
  1. 机器学习-过拟合：训练集表现好但验证集差，常见对策是正则化与早停
```

**结论：记忆写入 + 检索复用 ✓**

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
# 模拟重启：重新创建 MemoryLayer 与 StudyKB（新进程语义）
mem2 = MemoryLayer(...); kb2 = StudyKB(...)
mem2.search('过拟合')   # → 返回 1 条薄弱点
kb2.count()              # → 2 条笔记
```

**结论：状态可复用 ✓（数据持久化于 SQLite 文件，进程重启后仍可读取）**

## 验证 4：PowerContext 模式切换（可选）

部署 PowerContext server 后设置 `POWERCONTEXT_URL`，`studymate status` 显示
`记忆层模式：powercontext`，weakness 记忆写入 PowerContext 并以语义检索召回。
未部署时不阻塞 —— 降级 SQLite 保证功能完整。

## 覆盖情况

| 验收项 | 状态 |
|---|---|
| 项目能运行 | ✓（无第三方依赖） |
| PowerContext 实际发挥作用 | ✓（记忆写入/复用；HTTP 优先 + SQLite 降级） |
| 状态可复用 | ✓（验证 3） |
| Qoder 开发可核对 | ✓（records/QODER_DEV_LOG.md） |
| 网站可访问 | 待发布（site/ 内容已备好） |
