"""屏幕外生成关键页面截图（浅色/深色 × 宽/窄），供人工目检。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py
输出到 scripts/../screenshots/ 目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from qfluentwidgets import Theme, setTheme

from app.components.download_queue import download_queue
from app.components.widgets import DressCard, PackageCard, QueueCard

OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def shot(widget, name: str) -> None:
    widget.show()
    for _ in range(3):
        app.processEvents()
    pix = widget.grab()
    path = OUT / name
    if not pix.save(str(path)):
        print(f"  save FAIL: {path}")
    else:
        print(f"  saved: {path}")


def render(theme: Theme, tag: str) -> None:
    setTheme(theme)
    print(f"== {tag} ==")

    # Emoji 详情网格：图标占位背景
    grid = EmojiGrid()
    grid.set_emotes([(f"表情{i}", f"https://x.invalid/{i}.png") for i in range(6)])
    grid.resize(760, 420)
    shot(grid, f"emoji_grid_{tag}.png")
    grid.close()

    # 表情包卡片
    pkg = _Pkg(1)
    pc = PackageCard(pkg)
    pc.setFixedSize(160, 160)
    shot(pc, f"package_card_{tag}.png")
    pc.close()

    # 收藏集搜索卡
    dc = DressCard(_FakeSummary("测试收藏集名称", collection=True))
    dc.setFixedSize(200, 300)
    shot(dc, f"dress_card_{tag}.png")
    dc.close()

    # 队列卡（长名 + 勾选）
    qc = QueueCard(_FakeSummary("这是一个特别长的收藏集名称用来验证换行不会溢出卡片边界" * 2))
    qc.set_selectable(True)
    qc.setFixedSize(445, 112)
    shot(qc, f"queue_card_{tag}.png")
    qc.close()


# 本地便捷导入
from app.components.widgets import EmojiGrid


class _FakeSummary:
    def __init__(self, name: str, *, collection: bool = True) -> None:
        self.name = name
        self.raw = {
            "item_id": "999",
            "properties": (
                {"type": "dlc_act", "dlc_act_id": "1", "dlc_lottery_id": "2"}
                if collection
                else {"type": "ip"}
            ),
        }
        self.image_cover = ""
        self.sale_bp_forever = 6.0


class _Pkg:
    def __init__(self, pid: int) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = []
        self.url = ""


def main() -> None:
    # 下载页双列（深色）
    setTheme(Theme.DARK)
    from app.view.download_page import DownloadPage

    download_queue.clear()
    for i in range(6):
        download_queue.add(_Pkg(i))
    page = DownloadPage()
    page.resize(980, 640)
    shot(page, "download_page_2col_dark.png")
    page.resize(420, 640)
    shot(page, "download_page_1col_dark.png")
    page.close()

    # 设置页
    from app.view.setting_page import SettingPage

    sp = SettingPage()
    sp.resize(900, 700)
    shot(sp, "setting_page_dark.png")
    sp.close()

    # 收藏集页（深色，搜索态）
    from app.view.dress_page import DressPage

    dp = DressPage()
    dp.resize(1000, 680)
    dp._show_results([_FakeSummary(f"收藏集{i}", collection=True) for i in range(6)])
    shot(dp, "dress_search_dark.png")
    dp.close()

    # 浅色对照：表情包卡 / 收藏集卡
    render(Theme.LIGHT, "LIGHT")
    render(Theme.DARK, "DARK")


if __name__ == "__main__":
    main()
