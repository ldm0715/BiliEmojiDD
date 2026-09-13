"""屏幕外验证「直播间专属表情」：解析口径 / 队列第三类 / 内容数量 / 目录命名 / 页面。

1. `parse_emoticons` 只留 `room_<room_id>_` 前缀的表情，保序、去重、URL 归一成 https、
   `is_dynamic` 与 `.gif` 后缀两条 GIF 判据；
2. `data` 的三种形状（按包分组 / 直接列表 / 空）都能解析；
3. `set_enabled(False)` 后一个请求都不发（抛 `LiveEmojiDisabled`）；
4. 队列判别：`item_kind` / `item_key` / `item_cover_url` 走 live 分支，且与表情包 /
   收藏集的键不撞车（三类型混队互不覆盖）；
5. `content_meta.cached` 对 live 项零请求同步得出图片数；
6. `live_download_dir` 与 `download_live_batch` 建出的目录**完全同名**（徽标判定依赖它）；
7. `_collect_outcomes` 把该目录的文件结果归到 `("live", room_id)`；
8. `QueueCard` 渲染 live 项；`_LiveEmoteTab` 拉取 / 空态 / 入队 / 出队回流。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_live_emoji.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 隔离配置目录：APP_CONFIG_DIR 在 import 时按 APPDATA 计算，必须早于 app.* 的导入，
# 否则会写脏用户真实的 config.json（下载目录也在里面，断言会跟着用户状态变）
_SANDBOX = tempfile.mkdtemp(prefix="biliEmojiDD-live-")
os.environ["APPDATA"] = _SANDBOX

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from biliemoji import DownloadResult, DownloadStatus
from qfluentwidgets import Theme, setTheme

from app.components import api_cache, download_runner, live_emoji
from app.components.content_meta import ContentMeta, content_meta
from app.components.download_queue import (
    download_queue,
    item_cover_url,
    item_key,
    item_kind,
)
from app.components.download_runner import (
    _collect_outcomes,
    download_live_batch,
    live_download_dir,
    live_folder_name,
)
from app.components.live_emoji import LiveEmote, LiveEmotePack
from app.components.widgets import QueueCard
from app.view.emoji_page import EmojiPage

setTheme(Theme.LIGHT)
# 假 URL 不能真去请求 B 站：一个假地址排一个 15s 超时任务，脚本会卡着退不出去
content_meta.set_enabled(False)
live_emoji.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def preload(url: str) -> str:
    """假图预置 QPixmapCache：否则每个 URL 排一个 15s 超时的下载任务。"""
    pm = QPixmap(8, 8)
    pm.fill(QColor("#888888"))
    QPixmapCache.insert(url, pm)
    return url


# 本次实测响应里那个包的原文（只留断言用得到的字段），外加一个非本房间的表情包
ROOM_ID = "5236391"
FIXTURE = {
    "code": 0,
    "data": {
        "packages": [
            {
                "pkg_id": 142487,
                "pkg_name": "房间专属表情",
                "emoticons": [
                    {
                        "emoji": "墨镜猪",
                        "url": "http://i0.hdslb.com/bfs/live/e1e80a.png",
                        "is_dynamic": 0,
                        "emoticon_unique": "room_5236391_109772",
                    },
                    {
                        "emoji": "西装猪",
                        "url": "http://i0.hdslb.com/bfs/live/2612d3.png",
                        "is_dynamic": 0,
                        "emoticon_unique": "room_5236391_109774",
                    },
                    {
                        "emoji": "重复项",
                        "url": "http://i0.hdslb.com/bfs/live/2612d3.png",
                        "is_dynamic": 0,
                        "emoticon_unique": "room_5236391_109774",
                    },
                ],
            },
            {
                "pkg_id": 1,
                "pkg_name": "全局表情",
                "emoticons": [
                    {
                        "emoji": "不是本房间的",
                        "url": "http://i0.hdslb.com/bfs/live/other.png",
                        "is_dynamic": 0,
                        "emoticon_unique": "official_233",
                    },
                    {
                        "emoji": "房间号前缀只差一位",
                        "url": "http://i0.hdslb.com/bfs/live/x.png",
                        "is_dynamic": 0,
                        "emoticon_unique": "room_52363911_1",
                    },
                ],
            },
        ],
        # 这个键名不是 emoticons，遍历时不会收下它的元素
        "recently_used_emoticons": [
            {
                "emoji": "最近用过",
                "url": "http://i0.hdslb.com/bfs/live/r.png",
                "emoticon_unique": "room_5236391_9",
            }
        ],
    },
}

print("== 1. 解析口径：只留本房间、保序去重、URL 归一、GIF 两判据 ==")
emotes = live_emoji.parse_emoticons(FIXTURE, ROOM_ID)
check(len(emotes) == 2, f"只留 room_ 前缀的 2 个（实际 {len(emotes)}）")
check(
    [e.text for e in emotes] == ["墨镜猪", "西装猪"],
    f"保持接口里的顺序（实际 {[e.text for e in emotes]}）",
)
check(
    all(e.url.startswith("https://") for e in emotes),
    "http:// 的 hdslb CDN 地址已归一成 https",
)
check(
    all(e.unique.startswith("room_5236391_") for e in emotes),
    "unique 都是 room_5236391_ 前缀（room_52363911_ 不算）",
)
check(
    live_emoji.emote_is_gif("https://x/a.gif", 0) and live_emoji.emote_is_gif("https://x/a.png", 1),
    "GIF 判据取并集：.gif 后缀 或 is_dynamic",
)
check(
    not live_emoji.emote_is_gif("https://x/a.png", 0),
    "普通 png 不是 GIF",
)
check(
    live_emoji.normalize_url("https://i0.hdslb.com/a.png") == "https://i0.hdslb.com/a.png"
    and live_emoji.normalize_url("http://example.com/a.png") == "http://example.com/a.png",
    "已是 https 的原样返回，且不碰别的域名",
)
gif_em = LiveEmote("动图", preload("https://i0.hdslb.com/bfs/live/g.gif"), "u", True, {})
check(gif_em.ext() == ".gif", "目标后缀照 URL 原样（.gif）")
check(gif_em.expected_ext() == ".gif", "已知格式给出断言")
weird = LiveEmote("怪后缀", "https://i0.hdslb.com/bfs/live/a.apng", "u", True, {})
check(
    weird.expected_ext() is None,
    "认不出的后缀必须给 None，交给下载器嗅探（给错了会判 FAILED）",
)

print("== 2. data 形状 / 空结果 ==")
flat = {"data": [{"emoticons": FIXTURE["data"]["packages"][0]["emoticons"]}]}
check(len(live_emoji.parse_emoticons(flat, ROOM_ID)) == 2, "data 直接是列表也能解析")
check(live_emoji.parse_emoticons({"data": None}, ROOM_ID) == (), "data 为 None 返回空")
check(
    live_emoji.parse_emoticons(FIXTURE, "999") == (),
    "换一个 room_id 就什么都过滤不出来",
)
check(
    len(live_emoji.LiveEmotePack.from_dict(
        LiveEmotePack(ROOM_ID, "大东彦", "https://f.jpg",
                      emotes, ).to_dict()
    ).emotes) == 2,
    "缓存 to_dict / from_dict 无损",
)

print("== 3. set_enabled(False) 一个请求都不发 ==")
try:
    live_emoji.fetch_live_emotes(ROOM_ID)
    check(False, "关闭联网后仍发起了请求")
except live_emoji.LiveEmojiDisabled:
    check(True, "关闭联网后抛 LiveEmojiDisabled")
except Exception as exc:  # noqa: BLE001
    check(False, f"抛了别的异常：{exc!r}")

print("== 4. 队列第三类：判别与键不撞车 ==")
urls = [preload(f"https://i0.hdslb.com/bfs/live/{i}.png") for i in range(3)]
pack = LiveEmotePack(
    ROOM_ID,
    "大东彦",
    "",
    tuple(
        LiveEmote(f"表情{i}", u, f"room_{ROOM_ID}_{i}", False, {})
        for i, u in enumerate(urls)
    ),
)
check(item_kind(pack) == "live", "item_kind → live")
check(item_key(pack) == ("live", ROOM_ID), f'item_key → ("live", room_id)（实际 {item_key(pack)}）')
check(item_cover_url(pack) == urls[0], "封面取房间内第一张表情")


class _Emote:
    def __init__(self, text: str) -> None:
        self.text = text
        self.url = f"https://fake/{text}.png"
        self.gif_url = None


class _Pkg:
    def __init__(self, pid: int) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.url = None
        self.emote = (_Emote("a"),)
        self.raw = {}
        self.is_gif = False


class _Summary:
    def __init__(self, name: str, act: str, lottery: str) -> None:
        self.name = name
        self.image_cover = f"https://fake/{name}.png"
        self.sale_bp_forever = None
        self.raw = {"properties": {"type": "dlc_act", "dlc_act_id": act, "dlc_lottery_id": lottery}}


download_queue.clear()
pkg, coll = _Pkg(20), _Summary("收藏集A", "1", "2")
check(download_queue.add_many([pkg, coll, pack]) == 3, "三类项能同时入队")
keys = {item_key(it) for it in download_queue.items()}
check(len(keys) == 3, f"三个键互不相同（实际 {keys}）")
check(
    item_kind(pkg) == "package" and item_kind(coll) == "collection",
    "新增 live 分支没影响原有两类判别",
)
download_queue.clear()

print("== 5. 内容数量零请求 ==")
meta = content_meta.cached(pack)
check(
    meta == ContentMeta(3, 0),
    f"live 项同步得出 3 张图片（实际 {meta}）",
)
check(
    item_key(pack) in content_meta._cache,
    "已写进缓存（不会再排 _MetaTask）",
)
content_meta._cache.clear()

print("== 6. 目录命名：徽标判定与真正建目录必须同名 ==")
# 目标目录落在 APPDATA 沙箱里：download_live_batch 会真的 mkdir，别写用户盘
dest = Path(_SANDBOX) / "fake_live_dl"
name = live_folder_name(pack)
check(
    name == f"大东彦 [{ROOM_ID}]",
    f"目录名是「主播名 [room_id]」（实际 {name}）",
)
check(
    str(live_download_dir(pack)).endswith(name),
    "live_download_dir 用的是同一个名字",
)
# 建任务但不真下载：换掉下载器，只把「准备写进哪个目录」记下来
seen: list[Path] = []
_orig = download_runner.make_downloader


class _FakeDownloader:
    def download_many(self, tasks):
        seen.extend(t.target.parent for t in tasks)
        raise SystemExit  # 立刻中断，避免真联网


def _patched(**kwargs):
    return _FakeDownloader()


download_runner.make_downloader = _patched
try:
    download_live_batch([pack], dest)
except SystemExit:
    pass
finally:
    download_runner.make_downloader = _orig
check(bool(seen), "批量下载确实建了任务")
check(
    all(p == dest / name for p in seen),
    f"建目录与 live_download_dir 完全一致（实际 {sorted({str(p) for p in seen})}）",
)

print("== 7. 归属：结果按目录归回 live 键 ==")
owners = {dest / name: item_key(pack)}
results = (
    DownloadResult(url="u", target=dest / name / "a.png", status=DownloadStatus.SUCCESS),
    DownloadResult(url="u", target=dest / name / "b.gif", status=DownloadStatus.SKIPPED),
)
outcomes = _collect_outcomes(results, owners)
check(
    outcomes[item_key(pack)].all_ok,
    f"SUCCESS + SKIPPED 全算成功（实际 {outcomes[item_key(pack)]}）",
)
check(
    item_key(pack) in outcomes and len(outcomes) == 1,
    "结果只归到 live 这一项",
)

print("== 8. QueueCard 渲染 ==")
card = QueueCard(pack)
settle()
check(card.nameLabel.text() == "大东彦", f"名称取主播名（实际 {card.nameLabel.text()}）")
check(card.badgeLabel.text() == "直播间表情", f"徽标（实际 {card.badgeLabel.text()}）")
check(card.contentLabel.text() == "内容: 3 张图片", f"内容数量（实际 {card.contentLabel.text()}）")
blank = LiveEmotePack(ROOM_ID, "", "", ())
blank_card = QueueCard(blank)  # 必须留引用：临时对象会被 GC，控件随之析构
check(
    blank_card.nameLabel.text() == f"直播间 {ROOM_ID}",
    "拿不到主播名时退回「直播间 <room_id>」",
)

print("== 9. 页面：拉取 / 提示 / 入队 / 出队回流 ==")
api_cache.live_emotes = lambda room_id: pack
page = EmojiPage()
page.resize(900, 700)
page.show()
# 隐藏的 Tab 不参与布局，几何与文本断言前先切过去
page.pivot.setCurrentItem("live")
page.stackedWidget.setCurrentWidget(page.liveTab)
settle()

tab = page.liveTab
check(
    tab.nameLabel.text() == tab._EMPTY_NAME
    and tab.detailLabel.text() == tab._EMPTY_HINT
    and not tab.addBtn.isEnabled(),
    "初始态：详情卡写「尚未获取」+ 「加入下载」禁用",
)
check(len(tab.grid.items()) == 0, "初始态网格为空")

# 版式照「按 ID 查询」：命令卡里只有输入框 + 按钮，信息全在下面独立的详情卡里。
# 信息类文字挤在搜索行里，看着就是输入框的一部分
row_kids = [
    w
    for w in tab.commandCard.findChildren(QWidget)
    if w.isVisibleTo(tab) and w.parent() is tab.commandCard
]
check(
    row_kids == [tab.roomEdit, tab.fetchBtn],
    f"命令卡只有输入框 + 按钮（实际 {[type(w).__name__ for w in row_kids]}）",
)
check(
    tab.detailCard.mapTo(tab, QPoint(0, 0)).y() > tab.commandCard.mapTo(tab, QPoint(0, 0)).y(),
    "信息在命令卡**下方**的独立详情卡里",
)

tab.roomEdit.setText("abc")
tab._on_fetch()  # 非数字：本地拦掉，不发请求
settle()
check(tab.fetchBtn.isEnabled(), "非法 room_id 后获取按钮仍可用（不能永久禁用）")
check(not tab._loading, "非法 room_id 不算一次拉取")

tab.roomEdit.setText(ROOM_ID)
tab._on_fetch()
for _ in range(300):
    settle(1)
    if not tab._loading:
        break
check(not tab._loading, "拉取完成（_loading 在 on_finished 里收）")
check(tab.fetchBtn.isEnabled(), "拉取后获取按钮恢复可用")
check(tab.nameLabel.text() == "大东彦", f"主播名已填（实际 {tab.nameLabel.text()}）")
check(
    tab.detailLabel.text() == f"房间号: {ROOM_ID} · 3 个专属表情",
    f"详情行写房间号与数量（实际 {tab.detailLabel.text()}）",
)
check(len(tab.grid.items()) == 3, f"网格 3 项（实际 {len(tab.grid.items())}）")
check(tab.addBtn.isEnabled() and tab.addBtn.text() == "加入下载", "可加入下载")

tab.addBtn.click()
settle()
check(tab.addBtn.text() == "已加入" and not tab.addBtn.isEnabled(), "加入后变「已加入」并禁用")
check(len(download_queue) == 1, "队列里有一项")
check(download_queue.contains(pack), "队列内容就是该直播间")

download_queue.clear()
settle()
check(tab.addBtn.text() == "加入下载" and tab.addBtn.isEnabled(), "移除后按钮恢复")

# 空结果：同一个房间过滤后没有专属表情
api_cache.live_emotes = lambda room_id: LiveEmotePack(room_id, "某某", "", ())
tab.roomEdit.setText("12345678")
tab._on_fetch()
for _ in range(300):
    settle(1)
    if not tab._loading:
        break
check(
    "没有专属表情" in tab.detailLabel.text(),
    f"空态文案（实际 {tab.detailLabel.text()}）",
)
check(not tab.addBtn.isEnabled(), "空结果不给「加入下载」")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
