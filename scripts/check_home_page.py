"""屏幕外验证主页（欢迎页 + 功能入口引导）。

1. 版式：大标题「主页」与 36px 页边距对齐；滚动区显式透明；
2. 功能卡：三张卡标题正确，点击各自发出正确的 navigateRequested；
3. 英雄卡：主按钮随 Cookie 状态换文案与去向，状态行随队列/配置刷新；
   状态灯五态文案与配色（纯映射 + 写入记录后真的跟着变）；
4. 展示图：static/showcase 的图能读出来；素材缺失时整条缩略图带降级隐藏；
5. 响应式：宽/中/窄三档下功能卡列数为 3/2/1，且整页最小宽度不顶破最小窗口；
6. 滚轮能滚到底并停住；
7. 表情包页标签顺序（全部表情包在前且默认）与目标页公开入口
   EmojiPage.query_package_id / filter_packages、DressPage.search_keyword；
8. 滚动性能前提：图全走扁平化 ImageLabel（预缩放 + 预圆角 = 纯 blit）、
   一格滚轮的帧数被压到 12 且步数整除（见 page_scaffold.tune_scroll）；
9. 主题切换不崩。

用法：QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_home_page.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 隔离配置目录：APP_CONFIG_DIR 在 import 时按 APPDATA 计算，必须早于 app.* 的导入，
# 否则会写脏用户真实的 config.json / search_history.json
_SANDBOX = tempfile.mkdtemp(prefix="biliEmojiDD-home-")
os.environ["APPDATA"] = _SANDBOX

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from qfluentwidgets import ImageLabel, Theme, qconfig, setTheme

from app.common.config import cfg
from app.common.signal_bus import signal_bus
from app.common.theme import (
    DANGER_TEXT,
    ORANGE_TEXT,
    SECONDARY_TEXT,
    SUCCESS_TEXT,
)
from app.components import cookie_status
from app.components.content_meta import content_meta
from app.components.download_queue import download_queue
from app.components.page_scaffold import PAGE_MARGIN, SCROLL_DURATION, tune_scroll
from app.components.video_cache import video_cache
from app.view import dress_page as dress_mod
from app.view import emoji_page as emoji_mod
from app.view import home_page as home_mod
from app.view.dress_page import DressPage
from app.view.emoji_page import EmojiPage
from app.view.home_page import (
    NAV_DOWNLOAD,
    NAV_DRESS,
    NAV_EMOJI,
    NAV_SETTING,
    HomePage,
)

setTheme(Theme.LIGHT)
content_meta.set_enabled(False)  # 假数据会排一堆 15s 超时请求把脚本挂住
video_cache.set_enabled(False)
# 主页 showEvent 会触发一次 Cookie 检测：不关掉就会真发一个 nav 请求，
# 假 SESSDATA 只会排一个 10s 超时，把脚本挂在这里
cookie_status.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


class _Emote:
    text = "表情"
    url = ""
    gif_url = ""


class _Pkg:
    """最小可用的假表情包（队列去重只看 .id，卡片只读这几个字段）。"""

    def __init__(self, pid: int) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = [_Emote()]
        self.url = ""


def make_page() -> HomePage:
    page = HomePage()
    page.resize(1100, 800)
    page.show()
    settle()
    return page


# ---------------------------------------------------------------- 1. 版式
print("\n[版式]")
qconfig.set(cfg.cookie, "")
download_queue.clear()
page = make_page()

check(page.titleLabel.text() == "主页", "大标题为「主页」")
title_x = page.titleLabel.mapTo(page, QPoint(0, 0)).x()
check(title_x == PAGE_MARGIN, f"大标题与页边距对齐（x={title_x}，应为 {PAGE_MARGIN}）")
qss = page.scrollArea.styleSheet()
check("background:transparent" in qss, "滚动区显式透明（暗色下不露 Base 色块）")

# ---------------------------------------------------------------- 2. 功能卡跳转
print("\n[功能入口卡]")
titles = [card.titleLabel.text() for card in page.featureCards]
check(titles == ["表情包", "收藏集", "下载"], f"三张功能卡标题正确（{titles}）")

routes: list[str] = []
page.navigateRequested.connect(routes.append)
for card, expect in (
    (page.emojiCard, NAV_EMOJI),
    (page.dressCard, NAV_DRESS),
    (page.downloadCard, NAV_DOWNLOAD),
):
    routes.clear()
    card.clicked.emit()
    settle()
    check(routes == [expect], f"点「{card.titleLabel.text()}」卡 → {expect}（得到 {routes}）")

routes.clear()
page.emojiCard.enterBtn.click()
settle()
check(routes == [NAV_EMOJI], "点卡内「进入」按钮与点整卡等效")

# ---------------------------------------------------------------- 3. 英雄卡状态
print("\n[英雄卡]")
check(page.heroCard.primaryBtn.text() == "填写 Cookie", "无 Cookie 时主按钮为「填写 Cookie」")
routes.clear()
page.heroCard.primaryBtn.click()
settle()
check(routes == [NAV_SETTING], f"无 Cookie 时主按钮跳设置页（得到 {routes}）")
check("未配置" in page.heroCard.cookieLabel.text(), "状态行提示未配置 Cookie")

qconfig.set(cfg.cookie, "SESSDATA=x")
signal_bus.configChanged.emit()
settle()
check(page.heroCard.primaryBtn.text() == "开始使用", "配置 Cookie 后主按钮变「开始使用」")
routes.clear()
page.heroCard.primaryBtn.click()
settle()
check(routes == [NAV_EMOJI], f"有 Cookie 时主按钮跳表情包页（得到 {routes}）")
check("已配置" in page.heroCard.cookieLabel.text(), "状态行提示已配置 Cookie")

# ---- 状态灯：五态文案与配色（映射是纯函数，直接断言它，不从 QLabel 回读像素） ----
print("\n[Cookie 状态灯]")
_LIGHT_TEXT = {
    cookie_status.NO_COOKIE: ("● 未配置 Cookie", ORANGE_TEXT),
    cookie_status.CHECKING: ("● 正在检测 Cookie…", SECONDARY_TEXT),
    cookie_status.VALID: ("● Cookie 有效", SUCCESS_TEXT),
    cookie_status.INVALID: ("● Cookie 已失效", DANGER_TEXT),
    cookie_status.UNKNOWN: ("● Cookie 已配置（未验证）", SECONDARY_TEXT),
}
for state, (text, color) in _LIGHT_TEXT.items():
    got_text, got_color = home_mod.cookie_light(state)
    check(got_text == text, f"{state} 文案为「{text}」（得到「{got_text}」）")
    check(got_color == color, f"{state} 配色与该主题色对一致（{got_color}）")
check(
    home_mod.cookie_light("不认识的态") == home_mod.cookie_light(cookie_status.UNKNOWN),
    "认不出的状态退回「未验证」，不留空灯",
)

# 记录写下之后灯要跟着变（有 Cookie + 记录匹配指纹 → 有效/失效）
_ck = cfg.cookie.value
cookie_status.note(cookie_status.VALID, _ck)
settle()
check(
    page.heroCard.cookieLabel.text() == "● Cookie 有效",
    f"写入「有效」记录后灯变绿（得到「{page.heroCard.cookieLabel.text()}」）",
)
check(
    page.heroCard.cookieLabel.lightColor.name() == SUCCESS_TEXT[0],
    f"亮色档用的是 SUCCESS_TEXT（{page.heroCard.cookieLabel.lightColor.name()}）",
)
cookie_status.note(cookie_status.INVALID, _ck)
settle()
check(
    page.heroCard.cookieLabel.text() == "● Cookie 已失效",
    f"写入「失效」记录后灯变红（得到「{page.heroCard.cookieLabel.text()}」）",
)
check(
    page.heroCard.cookieLabel.lightColor.name() == DANGER_TEXT[0],
    f"亮色档用的是 DANGER_TEXT（{page.heroCard.cookieLabel.lightColor.name()}）",
)
check(page.heroCard.primaryBtn.text() == "开始使用", "失效时主按钮仍是「开始使用」（不改成去修复）")
routes.clear()
page.heroCard.primaryBtn.click()
settle()
check(routes == [NAV_EMOJI], f"失效时主按钮仍跳表情包页（得到 {routes}）")
cookie_status.invalidate()
settle()

download_queue.add(_Pkg(1))
settle()
check("1 项" in page.heroCard.queueLabel.text(), "英雄卡队列计数随入队刷新")
check("1 项" in page.queueCountLabel.text(), "下载卡队列计数随入队刷新")

# ---- 队列预览：实时显示前 4 项封面，不足 4 项就少显示 ----
check(page.queuePreview.visible_count() == 1, "队列 1 项时只显示 1 张封面")
for pid in range(2, 7):
    download_queue.add(_Pkg(pid))
settle()
check(page.queuePreview.visible_count() == 4, "队列 6 项时封面封顶 4 张")
check(page.queuePreview._moreLabel.text() == "+2", "多出来的项显示 +N")

download_queue.clear()
settle()
check("0 项" in page.queueCountLabel.text(), "清空队列后计数归零")
check(not page.queuePreview.isVisible(), "队列为空时预览条整体隐藏")
check(cfg.download_dir.value in page.heroCard.dirLabel.text(), "英雄卡显示下载目录")
check(page.heroCard.dirLabel.wordWrap(), "下载目录 Label 换行（否则顶高整页最小宽度）")

# ---------------------------------------------------------------- 4. 展示图
print("\n[展示图]")
if page.emojiStrip.count():
    first = page.emojiStrip.findChildren(ImageLabel)[0]
    check(not first.isNull(), "表情展示图能读出来")
    check(first.width() == home_mod._EMOJI_THUMB, "表情图按目标宽度缩放（方形）")
    check(page.dressStrip.count() > 0, "收藏集封面也有素材")
else:
    print("  skip static/showcase 为空，跳过素材断言（跑 scripts/fetch_showcase.py 生成）")

_real = home_mod.showcase_images
home_mod.showcase_images = lambda kind, limit=8: []
try:
    bare = make_page()
    check(not bare.emojiStrip.has_images(), "无素材时 has_images() 为假")
    check(not bare.emojiStrip.isVisible(), "无素材时表情缩略图带隐藏（降级不留空条）")
    check(not bare.dressStrip.isVisible(), "无素材时收藏集缩略图带隐藏")
    check(bare.emojiCard.isVisible(), "无素材时功能卡本身照常显示")
    bare.close()
finally:
    home_mod.showcase_images = _real

# 窄卡时按可用宽度减少显示张数（离散显隐，不改几何约束）。
# 独立构造一条不进任何布局的 strip：放进卡片里 resize 会立刻被父布局改回去。
if page.emojiStrip.count() > 1:
    strip = home_mod._ShowcaseStrip("emoji", width=home_mod._EMOJI_THUMB, ratio=1.0)
    strip.show()  # 未实现化的控件收不到 resizeEvent，_fit 不会跑
    settle()
    strip.resize(home_mod._EMOJI_THUMB, strip.height())
    settle()
    check(strip.visible_count() == 1, "极窄时只显示一张展示图")
    strip.resize(1000, strip.height())
    settle()
    check(strip.visible_count() == strip.count(), "变宽后全部展示图恢复显示")
    strip.deleteLater()

# ---------------------------------------------------------------- 5. 响应式
print("\n[响应式]")
for width, expect in ((1400, 3), (900, 2), (620, 1)):
    page.resize(width, 800)
    settle()
    check(
        page.feature_columns() == expect,
        f"宽 {width} → 功能卡 {expect} 列（得到 {page.feature_columns()}）",
    )
check(page.bottom_columns() == 1, "窄窗口时快速上手 / 关于收敛成单列")
min_w = page.minimumSizeHint().width()
check(min_w <= 760, f"整页最小宽度不顶破最小窗口（{min_w} <= 760）")

# ---------------------------------------------------------------- 6. 滚到底
print("\n[滚轮滚到底]")
page.resize(1000, 560)  # 内容明显高于视口，保证有可滚范围
settle()
scroll_bar = page.scrollArea.verticalScrollBar()
if scroll_bar.maximum() > 0:
    viewport = page.scrollArea.viewport()
    center = QPointF(viewport.width() / 2, viewport.height() / 2)
    for _ in range(6):  # 连滚几格，足够到底
        app.sendEvent(
            viewport,
            QWheelEvent(
                center,
                QPointF(viewport.mapToGlobal(center.toPoint())),
                QPoint(0, 0),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )
    # 等动画彻底跑完：定时器每 1000/fps ms 触发一次，要走真实时间
    deadline = time.time() + 2.0
    while time.time() < deadline:
        settle()
        time.sleep(0.02)
    check(
        scroll_bar.value() == scroll_bar.maximum(),
        f"滚轮能滚到底并停住（value={scroll_bar.value()} / max={scroll_bar.maximum()}）",
    )
else:
    print("  skip 当前尺寸下内容未溢出，无可滚范围")

# ---------------------------------------------------------------- 7. 目标页入口
print("\n[目标页公开入口]")
# 拦掉 run_task：这些入口会真的发起 B 站请求，屏幕外脚本既不该联网，
# 也会因为脚本先于 worker 退出而报「C++ object already deleted」假象。
# 两个页面都是 `from app.components.task import run_task`，patch 各自模块命名空间即可。
tasks: list[str] = []
emoji_mod.run_task = lambda *a, **kw: tasks.append("emoji")
dress_mod.run_task = lambda *a, **kw: tasks.append("dress")

emoji = EmojiPage()
emoji.resize(900, 700)
check(
    list(emoji.pivot.items) == ["all", "byId"],
    f"标签顺序为「全部表情包 → 按 ID 查询」（得到 {list(emoji.pivot.items)}）",
)
check(
    emoji.stackedWidget.indexOf(emoji.allTab) == 0,
    f"栈里 allTab 在第 0 位（得到 {emoji.stackedWidget.indexOf(emoji.allTab)}）",
)
check(
    emoji.stackedWidget.currentWidget() is emoji.allTab,
    "默认停在「全部表情包」（不再是一进去就空白的按 ID 查询）",
)
check(
    emoji.pivot.currentItem() is emoji.pivot.widget("all"),
    "Pivot 指示条同步落在「全部表情包」上",
)
emoji.filter_packages("热词")
settle()
check(emoji.stackedWidget.currentWidget() is emoji.allTab, "filter_packages 切到全部表情包页")
check(
    emoji.pivot.currentItem() is emoji.pivot.widget("all"), "Pivot 指示条同步到 all"
)
check(emoji.allTab.filterEdit.text() == "热词", "关键词已回填到过滤框")
check(emoji.allTab.grid.count() == 0, "未拉取全量时不擅自发起网络过滤")

tasks.clear()
emoji.query_package_id("53")
settle()
check(emoji.stackedWidget.currentWidget() is emoji.idTab, "query_package_id 切到按 ID 查询页")
check(
    emoji.pivot.currentItem() is emoji.pivot.widget("byId"), "Pivot 指示条同步到 byId"
)
check(emoji.idTab.idEdit.text() == "53", "ID 已回填")
check(tasks == ["emoji"], f"query_package_id 真的发起了查询（{tasks}）")
emoji.close()

dress = DressPage()
dress.resize(900, 700)
dress.stacked.setCurrentWidget(dress.detailPage)  # 模拟停在详情页
tasks.clear()
dress.search_keyword("2233")
settle()
check(dress.stacked.currentWidget() is dress.searchPage, "search_keyword 先回到搜索页")
check(dress.kwEdit.text() == "2233", "关键词已回填到搜索框")
check(tasks == ["dress"], f"search_keyword 真的发起了搜索（{tasks}）")
dress.close()

# ------------------------------------------------------- 8b. 滚动流畅度前提
print("\n[滚动性能]")
# 滚动流畅度的上限就是单帧重绘耗时 × 一格滚轮摊开的帧数，这里守住这两个前提。
labels = page.findChildren(home_mod._FlatImageLabel)
check(len(labels) > 0, f"主页的图都用扁平化 ImageLabel（{len(labels)} 个）")
check(
    not page.findChildren(ImageLabel, options=Qt.FindChildOption.FindChildrenRecursively)
    or all(isinstance(lb, home_mod._FlatImageLabel) for lb in page.findChildren(ImageLabel)),
    "没有漏网的上游 ImageLabel（它每帧都要组圆角路径 + 抗锯齿裁剪）",
)
check(
    home_mod._FlatImageLabel.paintEvent is not ImageLabel.paintEvent,
    "扁平化 ImageLabel 走自己的 paintEvent（纯 blit，不裁剪不缩放）",
)
sized = [lb for lb in labels if not lb._flat.isNull()]
check(bool(sized), f"至少有一张图真的画上了（{len(sized)}/{len(labels)}）")
check(
    all(
        lb._flat.size() == lb.size() * lb._flat.devicePixelRatio()
        for lb in sized
    ),
    "预处理图恰好是 size*dpr —— 绘制时是恒等 blit，没有隐藏的缩放",
)
if page.emojiStrip.count():
    # 圆角是烤进 alpha 的，不是画的时候裁的：左上角像素必须是透明的
    corner = page.emojiStrip._labels[0]._flat.pixelColor(0, 0)
    check(corner.alpha() == 0, f"圆角已合成进 alpha（左上角 alpha={corner.alpha()}）")

smooth = page.scrollArea.scrollDelagate.verticalSmoothScroll
steps = smooth.fps * smooth.duration / 1000
check(
    smooth.duration == SCROLL_DURATION,
    f"主页滚动区已调过平滑时长（{smooth.duration}ms，上游默认 400ms）",
)
check(
    steps == int(steps),
    f"一格滚轮的步数是整数（{steps}）——否则队列永远减不到 0，定时器不停",
)
check(steps <= 12, f"一格滚轮不超过 12 帧（当前 {steps:.0f}，上游默认 24）")
try:
    tune_scroll(page.scrollArea, 130)  # 60*130/1000 = 7.8，非整数
except ValueError:
    check(True, "非整除的时长被挡下（否则滚动队列永不清空）")
else:
    check(False, "非整除的时长应当抛 ValueError")
finally:
    tune_scroll(page.scrollArea)  # 恢复

# ---------------------------------------------------------------- 9. 主题
print("\n[主题]")
setTheme(Theme.DARK)
settle()
check(page.isVisible(), "切暗色后主页存活")
check(page.heroCard.primaryBtn.text() == "开始使用", "切主题不影响按钮状态")
setTheme(Theme.LIGHT)
settle()

page.close()

# ---------------------------------------------------------------- 收尾
print()
if FAILS:
    print(f"{len(FAILS)} 项失败：")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("全部通过")
