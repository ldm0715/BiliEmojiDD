# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

B 站表情包 / 收藏集（装扮）下载器 GUI：PySide6 + QFluentWidgets 界面，`biliemoji==2.0.0` 提供 B 站接口能力。功能：表情包按 ID 查询 / 全量列表多选加入下载队列、包详情（**GIF 开关按包内是否真有 gif_url 显隐** + 加入下载 + 已下载过）下载、收藏集关键词搜索 + **竖版四列卡片（收藏集/装扮类别徽标）+ 多选加入下载队列** + 详情预览（动态尺寸图片网格 + 视频折叠列表 + image/video/both 下载 + 加入下载 + 已下载过）、**两个详情页点击图片全屏查看（遮罩 lightbox + 左右翻页）**、**下载队列 Tab**（会话级，**混合表情包 + 收藏集**，宽屏两列窄屏单列，全选/删除/清空/批量下载，**卡片显示内容数量（懒加载）**、**全部成功的项下载后自动出队**）、**下载设置**（目录 + 打开文件夹 + 代理 + 线程数，**Fluent 设置卡片版式：分组 + 每行一张窄卡片 + Cookie / 下载目录可展开**）、**深色模式补全**（主题化 Label + 全局调色板）、**网格随窗口响应式填满**、**侧栏主题切换按钮**（图标随主题变换）、缩略图懒加载（**未到位时显示组件库加载环**）、全部表情包本地缓存。中文 UI。

## 常用命令

```bash
uv sync                                   # 安装/重建依赖
uv run python main.py                     # 启动应用（会弹窗）
uv run ruff check .                       # lint（--fix 自动修复）
uv run python -c "import app.MainWindow"   # 导入自检（连带验证 biliemoji/qfluentwidgets/PySide6）

# 屏幕外 GUI 验证脚本（无需 Cookie、不走网络）
QT_QPA_PLATFORM=offscreen uv run python scripts/check_image_viewer.py   # 查看器：letterbox/翻页/关闭
QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py     # 网格：点击 → 索引接线
QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py   # 改进批次：主题切换/双列几何/入队状态/侧栏
QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py   # 主题：侧栏按钮/下拉图标/网格容器重刷
QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py   # 设置页：功能控件仍在/版式/展开/窄窗口/主题
QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py   # 三页版式：控件仍在/大标题对齐/多选行/详情卡/窄窗口
QT_QPA_PLATFORM=offscreen uv run python scripts/check_download_improvements.py  # 下载体验：GIF行/内容数量/自动出队/加载环/去重键
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py     # 各页面亮/暗截图到 screenshots/（人工比对用）
```

无测试框架（未配置 pytest），也就没有「跑单个测试」的概念。GUI 逻辑靠 `scripts/` 下的屏幕外断言脚本验证，每个脚本自成一体、失败时 `exit 1`（见「验证」）。

## 文档（`docs/`）

改动涉及某个功能时**先读对应文档**，里面有本文件放不下的完整背景、踩坑推导与验证结论：

| 文档 | 内容 |
|---|---|
| `docs/usage.md` | 面向用户：页面功能、Cookie 获取、缓存、常见问题 |
| `docs/architecture.md` | 技术栈、模块分层、线程模型、数据流 |
| `docs/development.md` | 环境、代码约定、**关键坑点 8 条**、修改指南 |
| `docs/download_queue.md` | 下载队列初版（仅表情包）+ 下载设置 + 代理机制 |
| `docs/collection_page.md` | 收藏集页改造 + 类别判别 + 混合队列 |
| `docs/image_viewer.md` | 图片查看器：letterbox 方案 + qfluentwidgets 上游坑全清单 |
| `docs/ui_polish.md` | UI 改进：暗色主题补全（全局调色板 + 主题化 Label）、网格响应式填充、下载双列 + 去阴影、侧栏主题切换 |
| `docs/theme_grid_fixes.md` | 主题跟随 + 网格铺满 + 已下载徽标：主题切换三处失效根因、`QListView` gridSize 忽略 spacing、收藏集目录命名统一 |
| `docs/setting_page_redesign.md` | 设置页改版：Fluent 设置卡片版式（分组 + 窄卡片 + 可展开行）、只改界面不改功能的落实、`ExpandSettingCard` 上游坑 |
| `docs/page_card_layout.md` | 三页卡片版式：表情包 / 收藏集 / 下载页的大标题 + 命令卡 + 内容卡、`page_scaffold` 共用底座、长文本顶最小宽度等坑 |
| `docs/download_page_improvements.md` | 下载体验优化：GIF 选项按需显隐、队列内容数量懒加载（`content_meta`）、全部成功自动出队（`BatchReport`）、缩略图加载环、**收藏集去重键 `item_id` 非唯一**的根因 |

**新增功能时同步更新**：`docs/` 下新建一篇（结构参照 `download_queue.md`），并登记进 `docs/README.md` 导航表与根 `README.md` 文档列表。

## 环境约束（重要，勿改动）

- **Python 3.11**（`.python-version`）。**不要升级到 3.12**：qfluentwidgets 来自 GitHub fork `ldm0715/PyQt-Fluent-Widgets@PySide6`（v1.5.1），其 `setup.py` 要求 `PySide6<=6.4.2`，而 6.4.2 无 py3.12 wheel。代码禁用 PEP 701（f-string 内嵌同引号）等 3.12 专属语法——嵌套 f-string 请用 `('#' + str(x))` 之类写法。
- **不要**把 qfluentwidgets 换回官方 PyPI 版（`PySide6-Fluent-Widgets[full]`）。开源版（官方与 fork）都没有数字分页组件（`Pagination` 属 Pro 版），`app/components/page_bar.py` 的 `PageBar` 是自制组件。
- 依赖声明在 `pyproject.toml`，`[tool.uv] package=false`（应用非库）。

## 架构

- `main.py`：入口。**先建 `QApplication` 再导入 `MainWindow`**（保证控件/信号在主线程构造）；`setTheme(cfg.theme.value)` 应用主题；启动时 `proxy_env.remember()` + `apply(cfg.proxy.value)` 快照并应用代理环境变量。
- `app/MainWindow.py`：`FluentWindow` **四页导航**（表情包/收藏集/下载/设置，设置在 BOTTOM）。侧栏展开宽度 `setExpandWidth(150)`；主题切换按钮（`NavigationPushButton`，插在设置之前，展开时显示「主题」文字）随主题换图标（亮色=`CONSTRACT`、暗色=`BRIGHTNESS`），点击切换 `LIGHT/DARK` 并持久化 + `signal_bus.configChanged` 让设置页下拉同步。**接线只走 `addWidget(onClick=...)`，不要再手动 connect `clicked`**（会双触发）。`closeEvent` 里：有运行中下载时弹确认（下载不支持安全中断，退出会残留 `.part`）；`task_manager.clear_pending()` 只清未开始任务。
- `app/common/`：
  - `config.py`：`AppConfig(QConfig)` 单例 `cfg`，**持久化到 `%APPDATA%/biliEmojiDD/config.json`**（不写项目目录）。项：`cookie`、`download_dir`、`default_gif`、`max_workers`(1–16)、`proxy`、`theme`。`theme` 项必须带 `EnumSerializer(Theme)`（否则 JSON 序列化崩）。`qconfig.load` 后会同步 `qconfig.themeMode` 到 `cfg.theme.value`（否则配置文件里残留的 `QFluentWidgets.ThemeMode` 会覆盖应用主题导致反色）。
  - `signal_bus.py`：全局信号（缩略图、配置变更）。
  - `exception.py`：`show_bili_error(e, parent)` 统一 `BiliError` 子类 → 中文提示（`AuthRequired`→引导设置页、`DressNotFound`→"没有结果" 等）。提示走 `app/common/notify.py` 的 helper，不直接用 `InfoBar`。
  - `proxy.py`：`parse_proxy/split_proxy/build_proxy/proxy_scheme` + `ProxyEnvManager`（`remember` 快照 / `apply` 设置或清空恢复原值）。
  - `notify.py`：`notify_success/warning/error/info` —— **垂直布局 InfoBar**（标题一行/内容换行/按钮一行），全应用统一入口。
  - `theme.py`：主题感知取色对 `BODY_TEXT`/`SECONDARY_TEXT`/`ORANGE_TEXT`（(light, dark) 二元组，配主题化 Label 的 `setTextColor`）；`bind_theme(widget, fn)` 立即执行 + 每次 `themeChangedFinished` 重执行（fn 须为 widget 绑定方法，销毁自动断开）；**全局调色板**在主题切换时按生效主题 `app.setPalette(...)` 并强制 `update()` 全部控件（纯 QWidget 背景/文字依赖 palette）。`isDarkTheme()` 返回生效主题（AUTO 已被 `qconfig` 解析成具体值）。
- `app/components/`：
  - `task.py`：**线程层核心**。`Task`(QRunnable) + `TaskManager`（持有引用，finished 自动释放）+ `run_task()`。信号对象在主线程构造（亲和主线程），worker 线程 emit 自动 QueuedConnection。`autoDelete(False)` 防 C++ 对象提前释放丢信号。全局线程池 max 4。
  - `thumb.py`：异步缩略图。worker 向**常驻 `signal_bus`** 发原始信号（`thumbRawLoaded`/`thumbRawFailed`），主线程转 `QPixmap` 写 `QPixmapCache` 再广播 `thumbLoaded`。emit 用 try/except 守卫（应用关闭时忽略）。
  - `content_meta.py`：下载项**内容概要**（图片/视频数）。结构同 `thumb.py`：独立 `QThreadPool(2)`（不占 `task_manager` 的 4 线程）、worker 发 `signal_bus.contentMetaRaw(key, meta)`、主线程写缓存后广播 `contentMetaLoaded`（**载荷 None = 取不到**）。`cached()` 对自带 `emote` 的完整 `EmotePackage` 同步推导（零请求）；`request()` 只在卡片可见时调；**失败记 `_failed` 本会话不重试**；`remember()` 供两个详情页喂数据。**`set_enabled(False)` 给屏幕外脚本关联网**（否则假 ID 排一堆 15s 超时把脚本挂住）。
  - `widgets.py`：`EmojiCard`/`EmojiGrid`（表情网格，**复用 `_CardGridBase`**，卡片可点 → `imageClicked(index)`）、`_CardGridBase`（**组件库 `ListWidget`** 网格基类，主题自动重刷：懒加载缩略图 + 多选 API + 动态单元格 + `itemClicked(item)` / `itemClickedAt(index, item)`，内含 `verticalScrollBar().rangeChanged → _layout_items()` 联动重排）、`PackageCard`+`PackageGrid`（表情包卡片/网格，响应式填满）、`DressCard`+`DressGrid`（收藏集竖版四列卡片）、`DetailCard`+`DressDetailGrid`（详情动态尺寸网格，卡片可点 → `imageClicked(index)`）、`QueueCard`+`QueueList`（下载队列，**宽屏两列窄屏单列**，封面随单元格自适应）。`PackageCard`/`DressCard` **右上角**挂 `InfoBadge.success('已下载')`、**勾选框移到左上角**（两者同时显示不打架）；`DressCard` 名称 `setWordWrap` 两行 + 整卡 `ToolTipFilter` 兜底完整名。**所有卡片文字用主题化 `CaptionLabel`/`StrongBodyLabel`/`BodyLabel` + `setTextColor(light, dark)`，自动随主题切换**；选中背景用**类选择器**（如 `QueueCard { background-color: ... }`）限定自身，不级联子 label。
  - `page_scaffold.py`：**四页共用版式底座**——`PAGE_MARGIN=36` / `page_title` / `title_row`（缩进走布局边距）/ `CommandCard`（`SimpleCardWidget` + `add_row` / `add_row_widget` / `add_widget`）/ `SectionCard`（`HeaderCardWidget`，内容区边距收紧）。卡片基类自带主题重绘，别自己写 QSS。
  - `package_detail.py`（包详情视图，两个入口复用；头部卡 + `SectionCard("表情预览")`，`add_leading_widget()` 供「返回列表」嵌入）、`page_bar.py`（自制数字分页）、`image_viewer.py`（遮罩图片查看器，见下节）、`download_runner.py`（`start_download` + `download_package_batch`/`download_collection_batch`/`download_mixed_batch`）、`download_queue.py`（下载队列单例）、`dress_helpers.py`（收藏集类别判别 + dlc id 读取）、`cache.py`（全部表情包缓存）。
- `app/view/`：**四页统一 Fluent 卡片版式**（大标题 → 命令卡 → 内容，页边距 36，见 `docs/page_card_layout.md`）。`emoji_page.py`（Pivot 双标签 + 命令卡；多选行按需显隐；详情「返回列表」在头部卡内）、`dress_page.py`（搜索命令卡；详情头部卡 + `SectionCard("内容预览")` + 视频卡；「仅看收藏集」**默认勾选** + `_last_summaries` 存原始结果、`toggled` 实时重过滤；详情 `_detail_summary` 显式字段）、`download_page.py`（命令卡含计数/批量按钮/状态/进度条 + 队列列表）、`setting_page.py`（**Fluent 设置卡片版式**：`TitleLabel` 大标题 + `ScrollArea`/`ExpandLayout` + 三个 `SettingCardGroup`；Cookie / 下载目录用 `ExpandGroupSettingCard`，其余用本地 `_WidgetSettingCard`（`SettingCard` 尾部挂控件）；主题下拉带图标：`_sync_theme_icon` + `bind_theme`，外部切换后 `configChanged` 同步）。

## 图片查看器（`app/components/image_viewer.py`）

- 入口只有 `show_image_viewer(items, index, parent)`（`items` 为 `[(name, url), ...]`，`parent` 传 `page.window()`）；两个详情页复用：`EmojiGrid.imageClicked` / `DressDetailGrid.imageClicked` → 页面槽 → 该函数。
- 组件全部复用现成的：`HorizontalFlipView`（悬浮左右箭头 + 滚轮 + 平滑动画）、`MaskDialogBase`（窗口内遮罩）、`HorizontalPipsPager`（页码点，>15 张时隐藏）。图片走 `thumb_manager.request` + `signal_bus.thumbLoaded`，**先 connect 再 request**（命中 `QPixmapCache` 是同步 emit），只预取当前索引 ±2（一次性请求几十张会占满 3 线程的缩略图池）。
- GIF 只显示首帧（`FlipView` 存 `QImage`，动图需 `QMovie`，其 delegate 不支持）。

### qfluentwidgets 上游坑（本组件已绕过，勿"修回去"）

以下六条是改 `image_viewer.py` 时最容易"顺手改回去"的地方，完整推导见 `docs/image_viewer.md` 第五节。

- **`FlipView._adjustItemSize` 按图片宽高比算 sizeHint**：① 图片未加载时 `QImage()` 高为 0，`KeepAspectRatio` 分支**除零崩**；② 图片异步到位后 sizeHint 变化，而 `scrollToIndex` 按前序 item 宽度累加算滚动量 → 已显示的图**跑偏**。`_ViewerFlipView` 覆写为固定 `sizeHint = itemSize`，图片预先 letterbox 合成到 `itemSize * dpr` 画布（使 delegate 里的 `image.scaled(size * r, ...)` 成为恒等变换）。
- **`MaskDialogBase.setMaskColor` 的 B/G 参数写反**（`rgba(red, blue, green, alpha)`）：用纯黑遮罩正好绕过，别改成彩色。
- **`MaskDialogBase` 把 `self.widget` 无对齐地塞进 `_hBoxLayout`** → 铺满整个 dialog，「点击遮罩空白处关闭」永远判不出来。须按 `MessageBoxBase` 的做法 `removeWidget` 后 `addWidget(self.widget, 1, Qt.AlignCenter)` 重新居中。
- **`PipsPager.setCurrentIndex` 会发 `currentIndexChanged`**（经 `scrollToItem`），与 FlipView 双向绑定时要么加 guard 要么依赖 `FlipView.setCurrentIndex` 的同值早退；`setPageNumber` 内部也会 `setCurrentIndex(0)` 发一次信号，接线要放在它之后。
- **`FlipView.setCurrentIndex` 在 `index == currentIndex()` 时早退不发信号**，而 `addImages` 已把 `_currentIndex` 置为 0 → 初始索引为 0 时必须手动同步一次 UI。
- FlipView 继承 QListWidget，会吞掉方向键改 currentRow；查看器里给它和 pips 都设 `NoFocus`，方向键交给 dialog 的 `keyPressEvent`。

## 线程与 GUI 规则（易踩坑）

- 所有网络 I/O（biliemoji 调用、下载、缩略图）必须在后台线程，结果经 Qt 信号回主线程；**worker 线程禁止直接改控件**。
- biliemoji 下载器的 `on_progress(done, total, result)` 在内部线程池调用 → 桥接成 Qt 信号（`run_task(..., needs_progress=True)` 自动处理）。
- **on_progress 统一协议 `(done, total, result)`**：`result is None` 表示下载准备阶段（读取包详情），`start_download` 据此显示状态文字；自定义下载闭包必须 `def task(on_progress=None):` 并透传给 biliemoji（缺参会抛 `TypeError`）。
- `QPixmap` 只能在主线程创建/使用；worker 线程只产 `QImage` 或字节数据。
- `FlowLayout.takeAt(index)` 返回 **widget**（不是 QLayoutItem）；清理布局用 `widget.setParent(None)` + `deleteLater()` 防幽灵残影。
- **`QPushButton` 垂直 size policy 默认 `Fixed`**：`QVBoxLayout` 里加 `stretch=1` 也拉不撑（海报被压成 12px 的坑，多余空间全给文字 label）；需撑满时 `setSizePolicy(Expanding, Expanding)`。
- **卡片下标不要靠载荷身份反查**：`(name, url)` 这类内容相同的元组字面量会被 CPython 常量折叠成**同一个对象**（`items[1] is items[2]` 为真），`is` 反查会把两项判成同一下标。`_CardGridBase` 用建卡时的 `partial(self._emit_clicked, index)` 闭包发 `itemClickedAt(index, item)`。
- **qfluentwidgets `ComboBox.addItem(text, icon, userData)`**：第二位置参数是 **icon** 不是 userData；要 `currentData()` 有值必须 `addItem('文本', userData=值)`（曾致下载模式 `mode.lower()` 崩、设置页代理/主题切换失效）。
- **`ComboBox` 闭合态不显示选中项图标**：`ComboBoxBase.setCurrentIndex` 只 `setText` 从不 `setIcon`，`item.icon` 只在展开菜单时用。要显示得自己 `setIcon(combo.itemIcon(i))`（ComboBox 继承 QPushButton，`paintEvent` 会调 `QPushButton.paintEvent` 画出来）。补图标的时机有三处：建卡后、`currentIndexChanged`、以及 `blockSignals` 内的同步——首次 `addItem` 库会自动 `setCurrentIndex(0)`，之后设同一索引会提前 return 不发信号。`FluentIcon` 按取用瞬间的主题取黑/白 svg，主题切换后须重新 `setIcon`（用 `bind_theme` 绑定）。
- **`NavigationInterface.addWidget(..., onClick=fn)` 已经会把 `fn` 连到 `widget.clicked`**（`NavigationPanel._registerWidget`）。再手动 `widget.clicked.connect(fn)` 就是连了两遍，一次点击跑两次——主题切换按钮曾因此「切了又切回」，看起来完全无效。
- **设置卡片四条（详见 `docs/setting_page_redesign.md`）**：① `SettingCard.hBoxLayout` 末尾是 `addStretch(1)`，续 `addWidget` 即靠右排（`_WidgetSettingCard` 就靠这个挂 ComboBox/SpinBox）；② `HeaderSettingCard.addWidget` **只能调一次**（每次都会重新把 `expandButton` 塞进布局），多控件先包无边距容器；③ `ExpandSettingCard` 是 `QScrollArea` 子类，**没有 `setContent`**，标题行在 `.card` 上，且 `ExpandLayout.count()` 恒为 0（`addWidget` 进的是另一个列表）；④ `addGroupWidget` 的行必须 `setFixedHeight`（展开高度按 `viewLayout.sizeHint()` 算）。
- **有 QSS 的控件 `setContentsMargins` 会被忽略**：`QStyleSheetStyle` 按 QSS 盒模型重算 contentsMargins（`TitleLabel` 等组件库 Label 都注册了 QSS），缩进要走**布局边距**——设置页大标题曾因此贴在 x≈2 而不是 36。
- **页面里放 `QScrollArea` 必须显式透明**：页面在 `FluentWindow` 的 `stackedWidget` 子树里靠「自己不画背景」透出窗口底色，原生 `QScrollArea` 不透明会在暗色下露出 palette 的 Base 色块。写法 `QScrollArea{border:none;background:transparent}` + `.QWidget{background:transparent}`（`.QWidget` **类选择器**只命中 viewport / scrollWidget 这类纯 QWidget，不级联到卡片）。
- **`SpinBox` 右侧上下按钮占约 64px**：宽度给到 90 以下数字会被裁没（设置页端口 130 / 线程数 110）。
- **不换行的 `QLabel` 会把整页最小宽度顶起来**：`minimumSizeHint` 就是整串文字宽度，详情页长名一度让页面缩不到最小窗口（598px）。标题/元信息/提示类 Label 一律 `setWordWrap(True)`。
- **隐藏的子页不会重新布局**：`QStackedWidget` 非当前页、未 `show()` 的 Tab，几何停留在上次可见时的尺寸——写几何断言前先切到该页，否则量到过期数字「假通过」。
- **断言脚本里的假图 URL 要预置 `QPixmapCache`**：否则每个 URL 排一个 15s 超时的下载任务，脚本跑完卡着退不出去。
- **裸 `QListWidget` / `QToolButton` 等原生控件拿不到主题**：qfluentwidgets 靠 `updateStyleSheet()` 重刷 **已注册进 `styleSheetManager`** 的控件，原生控件从没注册过，背景色只能靠 `QPalette`——而全库从不调 `QApplication.setPalette`。列表用组件库 `ListWidget`（构造里 `FluentStyleSheet.LIST_VIEW.apply(self)` 自动注册），按钮用 `TransparentPushButton` 等，别自己写 QSS 兜。
- **`QListView` 设了 `setGridSize()` 后忽略 `setSpacing()`**：步进就是 `gridSize.width()`，spacing 只会把**首列**卡片右移一格（其余列不动），于是第一、二列之间没有间隙、其他列有。所以 `_CardGridBase` 直接 `setSpacing(0)`，所有 `_cell_size()` 一律按 `(vw - _CARD_GUTTER) // 列数` 均分铺满整行；换行判据是 `列数 * cellW > 视口宽 - 1`（闭区间），算宽必须留余量，否则最后一列被挤到下一行、右侧反而空出一整格。选中高亮用 `_SEL_INSET` 的 QSS `margin` 从卡片边缘内缩来分隔相邻卡片。**首列与次列之间仍然没有间隙**（`setItemWidget` 只右移首列，改不掉），已知未修复，见 `docs/theme_grid_fixes.md` 第四节。
- **`FluentIcon` 枚举名是 `CONSTRACT` 不是 `CONTRACT`**（官方把 contrast 拼错成 constract），用错名直接 `AttributeError`。
- **`NavigationToolButton` 构造只有 `(icon, parent)`**（不像 `NavigationPushButton` 的 `(icon, text, isSelectable, parent)`）。
- **主题化 Label**：文字优先用 `CaptionLabel`/`BodyLabel`/`StrongBodyLabel` + `setTextColor(light, dark)`，它们连 `qconfig.themeChanged` 自动切色；**不要**再给它们 `setStyleSheet` 设颜色（会覆盖主题色）。纯 QWidget 的背景/默认文字色依赖全局 palette（`theme.py` 已按主题应用）。
- **验证 worker 信号时**：不要写"短暂 `processEvents()` 后结束脚本"的测试——脚本退出早于 worker 会看到 `Internal C++ object ... already deleted` **假象**（真实 app 里 `app.exec()` 常驻无此问题）。要轮询等任务完成再退出。
- **缩略图加载环 `_SpinnerMixin`**（`widgets.py`）：`_center_spinner` 的早退判据必须用 **`isHidden()` 而不是 `not isVisible()`** —— 卡片尚未 `show()` 时子控件 `isVisible()` 恒为 False，用它会把建卡阶段的定位全部跳过，之后没有 resize 就永远卡在左上角 (0,0)。收环三条路径缺一不可：`set_pixmap()`、`_CardGridBase` 转发 `thumbRawFailed`、`set_cards()` 里 **url 为空的卡片建完即收环**（永远等不到信号，否则空转）。
- **构造 `DownloadPage` 的屏幕外脚本必须 `content_meta.set_enabled(False)`**：队列卡片会为可见项懒加载内容数量，假 ID 会排一堆 15s 超时请求，脚本跑完退不出去。

## 下载队列与下载设置（要点）

- **队列**：`download_queue`（`app/components/download_queue.py`）内存单例，**混合表情包 + 收藏集**，按 `item_key(item)` 去重（表情包 `("pkg", id)`；**收藏集 `("coll", "dlc:<act>:<lottery>")`**），`item_kind` 判类型；`changed` 信号驱动 `DownloadPage` 重建。**仅本次会话**，重启清空。
- **收藏集去重键不能用 `item_id`**：实测搜索接口里 **`item_id == properties.dlc_act_id`**，一个 dlc 活动下有多期 lottery（「2233的MBTI-能量之源」act=112667 lot=112709 与「2233的MBTI-ENFP」act=112667 lot=113521），每期都是独立的可下载收藏集。按 item_id 去重会把不同期判成同一项——多选加入时被悄悄丢掉、进详情页却因 `contains()` 命中显示「已加入」，和列表对不上（真实 Bug）。装扮（`type='ip'`，无 dlc id）退回 `item:`/`id:`/`name:` 前缀键。**别在别处硬编码键字面量**，一律 `item_key()`。
- **内容数量**：`QueueCard.contentLabel` 四态（`内容: N 张图片` / `内容: N 张图片 · M 个视频` / `内容读取中…` / `内容数量未知`），数据来自 `content_meta`，`QueueList._update_visible` 只为**可见**卡片 `request`、`contentMetaLoaded` 按 key 回填。
- **全部成功自动出队**：`download_*_batch` 返回 `BatchReport`（继承 biliemoji frozen `DownloadBatchResult`，多一个 `per_item: {item_key: ItemOutcome}`），`start_download(on_result=)` 把结果送回页面，`DownloadPage._on_batch_result` 移除 `all_ok` 的项。**SKIPPED 算成功**（文件已在本地）、**total==0 不算**（取详情失败 / 无可下文件）、**只在队列页批量下载触发**（详情页可只下图片或只下视频）。归属按 **`result.target.parent`**（`_resolve_target` 只改后缀不动父目录），不用下标对齐。
- **队列布局**：`QueueList._cell_size()` 响应式——`vw >= 2*min_w` 时两列 `(vw-_CARD_GUTTER)//2`，否则单列 `vw-_CARD_GUTTER`；配合 `_CardGridBase` 的 `rangeChanged` 联动在滚动条收窄视口后重排。`QueueCard` 封面随单元格自适应（`max(72, min(h-16, round(w*0.28)))`，值未变不动防递归）；名称 `setWordWrap(True)` 防截断；信息区右留 24px 防文字跑进勾选框。
- **详情页入队 / 已下载状态**：收藏集与表情包详情页都有「加入下载」按钮，状态走单一 `_sync_queue_btn`——每次打开详情重置「加入下载」禁用、`_show_detail`/`set_package` 后同步（已在队列 → 「已加入」禁用）、`download_queue.changed` 联动（移除/清空后恢复）、加入后自动「已加入」禁用；`_go_back` 清 `_detail_summary`。「已下载过」= `downloaded_exists(package_download_dir(...))`（目录存在且非空），目录命名与批量下载完全一致（`download_runner` 的 `package_download_dir` / `collection_download_dir` / `downloaded_exists`）。**收藏集目录一律按 `summary.name` 命名**（`collection_download_dir(summary)`）——搜索结果卡片手上只有 summary，若按 `certain_lottery_typed` 取回的 `coll.name` 命名，卡片徽标永远判不出已下载；所以收藏集详情页的单个下载也走 `download_collection_batch([summary], ...)` 而不是 `Dress.download_collection`（顺带拿到显式 proxies），`_refresh_downloaded` 同时认 summary 名与 coll 名两个目录以兼容改名前下载的旧数据。
- **批量下载**：`download_runner.download_package_batch(ids, dest, *, gif=None, max_workers=None, on_progress=None)`（表情包）与 `download_collection_batch(collections, dest, *, mode='both', max_workers=None, on_progress=None)`（收藏集，目录 `collection_download_dir(summary)`，即按搜索结果名）同构；下载页 `download_mixed_batch` 按 `item_kind` 拆分、顺序执行两子批并合并 `DownloadBatchResult`。`max_workers` 传入值优先、None 才读 `cfg.max_workers.value`；逐项 `certain_*_typed`（**单个失败 `except Exception` 合成 FAILED 结果后继续**，不中断整批）；**一个 `Downloader` + 一个总进度条**；表情包目录 `包名[:60] [包ID]` 防同名覆盖、文件名截断。
- **`start_download` 返回 False** 表示下载目录不可用（未建任务、无 finished 信号）——调用点必须自行恢复按钮状态，否则按钮永久禁用。
- **卡片多选**（`PackageCard`/`DressCard`/`QueueCard` 同套路）：容器无 Layout（或外层布局 + 绝对定位勾选框）；图片是 `QPushButton(setFlat=True)`（点击整图切换勾选）；勾选框 `CheckBox` 用 `setGeometry` 钉在图片/卡片**左上角** + `raise_()`（右上角留给 `InfoBadge`「已下载」，两者同时显示）；选中背景通过 `toggled` 同步整卡样式表背景，**必须 `setAttribute(WA_StyledBackground)`**（普通 QWidget 默认不绘制 stylesheet 背景），且样式表必须用**类选择器**（`"QueueCard { background-color: ... }"`）限定自身——无选择器的通用规则会级联到子 label 造成文字区整块上色。`DressCard` 是纯 QWidget（**不用 `CardWidget`**：其基类 `mouseReleaseEvent` 只发 0 参数 `clicked`，与 `Signal(object)` 冲突 → 点击死）。多选/懒加载逻辑统一在 `_CardGridBase`，卡片只需暴露 `.item` / `set_selectable` / `set_checked` / `is_checked` / `set_pixmap` / `set_cell` / `clicked` / `toggled`（`EmojiCard` 为表情展示，多选相关给占位实现）。
- **代理**：所有 `Emoji/Dress/Downloader` 显式传 `proxies=`（requests 显式值优先于环境变量）。biliemoji 的 typed 下载方法不转发 proxies 给内部 Downloader → 用环境变量 `HTTP(S)_PROXY` 兜底。**Windows 上 `os.environ` 大小写不敏感**：`ProxyEnvManager` 只管理大写键（POSIX 才双写），清空设置时恢复快照原值而非删除。
- **消息提示**：用 `app/common/notify.py` 的 `notify_*`，**不要直接调 `InfoBar.*`**。InfoBar 内容**不要开 `wordWrap`**（会让 QLabel 最小宽度塌缩、内容压成极窄一列），垂直布局 + `TextWrap` 预换行即可。

## biliemoji 2.0.0 要点

- `Emoji`：`certain_emoji_typed(ids)` 按包 ID 查（含完整 emote）、`all_packages()` 全量（**需 cookie**，且只含包元信息、**不含完整 emote**，进详情须另调 `certain_emoji_typed`）、`download_package(ids, dest, gif=, max_workers=, on_progress=)`。
- `Dress`：`search_dress_typed(num, keyword)`（空结果抛 `DressNotFound`）、`certain_lottery_typed(act_id, lottery_id)`、`download_collection(act_id, lottery_id, dest, mode='image'|'video'|'both')`。
- **`DressCollectionSummary.is_collection` / `.dlc_act_id` / `.dlc_lottery_id` / `.id` 恒为 None/False**（API 把 id 以字符串返回，`_optional_int` 拒收字符串）。判别与取 id 一律走 `app/components/dress_helpers.py`（读 `summary.raw`：`properties.type` `'dlc_act'`=收藏集 / `'ip'`=装扮；dlc id 取 raw 字符串，可直接传 `certain_lottery_typed`）。
- **`download_package`/`download_collection` 不会把 `proxies` 传给内部 `Downloader`**（`emoji.py`/`dress.py` 里只建 `Downloader(max_workers, on_progress)`），文件下载代理只能靠环境变量兜底；需要显式代理的批量下载请用 `download_package_batch`。
- **没有关键词搜索表情包的接口**；"搜索表情包" = 按 ID 查询 + `all_packages` 本地关键词过滤。
- 模型类从 **`biliemoji.models`** 导入（`EmotePackage`/`Emote`/`DressCollectionSummary` 等，顶层不导出；`Downloader`/`DownloadResult`/`DownloadBatchResult` 等从顶层导出）。
- 错误层次 `BiliError`：`AuthRequired`(-101)、`EmojiNotFound`/`DressNotFound`(-404)、`NetworkError`、`DownloadError`、`ValidationError`。
- `EmotePackage.raw` 是完整原始 dict，缓存用它持久化、`from_dict` 无损重建。
- 全部表情包缓存（`cache.py`）：按 cookie 指纹 + 24h TTL 存 `%APPDATA%/biliEmojiDD/all_packages.json`；「全部表情包」页有「强制刷新」按钮绕过缓存。

## 验证

- 启动：`uv run python main.py`（弹窗，需人工查看）。
- **屏幕外脚本**（`QT_QPA_PLATFORM=offscreen`）：`scripts/` 下已有五个可直接跑的断言脚本（命令见「常用命令」）。新写脚本的套路：构建页面 + 注入假数据（假 `EmotePackage` / 预置 `QPixmapCache.insert(url, pm)` 绕开网络）+ 断言几何/信号/像素，失败 `sys.exit(1)`。
  - 涉及后台任务时**必须轮询等任务完成再退出**（见线程规则），不要 `processEvents()` 后立刻结束。
  - **等属性动画（展开/滚动）要等真实时间**：光 `processEvents()` 不推进时间，须 `processEvents()` + `time.sleep(0.01)` 轮询到目标状态（设置页展开断言曾因此假失败）。
  - 脚本从 `scripts/` 运行，开头需 `sys.path.insert(0, 项目根)` 才 import 得到 `app`。
  - 弹窗类组件用 `show()` 而非 `exec()`（offscreen 下 `exec()` 会阻塞脚本）。
- 真实 B 站网络流程（拉取、下载、收藏集搜索）依赖用户 Cookie，无法自动化，需人工验证。
- 每次改动后跑 `uv run ruff check .` 与导入自检（`uv run python -c "import app.MainWindow"`）。