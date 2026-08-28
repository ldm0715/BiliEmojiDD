"""屏幕外验证下载体验四项优化 + 收藏集队列去重键修复。

1. 无 GIF 的表情包详情页不显示「下载动图 (GIF)」整行；
2. 下载队列卡片显示内容数量（缓存 / 同步推导 / 读取中 / 未知四态）；
3. 全部成功（含 SKIPPED）的项自动移出队列，有失败的留下；
4. 缩略图未到位时显示组件库加载环，图到位 / 无封面 / 加载失败即收环；
5. 同一 dlc 活动的不同期（act 相同、lottery 不同）是不同队列项，不被误去重。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_download_improvements.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from biliemoji import DownloadResult, DownloadStatus
from qfluentwidgets import Theme, setTheme

from app.components.content_meta import ContentMeta, content_meta
from app.components.download_queue import download_queue, item_key
from app.components.download_runner import BatchReport, ItemOutcome, _collect_outcomes
from app.components.package_detail import PackageDetailView
from app.components.widgets import DressCard, PackageCard, QueueCard, QueueList
from app.view.download_page import DownloadPage

setTheme(Theme.LIGHT)
# 假数据不能真去请求 B 站：一个假 ID 排一个 15s 超时任务，脚本会卡着退不出去
content_meta.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


class _Emote:
    def __init__(self, text: str, *, gif: bool = False) -> None:
        self.text = text
        self.url = f"https://fake/{text}.png"
        self.gif_url = f"https://fake/{text}.gif" if gif else None


class _Pkg:
    """EmotePackage 替身。"""

    def __init__(self, pid: int, *, emotes=(), gif_pkg: bool = False) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = gif_pkg
        self.emote = list(emotes)
        self.url = ""


class _Summary:
    """DressCollectionSummary 替身：act/lottery 走 properties（真实数据就是字符串）。"""

    def __init__(self, name: str, act: str, lot: str) -> None:
        self.name = name
        self.image_cover = ""
        self.sale_bp_forever = 6.0
        self.raw = {
            "item_id": int(act),  # 真实接口里 item_id == dlc_act_id
            "properties": {
                "type": "dlc_act",
                "dlc_act_id": act,
                "dlc_lottery_id": lot,
            },
        }


print("== 1. 无 GIF 的包不显示「下载动图 (GIF)」 ==")
detail = PackageDetailView()
detail.show()
settle()

static_pkg = _Pkg(1, emotes=[_Emote("a"), _Emote("b")])
detail.set_package(static_pkg)
settle()
check(not detail.gifRow.isVisible(), "静态包：GIF 选项整行隐藏")
check(not detail.gifCheck.isChecked(), "静态包：GIF 勾选强制取消（下载走 PNG）")

gif_pkg = _Pkg(2, emotes=[_Emote("c", gif=True), _Emote("d")], gif_pkg=True)
detail.set_package(gif_pkg)
settle()
check(detail.gifRow.isVisible(), "包内有 gif_url：GIF 选项整行显示")

detail.show_loading("加载中的包")
settle()
check(not detail.gifRow.isVisible(), "切到加载态：不继承上一个包的 GIF 行")

# 标了 GIF 包但没有任何 gif_url（meta.label_text 与实际取用不同步）
fake_gif = _Pkg(3, emotes=[_Emote("e")], gif_pkg=True)
detail.set_package(fake_gif)
settle()
check(
    not detail.gifRow.isVisible(),
    "is_gif 为真但无 gif_url：仍隐藏（判据是 emote.gif_url 而非 meta.label_text）",
)

print("== 2. 队列卡片内容数量 ==")
full_pkg = _Pkg(10, emotes=[_Emote(f"e{i}") for i in range(24)])
meta = content_meta.cached(full_pkg)
check(
    meta is not None and meta.images == 24 and meta.videos == 0,
    f"带完整 emote 的包同步推导出数量（实际 {meta}）",
)

card_full = QueueCard(full_pkg)
check(
    card_full.contentLabel.text() == "内容: 24 张图片",
    f"卡片显示表情数（实际「{card_full.contentLabel.text()}」）",
)

coll = _Summary("测试收藏集", "700", "701")
card_coll = QueueCard(coll)
check(
    card_coll.contentLabel.text() == "内容读取中…",
    f"未知内容：显示读取中（实际「{card_coll.contentLabel.text()}」）",
)
card_coll.set_content_meta(ContentMeta(12, 3))
check(
    card_coll.contentLabel.text() == "内容: 12 张图片 · 3 个视频",
    f"回填后显示图片 + 视频数（实际「{card_coll.contentLabel.text()}」）",
)
card_coll.set_content_meta(None)
check(
    card_coll.contentLabel.text() == "内容数量未知",
    f"取不到时显示未知（实际「{card_coll.contentLabel.text()}」）",
)

# remember() 会广播 contentMetaLoaded，队列列表按 key 回填对应卡片
download_queue.clear()
download_queue.add(coll)
qlist = QueueList()
qlist.resize(900, 600)
qlist.show()
qlist.set_items(download_queue.items())
settle()
content_meta.remember(coll, ContentMeta(9, 9))
settle()
listed = qlist.itemWidget(qlist.item(0))
check(
    listed.contentLabel.text() == "内容: 9 张图片 · 9 个视频",
    f"remember 广播后列表内卡片回填（实际「{listed.contentLabel.text()}」）",
)

print("== 3. 全部成功的项自动移出队列 ==")
dest = Path("F:/__fake_dl__")
pkg_dir = dest / "包20 [20]"
coll_dir = dest / "收藏集A"
owners = {pkg_dir: ("pkg", 20), coll_dir: ("coll", "dlc:1:2")}


def _result(target: Path, status: DownloadStatus) -> DownloadResult:
    return DownloadResult(url="https://fake", target=target, status=status)


results = (
    _result(pkg_dir / "a.png", DownloadStatus.SUCCESS),
    _result(pkg_dir / "b.png", DownloadStatus.SKIPPED),  # 已存在：算成功
    _result(coll_dir / "c.png", DownloadStatus.SUCCESS),
    _result(coll_dir / "d.mp4", DownloadStatus.FAILED),
    _result(dest / "_fetch_failed_9", DownloadStatus.FAILED),  # 不属于任何项
)
outcomes = _collect_outcomes(results, owners)
check(
    outcomes[("pkg", 20)].all_ok,
    f"SUCCESS + SKIPPED 全算成功（实际 {outcomes[('pkg', 20)]}）",
)
check(
    not outcomes[("coll", "dlc:1:2")].all_ok,
    f"含 FAILED 不算成功（实际 {outcomes[('coll', 'dlc:1:2')]}）",
)
check(
    not ItemOutcome().all_ok, "空结果（取详情失败 / 无可下文件）不算成功"
)
check(
    _collect_outcomes((), {pkg_dir: ("pkg", 20)})[("pkg", 20)].total == 0,
    "没有任何文件结果时 total 为 0",
)

download_queue.clear()
done_pkg = _Pkg(20, emotes=[_Emote("x")])
fail_coll = _Summary("收藏集A", "1", "2")
download_queue.add_many([done_pkg, fail_coll])
page = DownloadPage()
page.resize(900, 600)
page.show()
settle()
page._on_batch_result(
    BatchReport(results=results, elapsed=0.0, per_item=outcomes)
)
settle()
keys = [item_key(it) for it in download_queue.items()]
check(("pkg", 20) not in keys, "全部成功的表情包已自动移出队列")
check(item_key(fail_coll) in keys, "有失败的收藏集仍留在队列")
check(page.grid.count() == 1, f"列表随之重建为 1 项（实际 {page.grid.count()}）")

# 没有 per_item 的旧式结果不应炸
page._on_batch_result(object())
check(True, "结果对象无 per_item 时静默跳过，不抛异常")

print("== 4. 缩略图加载环 ==")
pm = QPixmap(8, 8)
pm.fill(QColor("#4c9"))

card = PackageCard(_Pkg(30))
card.setFixedSize(200, 200)
card.show()
settle()
check(card._spinner.isVisible(), "PackageCard: 建卡即显示加载环")
img = card.imageBtn.geometry()
center_ok = (
    abs(card._spinner.geometry().center().x() - img.center().x()) <= 1
    and abs(card._spinner.geometry().center().y() - img.center().y()) <= 1
)
check(center_ok, "加载环居中于图片区")
card.set_pixmap(pm)
settle()
check(not card._spinner.isVisible(), "PackageCard: 图片到位后收环")

dress_card = DressCard(_Summary("有封面的收藏集", "3", "4"))
dress_card.setFixedSize(200, 280)
dress_card.show()
settle()
check(dress_card._spinner.isVisible(), "DressCard: 建卡即显示加载环")
dress_card.thumb_done()
check(not dress_card._spinner.isVisible(), "thumb_done() 幂等收环（加载失败路径）")

# 无封面 URL 的卡片：网格建卡时立即收环（永远等不到 thumbLoaded/thumbRawFailed）
download_queue.clear()
no_cover = QueueList()
no_cover.resize(900, 600)
no_cover.show()
no_cover.set_items([_Pkg(31)])  # url 为空、emote 为空 → 无封面
settle()
blank = no_cover.itemWidget(no_cover.item(0))
check(not blank._spinner.isVisible(), "无封面地址的卡片建卡即收环，不空转")

print("== 5. 同活动不同期不被误去重（真实数据 item_id == dlc_act_id） ==")
a = _Summary("2233的MBTI-能量之源", "112667", "112709")
b = _Summary("2233的MBTI-ENFP", "112667", "113521")
check(item_key(a) != item_key(b), f"act 相同 lottery 不同 → 键不同（{item_key(a)} vs {item_key(b)}）")
download_queue.clear()
added = download_queue.add_many([a, b])
check(added == 2, f"两期都进队列（实际加入 {added} 个）")
check(
    download_queue.contains(b) and len(download_queue.items()) == 2,
    "contains 与队列内容一致（详情页「已加入」不再和列表打架）",
)
same = _Summary("2233的MBTI-ENFP", "112667", "113521")
check(not download_queue.add(same), "同 act 同 lottery 仍然去重")
download_queue.clear()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
