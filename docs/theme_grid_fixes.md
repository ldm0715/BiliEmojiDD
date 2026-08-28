# 主题跟随 + 网格铺满 + 已下载徽标（修复批次说明）

一批 UI 修复：主题切换的三个失效点、详情网格右侧大片空白、收藏集卡片长名被裁、「已下载」改用组件库徽标。本文记录每个问题的**根因定位过程**与最终实现，避免后续「修回去」。

前置阅读：[ui_polish.md](ui_polish.md)（上一批 UI 改进，本文是它的后续修复）。

## 一、背景

用户报告的问题，排查后是六个互相独立的根因：

1. 设置页主题下拉框**收起后只显示文字、不显示图标**。
2. 切主题时**表情包 / 收藏集的网格容器不跟随**，仍是旧主题底色。
3. **侧栏主题切换按钮点了完全没反应**。
4. 侧栏展开时主题按钮**没有文字**，只有一个图标。
5. 表情包 / 收藏集**详情页图片右侧留大片空白**。
6. 收藏集卡片**长名显示不出原文**；「已下载」提示是纯文字标签，希望用组件库徽标挂到卡片右上角。

修复原则（用户明确要求）：**组件库里有的组件就用组件库的，不自造控件、不手写 QSS 绕过主题机制。**

## 二、修改文件

| 文件 | 改动 |
|---|---|
| `app/MainWindow.py` | 删除重复的 `clicked.connect`；`NavigationToolButton` → `NavigationPushButton`（展开时显示「主题」） |
| `app/components/widgets.py` | `_CardGridBase` 基类 `QListWidget` → 组件库 `ListWidget`；`_cell_size()` 全部改为铺满整行；卡片加 `InfoBadge` 徽标、勾选框移左上角；`DressCard` 名称换行 + ToolTip |
| `app/view/setting_page.py` | `_sync_theme_icon()` + 三处调用 + `bind_theme` |
| `app/view/dress_page.py` | `videoList` → `ListWidget`；`videoToggle` `QToolButton` → `TransparentPushButton`；单个下载改走 `download_collection_batch`；`_refresh_downloaded` |
| `app/components/download_runner.py` | `download_collection_batch` 目录改按 `collection_download_dir(summary)` 命名 |
| `app/components/package_detail.py` | 「已下载过」`CaptionLabel` → `InfoBadge` |
| `scripts/check_theme_switch.py`（新） | 主题切换回归断言 |
| `scripts/check_improvements.py` | 新增第 9 组：卡片徽标 + 勾选框共存断言 |

## 三、功能与实现要点

### 1. 侧栏主题按钮点了没反应

`MainWindow.initNavigation` 里既手动 `themeNavBtn.clicked.connect(self._toggle_theme)`，又通过 `navigationInterface.addWidget(..., onClick=self._toggle_theme)` 接了一次——`NavigationPanel._registerWidget`（`navigation_panel.py:333-336`）会把 `onClick` 连到同一个 `clicked` 信号：

```python
widget.clicked.connect(self._onWidgetClicked)
if onClick is not None:
    widget.clicked.connect(onClick)
```

于是一次点击跑两遍 `_toggle_theme`：LIGHT→DARK→LIGHT，净效果为零，看起来像按钮完全失效。删掉手动那条即可。

按钮同时从 `NavigationToolButton(icon, parent)` 换成 `NavigationPushButton(icon, text, isSelectable, parent)`，侧栏展开时显示「主题」文字。

> `_update_theme_icon` 挂 `qconfig.themeChangedFinished` 是对的：`setTheme` 在 `style_sheet.py:401` **无条件**发这个信号（不像 `themeChanged` 会因 `item.value == value` 短路）。

### 2. 主题下拉框闭合态不显示图标

qfluentwidgets 上游行为，不是本项目 bug：`ComboBoxBase.setCurrentIndex`（`combo_box.py:123-142`）只 `setText` 从不 `setIcon`；`item.icon` 只在 `_showComboMenu`（`combo_box.py:301-302`）构建下拉菜单时用；`ComboBox.paintEvent`（`combo_box.py:398`）只画右侧箭头。库内**所有** ComboBox 变体（`EditableComboBox` / `AcrylicComboBox` / `ComboBoxSettingCard`）都一样。

`ComboBox` 继承 `QPushButton` 且 `paintEvent` 第一行就是 `QPushButton.paintEvent(self, e)`，所以**自己 `setIcon()` 就能画出来**，配合 combo_box.qss 的 `text-align:left` 图标落在文字左侧：

```python
def _sync_theme_icon(self) -> None:
    self.themeCombo.setIconSize(QSize(16, 16))
    self.themeCombo.setIcon(self.themeCombo.itemIcon(self.themeCombo.currentIndex()))
```

**调用点必须是三处**，缺一不可：

- `_build_theme_card` 末尾——首次 `addItem` 时库会自动 `setCurrentIndex(0)`（`combo_box.py:84-85`），之后再设同一索引会因 `index == self.currentIndex()` 提前 return（`combo_box.py:131`），`currentIndexChanged` 不发；
- `_on_theme_changed`——用户主动选择；
- `_sync_theme_combo` 的 `blockSignals` 块内——侧栏切主题后同步，信号被屏蔽，挂信号的方案收不到。

另外 `ComboItem.icon` 的 getter 是 `self._icon.icon()`（`combo_box.py:39-44`），`FluentIconBase.icon()` **按调用瞬间的主题**取黑/白 svg，所以主题切换后必须重新 `setIcon`。用现成的 `bind_theme(self, self._sync_theme_icon)` 绑定即可（立即执行一次 + 每次 `themeChangedFinished` 重执行，正好覆盖第一处调用点）。

### 3. 网格容器不跟随主题

`_CardGridBase` 继承的是 **PySide6 原生 `QListWidget`**，从没注册进 `styleSheetManager`，`setTheme()` → `updateStyleSheet()`（`style_sheet.py:371`）只遍历注册表，**完全跳过它**；它的视口背景只能靠 `QPalette`。而 qfluentwidgets 全库从不调 `QApplication.setPalette`——这正是 `app/common/theme.py` 存在的原因。

`theme.py::_apply_app_palette()` 确实会 `app.setPalette(...)` + `widget.update()`，但 `FluentWindow` 给 `stackedWidget` 套了 QSS（`fluent_window.py:37` `FluentStyleSheet.FLUENT_WINDOW.apply(self.stackedWidget)`），整棵子树由 `QStyleSheetStyle` 接管并缓存已解析的 palette，`update()` 只是用旧 palette 重画一遍。

**解法：换成组件库 `ListWidget`。** `ListBase.__init__`（`list_view.py:31-39`）里就有 `FluentStyleSheet.LIST_VIEW.apply(self)`，控件自动进注册表，此后每次主题切换都会被重刷。一处改动，`PackageGrid` / `DressGrid` / `EmojiGrid` / `DressDetailGrid` / `QueueList` 五个网格全部受益。

同页面的两个裸控件一并换掉：

- `dress_page.videoList`：`QListWidget` → `ListWidget`；
- `dress_page.videoToggle`：`QToolButton` + 手写 `setStyleSheet("QToolButton{border:none;...}")` → `TransparentPushButton` + `FluentIcon.CHEVRON_RIGHT` / `CHEVRON_DOWN_MED`（`setIcon` 替代 `setArrowType`）。

> 换基类的副作用：`ListBase` 会额外装 `ListItemDelegate` + `SmoothScrollDelegate` + `setMouseTracking(True)`。`SmoothScrollDelegate` 把原生滚动条置为 `AlwaysOff` 用浮层滚动条替代，`viewport().width()` 不再因滚动条出现而收窄。已用 `check_improvements.py` 的双列几何断言复核，无回归。

### 4. 详情页图片右侧大片空白

两个原因叠加，先用屏幕外脚本量出实际数字再动手（vw≈992）：

| 项目数 | 修复前右侧空白 | 修复后 |
|---|---|---|
| EmojiGrid 8/20/60 张 | 59px | 3px |
| DressDetailGrid 3 张 | 18px | 3px |
| DressDetailGrid 4 张 | 25px | 5px |
| DressDetailGrid 12 张 | 93px | 3px |
| DressDetailGrid 2 张 | 343px | 3px |

**原因一**：`_cell_size()` 按 `(vw - spacing*(列数-1)) // 列数` 算宽，但 **`QListView` 设了 `gridSize()` 后完全忽略 `spacing()`**——步进就是 `gridSize.width()`，于是每行白白少用 `spacing*(列数-1)` px。

**原因二**：`DressDetailGrid` 的卡片宽被高度压窄（`min(每格宽, 图高*3/4)`）之后，列数上限还卡死在 8，多出来的宽度全堆在最右侧。

改法：

- 单元格按 `(vw - _CARD_GUTTER) // 列数` 均分，`_CARD_GUTTER` 是换行余量；
- `DressDetailGrid` 列数上限从写死的 8 放开到「视口最多塞下几个最小卡」；
- 卡片受高度限制时**单元格仍取满整份宽度**，多余宽度变成每张图两侧的均匀留白（`QPushButton` 居中画图标），而不是全堆在最右侧；评分用**图片**面积而非单元格面积，避免选出一堆留白撑出来的假大格。

> **换行判据是 `列数 * cellW > 视口宽 - 1`**（`bounds.right()` 是闭区间）。算单元格宽时必须留余量，否则最后一列被挤到下一行、右侧反而空出一整格——修的过程中就踩过一次：`(vw-1)/c` 恰好整除时第 4 列被挤走，空白从 25px 涨到 249px。

### 5. 收藏集卡片长名看不到原文

`DressCard.nameLabel` 是唯一没设 `setWordWrap` 的卡片文字，超长名被 QLabel 直接裁掉且**不加省略号**，用户根本看不到原文。改为：

- `setWordWrap(True)` + 固定两行高（`_NAME_H = 40`，`_TEXT_H` 56 → 76）；
- 整卡挂 `ToolTipFilter(self, 500, ToolTipPosition.TOP)` + `setToolTip(完整名)` 兜底。

### 6. 「已下载」改用组件库徽标

`PackageCard` / `DressCard` **右上角**挂 `InfoBadge.success("已下载")`（构造时查一次目标目录），**勾选框改钉左上角**，两者可同时显示；两个详情页的 `CaptionLabel("已下载过")` 也换成 `InfoBadge`（属性名仍叫 `downloadedLabel`，检查脚本不用改）。

**收藏集徽标一开始死活不显示**，根因是目录命名不一致：

- `download_collection_batch` 按 `certain_lottery_typed` 取回的 `coll.name` 建目录；
- 卡片手上只有搜索结果 `summary`，`collection_download_dir(summary)` 查的是 `summary.name`；
- 两者常不相同 → 详情页（拿得到 `coll`）能显示「已下载」、卡片却永远判不出来。

> 「详情页能看到已下载」不是「命名没问题」的反证，恰恰是**两处查了不同名字**的证据。

统一为**一律按 `summary.name` 命名**：

- `download_collection_batch` 改用 `collection_download_dir(summary)` 建目录；
- 详情页单个下载从 `Dress.download_collection` 换成 `download_collection_batch([summary], ...)`——顺带解决了 biliemoji 的 typed 下载方法不转发 `proxies` 的问题；
- 详情页 `_refresh_downloaded(collection=None)` 同时认 summary 名与 coll 名两个目录，兼容改名之前下载的旧数据。

## 四、已知未修复

### 首列与次列之间没有间隙

`QListView` 在 `gridSize` 模式下会把**首列**卡片右移一格、其余列不移。实测（vw=992、cell=196、card=188）：

```
itemXs = [0,   196, 392, 588, 784]   ← 单元格完全均匀
cardXs = [8,   196, 392, 588, 784]   ← 只有第 0 列被右移 8px
相邻卡片间距 = [0, 8, 8, 8]
```

所以第一、二列贴死、其他列有间距。`setSpacing(0)`、`doItemsLayout()`、resize 重排都改不掉——这是 `setItemWidget`（`setIndexWidget`）的定位行为，不在单元格尺寸的控制范围内。

当前缓解：选中高亮用 QSS `margin: 4px` 从卡片边缘内缩，让相邻高亮之间有 8px 间隙（首列/次列之间仍为 0）。

**彻底解决**需要把网格从 `QListWidget + setItemWidget` 换成组件库 `FlowLayout`（`qfluentwidgets/components/layout/flow_layout.py`，支持真正均匀的 `horizontalSpacing` / `verticalSpacing`）放进 `SmoothScrollArea`。代价是 `_CardGridBase` 的懒加载（`scrollContentsBy` + `visualItemRect` 判可视）、多选 API、以及依赖 `count()` / `item()` / `itemWidget()` 的检查脚本都要重写，本批次未做。

### 其他

- **卡片徽标只在建卡时查一次目录**，同一个网格里下载完成不会自动刷新（重新搜索 / 翻页会更新）。`PackageCard.refresh_downloaded()` / `DressCard.refresh_downloaded()` 已写好但未接线。
- **旧下载的收藏集**仍在按 `coll.name` 命名的目录里：详情页认得出，但搜索结果卡片上的徽标要重新下载一次才会亮。

## 五、踩坑记录

1. **`NavigationInterface.addWidget(onClick=fn)` 已经会连 `clicked`**，再手动 connect 就是连两遍——切了又切回，看起来完全无效。
2. **`ComboBox` 闭合态不显示图标**是上游设计，只能自己 `setIcon`；补图标有三个时机（建卡后 / `currentIndexChanged` / `blockSignals` 内），且 `FluentIcon` 要随主题重取。
3. **裸原生控件拿不到主题**：`updateStyleSheet()` 只重刷注册过的控件，原生控件从没注册；列表用 `ListWidget`、按钮用 `TransparentPushButton`，别自己写 QSS 兜。
4. **`QListView` 设了 `gridSize()` 后忽略 `setSpacing()`**：步进就是 `gridSize.width()`，spacing 只把首列右移；间隙要做进单元格尺寸。
5. **换行判据是闭区间**：`列数 * cellW > 视口宽 - 1` 就换行，算宽要留余量。
6. **测试脚本别自己调 `setTheme` 又断言 `cfg.theme`**：`setTheme` 只改生效主题，`cfg.theme` 由 `_on_theme_changed` / `_toggle_theme` 写。混用会让两者脱节，写出假失败——`check_theme_switch.py` 第一版就栽在这上面，一律经下拉 / 侧栏按钮切换即可。
7. **`FluentIcon` 枚举名**：`CONSTRACT`（官方把 contrast 拼错）、`CHEVRON_DOWN_MED`、`CHEVRON_RIGHT`。

## 六、验证

```bash
uv run ruff check .
uv run python -c "import app.MainWindow"

QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py   # 本批次新增
QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py   # 含新增第 9 组
QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py
QT_QPA_PLATFORM=offscreen uv run python scripts/check_image_viewer.py
```

`scripts/check_theme_switch.py` 覆盖：

- 侧栏按钮点一次主题翻转一次、再点翻回来、`clicked` 每次只发一次（防双触发回归）；
- 下拉闭合态图标非空、切深色后 `cacheKey()` 变化（证明重新取色）；
- 侧栏切换后下拉索引同步且 `blockSignals` 块内补上了图标；
- `PackageGrid` 的 `styleSheet()` 在亮/暗之间确实变化（证明容器 QSS 随主题重刷）。

`scripts/check_improvements.py` 第 9 组覆盖：目录非空 → 徽标显示、目录不存在 → 不显示、多选态徽标与勾选框同时可见且 `checkBox.right() < badge.left()`（互不遮挡）。

四个脚本均 **ALL PASSED**。真实 B 站网络流程（搜索、拉取、下载）依赖 Cookie，需人工 `uv run python main.py` 验证。
