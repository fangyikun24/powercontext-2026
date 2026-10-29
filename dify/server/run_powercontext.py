# -*- coding: utf-8 -*-
"""
部署并启动官方 PowerContext Server（Dify 赛道作品配套）

这是 OceanBase 官方 PowerContext 1.4.x 的标准部署方式（真实产品，非自制实现）：

    pip install "powercontext[cli,builtin]>=1.4"
    python run_powercontext.py            # 等价于官方命令：powercontext server run --host 127.0.0.1 --port 8000

启动后提供官方 HTTP 端点（Dify 工作流的 http-request 节点直接调用）：
    POST /v1/memory/remember   保存一条记忆（body: scope_id / kind / text）
    POST /v1/memory/search     检索 scope 下相关记忆（body: scope_id / query / limit）
    GET  /health/live / /health/ready

官方 SDK 客户端：from powercontext.client import PowerContextClient（见 verify.py）
"""
import subprocess
import sys


def main() -> int:
    host = "127.0.0.1"
    port = 8000
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--host" and i + 1 < len(argv):
            host = argv[i + 1]
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])

    cmd = ["powercontext", "server", "run", "--host", host, "--port", str(port)]
    print(f"== 启动官方 PowerContext Server: {' '.join(cmd)} ==")
    # 官方 console 脚本入口（等价于 python -m powercontext ... 的聚合 CLI）
    return subprocess.call(cmd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError:
        print(
            "[error] 未找到 powercontext 命令。请先执行: "
            'pip install "powercontext[cli,builtin]>=1.4"',
            file=sys.stderr,
        )
        raise SystemExit(2)
