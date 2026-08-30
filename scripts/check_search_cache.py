"""屏幕外验证「搜索记录 + 磁盘缓存 + 应用标识」这一批改动。

1. `SearchHistory`：MRU 去重置顶、上限 10 条、删除/清空、JSON 持久化、namespace 隔离；
2. `SearchHistoryPanel`：浮层面板不占布局、点搜索框才下拉、失焦/移出收起、点记录发
   activated 并收起、× 只删一条、「清空」清全部；胶囊比搜索框矮且宽度不随悬停跳动；
3. `DiskCache`：put/get 往返、TTL 过期、超限按 mtime 淘汰最老的、clear 归零；
4. `api_cache`：第二次调用零网络请求，且重建出的对象字段与首次一致；
5. 三个搜索框：收藏集搜索 / 表情包 ID 查询 / 全部表情包过滤都挂了面板，且过滤改成
   回车或点放大镜才触发（不再是每敲一个字就重排）；
6. 设置页：logo + 应用名 + 版本号、「缓存」分组的上限 SpinBox 与清除按钮。

用法：QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_search_cache.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 隔离配置目录：APP_CONFIG_DIR 在 import 时按 APPDATA 计算，必须早于 app.* 的导入。
# 否则本脚本会读写用户真实的 config.json / search_history.json / 缓存目录。
_SANDBOX = tempfile.mkdtemp(prefix="biliEmojiDD-check-")
os.environ["APPDATA"] = _SANDBOX

from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from biliemoji.models import EmotePackage
from qfluentwidgets import (
    IconWidget,
    SearchLineEdit,
    SettingCardGroup,
    SpinBox,
    Theme,
    setTheme,
)

from app.common.config import APP_CONFIG_DIR, APP_VERSION, cfg
from app.components import api_cache
from app.components.content_meta import content_meta
from app.components.disk_cache import DiskCache, _digest
from app.components.search_history import (
    MAX_ITEMS,
    SearchHistory,
    SearchHistoryPanel,
    _HistoryChip,
)
from app.components.video_cache import video_cache
from app.view.dress_page import DressPage
from app.view.emoji_page import EmojiPage
from app.view.setting_page import SettingPage

setTheme(Theme.LIGHT)
content_meta.set_enabled(False)  # 假 ID 会排一堆 15s 超时请求把脚本挂住
video_cache.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def wait_until(cond, timeout: float = 2.0) -> bool:
    """轮询等待。属性动画要走真实时间，光 processEvents() 不推进时钟。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        settle()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


def wait_open(panel) -> None:
    """等展开动画真正跑完——只等 height>0 会量到动画中间帧。"""
    wait_until(
        lambda: panel.isVisible()
        and panel._ani.state() != QAbstractAnimation.State.Running
    )


def focus_in(widget) -> None:
    """离屏平台窗口不激活，setFocus 未必发 FocusIn——直接投递事件更稳。"""
    widget.setFocus()
    app.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn))


def focus_out(widget) -> None:
    app.sendEvent(widget, QFocusEvent(QEvent.Type.FocusOut))


def chips(panel: SearchHistoryPanel) -> list[_HistoryChip]:
    """当前排在面板里的胶囊（已从布局摘掉、等待 deleteLater 的不算）。"""
    out = []
    for i in range(panel._flow.count()):
        widget = panel._flow.itemAt(i).widget()
        if isinstance(widget, _HistoryChip):
            out.append(widget)
    return out


print("配置沙箱:", APP_CONFIG_DIR)
check(str(APP_CONFIG_DIR).startswith(_SANDBOX), "APP_CONFIG_DIR 指向临时沙箱（未碰真实配置）")

# ---------------------------------------------------------------- 1. SearchHistory
print("\n[1] SearchHistory 持久化与 MRU")
hist = SearchHistory("t1")
hist.clear()
for word in ("a", "b", "c"):
    hist.add(word)
check(hist.items() == ["c", "b", "a"], "新记录排在最前")
hist.add("a")
check(hist.items() == ["a", "c", "b"], "重复关键词去重后置顶，不新增一条")
hist.add("   ")
check(len(hist.items()) == 3, "空白关键词不入库")
for i in range(12):
    hist.add(f"w{i}")
items = hist.items()
check(len(items) == MAX_ITEMS, f"上限 {MAX_ITEMS} 条")
check(items[0] == "w11" and "a" not in items, "新的挤掉最老的")
check(SearchHistory("t1").items() == items, "换实例读到同一份（已落盘）")
check(SearchHistory("t2").items() == [], "namespace 之间互不干扰")
hist.remove("w11")
check("w11" not in hist.items() and len(hist.items()) == MAX_ITEMS - 1, "remove 只删一条")
hist.clear()
check(hist.items() == [], "clear 清空")

# ---------------------------------------------------------------- 2. SearchHistoryPanel
print("\n[2] SearchHistoryPanel 浮层面板")
host = QWidget()  # 宿主窗口：面板会把自己挂到 edit.window() 上
host_box = QVBoxLayout(host)
edit = SearchLineEdit(host)
host_box.addWidget(edit)
host_box.addStretch(1)
panel = SearchHistoryPanel(edit, "bar")
panel.clearBtn.click()  # 清掉可能的历史残留
host.resize(600, 300)
host.show()
settle()
check(panel.parent() is host, "面板的父级是顶层窗口，不是搜索框所在的布局")
check(host_box.indexOf(panel) == -1, "面板不占任何布局位置")
check(panel.isHidden(), "无记录时不展开")

focus_in(edit)
settle()
check(panel.isHidden(), "没有记录时点搜索框也不弹面板")

panel.record("2233")
panel.record("初音")
settle()
check([c.text() for c in chips(panel)] == ["初音", "2233"], "胶囊按 MRU 顺序排列")

focus_in(edit)
wait_open(panel)
check(panel.isVisible(), "点搜索框后面板下拉")
open_h = panel.height()
check(open_h > 0, f"展开后有高度（{open_h}）")
# 小巧：单行记录的面板不该比搜索框高多少（一行胶囊 26 + 上下 8 内边距 = 42）
chip_h = chips(panel)[0].height()
check(chip_h <= edit.height(), f"胶囊比搜索框矮（{chip_h} <= {edit.height()}）")
check(open_h <= edit.height() + 16, f"单行面板不臃肿（{open_h} <= {edit.height() + 16}）")
check(panel.clearBtn.isVisible(), "「清空」按钮随记录出现")

picked: list[str] = []
panel.activated.connect(picked.append)
chips(panel)[1].click()
settle()
check(picked == ["2233"], "点胶囊发出 activated(该条文本)")
wait_until(lambda: panel.isHidden())
check(panel.isHidden(), "点记录后自动收起")

focus_in(edit)
wait_open(panel)
chip = chips(panel)[0]
width_idle = chip.sizeHint().width()
chip.closeBtn.show()  # 模拟悬停：× 出现
check(chip.sizeHint().width() == width_idle, "× 恒定占位，悬停时胶囊宽度不跳动")
check(chip.closeBtn.width() > 0, "× 按钮有实际尺寸")

chip.closeBtn.click()  # 删掉「初音」
settle()
check([c.text() for c in chips(panel)] == ["2233"], "× 只删自己那一条")

focus_out(edit)
wait_until(lambda: panel.isHidden())
check(panel.isHidden(), "搜索框失焦后收起")

focus_in(edit)
wait_open(panel)
panel.clearBtn.click()
settle()
check(chips(panel) == [] and panel.isHidden(), "「清空」清掉全部并收起面板")
check(panel.clearBtn.parent() is panel._content, "「清空」按钮没被 takeAllWidgets 误删")

# ---------------------------------------------------------------- 3. DiskCache
print("\n[3] DiskCache 落盘与淘汰")
LIMIT = 4096
limit_box = [1 << 30]  # 先给足额度，写完再收紧触发淘汰
disk = DiskCache("check_tmp", limit_fn=lambda: limit_box[0])
disk.clear()
disk.put("k1", b"hello")
check(disk.get("k1") == b"hello", "put/get 往返")
check(disk.get("nope") is None, "未命中返回 None")

disk.put("ttl", b"x" * 10)
ttl_path = disk._root / _digest("ttl")
os.utime(ttl_path, (time.time() - 100, time.time() - 100))
check(disk.get("ttl", ttl=10) is None, "超过 TTL 视为未命中")
check(not ttl_path.exists(), "过期文件顺手删掉")

disk.clear()
blob = b"z" * 1024
now = time.time() - 1000  # 拉到过去：newest 必须是 mtime 最大的那个
for i in range(8):  # 先写 8 KB，不触发淘汰
    disk.put(f"e{i}", blob)
    # mtime 是 LRU 时间戳，Windows 上连续写入可能落在同一毫秒，显式拉开时间差
    os.utime(disk._root / _digest(f"e{i}"), (now + i, now + i))
limit_box[0] = LIMIT  # 收紧到 4 KB，下一次 put 触发淘汰
disk.put("newest", blob)
size = disk.size()
check(size <= LIMIT, f"超限后淘汰到上限内（{size} <= {LIMIT}）")
check(disk.get("e0") is None, "最久没读到的先被淘汰")
check(disk.get("newest") == blob, "最新写入的保留")
disk.clear()
check(disk.size() == 0, "clear 归零")

# ---------------------------------------------------------------- 4. api_cache
print("\n[4] api_cache 二次调用零请求")
PKG_RAW = {
    "id": 53,
    "text": "测试表情包",
    "url": "",
    "emote": [{"id": 1, "text": "a", "url": ""}],
}
COLL_RAW = {"id": 9, "name": "测试收藏集", "item_list": []}
SUMMARY_RAW = {
    "id": "111",
    "part_id": 0,
    "name": "测试收藏集",
    "properties": {
        "type": "dlc_act",
        "dlc_act_id": "111",
        "dlc_lottery_id": "222",
        "image_cover": "",
    },
}
CALLS = {"emoji": 0, "dress": 0}


class _FakeEmoji:
    def __init__(self, **kwargs) -> None:
        pass

    def certain_emoji_typed(self, pid):
        CALLS["emoji"] += 1
        from biliemoji.models import EmotePackage

        return EmotePackage.from_dict(dict(PKG_RAW, id=int(pid)))


class _FakeDress:
    def __init__(self, **kwargs) -> None:
        pass

    def certain_lottery_typed(self, act_id, lottery_id):
        CALLS["dress"] += 1
        from biliemoji.models import DressCollection

        return DressCollection.from_dict(COLL_RAW)

    def search_dress_typed(self, num, keyword=""):
        CALLS["dress"] += 1
        from biliemoji.models import DressCollectionSummary

        return (DressCollectionSummary.from_dict(SUMMARY_RAW),)


# api_cache 走 app/common/net.py 的工厂建联网对象，所以打桩要打在工厂上
api_cache.make_emoji = lambda **kwargs: _FakeEmoji()
api_cache.make_dress = lambda **kwargs: _FakeDress()

pkg1 = api_cache.emoji_package(53)
pkg2 = api_cache.emoji_package(53)
check(CALLS["emoji"] == 1, "同一表情包第二次取用不再请求")
check(
    (pkg2.id, pkg2.text, len(pkg2.emote)) == (pkg1.id, pkg1.text, len(pkg1.emote)),
    "缓存重建的 EmotePackage 字段一致",
)

CALLS["dress"] = 0
coll1 = api_cache.dress_collection("111", "222")
coll2 = api_cache.dress_collection("111", "222")
check(CALLS["dress"] == 1, "同一收藏集详情第二次取用不再请求")
check(coll2.name == coll1.name, "缓存重建的 DressCollection 字段一致")

CALLS["dress"] = 0
res1 = api_cache.search_dress(30, "缓存关键词")
res2 = api_cache.search_dress(30, "缓存关键词")
check(CALLS["dress"] == 1, "同一关键词第二次搜索不再请求")
check(len(res2) == len(res1) and res2[0].name == res1[0].name, "缓存重建的搜索结果一致")
check(api_cache.search_dress(30, "另一个词") is not None and CALLS["dress"] == 2, "不同关键词各自请求")

# ---------------------------------------------------------------- 5. 三个搜索框
print("\n[5] 搜索页接线（浮层面板 + 触发时机）")
dress = DressPage()
dress.resize(1000, 760)
dress.show()
settle()
panel = dress.historyPanel
check(panel.parent() is dress.window(), "面板挂在顶层窗口上（浮在页面之上）")
check(dress.searchCard.vBoxLayout.indexOf(panel) == -1, "面板不在命令卡布局里")
check(panel.isHidden(), "初始不展开")

card_h_before = dress.searchCard.sizeHint().height()
panel.record("2233")
settle()
check(
    dress.searchCard.sizeHint().height() == card_h_before,
    "记录出现后命令卡高度不变（浮层不挤压其他控件）",
)
check(panel.isHidden(), "有记录也不自动展开，要点搜索框才出来")

focus_in(dress.kwEdit)  # 模拟点进搜索框
settle()
check(panel.isVisible(), "聚焦搜索框后面板展开")
wait_until(lambda: panel.geometry().height() > 0)
rect = panel.geometry()
edit_bottom = dress.kwEdit.mapTo(dress.window(), QPoint(0, dress.kwEdit.height())).y()
check(rect.top() >= edit_bottom, f"面板贴在搜索框下沿（{rect.top()} >= {edit_bottom}）")
check(rect.width() >= dress.kwEdit.width(), "面板宽度不窄于搜索框")
check(rect.height() > 0, "展开动画结束后有高度")

app.sendEvent(panel, QEvent(QEvent.Type.Leave))  # 鼠标移出
wait_until(lambda: panel.isHidden())
check(panel.isHidden(), "鼠标移出后收起")

focus_in(dress.kwEdit)
settle()
chips(panel)[0].click()  # → 回填 + 触发搜索（走 fake Dress）
settle()
check(dress.kwEdit.text() == "2233", "点胶囊回填关键词")
wait_until(lambda: panel.isHidden())
check(panel.isHidden(), "点记录后面板收起")
wait_until(lambda: dress.searchBtn.isEnabled() and dress.grid.count() > 0)
check(dress.grid.count() == 1, "点胶囊直接触发搜索并渲染结果")

emoji = EmojiPage()
emoji.resize(1000, 760)
emoji.show()
settle()
check(emoji.idTab.historyPanel.parent() is emoji.window(), "表情包 ID 查询也有浮层面板")
emoji.idTab.idEdit.setText("53")
emoji.idTab._on_query()
wait_until(lambda: emoji.idTab.queryBtn.isEnabled())
check(
    [c.text() for c in chips(emoji.idTab.historyPanel)] == ["53"], "查询后记下该 ID"
)
check(emoji.idTab.detail._pkg is not None, "查询结果已渲染（走缓存/假接口）")

print("\n[5.1] 全部表情包过滤：回车/放大镜才触发")
all_tab = emoji.allTab
all_tab._set_packages(
    tuple(
        EmotePackage.from_dict({"id": i, "text": f"包{i}", "url": ""})
        for i in range(1, 6)
    )
)
settle()
check(all_tab.grid.count() == 5, "拉取后 5 个包全部展示")
all_tab.filterEdit.setText("包3")  # 只改文本，不该立刻过滤
settle()
check(all_tab.grid.count() == 5, "输入过程中不过滤（不再是 textChanged 触发）")
all_tab.filterEdit.searchSignal.emit("包3")  # 点放大镜
settle()
check(all_tab.grid.count() == 1, "点放大镜后才过滤")
check(
    [c.text() for c in chips(all_tab.historyPanel)] == ["包3"], "过滤关键词记入历史"
)
all_tab.filterEdit.clearSignal.emit()  # 点 ×
settle()
check(all_tab.grid.count() == 5, "清空后恢复全部")
chips(all_tab.historyPanel)[0].click()
settle()
check(all_tab.filterEdit.text() == "包3" and all_tab.grid.count() == 1, "点记录重新过滤")

# ---------------------------------------------------------------- 6. 设置页
print("\n[6] 设置页身份头与缓存分组")
setting = SettingPage()
setting.resize(1000, 760)
setting.show()
settle()
check(setting.titleLabel.text() == "BiliEmojiDD", "大标题为应用名")
check(setting.versionLabel.text() == f"v{APP_VERSION}", f"版本号为 v{APP_VERSION}")
check(isinstance(setting.logoIcon, IconWidget), "顶部有 logo（IconWidget）")
logo_rect = setting.logoIcon.geometry()
title_top = setting.titleLabel.mapTo(setting, setting.titleLabel.rect().topLeft()).y()
logo_bottom = setting.logoIcon.mapTo(setting, setting.logoIcon.rect().bottomLeft()).y()
check(logo_bottom <= title_top, "logo 在第一行，应用名在第二行")
check(logo_rect.width() >= 48, f"logo 够大（{logo_rect.width()} >= 48）")
logo_cx = setting.logoIcon.mapTo(setting, setting.logoIcon.rect().center()).x()
name_left = setting.titleLabel.mapTo(setting, setting.titleLabel.rect().topLeft()).x()
name_right = setting.versionLabel.mapTo(
    setting, setting.versionLabel.rect().topRight()
).x()
name_cx = (name_left + name_right) // 2
page_cx = setting.width() // 2
check(abs(logo_cx - page_cx) <= 2, f"logo 水平居中（{logo_cx} vs {page_cx}）")
check(abs(name_cx - page_cx) <= 4, f"应用名 + 版本号整体居中（{name_cx} vs {page_cx}）")

groups = [w for w in setting.scrollWidget.children() if isinstance(w, SettingCardGroup)]
titles = [g.titleLabel.text() for g in groups]
check("缓存" in titles, f"存在「缓存」分组（当前分组：{titles}）")
check(isinstance(setting.cacheSpin, SpinBox), "缓存上限用 SpinBox")
check(setting.cacheSpin.value() == cfg.cache_limit_mb.value, "上限初值取自配置")
check(setting.cacheSpin.width() >= 130, "SpinBox 够宽（上下按钮约占 64px）")
setting.cacheSpin.setValue(256)
settle()
check(cfg.cache_limit_mb.value == 256, "改上限即时写入配置")
setting.clearCacheBtn.click()
for _ in range(200):
    settle()
    if setting.clearCacheBtn.isEnabled():
        break
    time.sleep(0.01)
check("已用" in setting.cacheUsageCard.contentLabel.text(), "占用文案在清除后刷新")

# ---------------------------------------------------------------- 收尾
print()
if FAILS:
    print(f"{len(FAILS)} 项失败：")
    for msg in FAILS:
        print("  - " + msg)
    sys.exit(1)
print("全部通过")
