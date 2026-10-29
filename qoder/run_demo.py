"""StudyMate 一键自检（Qoder 赛道复现入口）。

运行：
    cd qoder
    python run_demo.py

它会按顺序执行：写入薄弱点 → 列出薄弱点 → 新增笔记 → 复习清单。
首次调用会自动拉起官方 PowerContext Server（若 127.0.0.1:8000 未启动）。
全部步骤返回码为 0 时输出 PASS。
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run_cli(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "studymate.cli.main", *args]
    return subprocess.run(
        cmd,
        cwd=HERE,
        text=True,
        capture_output=True,
        timeout=300,
    )


def main() -> int:
    steps = [
        ("写入薄弱点", ["weakness", "add", "机器学习-过拟合", "训练集表现好但验证集差，对策是正则化与早停"]),
        ("列出薄弱点", ["weakness", "list"]),
        ("新增笔记", ["note", "add", "SQL 索引原理", "--tags", "数据库", "SQL", "--content", "B+树索引按序存储，可加速范围查询"]),
        ("复习清单", ["review", "过拟合"]),
    ]
    for name, args in steps:
        print(f"== {name} ==")
        try:
            proc = run_cli(args)
        except subprocess.TimeoutExpired:
            print("TIMEOUT", file=sys.stderr)
            return 1
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if out:
            print(out)
        if proc.returncode != 0:
            print(f"FAIL (exit {proc.returncode})", file=sys.stderr)
            if err:
                print(err, file=sys.stderr)
            return 1
    print("\nPASS：官方 PowerContext 写入 / 检索 / 复习链路可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
