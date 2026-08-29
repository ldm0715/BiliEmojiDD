"""把 `static/font/` 下的 woff2 解成 Qt 能加载的 ttf（一次性工具，非运行时代码）。

Qt 的 `QFontDatabase.addApplicationFont()` 只认 **TrueType / TrueType Collection /
OpenType**，woff2 会直接返回 -1。而阿里普惠体官方只在 Web 包里给 woff2，所以先在本地
解一次、把 ttf 提交进仓库，运行时零依赖。

依赖 `fonttools` + `brotli`（都在 dev 组里，`uv sync` 已装）。

用法：
    uv run python scripts/convert_font.py --dry-run   # 只看会生成什么
    uv run python scripts/convert_font.py             # 真的写 ttf
    uv run python scripts/convert_font.py --force     # 覆盖已存在的 ttf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from app.common.resource import FONT_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="woff2 -> ttf（static/font）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 ttf")
    args = parser.parse_args()

    if not FONT_DIR.is_dir():
        print(f"字体目录不存在：{FONT_DIR}")
        return 1

    sources = sorted(FONT_DIR.glob("*.woff2"))
    if not sources:
        print(f"{FONT_DIR} 下没有 .woff2，无事可做")
        return 0

    from fontTools.ttLib.woff2 import decompress  # 延迟导入：dry-run 也不必装 brotli

    failed = 0
    for src in sources:
        dst = src.with_suffix(".ttf")
        if dst.exists() and not args.force:
            print(f"跳过（已存在，加 --force 覆盖）：{dst.name}")
            continue
        if args.dry_run:
            print(f"[dry-run] {src.name} -> {dst.name}")
            continue
        try:
            decompress(str(src), str(dst))
        except Exception as exc:  # noqa: BLE001 单个字体失败不阻塞其余
            print(f"失败：{src.name} -> {type(exc).__name__}: {exc}")
            failed += 1
            continue
        print(f"完成：{src.name} -> {dst.name}（{dst.stat().st_size / 1024 / 1024:.1f} MB）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
