"""屏幕外验证主题切换三处修复：

1. 侧栏主题按钮点一次只切一次（曾因 clicked 被 connect 两遍，切了又切回等于没切）；
2. 设置页主题下拉闭合态显示图标，且图标随主题重新取色；
3. 网格容器（表情包 / 收藏集 / 详情 / 队列）随主题重刷 QSS。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

# 注意：必须等 app 模块导入完成后再 setTheme——config 导入会 qconfig.load 读取
# 配置文件里的 QFluentWidgets.ThemeMode（可能残留旧值），覆盖之前设置的主题
from qfluentwidgets import Theme, setTheme

from app.common.theme import is_dark
from app.components.widgets import PackageGrid

setTheme(Theme.LIGHT)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


print("== 1. 侧栏主题按钮：点一次切一次 ==")
from app.MainWindow import MainWindow

win = MainWindow()
win.show()
app.processEvents()

before = is_dark()
win.themeNavBtn.click()
app.processEvents()
check(is_dark() != before, f"点一次后主题翻转（{before} -> {is_dark()}）")
win.themeNavBtn.click()
app.processEvents()
check(is_dark() == before, f"再点一次翻回原主题（当前 {is_dark()}）")

# 直接数 clicked 的接收方个数：重复 connect 会让一次点击跑两遍 _toggle_theme
calls = []
win.themeNavBtn.clicked.connect(lambda *_: calls.append(1))
win.themeNavBtn.click()
app.processEvents()
check(len(calls) == 1, f"clicked 每次点击只发一次（实际 {len(calls)}）")

print("== 2. 设置页主题下拉：闭合态显示图标且随主题换色 ==")
sp = win.settingPage
check(sp.themeCombo.count() == 3, f"主题下拉三项（实际 {sp.themeCombo.count()}）")
check(not sp.themeCombo.icon().isNull(), "闭合态图标非空（ComboBox 自身只 setText 不 setIcon）")

# 一律经下拉切换：_on_theme_changed 会同时 setTheme + 写 cfg.theme，
# 直接调 setTheme 会让「生效主题」与 cfg.theme 脱节，后面的同步断言就不成立了
sp.themeCombo.setCurrentIndex(1)  # 浅色
app.processEvents()
check(not is_dark(), "下拉切到浅色已生效")
light_key = sp.themeCombo.icon().cacheKey()

sp.themeCombo.setCurrentIndex(2)  # 深色
app.processEvents()
check(is_dark(), "下拉切到深色已生效")
check(not sp.themeCombo.icon().isNull(), "切深色后闭合态图标仍非空")
check(
    sp.themeCombo.icon().cacheKey() != light_key,
    "切深色后图标已重新取色（FluentIcon 按调用瞬间主题取黑/白 svg）",
)

# 侧栏切主题 -> configChanged -> _sync_theme_combo（blockSignals 内需手动补图标）
win.themeNavBtn.click()  # 深色 -> 浅色
app.processEvents()
check(not is_dark(), "侧栏按钮把主题切回浅色")
check(
    sp.themeCombo.currentIndex() == 1,
    f"侧栏切换后下拉同步到浅色（实际 {sp.themeCombo.currentIndex()}）",
)
check(
    not sp.themeCombo.icon().isNull(),
    "_sync_theme_combo 的 blockSignals 块内也补上了图标",
)

print("== 3. 网格容器随主题重刷 QSS ==")
setTheme(Theme.LIGHT)
grid = PackageGrid()
grid.resize(800, 400)
grid.show()
app.processEvents()
light_qss = grid.styleSheet()
check(bool(light_qss.strip()), "网格已注册组件库 QSS（裸 QListWidget 拿不到任何 QSS）")
setTheme(Theme.DARK)
app.processEvents()
dark_qss = grid.styleSheet()
check(dark_qss != light_qss, "切主题后网格 QSS 已重刷（容器背景随主题变化）")
setTheme(Theme.LIGHT)
app.processEvents()
check(grid.styleSheet() != dark_qss, "切回浅色后网格 QSS 再次重刷")

win.close()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
