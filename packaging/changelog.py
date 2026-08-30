"""从 `CHANGES.md` 里抽取指定版本的更新说明。

发版时这段文本有两个去处，是同一份内容：

1. GitHub Release 的正文（`packaging/build.py` 写到 `dist/release_notes.md`，
   工作流用 `body_path` 上传）；
2. 应用内更新弹窗里渲染的 markdown（更新器读的就是 Release 正文）。

所以「写更新日志」这件事只需要做一次。

单独试：`uv run python packaging/changelog.py 0.1.0`
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG_PATH = Path(__file__).resolve().parents[1] / "CHANGES.md"

# 版本小节的标题行：`## [0.1.0] - 2026-08-30` / `## v0.1.0` / `## 0.1.0` 都认
_HEADING = re.compile(r"^##\s+")


class VersionNotFound(LookupError):
    """`CHANGES.md` 里没有这个版本的小节。"""


def _normalize(text: str) -> str:
    """把标题里的版本记号归一成裸版本号，好做相等比较。"""
    return text.strip().strip("[]").lstrip("vV").strip()


def _heading_version(line: str) -> str:
    """从 `## [0.1.0] - 2026-08-30` 里取出 `0.1.0`；不是版本标题返回空串。"""
    body = _HEADING.sub("", line).strip()
    if not body:
        return ""
    # 版本号是标题里第一个 token，后面可能跟 ` - 日期`
    token = body.split(" - ")[0].split()[0]
    version = _normalize(token)
    return version if version and version[0].isdigit() else ""


def extract(version: str, path: Path | None = None) -> str:
    """取出该版本小节的正文（不含标题行）。

    找不到就抛 `VersionNotFound` —— 构建时直接失败：发一个更新说明为空的 Release，
    比构建失败更糟（用户点开弹窗一片空白，也没法回头补）。
    """
    target = _normalize(version)
    lines = (path or CHANGELOG_PATH).read_text(encoding="utf-8").splitlines()

    body: list[str] = []
    collecting = False
    for line in lines:
        if _HEADING.match(line):
            if collecting:  # 撞到下一个版本小节，收工
                break
            collecting = _heading_version(line) == target
            continue
        if collecting:
            body.append(line)

    text = "\n".join(body).strip()
    if not text:
        raise VersionNotFound(
            f"CHANGES.md 里没有版本 {version} 的小节（或该小节为空）。"
            "发版前请先补上更新说明。"
        )
    return text


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python packaging/changelog.py <版本号>", file=sys.stderr)
        raise SystemExit(2)
    print(extract(sys.argv[1]))
