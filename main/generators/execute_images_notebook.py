"""在干净内核验证 图像教程；离线预览与真实运行记录分开保存。"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from nbclient import NotebookClient

from execute_foundations_notebooks import assert_no_key, structure_report
from execute_box_notebook import load_api_key

ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT / "02_核心概念"
SOURCE = CHAPTER / "06_图像输入.ipynb"


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
    env.update(JEV_RUN_MODE=mode, JEV_IMAGES_DIR=str(CHAPTER))
    if mode == "offline":
        env.pop("TYPESAFE_API_KEY", None)
    with tempfile.TemporaryDirectory(prefix="jev-images-kernel-") as workdir:
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
              if "images-execution-audit" in c.metadata.get("tags", [])]
    if len(audits) != 1:
        raise ValueError("缺少唯一的来源记录")
    audit = json.loads("".join(
        output.get("text", "") for output in audits[0].outputs
        if output.output_type == "stream"))
    if audit["kind"] != "jev_images_execution_audit" or audit["run_mode"] != mode:
        raise ValueError("执行来源不匹配")
    expected_real, expected_offline = (15, 0) if mode == "live" else (0, 15)
    if (audit["real_calls"], audit["offline_calls"]) != (expected_real, expected_offline):
        raise ValueError("业务请求数量或来源不符合完整实验")
    if sum(len(call["questions"]) for call in audit["calls"]) != 23:
        raise ValueError("缺少实验问题")
    if (len(audit["results"]["photos"]) != 4 or len(audit["results"]["reference"]) != 2
            or len(audit["results"]["stickers"]) != 2 or len(audit["results"]["frames"]) != 2):
        raise ValueError("实验样本覆盖不足")
    if len(audit["probes"]) != 2 or any(not p["expected_rejection"] for p in audit["probes"]):
        raise ValueError("预期拒绝探针未完成")
    if audit["real_probe_calls"] != (2 if mode == "live" else 0):
        raise ValueError("拒绝探针来源不一致")
    notebook.metadata["jev_cookbook"].pop("output_review", None)
    validation = ROOT / "validation/images"
    validation.mkdir(parents=True, exist_ok=True)
    if mode == "live":
        notebook.cells[0].source = re.sub(
            r"\*\*运行状态：.*?\*\*",
            "**运行状态：本文件已执行真实 API，具体模型、时间与响应见末尾记录。**",
            notebook.cells[0].source, count=1)
        destination = SOURCE
        notebook.metadata["jev_cookbook"]["live_validation"] = "live_executed"
    else:
        notebook.cells[0].source = re.sub(
            r"\*\*运行状态：.*?\*\*",
            "**运行状态：本文件仅执行离线人工示例；真实结果见正式 Notebook 与实测归档。**",
            notebook.cells[0].source, count=1)
        notebook.cells[0].source = (
            "# 离线预览：人工答案，不是 Jev 实测\n\n" + notebook.cells[0].source)
        destination = validation / "06_图像输入.offline.ipynb"
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
    parser.add_argument("--env-file", type=Path,
                        help="安全读取 .env 中的 TYPESAFE_API_KEY 或 jev-key，仅限 live")
    args = parser.parse_args()
    if args.env_file:
        if args.mode != "live":
            parser.error("离线检查不读取密钥配置，请移除 --env-file。")
        try:
            os.environ["TYPESAFE_API_KEY"] = load_api_key(args.env_file)
        except (OSError, ValueError) as error:
            parser.error(f"无法读取密钥配置：{type(error).__name__}。")
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
