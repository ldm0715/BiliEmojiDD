# CLAUDE.md

**本文件只做两件事：给命令、给指针。** 功能背景、踩坑推导、实现细节全在 `docs/`（约 27 万字节），
**动手改某个功能前先读对应那篇**，不要从本文件的摘要里推断实现。

## 项目概述

B 站表情包 / 收藏集（装扮）下载器 GUI，中文界面。PySide6 6.4.2 + QFluentWidgets（GitHub fork 版）
+ `biliemoji==2.0.0`。五个页面：**主页**（启动默认页）、**表情包**（全部 / 按 ID / 直播间表情）、
**收藏集**、**下载**、**设置**。搜索历史挂浮层，缩略图与接口响应落盘缓存。

**许可 GPL-3.0-or-later**（根 `LICENSE`，署名 gcnanmu）——义务而非偏好：
`PySide6-Fluent-Widgets` 以 GPLv3 授权，本项目链接它并分发二进制，整体必须同样 GPLv3。
这**不解除**上游的商业限制（商用仍需向 zhiyiYo 购买授权）。

## 常用命令

```bash
uv sync                                   # 安装/重建依赖
uv run python main.py                     # 启动应用（会弹窗，需人工看）
uv run ruff check .                       # lint（--fix 自动修复）
uv run python -c "import app.MainWindow"   # 导入自检（连带验证 biliemoji/qfluentwidgets/PySide6）

# 屏幕外 GUI 验证脚本（无需 Cookie、不走网络）；脚本名即覆盖面，细节见各文件 docstring
QT_QPA_PLATFORM=offscreen uv run python scripts/check_image_viewer.py          # 查看器
QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py            # 网格点击下标
QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py          # 主题/双列/入队/侧栏
QT_QPA_PLATFORM=offscreen uv run python scripts/check_theme_switch.py          # 主题切换三处
QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py          # 设置页
QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py          # 三页版式 + 窄窗口
QT_QPA_PLATFORM=offscreen uv run python scripts/check_download_improvements.py # 下载体验
QT_QPA_PLATFORM=offscreen uv run python scripts/check_video_tab.py             # 收藏集视频页
QT_QPA_PLATFORM=offscreen uv run python scripts/check_search_cache.py          # 搜索历史/缓存
QT_QPA_PLATFORM=offscreen uv run python scripts/check_home_page.py             # 主页
QT_QPA_PLATFORM=offscreen uv run python scripts/check_proxy_hint.py            # 代理
QT_QPA_PLATFORM=offscreen uv run python scripts/check_shell.py                 # 应用外壳/字体
QT_QPA_PLATFORM=offscreen uv run python scripts/check_update.py                # 检查更新
QT_QPA_PLATFORM=offscreen uv run python scripts/check_reload.py                # 重新加载
QT_QPA_PLATFORM=offscreen uv run python scripts/check_splash.py                # 开屏面板
QT_QPA_PLATFORM=offscreen uv run python scripts/check_gif.py                   # GIF 角标与播放
QT_QPA_PLATFORM=offscreen uv run python scripts/check_login.py                 # 扫码登录
QT_QPA_PLATFORM=offscreen uv run python scripts/check_cookie_status.py         # Cookie 状态灯
QT_QPA_PLATFORM=offscreen uv run python scripts/check_live_emoji.py            # 直播间表情
QT_QPA_PLATFORM=offscreen uv run python scripts/check_clipboard.py             # 右键复制表情
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py            # 截图（**给用户人工比对，AI 不要跑**）

# 性能基准（非断言，不进收尾批跑）
QT_QPA_PLATFORM=offscreen uv run python scripts/bench_home_paint.py [--legacy] # 主页单帧重绘
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py [--legacy] # 网格滚动
# 真机帧率（**要窗口，别带 QT_QPA_PLATFORM**；默认档 60 / 加 --scroll-fps 120 对比）
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --seconds 8 --warmup 6 --no-net

# 主页展示图（非运行时；需网络，全量需 Cookie）
uv run python scripts/fetch_showcase.py --dry-run   # 先看要抓什么
uv run python scripts/fetch_showcase.py             # 抓+裁+写 static/showcase/

# 打包（详见 docs/update_and_packaging.md）
uv run python packaging/build.py                    # Nuitka standalone → dist/BiliEmojiDD/
uv run python packaging/build.py --installer        # 再加 NSIS 安装包 + 便携 zip + SHA256SUMS
uv run python packaging/changelog.py 0.1.0          # 抽某版本的更新说明

# 改动后的标准收尾：lint + 导入自检 + 全部断言脚本
uv run ruff check . && uv run python -c "import app.MainWindow" && \
for s in scripts/check_*.py; do printf "%-40s" "$s"; \
  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python "$s" >/tmp/o.txt 2>&1; tail -1 /tmp/o.txt; done
```

Windows 终端默认 GBK，中文断言文案会 `UnicodeEncodeError`——单跑脚本也要加 `PYTHONIOENCODING=utf-8`。
无测试框架（没配 pytest），GUI 逻辑全靠上面那些屏幕外断言脚本，每个自成一体、失败 `exit 1`。

## 环境约束（重要，勿改动）

- **Python 3.11**（`.python-version`）。**不要升 3.12**：qfluentwidgets 来自 fork
  `ldm0715/PyQt-Fluent-Widgets@PySide6`(v1.5.1)，`setup.py` 要求 `PySide6<=6.4.2`，而 6.4.2 无 py3.12 wheel。
  代码**禁用 PEP 701** 等 3.12 专属语法——嵌套 f-string 写 `('#' + str(x))`。
- **不要**把 qfluentwidgets 换回官方 PyPI 版：开源版都没有数字分页组件（`Pagination` 属 Pro 版），
  `app/components/page_bar.py` 的 `PageBar` 是自制的。
- 依赖声明在 `pyproject.toml`，`[tool.uv] package=false`（应用非库）。多两个运行时依赖：`PySocks`（`socks5://` 代理）、
  `segno`（二维码编码，只算矩阵、绘制交给 `QPainter`）；dev 组 `ruff` + `nuitka>=2.4`。
- **版本号唯一来源是 `pyproject.toml` 的 `[project] version`**（`app/common/version.py::project_version()` 读它，
  `packaging/build.py` 也读它）。改版本只改那一行，别在别处硬编码。
- **`main.py` 的调用顺序**：`apply_font_engine()` 必须在 `QApplication` **构造之前**（平台插件启动参数）；
  `apply_app_font(app)` 必须在 `import app.MainWindow` **之前**；`SplashWindow` 起在 `setTheme` 之后、
  那个 import 之前（要遮的正是这段 import + 五页构造）。

## 文档（`docs/`）

改哪个功能读哪篇，里面有本文件放不下的完整背景与推导：

| 文档 | 什么时候读 |
|---|---|
| `usage.md` | 面向用户的页面功能、Cookie 获取、缓存、常见问题 |
| `architecture.md` | 技术栈、**模块分层树**、线程模型、数据流、配置与缓存全清单 |
| `development.md` | 环境、代码约定、**关键坑点**、修改指南、验证流程 |
| `download_queue.md` | 下载队列初版（仅表情包）+ 下载设置 + 代理机制 |
| `collection_page.md` | 收藏集页改造 + 类别判别 + 混合队列 |
| `image_viewer.md` | 图片查看器 letterbox 方案 + **qfluentwidgets 上游坑全清单** |
| `ui_polish.md` | 暗色主题补全（全局调色板 + 主题化 Label）、网格响应式填充、下载双列 |
| `theme_grid_fixes.md` | 主题切换三处失效根因、`QListView` gridSize 忽略 spacing、目录命名统一 |
| `setting_page_redesign.md` | 设置页 Fluent 卡片版式 + 只改界面不改功能 + `ExpandSettingCard` 上游坑 |
| `page_card_layout.md` | 三页卡片版式底座 `page_scaffold`、长文本顶最小宽度等坑 |
| `download_page_improvements.md` | GIF 选项显隐、内容数量懒加载、全部成功自动出队、加载环三态、去重键根因 |
| `collection_video.md` | 内容分页 Pivot、内嵌播放器、**先下临时目录再本地播放**、`VideoWidget` 黑背景 |
| `search_and_cache.md` | 搜索历史浮层、磁盘缓存与容量、应用标识、`PillPushButton` 覆写坑 |
| `home_page.md` | 主页英雄卡/功能卡、`static/showcase` 素材、`_FlatImageLabel` 性能方案、滚动帧数 |
| `proxy_diagnostics.md` | 代理默认关、`trust_env=False`、`net.py` 联网工厂、`cause_hint` 成因表 |
| `app_shell.md` | 全局字体与 `getFont` 补丁、FreeType 后端、消息挂内容区、切页无动画 |
| `update_and_packaging.md` | 版本号单点、更新弹窗、加速镜像与 SHA-256、发版流程、Nuitka + NSIS |
| `reload_media.md` | 图片/视频失败重载、三层缓存作废顺序、`video_cache.forget` 边界 |
| `gif_preview.md` | GIF 角标与动图预览的两套口径、`QMovie(None)` 段错误 |
| `login.md` | 扫码登录接口与状态机、Cookie 提取双路径、轮询竞态、二维码绘制 |
| `cookie_status.md` | 五态状态机、7 天 / 30 分钟信任期、状态灯配色、静默预拉取 |
| `live_emoji.md` | 直播间三个接口、`room_<id>_` 过滤口径、队列第三类、两套 GIF 口径 |
| `clipboard_copy.md` | 右键「复制表情」、CF_DIB 装不下动画 / 动图落文件走 CF_HDROP、`image_cache` 取字节的三层降级、范围只到 `EmojiGrid` |
| `performance.md` | 帧率三个真凶的实测数字、加载环启停归网格管、可视区间游走、**滚动帧率设置项**、试过并回退的做法 |
| `fps_testing.md` | **帧率怎么测**：真机脚本的完整命令、看哪三行、达标判据、结果解读、踩坑速查 |

**新增功能时同步更新**：`docs/` 下新建一篇（结构参照 `download_queue.md`），并登记进
`docs/README.md` 导航表与根 `README.md` 文档列表。

## 硬规矩

每条都踩过坑，出处见括号。改到相关代码时先照着做，别「顺手改回去」。

**线程与信号**

- 所有网络 I/O 在后台线程，结果经 Qt 信号回主线程；**worker 禁止直接改控件**。
- `QPixmap` 只能在主线程创建/使用；worker 只产 `QImage` 或字节数据。
- **`on_progress` 统一协议 `(done, total, result)`**：`result is None` 表示准备阶段；
  自定义下载闭包必须是 `def task(on_progress=None):` 并透传（缺参抛 `TypeError`）。
- **清「正在飞」标志必须挂 `on_finished`**：成功与两条异常路都会走它，只挂 `on_success`
  会让失败一次之后永远不再重试（`development.md` 坑点 1）。
- 带载荷的信号不能直接接无参槽（`cookieStateChanged` 带 `str`），要包一层转发。

**联网与配置**

- **新增联网代码一律走 `app/common/net.py` 的工厂**（`make_client`/`make_emoji`/`make_dress`/
  `make_downloader`/`make_session`/`make_bili_session`），别直接 new 上游对象。工厂保证两件事：
  代理只来自设置页、**`trust_env = False`**（否则 requests 会读系统代理并覆盖显式 `proxies`）。
- 布尔配置项用 `_StrictBoolValidator(默认值)`，**别用上游 `BoolValidator`**（非法值兜底恒为 `True`）。
- 界面与文件不允许有机会不一致：设置项**改完即落库**，不做「点保存才生效」（`development.md` 坑点 5）。

**布局与渲染**

- **不换行的 `QLabel` 会把整页最小宽度顶起来**（`minimumSizeHint` 就是整串文字宽度）——
  标题/元信息/提示类一律 `setWordWrap(True)`。`QStackedWidget` 的最小尺寸**含隐藏页**，会外溢到整页。
- **给整个布局 `setAlignment` 会让每个子项只拿 sizeHint 宽度**；居中交给子项自己的对齐标志，
  要铺满整行的项 `addWidget(w)` **不带**标志（`app_shell.md`）。
- **有 QSS 的控件 `setContentsMargins` 会被忽略**，缩进走**布局边距**（`page_card_layout.md`）。
- **别在 `resizeEvent` 里写几何约束**（`setMaximumWidth`/`setFixedSize`）做「按内容自适应」：
  离屏跑一次收敛、断言全过，但交互拖拽时每帧跑好几轮「改约束 → 重新布局 → 又 resize」会卡且畸形。
  改用**静态 stretch 分配**（`collection_video.md`）。
- **页面里放 `QScrollArea` 必须显式透明**（`docs/ui_polish.md`）。
- **裸 `QListWidget` / `QToolButton` 拿不到主题**，用组件库控件；文字用 `CaptionLabel`/`BodyLabel`/
  `StrongBodyLabel` + `setTextColor(light, dark)`，**别再给它们 `setStyleSheet` 设颜色**。
- **`QGraphicsView` 的 `sizeHint()` 跟着只涨不落的场景矩形走**：`VideoWidget` 必须
  `setSceneRect` 钉住 + 覆写 `sizeHint`/`minimumSizeHint`（`collection_video.md`）。
- **`qfluentwidgets` 的 `VideoWidget` 必须配纯黑背景**（`setBackgroundBrush`，不是 `setStyleSheet`），
  否则视频反色（`collection_video.md`）。
- **图形特效不要叠在持续刷新的内容上**（`MaskDialogBase` 的淡入淡出 + 视频 → 全屏卡顿）。
- **滚轮平滑帧率只有一个出口 `tune_scroll`，取值只来自 `cfg.scroll_fps`**（设置页「外观 → 滚动帧率」，
  60 默认 / 120）。**`fps * duration % 1000` 必须整除**，否则 `stepsTotal` 是小数、`__smoothMove`
  永远减不到 0，那一格滚轮永久留在队列里、定时器再也不停。改这个设置要
  `apply_scroll_fps()` 刷已存在的滚动区域（新建的构造时自己读配置），**不需要重启**（`performance.md`）。
- **加载环的启停归网格管**（`_CardGridBase._sync_spinners` 只动差集，`hideEvent` 停光、`showEvent` 对齐）；
  卡片级默认仍是「建卡即转」，独立建卡的断言靠这个默认值（`performance.md`）。

**qfluentwidgets 用法**

- **`ComboBox.addItem(text, icon, userData)`**：第二位置参数是 **icon**，要 `currentData()` 有值必须
  `addItem('文本', userData=值)`（`development.md` 坑点 7）。
- **不要覆写组件库控件的 `__init__`**（库用 `singledispatchmethod` 内部会再调一次，子类必填位置参数直接
  `TypeError`），初始化走库留的 **`_postInit()`**（`InfoBadge` 没有这个钩子，只能覆写 `sizeHint`）。
- **`NavigationInterface.addWidget(..., onClick=fn)` 已经连了 `widget.clicked`**，再手动 connect 就是双触发。
- **改上游组件按钮的行为前先 `clicked.disconnect()`**。
- **`InfoBar` 的 `duration=0` 是「立刻消失」**，不消失要**负数**（用 `notify.NEVER_DISMISS`）。
- **`Pivot` 的 `setCurrentItem` 与 `onClick` 互不触发**，程序化切页两句都要写。
- 遮罩层上的按钮**必须自己钉死颜色**（`FluentIcon.X.icon(color=QColor("white"))`），
  否则亮色主题下黑图标压在黑遮罩上等于隐身（`image_viewer.md`）。
- `FluentIcon` 枚举名是 **`CONSTRACT`**（官方拼错）；`NavigationToolButton(icon, parent)` 没有 text 参数。
- 消息提示用 `app/common/notify.py` 的 `notify_*`，**不要直接调 `InfoBar.*`**；InfoBar 内容不要开 `wordWrap`。

**卡片网格（`widgets.py`）**

- **卡片下标不要靠载荷身份反查**：内容相同的元组会被 CPython 常量折叠成同一对象，用 `is` 反查会判错下标；
  基类用建卡时的 `partial(self._emit_clicked, index)` 闭包（`development.md` 坑点 4）。
- `_CardGridBase` 一律 `setSpacing(0)` + 按 `(vw - _CARD_GUTTER) // 列数` 均分铺满
  （`setGridSize()` 后 `setSpacing()` 被忽略）；换行判据是 `列数 * cellW > 视口宽 - 1`（`theme_grid_fixes.md`）。
- 卡片高度正比于宽度的网格，**宽度按 `self.width()` 而非 `viewport().width()`** 算，防滚动条抖动。
- `_SpinnerMixin` 的早退判据用 **`isHidden()` 不是 `not isVisible()`**；收环三条路径缺一不可
  （`download_page_improvements.md`）。

**屏幕外断言脚本**

- **假图 URL 要预置 `QPixmapCache`**，否则每个 URL 排一个 15s 超时任务、脚本退不出去。
- **脚本要先隔离 `APPDATA`**（在 `import app.*` **之前** `os.environ["APPDATA"] = tempfile.mkdtemp(...)`），
  否则写脏用户真实的 `config.json` / 历史 / 缓存。
- **按涉及面关掉联网开关**：`content_meta` / `video_cache` / `updater` / `bili_login` / `cookie_status` /
  `live_emoji` 的 `set_enabled(False)`——构造 `MainWindow` 或显示主页的脚本要关前几个。
- 涉及后台任务**必须轮询等任务完成再退出**（否则看到 `Internal C++ object already deleted` 假象）；
  等属性动画要**等真实时间**（`processEvents()` + `time.sleep`，并轮询 `QPropertyAnimation.state()`）。
- 隐藏的 Tab 不参与布局，几何断言前先切到该页；弹窗用 `show()` 而非 `exec()`。
- **量帧率不要用手写 `processEvents()` + `time.sleep()` 循环**：Windows 会把 2 ms 的休眠放大到
  ~15.6 ms，循环每秒只转 60 来次，**可测帧率被卡在 ~64 fps**，120 帧那档永远量不出来。
  用 `app.exec()` + `QTimer`（`scripts/bench_app_fps.py`），或只看不依赖测量方式的「绘制占用」（`fps_testing.md`）。
- **`bench_*.py` 不联网、不弹窗**：假图 URL 预置进 `QPixmapCache`（缓存上限 64 MB，用 128×128 的小图，
  600×600 × 300 张会把先塞的挤掉、退化成真网络请求）；真机帧率那条**不能带 `QT_QPA_PLATFORM=offscreen`**，
  且要 `--no-net`（否则更新检查 / Cookie 探测在 idle 也刷出几百次重绘）。

## biliemoji 2.0.0 要点

- `Emoji`：`certain_emoji_typed(ids)` 按包 ID 查（含完整 emote）、`all_packages()` 全量
  （**需 cookie**，且只有包元信息、**不含完整 emote**，进详情须另调前者）、
  `download_package(ids, dest, gif=, max_workers=, on_progress=)`。
- `Dress`：`search_dress_typed(num, keyword)`（空结果抛 `DressNotFound`）、
  `certain_lottery_typed(act_id, lottery_id)`、`download_collection(..., mode='image'|'video'|'both')`。
- **`DressCollectionSummary.is_collection` / `.dlc_act_id` / `.dlc_lottery_id` / `.id` 恒为 `None`/`False`**
  （API 把 id 以字符串返回，`_optional_int` 拒收）。判别与取 id 一律走 `app/components/dress_helpers.py` 读 `raw`。
- **`download_package` / `download_collection` 不把 `proxies` 传给内部 `Downloader`**；需要显式代理的
  批量下载用 `download_runner` 的 `download_*_batch`。
- **没有关键词搜索表情包的接口**；「搜索表情包」= 按 ID 查询 + `all_packages` 本地过滤。
- 模型类从 **`biliemoji.models`** 导入；`Downloader`/`DownloadResult`/`DownloadBatchResult` 从顶层导出。
- 错误层次 `BiliError`：`AuthRequired`(-101)、`EmojiNotFound`/`DressNotFound`(-404)、`NetworkError`、
  `DownloadError`、`ValidationError`。
- 全部表情包缓存（`cache.py`）：按 cookie 指纹 + 24h TTL 存 `%APPDATA%/biliEmojiDD/all_packages.json`。

## 验证

**不要自己截图验证 UI**。`scripts/screenshot_pages.py` 的产物是给用户人工比对的——离屏渲染跟真实观感
对不上，看图下结论只会得出错误判断。一律用 `scripts/check_*.py` 那种**可断言的屏幕外脚本**
（量几何、量状态、量信号）；量不出来的部分如实说「这条需要人工看」，不要假装验证过。

- 每次改动后：`uv run ruff check .` + 导入自检 + 跑全量 `check_*.py`（命令见「常用命令」收尾那行）。
- 新写脚本的套路与两个必须等的东西（后台任务、属性动画）见上「屏幕外断言脚本」。
- 真实 B 站网络流程（拉取、下载、收藏集搜索、Cookie 失效）依赖用户 Cookie，**无法自动化，需人工验证**。
- 完全未验证的改动要明说，别用「应该没问题」糊过去。
