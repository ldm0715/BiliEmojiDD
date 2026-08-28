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

from app.components.content_meta import content_meta
from app.components.download_queue import download_queue
from app.components.widgets import DressCard, PackageCard, QueueCard

# 队列卡片会为可见项懒加载「内容数量」，假数据会排一堆超时请求把脚本挂住
content_meta.set_enabled(False)

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


class _Emote:
    def __init__(self, i: int) -> None:
        self.text = f"表情{i}"
        self.url = f"https://x.invalid/{i}.png"
        self.gif_url = ""


class _Pkg:
    def __init__(self, pid: int, emotes: int = 0) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = [_Emote(i) for i in range(emotes)]
        self.url = ""


class _FakeCollection:
    name = "测试收藏集"

    def __init__(self, images: int = 8, videos: int = 2) -> None:
        self.item_list = [_FakeCollItem(i, i < videos) for i in range(images)]


class _FakeCollItem:
    def __init__(self, i: int, with_video: bool) -> None:
        self.card_name = f"内容{i}"
        self.card_img_download = f"https://x.invalid/c{i}.png"
        self.video_list = [f"https://x.invalid/v{i}.mp4"] if with_video else []


def shot_pages(theme: Theme, tag: str) -> None:
    """四个页面的整页截图（版式比对用）。"""
    setTheme(theme)
    print(f"== pages {tag} ==")

    from app.view.download_page import DownloadPage
    from app.view.dress_page import DressPage
    from app.view.emoji_page import EmojiPage

    # 表情包页：全部表情包列表 + 详情
    ep = EmojiPage()
    ep.resize(1000, 760)
    ep.pivot.setCurrentItem("all")
    ep.stackedWidget.setCurrentWidget(ep.allTab)
    ep.allTab._set_packages([_Pkg(i) for i in range(8)])
    shot(ep, f"emoji_page_list_{tag}.png")
    ep.allTab.stacked.setCurrentWidget(ep.allTab.detailPage)
    ep.allTab.detail.set_package(_Pkg(53, emotes=10))
    shot(ep, f"emoji_page_detail_{tag}.png")
    ep.close()

    # 收藏集页：搜索结果 + 详情
    dp = DressPage()
    dp.resize(1000, 760)
    dp._show_results([_FakeSummary(f"收藏集{i}", collection=True) for i in range(8)])
    shot(dp, f"dress_page_search_{tag}.png")
    dp._detail_summary = _FakeSummary("测试收藏集")
    dp.stacked.setCurrentWidget(dp.detailPage)
    dp.detailName.setText("测试收藏集")
    dp._show_detail(_FakeCollection())
    shot(dp, f"dress_page_detail_{tag}.png")
    dp.close()

    # 下载页：队列非空
    download_queue.clear()
    for i in range(6):
        download_queue.add(_Pkg(i))
    dl = DownloadPage()
    dl.resize(1000, 760)
    shot(dl, f"download_page_{tag}.png")
    dl.close()
    download_queue.clear()


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
    download_queue.clear()

    # 设置页（亮 / 暗对照，与「设置页面重新设计.png」逐行比对）
    from app.view.setting_page import SettingPage

    for theme, tag in ((Theme.DARK, "dark"), (Theme.LIGHT, "light")):
        setTheme(theme)
        sp = SettingPage()
        sp.resize(900, 900)
        shot(sp, f"setting_page_{tag}.png")
        sp.close()

    # 表情包 / 收藏集 / 下载三页整页版式
    shot_pages(Theme.LIGHT, "light")
    shot_pages(Theme.DARK, "dark")

    # 浅色对照：表情包卡 / 收藏集卡
    render(Theme.LIGHT, "LIGHT")
    render(Theme.DARK, "DARK")


if __name__ == "__main__":
    main()
