"""屏幕外验证设置页改版（Fluent 设置卡片版式）。

改版原则是「只改界面、不改功能」，所以本脚本一半断言在查**功能控件仍在且可用**，
另一半查新版式的几何与主题表现：

1. 功能控件属性名 / 类型 / 取值全部保留（槽函数逐字未改，靠它们工作）；
2. 五个分组 + 每组卡片数；
3. 下载目录副标题跟随 `dirEdit`（纯展示同步）；
3b. **下载组即时生效**（没有「保存」按钮）：线程数 / 下载目录改完即落库、
   空目录回填、`commit_pending_edits()` 补写未失焦的编辑，以及 **cfg→UI 方向**
   （配置是关时页面必须显示关——现有断言全是反方向）；
4. 可展开卡片展开后变高；
5. 窄窗口下右侧控件不被裁（代理行最挤）；
6. 卡片随主题重刷 QSS + 主题下拉闭合态图标随主题重新取色；
7. 滚动区显式透明（FluentWindow 里不透明会在暗色下露 palette Base 色块）。

账号卡的登录态切换（未登录两个按钮 / 登录后只剩退出）由 `check_login.py` 第 6 节覆盖。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 隔离配置目录：本脚本构造 SettingPage，而账号卡会读 cfg 里的 cookie / 账号信息。
# 不隔离就会加载用户真实的 config.json——副标题长度随用户状态变、断言不再确定，
# 存过头像 URL 时还会真排一次缩略图请求把脚本拖住。
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliemoji-check-setting-")

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from qfluentwidgets import (
    ExpandSettingCard,
    LineEdit,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    Theme,
    qconfig,
    setTheme,
)

from app.common.config import APP_NAME, CONFIG_FILE, cfg
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
    "verifyBtn",
    "scanLoginBtn",
    "manualCookieBtn",
    "logoutBtn",
    "dirEdit",
    "browseBtn",
    "openDirBtn",
    "proxySwitch",
    "proxyEdit",
    "threadSpin",
    "themeCombo",
    "fontEngineCombo",
]
missing = [n for n in NAMES if not hasattr(page, n)]
check(not missing, f"{len(NAMES)} 个功能控件齐全（缺失 {missing}）")
check(isinstance(page.dirEdit, LineEdit), "dirEdit 仍是 LineEdit（_on_browse 读写 text）")
check(isinstance(page.proxyEdit, LineEdit), "proxyEdit 是 LineEdit（_current_proxy 读 text）")
check(isinstance(page.threadSpin, SpinBox), "线程数仍是 SpinBox")
check(
    page.openDirBtn.text() == "打开下载文件夹",
    f"「打开下载文件夹」文案未变（实际 {page.openDirBtn.text()!r}）",
)
check(
    page.proxyEdit.isEnabled() == page.proxySwitch.isChecked(),
    "地址框可编辑性跟随代理开关",
)
check(
    page.fontEngineCombo.currentData() in ("default", "freetype"),
    f"字体渲染下拉 currentData 有值（实际 {page.fontEngineCombo.currentData()!r}）",
)
check(page.themeCombo.count() == 3, f"主题下拉三项（实际 {page.themeCombo.count()}）")
check(1 <= page.threadSpin.value() <= 16, f"线程数在 1–16（实际 {page.threadSpin.value()}）")

print("== 1b. 「测试」按钮的加载环：转圈时不跳宽、环不压文字 ==")
btn = page.proxyTestBtn
page.proxySwitch.setChecked(True)
settle()
idle_w, idle_text = btn.width(), btn.text()
check(not btn.is_busy(), "初始不是忙碌态")
btn.set_busy(True)
settle()
ring = btn._ring
check(btn.is_busy() and not ring.isHidden(), "忙碌时加载环出现")
check(btn.width() == idle_w, f"按钮宽度不跳（空闲 {idle_w} / 忙碌 {btn.width()}）")
check(btn.rect().contains(ring.geometry()), f"环落在按钮内（{ring.geometry().getRect()}）")
check(not btn.isEnabled(), "忙碌时禁用，防重复点")
# 环右边缘与文字起点之间要有空隙——空格数按空格实际宽度算，写死会随字体压到文字上
fm = btn.fontMetrics()
prefix_w = fm.horizontalAdvance(btn.text()) - fm.horizontalAdvance(btn.text().lstrip())
text_left = max(6, (btn.width() - fm.horizontalAdvance(btn.text())) // 2) + prefix_w
gap = text_left - (ring.x() + ring.width())
check(gap > 0, f"环与文字不重合（间距 {gap}px）")
btn.set_busy(False)
settle()
check(
    not btn.is_busy() and ring.isHidden() and btn.text() == idle_text,
    f"复原：环收起、文案回到 {idle_text!r}（实际 {btn.text()!r}）",
)

print("== 2. 版式结构：五个分组 + 每组卡片数 ==")
groups = [w for w in page.scrollWidget.children() if isinstance(w, SettingCardGroup)]
check(len(groups) == 5, f"五个 SettingCardGroup（实际 {len(groups)}）")
titles = [g.titleLabel.text() for g in groups]
check(
    titles == ["关于", "账号", "下载", "缓存", "外观"],
    f"分组标题依次为 关于/账号/下载/缓存/外观（实际 {titles}）",
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
check(
    counts == [5, 3, 3, 2, 3],
    f"每组卡片数 5/3/3/2/3（外观组 主题+字体渲染+滚动帧率）（实际 {counts}）",
)

print("== 3. 下载目录副标题跟随 dirEdit ==")
page.dirEdit.setText("X:/tmp/biliemoji")
settle()
check(
    page.dirCard.card.contentLabel.text() == "X:/tmp/biliemoji",
    f"改路径后卡片副标题同步（实际 {page.dirCard.card.contentLabel.text()!r}）",
)

print("== 3b. 下载组即时生效（没有「保存」按钮） ==")
# 先钉住「跑在隔离的配置目录里」——下面一堆「配置里应该是 X」的断言，
# 不确认这一点，结论可能是拿用户真实的 config.json 得出的
check(
    Path(CONFIG_FILE).parent.name == APP_NAME
    and Path(CONFIG_FILE).parent.parent == Path(os.environ["APPDATA"]),
    f"配置写在隔离目录里（{CONFIG_FILE}）",
)
check(
    not hasattr(page, "downloadSaveBtn") and not hasattr(page, "saveDownloadCard"),
    "「保存下载设置」卡片与按钮已删除",
)
check(not hasattr(page, "_on_save_download"), "保存槽 _on_save_download 已删除")

# cfg→UI 方向：现有断言全是「先 setChecked 再读 cfg」的单向，把初始化写成取反也照样全绿
qconfig.set(cfg.proxy_enabled, False)
qconfig.set(cfg.proxy, "")
fresh = SettingPage()
fresh.resize(900, 700)
fresh.show()
settle()
check(
    fresh.proxySwitch.isChecked() is cfg.proxy_enabled.value,
    f"开关初值跟随配置（开关 {fresh.proxySwitch.isChecked()} / 配置 {cfg.proxy_enabled.value}）",
)
check(fresh.proxySwitch.isChecked() is False, "配置为关时，新页面显示的就是关")
check(not fresh.proxyEdit.isEnabled(), "配置为关时地址框不可编辑")
check(
    "已关闭" in fresh.proxyCard.contentLabel.text(),
    f"配置为关时副标题说直连（实际 {fresh.proxyCard.contentLabel.text()!r}）",
)
fresh.close()

# 线程数：拨一下即落库。注意 SpinBox.setValue 只在值**真的变化**时才发 valueChanged，
# 所以断言必须换一个不同的值；顺手把这条 Qt 语义也钉住
qconfig.set(cfg.max_workers, 5)
page.threadSpin.setValue(3)
settle()
check(cfg.max_workers.value == 3, f"线程数改完即落库（{cfg.max_workers.value}）")
page.threadSpin.setValue(3)
settle()
check(cfg.max_workers.value == 3, "同值再设一次不发信号、也不落库（SpinBox 语义）")

# 下载目录：回车 / 失焦即落库
live_dir = str(Path(os.environ["APPDATA"]) / "dl-live")
page.dirEdit.setText(live_dir)
page.dirEdit.editingFinished.emit()  # = 回车 / 焦点移开
settle()
check(cfg.download_dir.value == live_dir, f"目录失焦即落库（{cfg.download_dir.value!r}）")

# 空目录：不落库 + 回填当前生效值（界面不许停在一个配置文件里没有的路径上）
page.dirEdit.setText("   ")
page.dirEdit.editingFinished.emit()
settle()
check(cfg.download_dir.value == live_dir, "空目录不落库（保持上一个值）")
check(
    page.dirEdit.text() == live_dir,
    f"空目录被回填成当前生效值（{page.dirEdit.text()!r}）",
)
check("不能为空" in page.dirCard.toolTip(), "目录卡 tooltip 写明空值会被回填")

# 「改了但没失焦」→ commit_pending_edits 补写（关窗那一路走的就是它）
pending_dir = str(Path(os.environ["APPDATA"]) / "dl-pending")
page.dirEdit.setText(pending_dir)
qconfig.set(cfg.proxy, "http://old.example:1")
page.proxySwitch.setChecked(True)
settle()
page.proxyEdit.setText("pending.example:9999")
# 这里**故意不**发 editingFinished：模拟「改完直接关窗」
page.commit_pending_edits()
settle()
check(cfg.download_dir.value == pending_dir, "关窗前补写了下载目录")
check(
    cfg.proxy.value == "http://pending.example:9999",
    f"关窗前补写了代理地址并规范化（{cfg.proxy.value!r}）",
)
raw = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
check(
    raw["Download"]["dir"] == pending_dir
    and raw["Download"]["proxy"] == "http://pending.example:9999",
    "补写是同步落盘的（配置原文里也是新值）",
)
page.proxySwitch.setChecked(False)  # 收尾，别把「开着」留给后面的版式断言
settle()

print("== 4. 可展开卡片能展开（下载目录） ==")
for name, card in (("下载目录", page.dirCard),):
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

print("== 5. 窄窗口下右侧控件不被裁（最小窗口 820 - 侧栏 150 - 页边距 72 ≈ 600） ==")
# 账号头像未登录时是隐藏的，这里先让它显形——量的是「登录之后」那种最挤的排布。
# 不显形就量不到它，等于漏测（隐藏控件的 geometry 是陈旧的，还会算出假重叠）。
page.avatar.setVisible(True)
page.resize(600, 760)
settle(8)
for name, card, widget in (
    ("代理-地址", page.proxyCard, page.proxyEdit),
    ("线程数", page.threadCard, page.threadSpin),
    ("主题", page.themeCard, page.themeCombo),
    ("验证", page.verifyCard, page.verifyBtn),
    ("扫码登录", page.loginCard, page.scanLoginBtn),
    ("手动填写", page.loginCard, page.manualCookieBtn),
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
    ("代理", page.proxyCard, page.proxyCard.contentLabel, page.proxyEdit),
    ("线程数", page.threadCard, page.threadCard.contentLabel, page.threadSpin),
    ("主题", page.themeCard, page.themeCard.contentLabel, page.themeCombo),
    # 账号卡右侧是「头像 + 按钮」两个控件，贴副标题最近的是头像
    ("登录账号", page.loginCard, page.loginCard.contentLabel, page.avatar),
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
