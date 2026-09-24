# Qt / QFluentWidgets 界面与渲染规范

技术栈是 **Windows Fluent Design**（PySide6 + QFluentWidgets），不是 Material Design。
主题走 `qfluentwidgets.setTheme()` + QSS，没有 CSS 框架。

## 页面版式

- 页边距一律 `PAGE_MARGIN = 36`，大标题 / 分组标题 / 命令卡左边缘都对齐在 x=36。版式常量与底座
  统一放 `app/components/page_scaffold.py`（`PAGE_MARGIN` / `PAGE_TOP` / `PAGE_BOTTOM` /
  `SECTION_SPACING` / `page_title` / `title_row` / `CommandCard` / `SectionCard`）。
- 页面骨架固定「大标题 → 命令卡（工具栏）→ 内容」；标题行 `QHBoxLayout(36, 20, 36, 12)`，
  表情包页 Tab 内部 `(36, 0, 36, 24)`；`SectionCard` 内容区边距 `(12, 4, 12, 12)`。
- 缩进一律走**布局边距**，禁止用 `setContentsMargins` 给 Label 定缩进——`TitleLabel` 注册过
  `FluentStyleSheet.LABEL`，QSS 会覆盖手设值。
- 列表网格（`PackageCard` / `DressCard` / `QueueCard`）直接铺页面底色，**禁止卡中卡**；
  详情预览网格（`EmojiGrid` / `DressDetailGrid`）必须进 `SectionCard` 补承载面。
- 内容页承载面用 `SimpleCardWidget` / `HeaderCardWidget`，禁止用设置页专用的 `SettingCard` 那套。
- 详情页信息 + 操作合成一张头部卡，不拆成信息卡 + 底部操作卡。
- 所有可能变长的 Label 必须 `setWordWrap(True)`，否则 `minimumSizeHint` 顶起整页最小宽度
  （最小窗口 820 − 侧栏 150 − 页边距 72 ≈ 598px）。
- 固定尺寸子项顶起整卡最小宽度时用 `layout.setSizeConstraint(SetNoConstraint)`，放不下的项自己隐藏。
- 响应式只做**离散列数切换**（`resizeEvent → _reflow()`），列数没变直接 return；
  **禁止在 `resizeEvent` 里改几何约束**做按比例自适应。
- 往布局塞 `FlowLayout` 必须用覆写过 `hasHeightForWidth()` / `heightForWidth()` / `sizeHint()`
  并 `setHeightForWidth(True)` 的容器——`FlowLayout.sizeHint()` 只有一行高，会重叠。
- 页面里的 `QScrollArea` 必须显式透明 + 无边框（`QScrollArea{border:none;background:transparent}`
  + `.QWidget{background:transparent}`），否则暗色下露 palette Base 色块。
- `HeaderCardWidget.viewLayout` 是 `QHBoxLayout`，多行内容先包容器再 `add_widget()`。

## 网格与卡片

- 单元格宽算法 `n = min(8, max(1, vw // (min_cell.width() + _CARD_GUTTER)))`、
  `w = max(min_cell.width(), (vw - _CARD_GUTTER) // n)`，`_CARD_GUTTER = 8`；
  `PackageGrid` 返回 `QSize(w, w)`、`EmojiGrid` 返回 `QSize(w, w + 36)`。
- `QueueList._cell_size()`：`vw >= 2*min_w` 两列 `w = (vw - _CARD_GUTTER) // 2`，
  否则单列 `w = vw - _CARD_GUTTER`。
- 换行判据是闭区间 `列数 * cellW > 视口宽 - 1`；算单元格宽必须留余量，
  否则末列被挤到下一行、右侧空一整格。
- `DressDetailGrid` 列数上限禁止写死 8，要放开到「视口最多塞下几个最小卡」。
- **逐项 `item.setSizeHint(cell)` 不能省**（即使已 `setUniformItemSizes(True)` + `setGridSize`），
  去掉会横向溢出——已试过并回退。
- `_CardGridBase` 必须基于组件库 `ListWidget`（不是原生 `QListWidget`），五个网格共用。
- **网格设了 `gridSize()` 后 `QListView` 完全忽略 `spacing()`**，禁止用 `setSpacing` 做间隙，
  间隙必须做进单元格尺寸。
- 「首列与次列无间隙」（首列被右移 8px）是 `setItemWidget` 的定位行为，禁止试图用
  `setSpacing(0)` / `doItemsLayout()` / resize 重排解决；现行缓解是选中高亮 QSS 用 `margin: 4px` 内缩。
- 网格点击索引必须用建卡闭包固定下标（`partial(self._emit_clicked, index)` → `itemClickedAt`），
  **禁止用 `is` / 内容反查**——相同元组字面量会被 CPython 常量折叠成同一对象。
- 卡片四角分工：勾选框钉左上、`InfoBadge.success("已下载")` 挂右上、GIF 角标在左下，三者不得重叠。
- 选中态背景必须用**类选择器** `"QueueCard { background-color: ... }"` 限定自身，禁止通用规则
  （会级联到子 label，把文字区整块上色）。
- 选中背景计算收敛到幂等的 `_apply_card_bg(card, class_name, checked)`（状态没变直接 return）——
  建卡时会连调三次，`setStyleSheet` 占建卡耗时 30%。
- `QPushButton` 垂直 size policy 默认 `Fixed`，`QVBoxLayout` 加 `stretch=1` 也拉不撑；
  卡片必须 `setSizePolicy(Expanding, Expanding)`。
- 图标缩放走 memo 化的 `_apply_scaled_icon` / `_apply_scaled_pixmap` / `_rescale`，
  比较用 `is` 而非 `==`（`QPixmap.__eq__` 逐像素比，比重缩放还贵）。
- `DressCard` 名称 `setWordWrap(True)` + 固定两行高（`_NAME_H = 40` / `_TEXT_H = 76`）
  + `ToolTipFilter(self, 500, ToolTipPosition.TOP)` + `setToolTip(完整名)`。

## 主题与取色

- 组件库有的组件就用组件库的；**禁止自造控件、禁止手写 QSS 绕过主题机制**。
- 裸原生控件拿不到主题（`updateStyleSheet()` 只重刷注册过的控件）：列表用 `ListWidget`、
  按钮用 `TransparentPushButton`（`setIcon` 替代 `setArrowType`）。
- 文字一律用 `CaptionLabel` / `StrongBodyLabel` / `BodyLabel` + `setTextColor(light, dark)`。
- `bind_theme(widget, fn)`：`fn()` 立即执行 + 每次主题切换重执行；`fn` 必须是 widget 的
  绑定方法（靠 PySide6 自动断连防泄漏）。
- **`app.setPalette()` + `update()` 对网格容器无效**——`FluentWindow` 给 `stackedWidget` 套了 QSS，
  整棵子树被 `QStyleSheetStyle` 接管并缓存 palette。
- 主题保存顺序必须「**先 `setTheme` 再 `qconfig.set(cfg.theme, ...)`**」；`config.py` 加载后要
  `qconfig.set(qconfig.themeMode, cfg.theme.value, save=False)` 强制同步，
  否则 config.json 里 `QFluentWidgets.ThemeMode` 残留会导致反色。
- 取色直接用 `isDarkTheme()`（AUTO 已被 qconfig 解析成具体值）。
- 测试脚本里 `setTheme` 必须在 `import app.*` 之后调用；禁止把 `setTheme` 与断言 `cfg.theme` 混用
  （`cfg.theme` 由 `_on_theme_changed` / `_toggle_theme` 写）。
- `FluentIcon` 枚举名是 **`CONSTRACT`**（官方把 contrast 拼错），另有 `CHEVRON_DOWN_MED` /
  `CHEVRON_RIGHT`；主题下拉图标：跟随系统=SYNC、浅色=BRIGHTNESS、深色=CONSTRACT。
- **`FluentIcon` 按调用瞬间的主题取黑 / 白 svg，主题切换后必须重新 `setIcon`**。

## 上游组件坑（qfluentwidgets / PySide6）

- **`NavigationInterface.addWidget(onClick=fn)` 内部已连 `clicked`，禁止再手动 `connect`**
  ——连两遍会让切换动作跑两次、净效果为零。
- **`ToolButton` / `PushButton` / `InfoBadge` / `ImageLabel` / `PillPushButton` / `FluentLabelBase`
  的 `__init__` 是 `singledispatchmethod`，子类禁止覆写**，初始化走 `_postInit()` 钩子
  （它在 `setText` 之前执行，依赖文本的 tooltip 只能建完对象再设）。
- **`MaskDialogBase.setMaskColor` 的 B/G 参数写反**（`rgba(red, blue, green, alpha)`），
  只能用纯黑遮罩绕过，禁止改彩色。
- **`MaskDialogBase` 把 `self.widget` 无对齐塞进 `_hBoxLayout`**，必须 `removeWidget` 后
  `addWidget(self.widget, 1, Qt.AlignCenter)` 重新居中，否则「点遮罩空白处关闭」永远判不出来。
- `MaskDialogBase.showEvent` / `done()` 的 `QGraphicsOpacityEffect` 淡入淡出会拖垮含
  `QGraphicsVideoItem` 的 dialog，全屏遮罩必须覆写这两个方法直接调 `QDialog` 实现。
  `done()` 是 100ms 淡出，`finished` 延迟发出——测试等它必须轮询真实时间。
- **`FlipView._adjustItemSize` 按图片宽高比算 sizeHint**：空图 `ZeroDivisionError`、
  异步到位后滚动位置跑偏——必须覆写为固定 sizeHint + 预先 letterbox。
- `FlipView.setCurrentIndex` 在 `index == currentIndex()` 时早退不发信号；初始索引为 0 时
  必须手动同步一次 UI。自带 `ScrollButton` 是 16×38 且钉在最左 / 最右极边，
  必须 `preButton.hide()` / `nextButton.hide()` 一次性藏死。
- `FlipView` / `pips` / 翻页按钮都设 `NoFocus`（`FlipView` 继承 `QListWidget` 会吞方向键改 `currentRow`）。
- **`ComboBox` 闭合态不显示图标**（上游 `setCurrentIndex` 只 `setText`），必须自己 `setIcon`，
  三处调用缺一不可：建卡末尾、`currentIndexChanged`、`_sync_theme_combo` 的 `blockSignals` 块内；
  用 `bind_theme(self, self._sync_theme_icon)` 覆盖第一处。
- **`ComboBox.addItem(text, icon, userData)` 第二位置是 icon**，要 `currentData()` 有值
  必须 `addItem("文本", userData="值")`。
- `PipsPager.setCurrentIndex` 会发 `currentIndexChanged`（经 `scrollToItem`），
  `setPageNumber` 内部也会 `setCurrentIndex(0)`——接线必须放在它之后，双向绑定要加 guard。
- `TransparentToolButton` / `TransparentPushButton` 图标按主题取色（亮色=黑），
  压在深色遮罩上必须自己钉死（`FluentIcon.CLOSE.icon(color=QColor("white"))` + 自绘半透明圆底）。
- **`InfoBadge` 的 qss `min-width` 会把文字撑到 50px**，角标必须 `setFixedSize`（按 `fontMetrics()` 现算）；
  禁止用 `setStyleSheet` 改——已注册进 `styleSheetManager`，切主题会冲掉；改色用 `setCustomBackgroundColor`。
- `InfoBadge` 的 `InfoLevel` 只定语义、颜色必须显式给（`page_scaffold.status_badge(..., colors=(亮, 暗))`）：
  上游暗色主题 WARNING / ERROR 是浅底而 qss 把文字钉成 `color: white`。版本号胶囊统一用
  `page_scaffold.version_badge()`。
- `_update_theme_icon` 挂 `qconfig.themeChangedFinished`（`setTheme` 无条件发它，`themeChanged` 会同值短路）。
- 侧栏主题按钮用 `NavigationPushButton(icon, text, isSelectable, parent)`，
  不用只有 2 参的 `NavigationToolButton`。
- `HeaderSettingCard.addWidget` 只能调一次（每次都会 `removeItem` 再重加 `expandButton`），
  多个控件先包进无边距容器。`ExpandSettingCard` 没有 `setContent`，要写 `card.card.setContent(...)`。
- `ExpandLayout.count()` 恒为 0（只数 `addItem` 的 QLayoutItem），数卡片必须遍历子控件。
- `FlowLayout.itemAt(i)` 返回 `QWidgetItem`（要 `.widget()`），`takeAt(i)` 直接返回 widget。
  `takeAt` 清理用 `widget.setParent(None)` + `deleteLater()` 防残影；清空优先用库自带
  `takeAllWidgets()`，但常驻控件重建前必须先 `removeWidget` 摘出来，否则被一起 `deleteLater()`。
- `ListBase` 会额外装 `ListItemDelegate` + `SmoothScrollDelegate` + `setMouseTracking(True)`，
  并把原生滚动条置 `AlwaysOff`（浮层替代）——`viewport().width()` 不再因滚动条收窄。
- **上游 QSS 把字体族写死**（23 处 `font: 14px 'Segoe UI', ...`），QSS 优先级高于 `QWidget.setFont`；
  `LINE_EDIT` / `COMBO_BOX` 里那两行是注释掉的，所以「有的对有的不对」。
- **`QMovie(parent)` 传 `None` 会命中 `QIODevice*` 重载并在 `frameCount()` 段错误**（进程直接没）；
  必须无参构造再 `setParent`，`QBuffer` 挂在 movie 上。
- 带对齐标志的布局项拿的是 sizeHint 宽度、**不会被压缩**（`addWidget(w, 0, Qt.AlignRight)`
  会让窄窗口溢出）；横向 Expanding 的控件改用 `addWidget(w, 1)` 按 stretch 加，
  并设 `setMinimumWidth(150)` + `setMaximumWidth(320)`。
- `SearchLineEdit` 的 `searchSignal` 必须使用方自己接（库内部只把按钮连到自己的 `search()`，
  不接则点放大镜毫无反应）。
- `CardWidget.clicked` 是无参信号 `Signal()`，整卡可点直接用它。
- **`index.data(CheckStateRole)` 返回 int**，而 `Qt.CheckState` 在 PySide6 不是 IntEnum
  （`2 != Qt.CheckState.Checked` 恒 True），比较必须用 `.value`。
- 普通 `QWidget` 不绘制 stylesheet 的 `background-color`，需 `setAttribute(WA_StyledBackground)`
  （`QLabel` / `QFrame` 无此问题）。
- `MirrorSettingCard` 必须覆写 `setExpand`：先 `_adjustViewSize()` 算准高度，调完 `super()` 后
  收起方向自己停动画、滚动条推到底、`setFixedHeight(self.card.height())`
  （上游 `ExpandSettingCard` 覆写 `resizeEvent` 没调 `super()`，滚动条 range 停在构造期）。
- `FlipView` / `MaskDialogBase` / `PipsPager` 的上游 bug 已在 `app/components/image_viewer.py`
  绕过并注释，**勿「修回去」**。

## 字体与渲染

- `static/font/` 只放 TrueType / TTC / OpenType；woff / woff2 会被 `addApplicationFont()` 返回 -1，
  必须先离线转 ttf。
- 生效字体由 **`PREFERRED_FAMILY`**（`LXGW WenKai Mono GB`）这个显式常量决定，
  禁止依赖文件名排序取第一个。
- 必须打 `getFont` 补丁，并额外扫 `sys.modules` 把 21 个模块级 `getFont` 引用重绑；`setFont` 不用重绑。
- 必须再包一层 `getStyleSheetFromFile`（`_patch_stylesheet_font` + 正则 `_QSS_FAMILIES_RE`，
  单双引号与可选的 `PingFang SC` 都要匹配），否则按钮 / 勾选框 / InfoBar / 设置卡仍被 QSS 族名盖掉。
- 字体切换只能靠平台插件启动参数 `os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"`，
  **必须在 `QApplication` 构造之前设**；`QT_QPA_PLATFORM` 已被外部指定（如 `offscreen`）时不得覆盖。
- `FONT_ENGINES` 只给 `("default", "freetype")`——GDI 不支持、乱写的值 Qt 静默忽略不报警告。
- 应用字体与补丁后的 `getFont` 都设 `QFont.HintingPreference.PreferFullHinting`。
- 字重想用真粗体，把同族 ttf 丢进 `static/font/` 即可（`app_font_files()` 扫全目录、无需改代码）；
  字体缺失一律静默返回 `None`，不影响启动。
- **字体回归断言必须 `ensurePolished()` 之后再量**，否则量不出 QSS 覆盖这个 bug。
- 高 DPI 舍入策略是 `PassThrough`（`main.py`），本机 `devicePixelRatio = 1.25`。

## 滚动与性能

- 所有滚动区域 / 网格必须调 `page_scaffold.tune_scroll()`（`_CardGridBase.__init__` 里统一调一次）
  ——库默认 400ms 平滑滚动 = 一格滚轮 24 次整块重绘。
- `SCROLL_DURATION = 200` 固定；步数 `= fps * duration / 1000` **必须整除**
  （`fps * duration % 1000 == 0`），否则 `stepsTotal` 是小数、定时器永不停止且页面被反向滚动；
  `tune_scroll` 会 `raise ValueError` 拦住。
- 滚动帧率是设置项 `cfg.scroll_fps`（60 默认 / 120），`OptionsValidator` 兜底顺序里省 CPU 的 60
  必须排第一。
- 改滚动帧率即时生效无需重启：新建滚动区域天然跟随，已存在的由
  `page_scaffold.apply_scroll_fps()` 遍历 `QApplication.allWidgets()` 刷；
  `ScrollArea.scrollDelagate`（上游拼错）与 `ListBase.scrollDelegate` 两种属性名都要认。
- 加载环启停归网格管：`_sync_spinners(first, last)` 只对**差集**动手，建卡后从「全都在转」记账，
  `hideEvent` 全停并清账、`showEvent` 重新对齐。
- `thumb_restart()` 必须尊重 `_spinner_wanted`（右键「重新加载」不得把视口外的卡重新点着）；
  判「隐藏」一律用 `isHidden()` 而非 `isVisible()`。
- `_visible_index_range()` 用 `indexAt(QPoint(1, 1))` 当种子向两侧有界游走；
  **禁止用 `indexAt` 取两端**——IconMode 下右下角逐点常落在末列右侧空隙里、返回无效 index；
  判据是 `visualItemRect(...).intersects(viewport)`。
- 网格页必须由网格自己画背景并自己管环的脏区；不要指望 `QPalette` 取背景色
  （qfluentwidgets 全用 QSS 上色，`QPalette` 全黑）。
- **禁止「把子树塞进 `QOpenGLWidget` 提速」**——Qt Widgets 是 CPU 软件光栅，
  反而多一层离屏渲染；瓶颈是白烧的动画。
- 禁止给卡片设 `WA_OpaquePaintEvent`、禁止把网格套进外层 `QScrollArea` 借 blit、
  禁止把 item delegate 换成裸 `QStyledItemDelegate`——均已试过并回退。
- 网格隐藏 / 滚出视口时加载环必须停：一屏 150 卡全在转会白烧 **41.7% 单核**，
  且每次 tick 触发整块 viewport 重绘。

## 图片查看器

- 唯一入口 `show_image_viewer(items, index, parent)`，`items` 为 `[(name, url), ...]`；
  `parent` 必须传 `page.window()`（`MaskDialogBase.__init__` 直接读 `parent.width()`）。
- **所有 item 尺寸必须恒等**：覆写 `_ViewerFlipView._adjustItemSize` 为固定 `sizeHint = itemSize`，
  并把图预先等比缩放、居中合成到 `itemSize * dpr` 的透明画布（`_letterbox`），
  使 delegate 的 `scaled` 成为恒等变换。
- 画布宽 `min(int(parent.width() * 0.62), _MAX_W)`，`_MAX_W = 900`；
  目标框取「画布尺寸」与「原图 × `_MAX_UPSCALE`(=2)」的较小者。
- **图片加载必须先 `connect` 再 `request`**（命中 `QPixmapCache` 时是同步 emit，顺序颠倒会丢图）。
- 只预取当前索引 ± `_PREFETCH`(=2)；禁止一次性请求几十张（缩略图池只有 3 线程）。
- 未加载时显示 `_placeholder` 极淡白画布；`finished` 信号里 `disconnect(self._on_thumb)`；
  dialog 设 `WA_DeleteOnClose`。
- 翻页按钮在底部信息行（`‹ 名称 3 / 20 ›`，36×36），首尾禁用在 `_sync_ui()` 里跟着索引刷；
  禁止用上游贴边的小箭头。
- 关闭按钮贴在图片框右上角外侧，按 `self.widget` 几何算位置并用 `min` / `max` 夹住；
  `resizeEvent` 与 `showEvent` 各摆一次。
- 遮罩层上的按钮一律用本文件的 `_OverlayToolButton`（白色 svg + 半透明深色圆底 + `_postInit()`）。
- 页码：名称 + `"3 / 12"` 文字 + `HorizontalPipsPager`，超过 `_MAX_PIPS`(=15) 张时隐藏点只留文字。
- 图片地址用详情页给出的 `item.card_img_download` / `em.gif_url or em.url`，
  走 `thumb_manager` + `signal_bus.thumbLoaded`，**禁止新增网络代码**。
- 详情页 `_detail_items` / `_detail_videos` 必须在 `_open_detail` / `_show_detail` 里
  **同一次循环构建**，下标一一对应。

## GIF 动图

- **两套判定口径故意不统一**：角标显隐用数据字段（`pkg.is_gif` / `em.gif_url`），
  能不能播用原始字节（`QMovie.frameCount() > 1`）。
- `package_has_gif(pkg)` 必须取并集（`pkg.is_gif` **或** 包内任一 `em.gif_url`）——
  `all_packages()` 列表不含 emote，只有 `label_text` 可用。
- 播放唯一路径是 `image_cache.get(url) → QByteArray → QBuffer → QMovie`（`movie_from_cache`），
  不改线程层、不再发网络请求；字节拿不到一律返回 `None` 静默不播。
- 表情详情网格只播鼠标底下那一张：`EmojiCard.enterEvent` 起 movie、`leaveEvent` 停并退回静态图。
  `leaveEvent` 必须加 `rect().contains(mapFromGlobal(QCursor.pos()))` 判据，
  否则鼠标移到子控件上会「一进去就停」。`hideEvent` 与 `set_cell` 里也要停一次。
- 图片查看器打开即播：自己驱一个 movie，每帧 `_letterbox(movie.currentPixmap(), ...)` 合成后
  `setItemImage` 顶回去；三个触发点缺一不可——构造末尾、翻页、`_on_thumb`。
  只播当前项，翻页先停旧的再起新的；`_stop_movie()` 退回静态首帧；
  `_on_finished` 里必须停，movie 不得活过 dialog。
- 查看器帧率不够时把 `SmoothTransformation` 降成 `FastTransformation`。
- `EmojiGrid.set_emotes` 载荷第三位 `is_gif`：表情详情 / 按 ID 用 `bool(em.gif_url)`，
  直播间用 `LiveEmote.is_gif`（纯 `.gif` / `.webp` 后缀白名单）；**接口的 `is_dynamic` 不能当判据**。
  加第三位不破坏既有取值（`_cover_url(item)` 取 `item[1]`，老两元组调用照常可用）。
- GIF 角标必须 `WA_TransparentForMouseEvents`（不得吃掉图片区的点击 / 悬浮），
  定位靠给图片区装事件过滤器监听其 `Resize` / `Move`，不能只靠卡片自己的 `resizeEvent`。
- 图片查看器已支持动图播放，「GIF 只显示首帧」的旧限制作废。

## 内嵌视频

- 视频页左右按 1:2 **静态**分配（`_PLAYER_STRETCH = 1` / `_STRIP_STRETCH = 2`）。
- **禁止在 `resizeEvent` 里按画面比例写播放器宽度**（`_apply_aspect` + `setMaximumWidth`）——
  拖拽窗口每帧会跑好几轮「改宽 → 重排 → resize → `fitInView` + `setGridSize` 重排」，
  画面畸形 + 明显卡顿。`aspect_ratio()` 只在全屏遮罩打开那一刻用一次算容器尺寸。
- **禁止用 `QMediaPlayer.setSource(QUrl(远程地址))` 流式播放**（走 Media Foundation 自己的网络栈：
  读 Windows 系统代理、无法自定义 UA）；必须复用 `biliemoji.Downloader.download(DownloadTask(...))`
  先下到 `tempfile.mkdtemp(prefix="biliEmojiDD-video-")` 再播本地文件，
  `MainWindow.closeEvent` 里 `shutil.rmtree(ignore_errors=True)`。
- `video_cache` 用独立 `QThreadPool(2)`（不占 `task_manager` 的 4 个线程）；worker 只下载、
  经常驻 `signal_bus` 发 `videoRawReady`，主线程槽写缓存后广播 `videoReady`（载荷 None = 取不到）。
  `_failed` 记失败、本会话不重试，重来走 `forget(url)`。
- `signal_bus.videoReady` 的槽里必须 `if url != self._pending_url: return`，晚到信号不得顶掉当前画面。
- **`VideoWidget` 必须 `setBackgroundBrush(QColor(0, 0, 0))`**——上游 `GraphicsVideoItem.paint`
  用 `CompositionMode_Difference`，背景非纯黑会把整段视频反色；必须用 `backgroundBrush`
  而不是 `setStyleSheet`（`MEDIA_PLAYER` 已注册，切主题会重刷 QSS）。
- **控制条改造必须先 `clicked.disconnect()`**（上游已连 `skipBack(10000)` / `skipForward(30000)`），
  图标换 `CARE_LEFT_SOLID` / `CARE_RIGHT_SOLID` 接到 `play_prev` / `play_next`；首尾禁用 + 槽内
  边界判断越界直接 return，列表为空时连全屏按钮一起禁。全屏按钮塞进 `bar.rightButtonLayout`。
- `_VideoView` 必须覆写 `resizeEvent` / `enterEvent` / `leaveEvent` 调祖父类，
  跳过上游 `playBar.move()` / `setFixedSize()` / 淡入淡出，然后把 `self.view.playBar`
  直接 `addWidget` 到竖直布局里常显。
- **全屏必须复用现有播放器实例**（记下原布局下标与 stretch，`addWidget` 搬进遮罩、
  `insertWidget` 搬回），禁止新建播放器（会多一组 `QMediaPlayer` / `QAudioOutput`，
  声音重叠、进度从头）。搬家会触发 `VideoWidget.hideEvent` 的 `pause()`：搬前记 `is_playing()`、
  搬完 `resume()`；关闭方向必须覆写 `done()` 在 `QDialog.done` 之前记状态。
- 播放 / 暂停图标必须接 `player.playbackStateChanged` → `_sync_play_button`
  （上游只在 `mediaStatusChanged` 刷，`hideEvent` 里的自动 pause 会留下错误图标）。
- **`_VideoView` 必须覆写 `sizeHint()` / `minimumSizeHint()` 返回小常量，并在 `resizeEvent` 里
  `graphicsScene.setSceneRect(0, 0, view.width, view.height)`**——`QGraphicsScene` 未设 sceneRect 时
  返回只涨不落的 `growingItemsBoundingRect`，会把整条父链的 sizeHint 顶高且缩不回去。
- `VideoStrip` 栏数 = `avail // _TARGET_CELL_W`（`_TARGET_CELL_W = 120`），只要塞得下就至少两栏，
  项目数少于栏数时收敛到项目数。宽度必须按 `self.width()` 算而不是 `viewport().width()`，
  并固定预留 `_SCROLL_RESERVE = 22`，否则出现「滚动条出现 → 变窄 → 变矮 → 不再需要滚动条 → 变宽」的抖动。
- `VideoCard` 的播放角标必须 `WA_TransparentForMouseEvents`；`set_active(bool)` 样式表必须用
  类选择器 `VideoCard { ... }`。视频地址由页面按下标持有（`DressPage._detail_videos`），
  点击走 `itemClickedAt` 的下标闭包。
- **视频每项只取 `video_list[0]`**，与 `download_collection_batch` 建任务、
  `content_meta.collection_meta` 计数的口径严格一致。
- 播放状态生命周期固定：进新详情 `_reset_video_tab()`（停播 + 清两列表 + 回图片页）；
  切「静态图片」页 `videoPlayer.release()`；切「动态视频」页仅在 `is_idle()` 时加载
  `max(0, current_index())`；`_go_back` `release()`；关窗 `video_cache.cleanup()`。
- 已下载过的收藏集必须 `_adopt_downloaded_videos()` 按
  `collection_download_dir(summary) / f"{sanitize_filename(name)}.mp4"` 探本地文件并
  `video_cache.remember(url, path)`，同时认 summary 名与 `coll.name` 两个目录。

## 设置页

- 骨架：`SettingPage(QWidget)` → `QVBoxLayout(0,0,0,0)` → `QHBoxLayout(36, 20, 36, 12)`
  + `TitleLabel("设置")` → `ScrollArea`（透明 + 无边框 + 关横向）→ `ExpandLayout(36, 0, 36, 24)`
  spacing 28。
- **`SettingPage` 必须保持 `QWidget`**（不改成 `ScrollArea` 子类），以保证槽里
  `notify_*(parent=self, ...)` 的 InfoBar 定位行为不变。
- 分组为 关于 / 账号 / 下载 / 缓存 / 外观，每组卡片数 5/3/3/2/3，分组标题与卡片左边缘都对齐在
  `PAGE_MARGIN`。
- 横向 `Expanding` 的控件必须按 stretch 挂（`addWidget(w, 1)`），只给 min / max 不给固定宽度。
- `_WidgetSettingCard(icon, title, content, widgets, parent)`：在 `SettingCard.hBoxLayout` 末尾
  `addStretch(1)` 之后 `addWidget` 自然靠右排；必须用组件库控件（`PushButton` / `ComboBox` /
  `SpinBox`），而非 `PushSettingCard.button` 的裸 `QPushButton`。
- `_expand_row(widgets)` 用 `QHBoxLayout(48, 12, 24, 12)` 左缩进对齐标题列，并必须 `setFixedHeight`。
- Cookie / 下载目录用可展开卡片（输入框太宽，行内摆会在 600px 可用宽度下挤爆右侧控件）；
  未配置 Cookie 时构造即展开。
- 代理行现行控件是 `proxySwitch` + `proxyEdit` + `proxyTestBtn`；代理副标题精简为
  「留空不使用代理」，长提示（socks / 端口范围）挪到 `setToolTip`。
- 下载 / 线程数 / 代理 / 主题 / 字体渲染 / 滚动帧率一律**即时生效，无「保存」按钮**。
- `SpinBox` 宽度给少了数字会被上下按钮（约 64px）挤没：端口 130 / 线程 110。
- 设置页主题下拉的三个同步点必须齐全：`_sync_theme_icon()` + 三处调用 + `bind_theme`。
- 展开动画（`setExpand` 是 200ms `QPropertyAnimation`）与主题下拉的断言必须用
  `wait_until(cond, timeout)`（`processEvents` + `time.sleep(0.01)` 轮询）。

## 应用外壳

- splash 只能 import `config` / `resource` / `theme` / `page_scaffold`，
  **禁止碰 `app.view.*` 或 `app.MainWindow`**（用 `ast` 解析 import 做断言）。
- splash 进度更新走 `repaint()` 不走 `processEvents()`（构造期间没有事件循环，会重入事件派发）；
  只有 `start()` 里那一次 `processEvents` 安全。
- splash 不做动画（没有事件循环，转圈会僵帧）；`QVBoxLayout` 不设 `setAlignment`
  （会让每个子项只拿 sizeHint 宽度、`wordWrap` label 被压成细长一条），
  需要铺满的 `messageLabel` `addWidget` 不带对齐标志并 `setFixedHeight(两行)`。
- **禁止用上游 `SplashScreen`**（必须挂在已存在的 `FluentWindow` 上，且只有居中图标 + TitleBar）。
- 消息提示一律经 `app/common/notify.py` 的 `_resolve_parent()` 归一：挂到
  `widget.window().stackedWidget` 上并 `bar.raise_()`；调用点仍传自己的页面 widget。
- **切页必须跳过 `PopUpAniStackedWidget` 的 300ms 位移动画**，改为替换 `stackedWidget` 实例上的
  `setCurrentWidget` 方法（一次盖全侧栏点击 / 程序化 `switchTo` / 标题栏返回三个入口）；
  切前有动画在跑要 `stop()`，切完 `interface.move(x, 0)`。
- 侧栏展开宽度 `navigationInterface.setExpandWidth(150)`（库默认 322）。
- 表情包页 Pivot 顺序「全部表情包 → 按 ID 查询 →（直播间）」，默认停在 index 0
  （`setCurrentItem` 不触发 `onClick`，`onClick` 也不移动指示条，初始化两句都要写）。
- 主页必须放侧栏第一位（`FluentWindowBase.addSubInterface` 在 `stackedWidget.count() == 1` 时
  自动 `setCurrentItem` + `setDefaultRouteKey`，无需额外 `switchTo`）。
- 应用标识：`static/logo.ico` 走 `resource.py::STATIC_DIR`（文件缺失返回空 `QIcon`、不抛）。
