"""在干净内核验证 Box 教程；离线预览与真实运行记录分开保存。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from nbclient import NotebookClient

from execute_foundations_notebooks import assert_no_key, structure_report

ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT / "02_核心概念"
SOURCE = CHAPTER / "07_box定位.ipynb"


def execute(mode):
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if mode == "live" and not key:
        raise ValueError("缺少 TYPESAFE_API_KEY，未执行或改写 Notebook")
    notebook = nbformat.read(SOURCE, as_version=4)
    dimensions = structure_report(notebook)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.execution_count = None
    env = os.environ.copy()
    env.update(JEV_RUN_MODE=mode, JEV_BOX_DIR=str(CHAPTER))
    if mode == "offline":
        env.pop("TYPESAFE_API_KEY", None)
    with tempfile.TemporaryDirectory(prefix="jev-box-kernel-") as workdir:
        env["IPYTHONDIR"] = str(Path(workdir) / "ipython")
        env["JUPYTER_RUNTIME_DIR"] = str(Path(workdir) / "runtime")
        manager = KernelManager(kernel_name="python3")
        manager.kernel_spec.argv = [
            sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
        runner = NotebookClient(
            notebook, km=manager, timeout=180, startup_timeout=30,
            allow_errors=False, resources={"metadata": {"path": workdir}})
        try:
            runner.execute(env=env)
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
            manager.cleanup_resources()
    structure_report(notebook)
    audits = [c for c in notebook.cells
              if "box-execution-audit" in c.metadata.get("tags", [])]
    if len(audits) != 1:
        raise ValueError("缺少唯一的来源记录")
    audit = json.loads("".join(
        output.get("text", "") for output in audits[0].outputs
        if output.output_type == "stream"))
    if audit["kind"] != "jev_box_execution_audit" or audit["run_mode"] != mode:
        raise ValueError("执行来源不匹配")
    expected_real, expected_offline = (7, 0) if mode == "live" else (0, 7)
    if (audit["real_calls"], audit["offline_calls"]) != (expected_real, expected_offline):
        raise ValueError("业务请求数量或来源不符合完整实验")
    if sum(len(call["questions"]) for call in audit["calls"]) != 17:
        raise ValueError("缺少实验问题")
    if len(audit["results"]["controlled"]) != 4 or len(audit["results"]["crops"]) != 3:
        raise ValueError("实验样本覆盖不足")
    validation = ROOT / "validation/box"
    validation.mkdir(parents=True, exist_ok=True)
    if mode == "live":
        notebook.cells[0].source = notebook.cells[0].source.replace(
            "**运行状态：本版正式文件未执行新实验的真实 API。**",
            "**运行状态：本文件已执行真实 API，具体模型、时间与响应见末尾记录。**")
        destination = SOURCE
        notebook.metadata["jev_cookbook"]["live_validation"] = "live_executed"
    else:
        notebook.cells[0].source = (
            "# 离线预览：人工答案，不是 Jev 实测\n\n" + notebook.cells[0].source)
        destination = validation / "07_box定位.offline.ipynb"
        notebook.metadata["jev_cookbook"]["live_validation"] = "offline_verified_live_pending"
    serialized = nbformat.writes(notebook)
    report = json.dumps({"status": "offline_verified_live_pending" if mode == "offline"
                         else "live_executed_manual_review_pending",
                         "notebook": str(destination.relative_to(ROOT)),
                         **dimensions, **audit}, ensure_ascii=False, indent=2)
    assert_no_key(serialized, key)
    assert_no_key(report, key)
    destination.write_text(serialized, encoding="utf-8")
    (validation / f"{mode}.json").write_text(report + "\n", encoding="utf-8")
    return destination, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="live")
    args = parser.parse_args()
    if args.mode == "live" and not os.environ.get("TYPESAFE_API_KEY"):
        parser.error("缺少 TYPESAFE_API_KEY；可先显式选择 --mode offline。")
    try:
        destination, audit = execute(args.mode)
    except Exception as error:
        # 异常消息可能含服务端认证信息；不要复制到公开记录。
        print(f"失败：{type(error).__name__}；本次未保存实验输出。", file=sys.stderr)
        return 1
    print(f"通过：{destination}")
    print(f"真实调用={audit['real_calls']}，离线调用={audit['offline_calls']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
