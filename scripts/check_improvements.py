"""屏幕外验证 6 项改进：亮暗主题重刷、队列响应式双列（实际 geometry + 滚动条）、
QueueCard 阴影修复与长名防裁剪、详情页入队/已加入/已下载状态同步、仅看收藏集默认勾选、
设置页按钮与侧栏宽度。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from qfluentwidgets import Theme, setTheme

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from app.common.theme import color_secondary
from app.components.download_queue import download_queue, item_key
from app.components.widgets import DressCard, QueueCard, QueueList

setTheme(Theme.LIGHT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class _FakeSummary:
    """DressCard/QueueCard 用的最小 DressCollectionSummary 替身。"""

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
    """表情包替身（EmotePackage 最小实现）。"""

    def __init__(self, pid: int) -> None:
        self.id = pid
        self.text = f"包{pid}"
        self.is_gif = False
        self.emote = []
        self.url = ""


class _FakeItem:
    def __init__(self, name: str) -> None:
        self.card_name = name
        self.card_img_download = ""
        self.video_list = []


class _FakeCollection:
    name = "测试收藏集"

    def __init__(self) -> None:
        self.item_list = [_FakeItem("图1"), _FakeItem("图2")]


print("== 1. 亮暗主题重刷（主题化 Label 颜色随 setTheme 变化） ==")
card = DressCard(_FakeSummary("测试收藏集"))
check("#000000" in card.nameLabel.styleSheet(), "LIGHT：DressCard.nameLabel 为主题化 Label 的黑色")
setTheme(Theme.DARK)
check("#ffffff" in card.nameLabel.styleSheet(), "切到 DARK 后 nameLabel 自动重刷为白色")
check(color_secondary() == "#9aa0a6", f"DARK 下 color_secondary 为 #9aa0a6（实际 {color_secondary()}）")
setTheme(Theme.LIGHT)
check("#000000" in card.nameLabel.styleSheet(), "切回 LIGHT 后 nameLabel 恢复黑色")

print("== 2. QueueList 响应式双列（实际 geometry + 滚动条 + 不溢出/不重叠） ==")


def make_items(n: int):
    return [_Pkg(i) for i in range(n)]


grid = QueueList()
grid.resize(900, 600)
grid.show()
grid.set_items(make_items(20))
app.processEvents()
app.processEvents()


def geometry_checks(g, tag: str, expect_cols: int) -> None:
    vpw = g.viewport().width()
    hmax = g.horizontalScrollBar().maximum()
    check(hmax == 0, f"{tag}: 无横向滚动条（max={hmax}）")
    r0 = g.visualItemRect(g.item(0))
    r1 = g.visualItemRect(g.item(1))
    r2 = g.visualItemRect(g.item(2))
    if expect_cols == 2:
        check(
            r1.y() == r0.y() and r2.y() > r0.y(),
            f"{tag}: 前两项同行、第三项换行（y0={r0.y()} y1={r1.y()} y2={r2.y()}）",
        )
    else:
        check(
            r1.y() > r0.y(),
            f"{tag}: 每行一项（y0={r0.y()} y1={r1.y()}）",
        )
    overflow = 0
    for i in range(g.count()):
        w = g.itemWidget(g.item(i))
        if w is None:
            continue
        r = g.visualItemRect(g.item(i))
        if r.right() > vpw or w.geometry().right() > vpw:
            overflow += 1
    check(overflow == 0, f"{tag}: 无横向溢出（视口宽 {vpw}，溢出 {overflow} 项）")
    overlap = 0
    for i in range(g.count() - 1):
        ri = g.visualItemRect(g.item(i))
        rj = g.visualItemRect(g.item(i + 1))
        if ri.y() == rj.y() and ri.x() + ri.width() > rj.x():
            overlap += 1
    check(overlap == 0, f"{tag}: 同行相邻项不重叠")


geometry_checks(grid, "宽 900", 2)
check(grid.count() == 20, "20 项全部入格")

grid.resize(420, 600)
app.processEvents()
app.processEvents()
geometry_checks(grid, "窄 420", 1)

print("== 3. QueueCard 阴影修复（选中背景类选择器限定自身，不级联子 label） ==")
qc = QueueCard(_FakeSummary("测试"))
qc.set_selectable(True)
qc.set_checked(True)
check("QueueCard {" in qc.styleSheet(), "选中态样式含类选择器限定（防文字区整块上色）")
qc.set_checked(False)
check("transparent" in qc.styleSheet(), "未选中态背景透明")

print("== 4. QueueCard 长名换行不裁剪、不被复选框遮挡 ==")
long_name = "这是一个特别长的收藏集名称用来验证换行不会溢出卡片边界" * 2  # 约 50 字符
qc2 = QueueCard(_FakeSummary(long_name))
qc2.setFixedSize(445, 112)
qc2.show()
app.processEvents()
check(
    qc2.nameLabel.height() >= qc2.nameLabel.sizeHint().height(),
    f"nameLabel 未裁剪（实际高 {qc2.nameLabel.height()} >= sizeHint {qc2.nameLabel.sizeHint().height()}）",
)
right = qc2.nameLabel.mapTo(qc2, qc2.nameLabel.rect().topRight()).x()
check(
    right <= qc2.checkBox.geometry().left(),
    f"nameLabel 右缘({right}) 在复选框左缘({qc2.checkBox.geometry().left()}) 左侧",
)

print("== 5. 收藏集详情页「加入下载/已加入/已下载」状态同步 ==")
from app.view import dress_page as dress_page_mod
from app.view.dress_page import DressPage

dress_page_mod.run_task = lambda *a, **k: None  # 禁用网络拉取
download_queue.clear()
page = DressPage()
page.show()
app.processEvents()
summary2 = _FakeSummary("同步测试收藏集")

page._open_detail(summary2)
check(page._detail_summary is summary2, "打开详情后 _detail_summary 已设置")
check(
    page.queueBtn.text() == "加入下载" and not page.queueBtn.isEnabled(),
    "打开详情即重置按钮为「加入下载」禁用（不继承上一个状态）",
)
page._show_detail(_FakeCollection())
check(
    page.queueBtn.text() == "加入下载" and page.queueBtn.isEnabled(),
    "拉取成功后按钮「加入下载」可用",
)
page.queueBtn.click()
check(download_queue.contains(summary2), "点击后已加入队列")
check(
    page.queueBtn.text() == "已加入" and not page.queueBtn.isEnabled(),
    "加入后按钮「已加入」禁用",
)
page._go_back()
check(page._detail_summary is None, "返回后 _detail_summary 清空")
page._open_detail(summary2)
page._show_detail(_FakeCollection())
check(
    page.queueBtn.text() == "已加入" and not page.queueBtn.isEnabled(),
    "已在队列再进详情：按钮「已加入」禁用",
)
download_queue.remove([item_key(summary2)])
check(
    page.queueBtn.text() == "加入下载" and page.queueBtn.isEnabled(),
    "队列移除后按钮恢复「加入下载」可用",
)
# 收藏集已下载状态
orig_coll_dir = dress_page_mod.collection_download_dir
coll_tmp = Path(tempfile.mkdtemp(prefix="biliemoji_coll_"))
coll_folder = coll_tmp / "测试收藏集"
try:
    dress_page_mod.collection_download_dir = lambda s: coll_folder
    page._show_detail(_FakeCollection())
    check(not page.downloadedLabel.isVisible(), "无目录：不显示「已下载过」")
    coll_folder.mkdir(parents=True, exist_ok=True)
    (coll_folder / "a.png").write_bytes(b"x")
    page._show_detail(_FakeCollection())
    check(page.downloadedLabel.isVisible(), "目标目录非空：显示「已下载过」")
finally:
    shutil.rmtree(coll_tmp, ignore_errors=True)
    dress_page_mod.collection_download_dir = orig_coll_dir

print("== 6. 表情包详情页「加入下载/已加入/已下载」状态同步 ==")
from app.components import package_detail as pd_mod
from app.components.package_detail import PackageDetailView

download_queue.clear()
d = PackageDetailView()
d.show()
app.processEvents()
pkg = _Pkg(7)
d.set_package(pkg)
check(
    d.queueBtn.text() == "加入下载" and d.queueBtn.isEnabled(),
    "展示未入队表情包：按钮「加入下载」可用",
)
d.queueBtn.click()
check(download_queue.contains(pkg), "点击后已加入队列")
check(
    d.queueBtn.text() == "已加入" and not d.queueBtn.isEnabled(),
    "加入后按钮「已加入」禁用",
)
download_queue.remove([("pkg", 7)])
check(
    d.queueBtn.text() == "加入下载" and d.queueBtn.isEnabled(),
    "移除后按钮恢复「加入下载」可用",
)
# 表情包已下载状态
orig_pkg_dir = pd_mod.package_download_dir
pkg_tmp = Path(tempfile.mkdtemp(prefix="biliemoji_pkg_"))
pkg_folder = pkg_tmp / "包7 [7]"
try:
    pd_mod.package_download_dir = lambda p: pkg_folder
    check(not d.downloadedLabel.isVisible(), "无目录：不显示「已下载过」")
    pkg_folder.mkdir(parents=True, exist_ok=True)
    (pkg_folder / "a.png").write_bytes(b"x")
    d._refresh_downloaded()
    check(d.downloadedLabel.isVisible(), "目标目录非空：显示「已下载过」")
finally:
    shutil.rmtree(pkg_tmp, ignore_errors=True)
    pd_mod.package_download_dir = orig_pkg_dir

print("== 7. 仅看收藏集默认勾选 + 实时过滤 ==")
page2 = DressPage()
check(page2.onlyCollCheck.isChecked(), "「仅看收藏集」默认勾选")
col = _FakeSummary("收藏集A", collection=True)
dress = _FakeSummary("装扮B", collection=False)
page2._show_results([col, dress])
check(page2.grid.count() == 1, f"勾选状态下只显示收藏集（实际 {page2.grid.count()}）")
page2.onlyCollCheck.setChecked(False)
check(page2.grid.count() == 2, f"取消勾选后显示全部（实际 {page2.grid.count()}）")
page2.onlyCollCheck.setChecked(True)
check(page2.grid.count() == 1, "重新勾选只显示收藏集")

print("== 8. 设置页按钮 + 侧栏宽度 ==")
from app.view.setting_page import SettingPage

sp = SettingPage()
check(
    hasattr(sp, "openDirBtn") and sp.openDirBtn.text() == "打开下载文件夹",
    "设置页存在「打开下载文件夹」按钮",
)
from app.components import updater

updater.set_enabled(False)  # MainWindow 启动后会静默查一次新版本

from app.MainWindow import MainWindow

win = MainWindow()
panel = win.navigationInterface.panel
check(panel.expandWidth == 150, f"侧栏展开宽度 150（实际 {panel.expandWidth}）")
win.close()

print("== 9. 卡片「已下载」徽标 + 勾选框可同时显示（徽标右上、勾选框左上） ==")
from app.components import widgets as widgets_mod

badge_tmp = Path(tempfile.mkdtemp(prefix="biliemoji_badge_"))
done_folder = badge_tmp / "已下载的"
done_folder.mkdir(parents=True, exist_ok=True)
(done_folder / "a.png").write_bytes(b"x")
orig_coll = widgets_mod.collection_download_dir
orig_pkg = widgets_mod.package_download_dir
try:
    widgets_mod.collection_download_dir = lambda s: done_folder
    widgets_mod.package_download_dir = lambda p: done_folder
    for name, card in (
        ("DressCard", widgets_mod.DressCard(_FakeSummary("已下载的"))),
        ("PackageCard", widgets_mod.PackageCard(_Pkg(1))),
    ):
        card.setFixedSize(200, 260)
        card.show()
        app.processEvents()
        check(card.downloadedBadge.isVisible(), f"{name}: 目录非空 → 显示「已下载」徽标")
        card.set_selectable(True)
        app.processEvents()
        check(
            card.downloadedBadge.isVisible() and card.checkBox.isVisible(),
            f"{name}: 多选态下徽标与勾选框同时显示",
        )
        b = card.downloadedBadge.geometry()
        c = card.checkBox.geometry()
        check(
            c.right() < b.left(),
            f"{name}: 勾选框在左上({c.right()})、徽标在右上({b.left()})，互不遮挡",
        )
    widgets_mod.collection_download_dir = lambda s: badge_tmp / "不存在"
    undone = widgets_mod.DressCard(_FakeSummary("没下过"))
    undone.show()
    app.processEvents()
    check(not undone.downloadedBadge.isVisible(), "DressCard: 目录不存在 → 不显示徽标")
finally:
    shutil.rmtree(badge_tmp, ignore_errors=True)
    widgets_mod.collection_download_dir = orig_coll
    widgets_mod.package_download_dir = orig_pkg

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
