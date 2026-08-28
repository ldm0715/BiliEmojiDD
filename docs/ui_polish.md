# UI 改进：暗色主题补全 + 网格填充 + 主题切换

一次 UI 改进批次：设置页「打开下载文件夹」、补全暗色主题、收藏集详情「加入下载」、网格响应式填满、下载双列、侧栏主题切换等。本文记录改动内容、关键实现与踩坑，便于后续维护。

## 一、背景

原有问题：

1. **暗色主题名存实亡**：qfluentwidgets 只给其组件套 QSS、不改全局 palette，本项目大量纯 QWidget（`QScrollArea` / `QListWidget` / `QLabel`）用系统浅色调色板——暗色模式下背景发白、文字发黑，切换后还偶发反色残留。
2. **表情包网格不填满**：表情包卡/表情详情网格是固定小卡片靠左排，窗口放大缩小出现大量空白，与收藏集网格的填满风格不一致。
3. **收藏集详情无入队**：只能单包下载，不能像表情包详情那样「加入下载」攒队列。
4. **「仅看收藏集」默认不勾**、勾选后要重新搜索才生效。
5. **下载队列单列、多选后文字区有阴影**；侧栏展开宽度 400 过宽。

## 二、新增 / 修改文件

| 文件 | 说明 |
|---|---|
| `app/common/theme.py`（新） | 全局调色板 + 主题感知取色对 + `bind_theme` |
| `app/components/widgets.py` | 卡片改用主题化 Label；`_apply_bg` 改类选择器；PackageGrid/EmojiGrid 响应式；QueueList 双列；QueueCard 自适应封面 |
| `app/common/config.py` | `qconfig` 加载后同步 `themeMode`（修反色根因） |
| `app/MainWindow.py` | 侧栏展开宽度 150；`NavigationToolButton` 主题切换按钮 |
| `app/view/setting_page.py` | 打开下载文件夹按钮；主题下拉图标；外部切换主题后下拉同步 |
| `app/view/dress_page.py` | 详情「加入下载」+「已下载过」；「仅看收藏集」默认勾选 + 实时过滤 |
| `app/view/emoji_page.py` / `app/view/download_page.py` / `app/components/package_detail.py` | 提示标签改为主题化组件 |
| `app/components/download_runner.py` | `package_download_dir` / `collection_download_dir` / `downloaded_exists` |

## 三、功能与实现要点

### 1. 暗色主题（核心）

- **根因**：qfluentwidgets 不改全局 palette。纯 QWidget 的背景/默认文字色来自 palette。
- **全局调色板**：`theme.py` 在 `themeChangedFinished` 时按生效主题 `app.setPalette(暗色板 / 标准板)`，并强制 `update()` 全部控件（个别控件 `update` 签名被覆写，逐个 `try/except`）。
- **文字用组件库 Label**：全部替换为 `CaptionLabel` / `StrongBodyLabel` / `BodyLabel` + `setTextColor(light, dark)`，它们内部连 `qconfig.themeChanged` 自动切换颜色，无需手写 QSS。
- **`bind_theme(widget, fn)`**：`fn()` 立即执行 + 每次主题切换重执行；`fn` 须为 widget 的**绑定方法**（widget 销毁时 PySide6 自动断开连接，无泄漏）。现仅用于卡片选中背景 accent 的重算。
- **反色根因修复**：config.json 里的 `QFluentWidgets.ThemeMode` 会残留旧值，`qconfig.load` 把它读回来覆盖应用主题。两步修复：
  - `config.py` 加载后 `qconfig.set(qconfig.themeMode, cfg.theme.value, save=False)` 强制同步；
  - 主题保存顺序改为「先 `setTheme` 再 `qconfig.set(cfg.theme, ...)`」，保证落盘的 `ThemeMode` 与应用主题一致。
- `isDarkTheme()` 返回**生效主题**（AUTO 已被 `qconfig` 解析成具体值），取色直接用。

### 2. 网格响应式填充

- `_CardGridBase` 已内置 `resizeEvent → _layout_items()` 重算 `_cell_size()`，窗口缩放实时重排。
- `PackageGrid` / `EmojiGrid` 的 `_cell_size()` 与 `DressGrid` 同款：
  ```python
  n = min(8, max(1, vw // (min_cell.width() + spacing)))
  w = max(min_cell.width(), (vw - spacing * (n - 1)) // n)
  return QSize(w, w)          # PackageGrid 正方形
  # EmojiGrid 高 = w + 36（图标 + 底部文字）
  ```
- `EmojiCard` 复用 `_CardGridBase` 契约：`set_cell` 里图标随单元格缩放、文字宽度对齐；补 `set_selectable`/`toggled`/`is_checked` 占位（表情不支持多选）。
- **踩坑**：QPushButton 垂直 size policy 默认 `Fixed`，`QVBoxLayout` 加 `stretch=1` 也拉不撑——重构 `PackageCard` 时漏了 `setSizePolicy(Expanding, Expanding)`，图片被压成 sizeHint 高度、卡片大量空白（CLAUDE.md 已记此坑，又踩一次）。

### 3. 下载队列双列 + 去阴影

- `QueueList._cell_size()`：`vw >= 2*min_w + spacing` → 两列 `w=(vw-spacing)//2`；否则单列 `w=vw-spacing`。数学上 `2w+spacing ≤ vw`（两列）、`w+spacing = vw`（单列）→ 不横向溢出。
- 垂直滚动条出现会收窄视口，`_CardGridBase` 增加 `verticalScrollBar().rangeChanged → _layout_items()` 联动重排。
- **阴影根因**：选中态 `setStyleSheet("background-color: rgba(...)")` 是无选择器的通用规则，会级联到无自己背景规则的子 label → 文字区整块上色。改用**类选择器** `"QueueCard { background-color: ... }"` 限定自身（PySide6 类选择器按 Python 类名匹配，已验证不级联）。
- `QueueCard` 封面随单元格自适应：`img = max(72, min(h-16, round(w*0.28)))`，值未变时不 `setFixedSize`（防递归布局）；名称 `setWordWrap(True)` 防截断；信息区右留 24px 防文字跑进勾选框。

### 4. 详情页入队 / 已下载

- `DressPage` 新增显式字段 `self._detail_summary`（不用 `_detail[2]` 魔法下标）。
- **`_sync_queue_btn` 单一同步源**：
  - 每次 `_open_detail` 重置按钮「加入下载」禁用；
  - `_show_detail`（拉取成功）调 `_sync_queue_btn` —— summary 已在队列则「已加入」禁用；
  - `download_queue.changed` → `_sync_queue_btn`（从下载页删除/清空自动恢复）；
  - `_go_back` 清 `_detail_summary` 并重置。
- **「已下载过」**：`downloaded_exists(package_download_dir(pkg))`（目录存在且非空）。目录命名与批量下载**完全一致**（`download_runner` 提供 helper）：表情包 `清洗名[:60] [包ID]`、收藏集 `清洗名`。

### 5. 侧栏

- `MainWindow.__init__`：`navigationInterface.setExpandWidth(150)`（qfluentwidgets 1.5.1 默认 322）。
- **主题切换按钮**：`NavigationToolButton(icon, parent)`（注意构造只有 2 参），插在设置之前（bottom 布局先加的在上面）→ 位于设置上方。`_update_theme_icon` 连 `themeChangedFinished` 随主题换图标（亮色=CONTRACT、暗色=BRIGHTNESS），点击切换 `LIGHT/DARK` 并持久化 + `signal_bus.configChanged` 让设置页下拉同步。
- **主题下拉图标**：跟随系统=SYNC、浅色=BRIGHTNESS、深色=CONTRACT（qfluentwidgets 枚举名是 `CONTRACT`——官方对 contrast 的拼写错误，没有 `CONTRACT`）。

### 6. 「仅看收藏集」

- 默认 `setChecked(True)`；`_show_results` 存 `self._last_summaries` 原始结果；`toggled → _apply_filter` 实时重过滤（取消勾选无需重新搜索即看回全部）。

## 四、踩坑记录

1. **QPushButton 缺 Expanding 撑不满**：垂直 size policy 默认 Fixed，stretch 无效，图片被压小（PackageCard 重构）。
2. **PySide6 个别控件 `update` 签名被覆写**：全局强制重绘循环里 `widget.update()` 会 `TypeError`，逐个 `try/except`。
3. **`NavigationToolButton` 构造只有 `(icon, parent)`**：传 5 参会 `TypeError`。
4. **枚举名是 `CONSTRACT` 不是 `CONTRACT`**：qfluentwidgets 把 contrast 拼错了，用错名直接 `AttributeError`。
5. **`QFluentWidgets.ThemeMode` 残留**：config.json 旧值覆盖应用主题导致反色，见「三.1」。
6. **测试脚本时序**：`setTheme` 须放在 app 模块导入之后——`config` 导入会 `qconfig.load` 读配置文件里的 ThemeMode 覆盖已设主题。

## 五、验证

- `uv run ruff check .`；`uv run python -c "import app.MainWindow"`。
- `QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py`：主题切换重刷、双列几何（实际 item 坐标 + 滚动条 + 不溢出/不重叠）、长名防裁剪/防复选框遮挡、详情入队/已下载状态同步、过滤默认勾选、设置页按钮、侧栏宽度——ALL PASSED。
- `QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py`：网格点击索引接线——ALL PASSED。
- 人工 `uv run python main.py`：深色观感、网格缩放填满、侧栏主题切换、详情三态（加入/已加入/已下载过）。

## 六、后续修复

本批次之后又修了一轮主题跟随 / 网格铺满 / 已下载徽标的问题，见 [theme_grid_fixes.md](theme_grid_fixes.md)。其中修正了本文两处结论：

- 「三.1 暗色主题」里的全局调色板方案对**网格容器无效**——`FluentWindow` 给 `stackedWidget` 套了 QSS，整棵子树被 `QStyleSheetStyle` 接管并缓存 palette，`app.setPalette()` + `update()` 刷不动它；正解是把 `_CardGridBase` 换成组件库 `ListWidget`（自带 QSS 注册）。
- 「三.2 网格响应式填充」的 `(vw - spacing*(n-1)) // n` 公式**多减了一份间距**——`QListView` 设了 `gridSize()` 后完全忽略 `spacing()`，每行会白白少用 `spacing*(n-1)` px。
