"""屏幕外验证设置页改版（Fluent 设置卡片版式）。

改版原则是「只改界面、不改功能」，所以本脚本一半断言在查**功能控件仍在且可用**，
另一半查新版式的几何与主题表现：

1. 功能控件属性名 / 类型 / 取值全部保留（槽函数逐字未改，靠它们工作）；
2. 三个分组 + 每组卡片数；
3. 下载目录副标题跟随 `dirEdit`（纯展示同步）；
4. 可展开卡片展开后变高；
5. 窄窗口下右侧控件不被裁（代理行最挤）；
6. 卡片随主题重刷 QSS + 主题下拉闭合态图标随主题重新取色；
7. 滚动区显式透明（FluentWindow 里不透明会在暗色下露 palette Base 色块）。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from qfluentwidgets import (
    ComboBox,
    ExpandSettingCard,
    LineEdit,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    Theme,
    setTheme,
)

from app.view.setting_page import SettingPage

setTheme(Theme.LIGHT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def _cards_of(group: SettingCardGroup) -> list:
    """分组里的设置卡。

    `ExpandLayout.count()` 只数 `addItem` 进来的 QLayoutItem，`addWidget` 走的是
    另一个列表（`expand_layout.py:15-32`），所以卡片数只能从子控件里数。
    """
    return [
        w
        for w in group.children()
        if isinstance(w, (SettingCard, ExpandSettingCard))
    ]


def wait_until(cond, timeout: float = 2.0) -> None:
    """轮询等待（展开是 200ms 属性动画，光 processEvents 不推进真实时间）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cond():
        settle(2)
        time.sleep(0.01)
    settle(2)


page = SettingPage()
page.resize(900, 760)
page.show()
settle()

print("== 1. 功能控件仍在（槽函数按属性名取用，改名即崩） ==")
NAMES = [
    "cookieEdit",
    "saveBtn",
    "verifyBtn",
    "dirEdit",
    "browseBtn",
    "openDirBtn",
    "protoCombo",
    "hostEdit",
    "portSpin",
    "threadSpin",
    "downloadSaveBtn",
    "themeCombo",
]
missing = [n for n in NAMES if not hasattr(page, n)]
check(not missing, f"12 个功能控件齐全（缺失 {missing}）")
check(isinstance(page.dirEdit, LineEdit), "dirEdit 仍是 LineEdit（_on_browse 读写 text）")
check(isinstance(page.protoCombo, ComboBox), "protoCombo 仍是组件库 ComboBox")
check(isinstance(page.portSpin, SpinBox) and isinstance(page.threadSpin, SpinBox), "端口 / 线程数仍是 SpinBox")
check(
    page.openDirBtn.text() == "打开下载文件夹",
    f"「打开下载文件夹」文案未变（实际 {page.openDirBtn.text()!r}）",
)
check(
    page.protoCombo.currentData() in ("http", "https"),
    f"protoCombo.currentData() 有值（实际 {page.protoCombo.currentData()!r}）",
)
check(page.protoCombo.count() == 2, f"代理协议两项（实际 {page.protoCombo.count()}）")
check(page.themeCombo.count() == 3, f"主题下拉三项（实际 {page.themeCombo.count()}）")
check(page.portSpin.value() > 0, f"端口有默认值（实际 {page.portSpin.value()}）")
check(1 <= page.threadSpin.value() <= 16, f"线程数在 1–16（实际 {page.threadSpin.value()}）")

print("== 2. 版式结构：四个分组 + 每组卡片数 ==")
groups = [w for w in page.scrollWidget.children() if isinstance(w, SettingCardGroup)]
check(len(groups) == 4, f"四个 SettingCardGroup（实际 {len(groups)}）")
titles = [g.titleLabel.text() for g in groups]
check(
    titles == ["账号", "下载", "缓存", "外观"],
    f"分组标题依次为 账号/下载/缓存/外观（实际 {titles}）",
)
# 顶部是居中的应用身份区（大图标 / 应用名 + 版本号），细节断言见 check_search_cache.py
check(page.titleLabel.text() == "BiliEmojiDD", "页面大标题为应用名")
# 身份区居中；分组标题与卡片左边缘仍对齐在 PAGE_MARGIN
# （Label 有组件库 QSS，setContentsMargins 会被忽略，缩进只能走布局边距）
logo_center = page.logoIcon.mapTo(page, page.logoIcon.rect().center()).x()
check(
    abs(logo_center - page.width() // 2) <= 2,
    f"logo 水平居中（{logo_center} vs {page.width() // 2}）",
)
group_x = groups[0].titleLabel.mapTo(page, groups[0].titleLabel.rect().topLeft()).x()
card_x = _cards_of(groups[0])[0].mapTo(page, page.rect().topLeft()).x()
check(group_x == card_x, f"分组标题 / 卡片左对齐（{group_x} / {card_x}）")
counts = [len(_cards_of(g)) for g in groups]
check(counts == [3, 4, 2, 1], f"每组卡片数 3/4/2/1（实际 {counts}）")

print("== 3. 下载目录副标题跟随 dirEdit ==")
page.dirEdit.setText("X:/tmp/biliemoji")
settle()
check(
    page.dirCard.card.contentLabel.text() == "X:/tmp/biliemoji",
    f"改路径后卡片副标题同步（实际 {page.dirCard.card.contentLabel.text()!r}）",
)

print("== 4. 可展开卡片能展开（Cookie / 下载目录） ==")
for name, card in (("Cookie", page.cookieCard), ("下载目录", page.dirCard)):
    # Cookie 卡在未配置 Cookie 时会自动展开，先收起再量收起态高度
    card.setExpand(False)
    wait_until(lambda c=card: not c.expandAni.state())
    folded = card.height()
    target = folded + card.viewLayout.sizeHint().height()
    card.setExpand(True)
    wait_until(lambda c=card, t=target: c.height() >= t)
    check(
        card.height() >= target,
        f"{name} 卡展开到位（{folded} -> {card.height()}，目标 {target}）",
    )
    card.setExpand(False)
    wait_until(lambda c=card, f=folded: c.height() <= f)
    check(card.height() == folded, f"{name} 卡收起复原（{card.height()} == {folded}）")

print("== 4b. 未填 Cookie 时默认展开（首次使用不用先找 ⌄） ==")
from app.common.config import cfg

fresh = SettingPage()
fresh.show()
settle()
check(
    fresh.cookieCard.isExpand == (not cfg.cookie.value.strip()),
    f"Cookie 卡展开态与「是否已配置 Cookie」一致（已配置={bool(cfg.cookie.value.strip())}，"
    f"展开={fresh.cookieCard.isExpand}）",
)
fresh.close()

print("== 5. 窄窗口下右侧控件不被裁（最小窗口 820 - 侧栏 150 - 页边距 72 ≈ 600） ==")
page.resize(600, 760)
settle(8)
for name, card, widget in (
    ("代理-端口", page.proxyCard, page.portSpin),
    ("线程数", page.threadCard, page.threadSpin),
    ("保存下载设置", page.saveDownloadCard, page.downloadSaveBtn),
    ("主题", page.themeCard, page.themeCombo),
    ("验证", page.verifyCard, page.verifyBtn),
):
    right = widget.geometry().right()
    check(
        0 < right <= card.width(),
        f"{name}：控件右边缘 {right} 未超出卡片宽 {card.width()}",
    )
check(
    page.proxyCard.width() <= page.scrollArea.viewport().width(),
    f"代理卡未横向溢出视口（卡 {page.proxyCard.width()} / 视口 {page.scrollArea.viewport().width()}）",
)
# 右边缘不越界还不够：文字列的最小宽度会把控件顶出去，两者可能重叠
for name, card, label, widget in (
    ("代理", page.proxyCard, page.proxyCard.contentLabel, page.protoCombo),
    ("线程数", page.threadCard, page.threadCard.contentLabel, page.threadSpin),
    ("主题", page.themeCard, page.themeCard.contentLabel, page.themeCombo),
):
    gap = widget.geometry().left() - label.mapTo(card, label.rect().topRight()).x()
    check(gap > 0, f"{name}：副标题与右侧控件不重叠（间距 {gap}px）")
page.resize(900, 760)
settle()

print("== 6. 主题：卡片 QSS 随主题重刷 + 下拉图标重新取色 ==")
light_qss = page.proxyCard.styleSheet()
check(bool(light_qss.strip()), "设置卡已注册组件库 QSS（裸控件拿不到任何 QSS）")
check(not page.themeCombo.icon().isNull(), "闭合态图标非空（ComboBox 自身只 setText 不 setIcon）")
light_key = page.themeCombo.icon().cacheKey()
setTheme(Theme.DARK)
settle()
check(page.proxyCard.styleSheet() != light_qss, "切深色后设置卡 QSS 已重刷")
check(
    page.themeCombo.icon().cacheKey() != light_key,
    "切深色后下拉图标重新取色（FluentIcon 按调用瞬间主题取黑/白 svg）",
)
setTheme(Theme.LIGHT)
settle()

print("== 7. 滚动区显式透明（FluentWindow 里不透明会露 palette Base 色块） ==")
qss = page.scrollArea.styleSheet()
check("transparent" in qss, "ScrollArea 背景透明")
check("border:none" in qss.replace(" ", ""), "ScrollArea 无边框")

page.close()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
