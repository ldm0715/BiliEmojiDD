"""屏幕外验证表情包 / 收藏集 / 下载三页改版（Fluent 卡片版式）。

与设置页那批同一原则：**只改界面、不改功能**，所以断言分两半——
一半查功能控件仍在且可用，一半查新版式的结构、几何与主题表现。

1. 三页 + `PackageDetailView` 的功能控件属性齐全、类型未变；
2. 每页有大标题，标题与命令卡左边缘对齐（都在 PAGE_MARGIN）；
3. 多选行随「多选」勾选显隐（隐藏时命令卡自动收缩一行）；
4. 详情头部卡：`add_leading_widget` 的返回按钮在名称左侧；`set_package` 后按钮可用；
5. 收藏集详情：有视频显示视频卡、无视频���卡隐藏；
6. 窄窗口（600）命令卡内控件不越界；下载页 980 宽仍是两列；
7. 切主题后卡片背景色跟随（`BackgroundAnimationWidget` 生效）。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from qfluentwidgets import CheckBox, ComboBox, SimpleCardWidget, Theme, setTheme

from app.components.download_queue import download_queue
from app.components.page_scaffold import PAGE_MARGIN, CommandCard, SectionCard
from app.view.download_page import DownloadPage
from app.view.dress_page import DressPage
from app.view.emoji_page import EmojiPage

setTheme(Theme.LIGHT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def wait_until(cond, timeout: float = 2.0) -> None:
    """轮询等待（背景色是 120ms 属性动画，光 processEvents 不推进真实时间）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cond():
        settle(2)
        time.sleep(0.01)
    settle(2)


def left_of(widget, page) -> int:
    return widget.mapTo(page, widget.rect().topLeft()).x()


def preload(url: str) -> str:
    """把假图预置进 QPixmapCache，thumb_manager.request 同步命中不走网络。

    不预置的话每个假 URL 都会起一个 15s 超时的下载任务，脚本跑完退不出去
    （进程要等全局线程池收工）。
    """
    pm = QPixmap(8, 8)
    pm.fill(QColor("#888888"))
    QPixmapCache.insert(url, pm)
    return url


class _Emote:
    def __init__(self, i: int) -> None:
        self.text = f"表情{i}"
        self.url = preload(f"https://x.invalid/{i}.png")
        self.gif_url = ""


class _Pkg:
    def __init__(self, pid: int, emotes: int = 0) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = [_Emote(i) for i in range(emotes)]
        self.url = ""


class _CollItem:
    def __init__(self, i: int, with_video: bool) -> None:
        self.card_name = f"内容{i}"
        self.card_img_download = preload(f"https://x.invalid/c{i}.png")
        self.video_list = [f"https://x.invalid/v{i}.mp4"] if with_video else []


class _Collection:
    name = "测试收藏集"

    def __init__(self, videos: int = 2) -> None:
        self.item_list = [_CollItem(i, i < videos) for i in range(4)]


class _Summary:
    def __init__(self, name: str) -> None:
        self.name = name
        self.raw = {
            "item_id": "999",
            "properties": {
                "type": "dlc_act",
                "dlc_act_id": "1",
                "dlc_lottery_id": "2",
            },
        }
        self.image_cover = ""
        self.sale_bp_forever = 6.0


emoji = EmojiPage()
emoji.resize(1000, 760)
emoji.show()
dress = DressPage()
dress.resize(1000, 760)
dress.show()
download_queue.clear()
for i in range(4):
    download_queue.add(_Pkg(i))
dl = DownloadPage()
dl.resize(1000, 760)
dl.show()
# 隐藏的 Tab 不会被 Qt 布局，几何断言前先切到「全部表情包」
emoji.pivot.setCurrentItem("all")
emoji.stackedWidget.setCurrentWidget(emoji.allTab)
settle()

print("== 1. 功能控件仍在（槽函数按属性名取用，改名即崩） ==")
EMOJI_NAMES = ["idEdit", "queryBtn", "detail"]
ALL_NAMES = [
    "fetchBtn",
    "refreshBtn",
    "filterEdit",
    "countLabel",
    "multiBtn",
    "selectLabel",
    "addBtn",
    "grid",
    "pager",
    "backBtn",
    "detail",
]
DRESS_NAMES = [
    "kwEdit",
    "onlyCollCheck",
    "multiBtn",
    "searchBtn",
    "selectLabel",
    "addBtn",
    "grid",
    "hintLabel",
    "backBtn",
    "detailName",
    "detailInfo",
    "detailGrid",
    "videoToggle",
    "videoList",
    "modeCombo",
    "downloadedLabel",
    "queueBtn",
    "detailBtn",
    "detailBar",
]
DL_NAMES = [
    "countLabel",
    "selectAllBtn",
    "deleteBtn",
    "clearBtn",
    "downloadBtn",
    "grid",
    "emptyLabel",
    "statusLabel",
    "bar",
]
DETAIL_NAMES = [
    "nameLabel",
    "detailLabel",
    "grid",
    "gifCheck",
    "downloadedLabel",
    "queueBtn",
    "downloadBtn",
    "bar",
]
for tag, obj, names in (
    ("EmojiPage.idTab", emoji.idTab, EMOJI_NAMES),
    ("EmojiPage.allTab", emoji.allTab, ALL_NAMES),
    ("DressPage", dress, DRESS_NAMES),
    ("DownloadPage", dl, DL_NAMES),
    ("PackageDetailView", emoji.idTab.detail, DETAIL_NAMES),
):
    missing = [n for n in names if not hasattr(obj, n)]
    check(not missing, f"{tag}: {len(names)} 个功能控件齐全（缺失 {missing}）")

check(isinstance(dress.modeCombo, ComboBox), "modeCombo 仍是组件库 ComboBox")
check(
    [dress.modeCombo.itemData(i) for i in range(3)] == ["image", "video", "both"],
    "下载模式仍是 image/video/both（addItem 的 userData 没被 icon 位吃掉）",
)
check(isinstance(dress.multiBtn, CheckBox), "多选仍是 CheckBox")
check(dress.onlyCollCheck.isChecked(), "「仅看收藏集」仍默认勾选")

print("== 2. 版式：大标题 + 命令卡 + 左对齐 ==")
for tag, page, title, card in (
    ("表情包", emoji, "表情包", emoji.allTab.commandCard),
    ("收藏集", dress, "收藏集", dress.searchCard),
    ("下载", dl, "下载队列", dl.commandCard),
):
    check(page.titleLabel.text() == title, f"{tag}页大标题为「{title}」")
    check(isinstance(card, CommandCard), f"{tag}页工具栏是 CommandCard")
    tx, cx = left_of(page.titleLabel, page), left_of(card, page)
    check(
        tx == cx == PAGE_MARGIN,
        f"{tag}页标题与命令卡左对齐且为 {PAGE_MARGIN}（实际 {tx} / {cx}）",
    )
check(isinstance(emoji.idTab.searchCard, CommandCard), "按 ID 查询页也是 CommandCard")
check(
    isinstance(emoji.idTab.detail.previewCard, SectionCard)
    and isinstance(dress.previewCard, SectionCard),
    "两个详情页的预览网格都包在带标题的 SectionCard 里",
)
check(
    emoji.idTab.detail.previewCard.headerLabel.text() == "表情预览"
    and dress.previewCard.headerLabel.text() == "内容预览",
    "预览卡标题分别为「表情预览」「内容预览」",
)

print("== 3. 多选行随勾选显隐 ==")
for tag, card, multi_btn, row in (
    ("表情包", emoji.allTab.commandCard, emoji.allTab.multiBtn, emoji.allTab.selectRow),
    ("收藏集", dress.searchCard, dress.multiBtn, dress.selectRow),
):
    check(not row.isVisible(), f"{tag}：默认不显示多选行")
    before = card.height()
    multi_btn.setChecked(True)
    settle()
    check(row.isVisible(), f"{tag}：勾选「多选」后多选行出现")
    check(
        card.height() > before,
        f"{tag}：命令卡随多选行变高（{before} -> {card.height()}）",
    )
    multi_btn.setChecked(False)
    settle()
    check(not row.isVisible(), f"{tag}：取消多选后多选行收起")
    check(
        card.height() == before,
        f"{tag}：命令卡高度复原（{card.height()} == {before}）",
    )

print("== 4. 详情头部卡：返回按钮在名称左侧 + set_package 后可用 ==")
detail = emoji.allTab.detail
back = emoji.allTab.backBtn
check(back.parent() is detail.headerCard, "「返回列表」按钮挂在详情头部卡上")
emoji.allTab.stacked.setCurrentWidget(emoji.allTab.detailPage)
detail.set_package(_Pkg(53, emotes=6))
settle()
check(back.geometry().right() <= detail.nameLabel.geometry().left(), "返回按钮在名称左侧")
check(detail.nameLabel.text() == "包53", f"名称已填充（实际 {detail.nameLabel.text()!r}）")
check("6 个表情" in detail.detailLabel.text(), f"元信息已填充（{detail.detailLabel.text()!r}）")
check(detail.downloadBtn.isEnabled(), "「下载到本地」可用")
check(detail.grid.count() == 6, f"预览网格填了 6 张（实际 {detail.grid.count()}）")

print("== 5. 收藏集详情：视频卡随视频有无显隐 ==")
check(isinstance(dress.videoCard, SimpleCardWidget), "视频区包在组件库卡片里")
dress._detail_summary = _Summary("测试收藏集")
dress.stacked.setCurrentWidget(dress.detailPage)
dress._show_detail(_Collection(videos=2))
settle()
check(dress.videoCard.isVisible(), "有视频：视频卡显示")
check("2 个" in dress.videoToggle.text(), f"视频数写进标题（{dress.videoToggle.text()!r}）")
check(not dress.videoList.isVisible(), "视频列表默认收起")
dress.videoToggle.click()
settle()
check(dress.videoList.isVisible(), "点标题展开视频列表")
dress._show_detail(_Collection(videos=0))
settle()
check(not dress.videoCard.isVisible(), "无视频：整卡隐藏")

print("== 6. 窄窗口不越界 + 下载页仍两列 ==")
# 隐藏的子页不会重新布局，几何会停留在上次可见时的尺寸 —— 先切回列表/搜索页
emoji.allTab.stacked.setCurrentWidget(emoji.allTab.listPage)
dress.stacked.setCurrentWidget(dress.searchPage)
settle()
for tag, page, card, widget in (
    ("表情包", emoji, emoji.allTab.commandCard, emoji.allTab.countLabel),
    ("收藏集", dress, dress.searchCard, dress.searchBtn),
    ("下载", dl, dl.commandCard, dl.downloadBtn),
):
    page.resize(600, 700)
    settle(8)
    check(page.width() == 600, f"{tag}：页面确实缩到 600（实际 {page.width()}，防量到过期几何）")
    right = widget.geometry().right()
    check(
        0 < right <= card.width(),
        f"{tag}：命令卡最右控件不越界（{right} <= {card.width()}）",
    )
    page.resize(1000, 760)
    settle(4)

dl.resize(980, 700)
settle(8)
r0 = dl.grid.visualItemRect(dl.grid.item(0))
r1 = dl.grid.visualItemRect(dl.grid.item(1))
check(
    r1.y() == r0.y(),
    f"下载页 980 宽仍是两列（y0={r0.y()} y1={r1.y()}，36 边距没把它挤回单列）",
)

print("== 7. 卡片背景随主题变化 ==")
light_alpha = dl.commandCard.backgroundColor.alpha()
setTheme(Theme.DARK)
wait_until(lambda: dl.commandCard.backgroundColor.alpha() != light_alpha)
dark_alpha = dl.commandCard.backgroundColor.alpha()
check(
    dark_alpha != light_alpha,
    f"切深色后命令卡背景重算（alpha {light_alpha} -> {dark_alpha}）",
)
setTheme(Theme.LIGHT)
wait_until(lambda: dl.commandCard.backgroundColor.alpha() == light_alpha)
check(dl.commandCard.backgroundColor.alpha() == light_alpha, "切回浅色后背景复原")

emoji.close()
dress.close()
dl.close()
download_queue.clear()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
