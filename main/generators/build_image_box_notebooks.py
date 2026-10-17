"""兼容旧批量入口；图像与 Box 教程各自维护独立生成器。"""
from pathlib import Path

import nbformat as nbf


def build_images_notebook():
    from build_images_notebook import build_images_notebook as builder
    return builder()


def build_box_notebook():
    from build_box_notebook import build_box_notebook as builder
    return builder()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", choices=("images", "box", "all"), default="all")
    parser.add_argument("--force", action="store_true", help="覆盖已有输出，需先保存历史实验")
    args = parser.parse_args()
    out = Path(__file__).resolve().parents[1] / "02_核心概念"
    builders = {"images": ("06_图像输入.ipynb", build_images_notebook),
                "box": ("07_box定位.ipynb", build_box_notebook)}
    selected = list(builders) if args.chapter == "all" else [args.chapter]
    for chapter in selected:
        name, _ = builders[chapter]
        path = out / name
        if path.exists() and not args.force:
            existing = nbf.read(path, as_version=4)
            if any(c.get("outputs") for c in existing.cells):
                parser.error(f"{name} 已有执行输出；请先归档，再用 --force。")
    for chapter in selected:
        name, builder = builders[chapter]
        nb = builder()
        nbf.validate(nb)
        nbf.write(nb, out / name)
        codes = [c for c in nb.cells if c.cell_type == "code"]
        markdown_count = sum(c.cell_type == "markdown" for c in nb.cells)
        print(f"{name}: {markdown_count} md / {len(codes)} code "
              f"(比 {markdown_count/len(codes):.2f}), "
              f"最长 code {max(len(c.source.splitlines()) for c in codes)} 行")
