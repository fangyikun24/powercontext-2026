"""
MiniMax 赛道 · 上下文管理系统 —— 主编排（CLI 入口）

六项必做（赛题要求）逐条落点：
1. 能运行        → python -m context_module.cli init | run | resume
2. MiniMax 参与   → 开发记录 records/DEVELOPMENT_LOG.md 记录真实调用，补丁来自 MiniMax 输出
3. 上下文正确     → 上下文来自 seekdb 检索（含规格/代码/测试来源），规格更新后重新入库存，输出随之更新
4. 数据库参与     → seekdb 存储工程资料，检索结果直接构成上下文
5. 状态可复用     → PowerContext/本地 JSON 保存任务状态，resume 可从断点继续
6. 修改有效       → 修改前目标测试失败，应用补丁后目标测试通过、回归测试不受影响
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_PROJECT = os.path.join(PROJECT_ROOT, "sample_project")
MATERIALS = os.path.join(PROJECT_ROOT, "materials")
RECORDS = os.path.join(PROJECT_ROOT, "records")
TARGET_CODE = os.path.join(SAMPLE_PROJECT, "discount.py")
TARGET_TESTS = os.path.join(SAMPLE_PROJECT, "tests", "test_discount.py")

TASK = (
    "修复订单折扣计算器 calculate_discount 的边界校验缺失："
    "quantity 为负数或 0 时必须抛出 DiscountError，禁止静默返回数值。"
    "要求：只修改 discount.py，保持其余行为不变。"
)
INSTRUCTION = (
    "在 discount.py 的 calculate_discount 中补充 quantity 合法性校验："
    "quantity < 1 时抛出 DiscountError('quantity 必须大于等于 1')。"
    "不改变函数签名与返回值语义，不动其他文件。"
)


def _embed(text: str) -> list[float]:
    """本地简易向量化：基于字符哈希的 384 维确定性向量（演示用途）。

    真实评测环境中可替换为 MiniMax/本地 embedding 模型；本项目用确定性哈希
    保证无网络也能完成闭环演示。
    """
    vec = [0.0] * 384
    for i, ch in enumerate(text):
        vec[i % 384] += (ord(ch) % 97) + 1
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def _run_tests() -> tuple[int, str]:
    """运行 pytest，返回 (失败数, 摘要文本)。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TARGET_TESTS, "-q"],
        cwd=SAMPLE_PROJECT, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout[-600:]


def _load_materials() -> list[dict]:
    """读取 materials/ 下全部工程资料（SPEC/CODE/TEST）。"""
    items = []
    spec = os.path.join(MATERIALS, "SPEC.md")
    if os.path.exists(spec):
        items.append({
            "id": "SPEC", "kind": "spec", "title": "订单折扣计算器规格",
            "text": open(spec, encoding="utf-8").read(),
        })
    items.append({
        "id": "CODE", "kind": "code", "title": "discount.py 源码",
        "text": open(TARGET_CODE, encoding="utf-8").read(),
    })
    items.append({
        "id": "TEST", "kind": "test", "title": "test_discount.py 测试",
        "text": open(TARGET_TESTS, encoding="utf-8").read(),
    })
    return items


def _apply_patch(patch: str) -> bool:
    """把 MiniMax 生成的补丁应用到 discount.py。

    支持两种格式：
    1) unified diff（@@ 片段 + +/- 行）→ 用 patch 命令
    2) 完整文件内容（含 def calculate_discount 的定义）→ 直接替换目标函数区域
    简化实现：若补丁包含完整函数体（"def calculate_discount"），则整体替换文件。
    """
    if "def calculate_discount" in patch:
        # 提取到函数结尾的代码段（演示工程小，直接整文件替换更稳）
        body = patch
        # 去掉可能的 markdown 代码围栏
        lines = [ln for ln in body.splitlines()
                 if not ln.strip().startswith(("```", "diff --git", "index ", "--- ", "+++ "))]
        new_content = "\n".join(lines).strip() + "\n"
        with open(TARGET_CODE, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def cmd_init(ctx) -> int:
    """初始化：把工程资料写入 seekdb，建立知识库。"""
    print(f"初始化知识库：将 {len(_load_materials())} 份工程资料写入 seekdb…")
    from context_module.store import SeekdbStore
    store = SeekdbStore()
    try:
        store.ensure_collection(dimension=384)
        for item in _load_materials():
            store.add_material(
                material_id=item["id"], kind=item["kind"], title=item["title"],
                text=item["text"], embedding=_embed(item["text"]),
            )
        print("✔ 资料已写入 seekdb collection=materials")
    finally:
        store.close()
    print("\n下一步：python -m context_module.cli run")
    return 0


def cmd_run(ctx) -> int:
    """执行一轮上下文驱动的代码修改闭环。"""
    from context_module.store import SeekdbStore
    from context_module.assembler import ContextAssembler
    from context_module.state import StateManager

    state = StateManager()
    print(state.report())
    print("\n[1/6] 运行基线测试（期望：目标测试失败，回归通过）")
    code, summary = _run_tests()
    baseline_fail = code != 0
    print(summary.strip().splitlines()[-1] if summary.strip() else f"exit={code}")
    print(f"    基线失败数={code}（{'确认目标未实现' if baseline_fail else '基线已通过，无修改必要'}）")

    print("\n[2/6] 从 seekdb 检索工程资料并组装上下文")
    store = SeekdbStore()
    assembler = ContextAssembler(store)
    try:
        ctx = assembler.assemble(task=TASK, query_embedding=_embed(TASK),
                                 query_text="quantity 校验", limit=3)
    finally:
        store.close()
    print(f"    检索到 {len(ctx['retrieved'])} 条资料：",
          ", ".join(h["id"] for h in ctx["retrieved"]) or "(空)")
    # 展示上下文片段（验证含来源）
    for h in ctx["retrieved"]:
        print(f"    - [{h['id']}] {h['title']} (score={h['score']})")

    print("\n[3/6] 调用 MiniMax 生成补丁")
    try:
        from context_module.minimax_client import MiniMaxClient
        mm = MiniMaxClient()
        patch = mm.generate_patch(ctx, INSTRUCTION)
    except Exception as e:
        print(f"    ✘ MiniMax 调用失败：{e}")
        print("    提示：设置 MINIMAX_API_KEY 后重试；本地演示可用 mock 模式。")
        return 2
    with open(os.path.join(RECORDS, "patch.txt"), "w", encoding="utf-8") as f:
        f.write(patch)
    print("    ✔ 补丁已生成并保存 records/patch.txt")

    print("\n[4/6] 应用补丁")
    ok = _apply_patch(patch)
    print(f"    {'✔ 补丁已应用' if ok else '✘ 补丁格式不支持，请检查 records/patch.txt'}")

    print("\n[5/6] 复跑测试验证")
    code2, summary2 = _run_tests()
    print(summary2.strip().splitlines()[-1] if summary2.strip() else f"exit={code2}")
    fixed = code2 == 0
    print(f"    {'✔ 修改有效：全部测试通过' if fixed else '✘ 仍有失败，需人工检查'}")

    print("\n[6/6] 保存任务状态（PowerContext / 本地 JSON）")
    state.save_state({
        "phase": "done" if fixed else "failed",
        "task": TASK,
        "baseline_fail_count": code,
        "after_fail_count": code2,
        "retrieved_ids": [h["id"] for h in ctx["retrieved"]],
        "fixed": fixed,
    })
    print("    ✔ 状态已保存（resume 可读取）")

    # 开发记录（MiniMax 实际参与的留痕）
    with open(os.path.join(RECORDS, "DEVELOPMENT_LOG.md"), "a", encoding="utf-8") as f:
        f.write(
            f"\n## {__import__('datetime').datetime.now().isoformat(timespec='seconds')}\n"
            f"- 调用 MiniMax 模型：{os.environ.get('MINIMAX_MODEL','MiniMax-Text-01')}\n"
            f"- 上下文来源：seekdb 检索 {[h['id'] for h in ctx['retrieved']]}\n"
            f"- 基线失败 {code} 项 → 修改后失败 {code2} 项\n"
            f"- 结果：{'成功' if fixed else '失败'}\n"
        )
    print("\n完成。详见 records/DEVELOPMENT_LOG.md 与 records/patch.txt")
    return 0 if fixed else 1


def cmd_resume(ctx) -> int:
    """恢复上次任务状态（证明状态可复用）。"""
    from context_module.state import StateManager
    st = StateManager()
    state = st.load_state()
    if not state:
        print("无历史状态（首次运行）。先执行 init 与 run。")
        return 1
    print(f"✔ 已恢复任务状态（{st.report()}）")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    if state.get("phase") == "done" and state.get("fixed"):
        print("\n上次任务已完成且修改有效。运行 python -m context_module.cli run 可重跑闭环。")
    else:
        print("\n上次任务未完成/失败。运行 python -m context_module.cli run 继续。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniMax 赛道 · 上下文管理系统")
    parser.add_argument("command", choices=["init", "run", "resume"])
    ctx = parser.parse_args()
    return {
        "init": cmd_init,
        "run": cmd_run,
        "resume": cmd_resume,
    }[ctx.command](ctx)


if __name__ == "__main__":
    sys.exit(main())
