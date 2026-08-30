# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

B 站表情包 / 收藏集（装扮）下载器 GUI，中文界面。PySide6 6.4.2 + QFluentWidgets（fork 版）
做界面，`biliemoji==2.0.0` 提供 B 站接口能力。

五个页面：**主页**（启动默认页：应用介绍 + 状态概览 + 功能入口卡 + 快速上手 / 关于 / 最近搜索）、
**表情包**（按 ID 查询 / 全量列表 + 包详情下载）、**收藏集**（关键词搜索 + 详情预览，
内容分页成静态图片网格与动态视频内嵌播放）、**下载**（会话级混合队列，批量下载）、**设置**
（关于 / Cookie / 目录 / 代理 / 线程数 / 缓存上限 / 主题）。搜索框挂浮层搜索历史，缩略图与接口响应
落盘缓存（`disk_cache` / `api_cache`），主页展示图为入库的静态素材（`static/showcase`）。
设置页「关于」组可查 GitHub Release 更新并下载安装（`packaging/` 下是 Nuitka + NSIS 打包，
`.github/workflows/release.yml` 打 tag 即发布）。
功能细节见 `README.md` 与 `docs/`，实现要点见下文「架构」。

**许可 GPL-3.0-or-later**（根目录 `LICENSE`，署名 gcnanmu）——不是偏好而是义务：
`PySide6-Fluent-Widgets` 以 GPLv3 授权，本项目链接它并分发二进制，整体必须同样 GPLv3。
注意这**不解除**上游的商业限制（商用仍需向 zhiyiYo 购买授权），见 `README.md` 许可小节。

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
QT_QPA_PLATFORM=offscreen uv run python scripts/check_setting_page.py   # 设置页：功能控件仍在/测试按钮加载环/版式/展开/窄窗口/主题
QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py   # 三页版式：控件仍在/大标题对齐/多选行/详情卡/窄窗口
QT_QPA_PLATFORM=offscreen uv run python scripts/check_download_improvements.py  # 下载体验：GIF行/内容数量/自动出队/加载环/去重键
QT_QPA_PLATFORM=offscreen uv run python scripts/check_video_tab.py      # 收藏集视频页：Pivot/选择条/高亮/续播/黑背景
QT_QPA_PLATFORM=offscreen uv run python scripts/check_search_cache.py   # 搜索历史浮层/磁盘缓存/接口缓存/触发时机/设置页身份头
QT_QPA_PLATFORM=offscreen uv run python scripts/check_home_page.py      # 主页：功能卡路由/英雄卡状态/队列预览/展示图降级/响应式列数/滚到底
QT_QPA_PLATFORM=offscreen uv run python scripts/check_proxy_hint.py     # 代理：地址规范化/旧 API 已删/trust_env=False/开关语义/因果翻译
QT_QPA_PLATFORM=offscreen uv run python scripts/check_shell.py          # 应用外壳：内置字体+首选族名+getFont 补丁/渲染后端/消息挂内容区/切页无动画
QT_QPA_PLATFORM=offscreen uv run python scripts/check_update.py         # 检查更新：版本比较/镜像增删改排/测速分档/关于组/更新弹窗/CHANGES 抽取/SHA-256/版本胶囊/加速卡收起
QT_QPA_PLATFORM=offscreen uv run python scripts/check_reload.py         # 重新加载：缓存作废顺序/网格失败态重试按钮/右键路径/video_cache.forget 不误删下载产物
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py     # 各页面亮/暗截图到 screenshots/（人工比对用）

# 主页展示图（非运行时代码，只在需要更新素材时手工跑；需网络，全量表情包需 Cookie）
uv run python scripts/fetch_showcase.py --dry-run   # 先看要抓什么
uv run python scripts/fetch_showcase.py             # 抓好裁好写进 static/showcase/

# 打包（详见 docs/update_and_packaging.md）
uv run python packaging/build.py                    # 只编译（Nuitka standalone → dist/BiliEmojiDD/）
uv run python packaging/build.py --installer        # 再加 NSIS 安装包 + 便携 zip + SHA256SUMS
uv run python packaging/changelog.py 0.1.0          # 看某版本从 CHANGES.md 抽出来的更新说明

# 一次跑完 lint + 导入自检 + 全部断言脚本（改动后的标准收尾）
uv run ruff check . && uv run python -c "import app.MainWindow" && \
for s in scripts/check_*.py; do printf "%-40s" "$s"; \
  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python "$s" >/tmp/o.txt 2>&1; tail -1 /tmp/o.txt; done
```

Windows 终端默认 GBK，脚本里的中文断言文案会 `UnicodeEncodeError`——单跑某个脚本时也加
`PYTHONIOENCODING=utf-8`。

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
| `docs/image_viewer.md` | 图片查看器：letterbox 方案 + **翻页按钮下移到底部信息行、关闭按钮贴图片右上角并固定白图标圆底** + qfluentwidgets 上游坑全清单 |
| `docs/ui_polish.md` | UI 改进：暗色主题补全（全局调色板 + 主题化 Label）、网格响应式填充、下载双列 + 去阴影、侧栏主题切换 |
| `docs/theme_grid_fixes.md` | 主题跟随 + 网格铺满 + 已下载徽标：主题切换三处失效根因、`QListView` gridSize 忽略 spacing、收藏集目录命名统一 |
| `docs/setting_page_redesign.md` | 设置页改版：Fluent 设置卡片版式（分组 + 窄卡片 + 可展开行）、只改界面不改功能的落实、`ExpandSettingCard` 上游坑 |
| `docs/page_card_layout.md` | 三页卡片版式：表情包 / 收藏集 / 下载页的大标题 + 命令卡 + 内容卡、`page_scaffold` 共用底座、长文本顶最小宽度等坑 |
| `docs/download_page_improvements.md` | 下载体验优化：GIF 选项按需显隐、队列内容数量懒加载（`content_meta`）、全部成功自动出队（`BatchReport`）、缩略图加载环、**收藏集去重键 `item_id` 非唯一**的根因 |
| `docs/collection_video.md` | 收藏集视频预览：内容分页 Pivot、内嵌播放器 + 缩略图选择条、**先下到临时目录再本地播放**（`QMediaPlayer` 不读应用内代理）、`VideoWidget` 必须配黑背景否则反色 |
| `docs/search_and_cache.md` | 搜索历史浮层面板 + 磁盘缓存 + 应用标识：`PillPushButton` 不能覆写 `__init__`、hover 删除按钮的 leaveEvent 坑、mtime 当 LRU 时间戳、`api_cache` 无损重建、窗口图标与版本号 |
| `docs/home_page.md` | 主页（欢迎页）：英雄卡 + 功能入口卡 + 快速上手 / 关于 / 最近搜索、`static/showcase` 静态素材与抓取脚本、**`ImageLabel` 每帧平滑缩放**、**`FlowLayout` sizeHint 只有一行高导致重叠**、定尺寸子项顶高最小宽度、`SmoothScroll.duration` 步数必须为整数 |
| `docs/proxy_diagnostics.md` | 代理：**只认设置页里那一个地址**（开关 + 地址框）、**`trust_env=False`** 断开 Windows 系统代理这条暗线、`app/common/net.py` 联网工厂、`cause_hint` 成因表、设置页「测试」按钮 |
| `docs/app_shell.md` | 应用外壳：全局字体 LXGW 文楷等宽（**Qt 不认 woff2**、首选族名、qfluentwidgets `getFont` 硬编码字体族需打补丁 + `sys.modules` 重绑）、**FreeType 渲染后端**（`gdi` 实测无效）、消息提示统一挂 `stackedWidget`、**切页去掉上游 300ms 整页位移动画** |
| `docs/update_and_packaging.md` | 检查更新与打包发布：**版本号唯一来源是 `pyproject.toml`**、GitHub Release 查询与更新弹窗（`MessageBoxBase` 的 yesButton 要先 disconnect）、**下载加速镜像 ≠ 代理**、自定义源的增删改排（三个配置项分工 + 「先算顺序再改成员」）、测速三档与三色胶囊、手写拖动排序、**校验和固定直连取**、`CHANGES.md` 发版流程、Nuitka 参数逐条 + NSIS + 工作流、**非 ASCII 用户名下 Nuitka 的三处坑**、版本胶囊、**`ExpandSettingCard` 收起动画终值取到陈旧滚动条 range 导致「收不回去」** |

| `docs/reload_media.md` | 重新加载：图片 / 视频加载失败后的右键菜单与可点击失败态、**三层缓存作废必须先清 `QPixmapCache` 再 request**、`video_cache.forget` 只删自己 mkdtemp 出来的临时文件（不碰下载产物）、`_SpinnerMixin` 的加载中 / 失败 / 重来三态 |

**新增功能时同步更新**：`docs/` 下新建一篇（结构参照 `download_queue.md`），并登记进 `docs/README.md` 导航表与根 `README.md` 文档列表。

## 环境约束（重要，勿改动）

- **Python 3.11**（`.python-version`）。**不要升级到 3.12**：qfluentwidgets 来自 GitHub fork `ldm0715/PyQt-Fluent-Widgets@PySide6`（v1.5.1），其 `setup.py` 要求 `PySide6<=6.4.2`，而 6.4.2 无 py3.12 wheel。代码禁用 PEP 701（f-string 内嵌同引号）等 3.12 专属语法——嵌套 f-string 请用 `('#' + str(x))` 之类写法。
- **不要**把 qfluentwidgets 换回官方 PyPI 版（`PySide6-Fluent-Widgets[full]`）。开源版（官方与 fork）都没有数字分页组件（`Pagination` 属 Pro 版），`app/components/page_bar.py` 的 `PageBar` 是自制组件。
- 依赖声明在 `pyproject.toml`，`[tool.uv] package=false`（应用非库）。运行时依赖多一个 `PySocks`（代理地址写 `socks5://` 时要用）；dev 组是 `ruff` + `nuitka>=2.4`（只打包时用）。
- **版本号唯一来源是 `pyproject.toml` 的 `[project] version`**：运行时 `app/common/version.py::project_version()` 读它，`packaging/build.py` 也读它。改版本只改那一行，别在别处硬编码；主页与设置页三处显示都走 `APP_VERSION`。
- `main.py` 里 `QApplication` 建好后、`import app.MainWindow` **之前**必须调 `apply_app_font(app)`；`apply_font_engine()` 则要在 `QApplication` **构造之前**（平台插件启动参数），见 `app/common/font.py` 的时机说明。

## 架构

- `main.py`：入口。**先建 `QApplication` 再导入 `MainWindow`**（保证控件/信号在主线程构造）；两者之间调 `apply_app_font(app)` 装内置字体并给 qfluentwidgets 打补丁；`setTheme(cfg.theme.value)` 应用主题；`app.setWindowIcon(app_icon())` 设任务栏图标。**第一句是 `apply_font_engine()`**（字体渲染后端是平台插件参数，必须早于 `QApplication`）。**不再动任何代理环境变量**（代理只经 `proxies=` 显式传）。
- `app/MainWindow.py`：`FluentWindow` **五页导航**（主页/表情包/收藏集/下载/设置，设置在 BOTTOM）。**主页放第一个 `addSubInterface`** —— 上游在 `stackedWidget.count()==1` 时自动 `setCurrentItem` + `setDefaultRouteKey`，它自然成为启动页，不需要额外 `switchTo`。**切页无动画**：`_set_current_interface()` 跳过上游 300ms 的整页位移动画，并直接换掉 `stackedWidget` 实例上的 `setCurrentWidget`（覆盖侧栏点击 / `switchTo` / 标题栏返回三条路径，见坑点）。主页只发信号（`navigateRequested` / `searchRequested`），窗口的 `_navigate` / `_search_from_home` 负责 `switchTo` 并调用目标页的公开入口（`EmojiPage.query_package_id` / `filter_packages`、`DressPage.search_keyword`），主页不反向引用窗口。窗口标题 `BiliEmojiDD` + `setWindowIcon`——**不用自定义标题栏**，`FluentTitleBar` 自带 `iconLabel`/`titleLabel` 且已连 `windowIconChanged`/`windowTitleChanged`。侧栏展开宽度 `setExpandWidth(150)`；主题切换按钮（`NavigationPushButton`，插在设置之前，展开时显示「主题」文字）随主题换图标（亮色=`CONSTRACT`、暗色=`BRIGHTNESS`），点击切换 `LIGHT/DARK` 并持久化 + `signal_bus.configChanged` 让设置页下拉同步。**接线只走 `addWidget(onClick=...)`，不要再手动 connect `clicked`**（会双触发）。**启动 3 秒后静默检查更新**（`cfg.auto_check_update` 开时）：`_auto_check_update` → `run_task(fetch_latest_release)`，**失败彻底静默**（`on_error=lambda e: None`），有新版才发一条带「查看更新」按钮的 InfoBar，**不弹模态窗**。`closeEvent` 里：有运行中下载时弹确认（下载不支持安全中断，退出会残留 `.part`）；`task_manager.clear_pending()` 只清未开始任务。
- `app/common/`：
  - `config.py`：`AppConfig(QConfig)` 单例 `cfg`，**持久化到 `%APPDATA%/biliEmojiDD/config.json`**（不写项目目录）。项：`cookie`、`download_dir`、`default_gif`、`max_workers`(1–16)、`proxy_enabled`(默认关)、`proxy`、`cache_limit_mb`(64–8192 MB)、`theme`、`font_engine`(default/freetype)、`auto_check_update`(默认**开**)、`gh_mirror`(当前加速源，默认空=直连)、`custom_mirrors`(用户加的源，成员)、`mirror_order`(所有源的顺序)。`theme` 项必须带 `EnumSerializer(Theme)`（否则 JSON 序列化崩）；**`gh_mirror` 反过来不能带 `OptionsValidator`**——取值集合随用户增删而变，写死校验器会让自定义源一保存就被打回默认值。`qconfig.load` 后会同步 `qconfig.themeMode` 到 `cfg.theme.value`（否则配置文件里残留的 `QFluentWidgets.ThemeMode` 会覆盖应用主题导致反色）。另有 `_migrate_proxy_enabled()`：老配置里没有 `proxyEnabled` 键而 `proxy` 非空时置 True（升级不断网；只认「键不存在」，用户自己关掉后不会被翻回来）。还有 `APP_NAME` / **`APP_VERSION`（运行时读 `pyproject.toml`，见 `version.py`——改版本只改那一处）** / `APP_CONFIG_DIR` / `CONFIG_FILE` / `FONT_ENGINES` / 仓库常量 `REPO_*` `LATEST_RELEASE_API` / 内置镜像表 `GH_MIRRORS` `GH_MIRROR_CHAIN`。
  - `version.py`：`project_version()` 用 `tomllib` 读 `pyproject.toml` 的 `[project] version`（`package=false` 拿不到 `importlib.metadata`），读不到返回 `"unknown"`——**故意是个解析不出来的值**，`is_newer` 遇到它返回 False，检查更新会安静地不提示而不是天天弹窗。另有 `parse_version` / `is_newer`（补零对齐、正式版 > 同号预发布、脏 tag 一律 False）。
  - `resource.py`：`PROJECT_ROOT` / `STATIC_DIR` / `PYPROJECT_PATH` / `APP_ICON_PATH` / `app_icon()`——文件缺失返回空 `QIcon` 不抛。**`_project_root()` 分两种情形**：源码运行按本文件回溯两级到项目根；**Nuitka 编译后（模块里有 `__compiled__`）取 exe 所在目录**（`__file__` 那时指向 dist 内的虚拟路径，回溯不得）。另有主页素材入口 `SHOWCASE_DIR` / `showcase_images(kind, limit)` / `showcase_names(kind)`（读 `static/showcase/manifest.json` 定序，清单缺失退回文件名排序，**目录不存在返回 `[]`**，主页据此隐藏缩略图带）、内置字体入口 `FONT_DIR` / `app_font_files()`（扫 `static/font/` 下的 `.ttf`/`.otf`/`.ttc`；目录里现在只有 LXGW 文楷等宽）与两个依赖徽标 `QFLUENT_LOGO_PATH` / `PYSIDE_LOGO_PATH`。
  - `font.py`：全局字体与渲染后端（详见 `docs/app_shell.md`）。`apply_app_font(app)` = `QFontDatabase.addApplicationFont` 装 `static/font/` 下所有字体 + `app.setFont` + **给 qfluentwidgets 打补丁**，**必须在 `import app.MainWindow` 之前调**。`load_app_fonts()` 优先返回 `PREFERRED_FAMILY`(`LXGW WenKai Mono GB`)，不在才退回第一个——别让「用哪个字体」取决于文件名排序。**Qt 不认 woff2**（只认 TTF/TTC/OTF），这类字体得离线转成 ttf 再入库。补丁两步：换掉 `qfluentwidgets.common.font.getFont`，再扫 `sys.modules` 把 21 个模块导入时绑死的 `getFont` 重绑（`setFont` 不用重绑，它在自己模块 globals 里查 `getFont`）。**光打 `getFont` 补丁会漏一半控件**——上游 23 个 qss 把字体族写死了、且 QSS 赢过 `setFont`，所以还有第三步 `_patch_stylesheet_font()`：包一层 `getStyleSheetFromFile`，用正则替换 qss 里的 `'Segoe UI', 'Microsoft YaHei'...`（见坑点）。另有 `apply_font_engine()`：按 `cfg.font_engine` 写 `QT_QPA_PLATFORM=windows:fontengine=freetype`，**必须在 `QApplication` 构造之前调**，`QT_QPA_PLATFORM` 已被外部设过（屏幕外脚本）就让路。无字体静默返回 `None`。
  - `signal_bus.py`：全局信号（缩略图、配置变更）。
  - `exception.py`：`show_bili_error(e, parent)` 统一 `BiliError` 子类 → 中文提示（`AuthRequired`→引导设置页、`DressNotFound`→"没有结果" 等）。提示走 `app/common/notify.py` 的 helper，不直接用 `InfoBar`。另有 `cause_hint(exc)`：沿 `__cause__`/`__context__` 挖出真正的 requests 异常翻成可行动中文（407 认证 / 连不上代理 / 超时 / TLS / 地址格式），网络类提示会附上当前代理（`redact_proxy`，开关关着时说明「已关闭」）。
  - `proxy.py`：纯字符串工具，只有 `PROXY_PLACEHOLDER` / `normalize_proxy`（无 scheme 补 `http://`）/ `parse_proxy` / `redact_proxy`（密码打码，认证段按**最后一个 `@`** 切——`@` 是合法密码字符）。协议、主机、端口、认证不再拆开——地址就是 requests 认的那种完整 URL。
  - `net.py`：**唯一的联网对象工厂**（见 `docs/proxy_diagnostics.md`）。`current_proxies()`（代理开关关 → `None`）+ `make_client` / `make_emoji` / `make_dress` / `make_downloader` / **`make_session`**（非 B 站请求，检查更新走它，自带 UA——GitHub API 不带 UA 会 403）。两条硬规矩：代理只来自设置页（`proxies` 默认值是哨兵 `_FROM_CFG`，漏传就读配置而不是静默直连）；**所有 Session `trust_env = False`** —— requests 默认会读 `HTTP_PROXY` 与 **Windows 注册表里的系统代理**，还会用它**覆盖**显式传入的 `proxies`（`sessions.py:845/863`）。
  - `notify.py`：`notify_success/warning/error/info` —— **垂直布局 InfoBar**（标题一行/内容换行/按钮一行），全应用统一入口。`_resolve_parent()` 把传入的页面 widget 归一成 `window.stackedWidget`（内容区），**调用点照传自己的页面即可**；这样位置固定在内容区右上角、且切页后消息不会跟着被藏掉。另导出 `NEVER_DISMISS = -1`——「不自动消失」是**负数**，写 `duration=0` 是「0 毫秒后淡出」，提示会一闪而过（见坑点）。
  - `theme.py`：主题感知取色对 `BODY_TEXT`/`SECONDARY_TEXT`/`ORANGE_TEXT`（(light, dark) 二元组，配主题化 Label 的 `setTextColor`）；`bind_theme(widget, fn)` 立即执行 + 每次 `themeChangedFinished` 重执行（fn 须为 widget 绑定方法，销毁自动断开）；**全局调色板**在主题切换时按生效主题 `app.setPalette(...)` 并强制 `update()` 全部控件（纯 QWidget 背景/文字依赖 palette）。`isDarkTheme()` 返回生效主题（AUTO 已被 `qconfig` 解析成具体值）。
- `app/components/`：
  - `task.py`：**线程层核心**。`Task`(QRunnable) + `TaskManager`（持有引用，finished 自动释放）+ `run_task()`。信号对象在主线程构造（亲和主线程），worker 线程 emit 自动 QueuedConnection。`autoDelete(False)` 防 C++ 对象提前释放丢信号。全局线程池 max 4。
  - `thumb.py`：异步缩略图。worker 向**常驻 `signal_bus`** 发原始信号（`thumbRawLoaded`/`thumbRawFailed`），主线程转 `QPixmap` 写 `QPixmapCache` 再广播 `thumbLoaded`。**取字节前先查 `image_cache` 磁盘缓存**，未命中才联网并回写。cookie 与 **proxies 都在主线程 `request()` 里读一次再交给 worker**（worker 不碰 `cfg`）。emit 用 try/except 守卫（应用关闭时忽略）。构造里把 `QPixmapCache` 上限从默认 10 MB 提到 64 MB（单位 KB）。另有 `reload(url)`：作废内存 + 磁盘两层再重新请求，**必须先清 `QPixmapCache` 再 `request`**（否则 request 命中内存缓存直接同步 emit 旧图，看着像没生效）。
  - `disk_cache.py`：通用磁盘缓存（`%APPDATA%/biliEmojiDD/cache/<name>/`）。**文件 `mtime` 兼作 LRU 时间戳**（读命中 `os.utime` 刷新），不写索引文件；写 `.part` 再 `os.replace`；超限按 mtime 升序删到上限 90%；上限每次 `put` 现读 `cfg.cache_limit_mb`。两个实例：`image_cache`（无 TTL，纯 LRU）、`api_store`（`touch_on_read=False`，TTL 由调用方给——**读会刷 mtime 的实例不能用 TTL**，否则永不过期）。`total_size()` / `clear_all()` 供设置页；`remove(key)` 作废单条（「重新加载」用）。
  - `api_cache.py`：带 TTL 磁盘缓存的取数入口 `search_dress` / `emoji_package` / `dress_collection`。存 `raw` dict、读回来 `from_dict` 无损重建；**只缓存成功结果**（`AuthRequired`/`DressNotFound` 照常抛）；key 不掺 cookie 指纹（这三个接口与账号无关）。**只在 worker 线程调用**。页面与 `content_meta` 一律走它，别再直接 new `Emoji`/`Dress`（`all_packages` 例外，它有自己的 `cache.py`）。
  - `search_history.py`：搜索历史。`SearchHistory`（`%APPDATA%/biliEmojiDD/search_history.json`，按 namespace 分表、MRU、最多 10 条）+ `SearchHistoryPanel`（**浮层下拉面板**：parent 是顶层窗口、不进任何布局、点搜索框展开、失焦/移出收起、动画动 `geometry`）+ `_HistoryChip`（`PillPushButton` + 悬停出现的 × ）。
  - `content_meta.py`：下载项**内容概要**（图片/视频数）。结构同 `thumb.py`：独立 `QThreadPool(2)`（不占 `task_manager` 的 4 线程）、worker 发 `signal_bus.contentMetaRaw(key, meta)`、主线程写缓存后广播 `contentMetaLoaded`（**载荷 None = 取不到**）。`cached()` 对自带 `emote` 的完整 `EmotePackage` 同步推导（零请求）；`request()` 只在卡片可见时调；**失败记 `_failed` 本会话不重试**；`remember()` 供两个详情页喂数据。**`set_enabled(False)` 给屏幕外脚本关联网**（否则假 ID 排一堆 15s 超时把脚本挂住）。
  - `video_cache.py`：收藏集视频的**会话级本地缓存**。结构同 `content_meta.py`：独立 `QThreadPool(2)`、worker 用 `Downloader.download()` 下到 `tempfile.mkdtemp()` 目录后发 `signal_bus.videoRawReady(url, path|None)`、主线程写缓存后广播 `videoReady`。**不流式播远程 URL**（`QMediaPlayer` 走 WMF 自己的网络栈，读系统代理、不读应用内代理，也无法自定义 UA）。`remember(url, path)` 供详情页登记「已整包下载过」的本地 `.mp4`；`cleanup()` 在 `MainWindow.closeEvent` 里删临时目录；**`set_enabled(False)` 给屏幕外脚本关联网**。`forget(url)` 清失败标记与缓存让下次真的重下——**只删自己 `mkdtemp` 出来的临时文件**，`remember()` 登记的是用户下载目录里的成品，只摘引用不能删。
  - `video_player.py`：`CollectionVideoPlayer` —— 组件库 `VideoWidget` + 缓冲/失败覆盖层。
    - **加载失败可重来**：右键 →「重新加载」，或直接点提示文字（失败态才摘掉 `WA_TransparentForMouseEvents`，缓冲态仍穿透）。两条路都走 `reload_current()` = `video_cache.forget(url)` + `play(index)`。
    - **控制条从画面里挪到下方常显**：`_VideoView` 覆写 `resizeEvent`/`enterEvent`/`leaveEvent`，解绑上游的绝对定位与 hover 淡出；`_VideoView` 还把场景背景钉成纯黑（见坑点）。
    - **画面区不参与尺寸协商**：`_VideoView` 覆写 `sizeHint`/`minimumSizeHint` 返回小常量 + `resizeEvent` 里 `setSceneRect` 钉住场景矩形。两者都不能去掉，否则 `growingItemsBoundingRect` 只涨不落会把整页 sizeHint 顶起来（见坑点）。
    - 控制条上游的「后退10s/前进30s」改成**上一个/下一个视频**（先 `clicked.disconnect()` 再接自己的槽，首尾禁用、越界直接 return），右侧补**全屏**按钮。
    - 播放/暂停图标接 `player.playbackStateChanged`（上游只在 `mediaStatusChanged` 时刷，自动暂停后图标不复位）。
    - **内嵌宽度完全交给布局 stretch，不在 `resizeEvent` 里写宽度约束**（见坑点）。
    - `play(index)` 命中缓存直接播、否则转加载环并 `video_cache.request`；`videoReady` 槽**必须校验 `url == self._pending_url`**（缓冲期间用户可能已切走）。
    - `release()` = `stop()` + `setSource(QUrl())` 释放文件句柄；`is_idle()` 供页面判断切回视频页要不要重新加载。
    - `VideoLightbox`（`MaskDialogBase`）：**把现有播放器搬进遮罩再搬回**，不新建 `QMediaPlayer`；**跳过上游淡入淡出**（特效叠在刷帧视频上会卡）；**覆写 `done()` 在隐藏前记 `is_playing()`**（`finished` 时播放器已被 `hideEvent` 暂停）。
  - `widgets.py`：卡片与网格全家桶。**共用基类 `_CardGridBase`**（组件库 `ListWidget` + `setItemWidget`）：懒加载缩略图 + 多选 API + 动态单元格 + `itemClicked(item)` / `itemClickedAt(index, item)`，内含 `verticalScrollBar().rangeChanged → _layout_items()` 联动重排，主题自动重刷。
    - `EmojiCard`+`EmojiGrid`（表情网格，卡片可点 → `imageClicked(index)`）
    - `PackageCard`+`PackageGrid`（表情包卡片/网格，响应式填满）
    - `DressCard`+`DressGrid`（收藏集竖版四列卡片）
    - `DetailCard`+`DressDetailGrid`（详情动态尺寸网格，卡片可点 → `imageClicked(index)`）
    - `VideoCard`+`VideoStrip`（收藏集视频网格：`DetailCard` + 播放角标 + `set_active` 高亮；**栏数动态**（至少两栏、项目数少于栏数时收敛）、**宽度按 `self.width()` 而非 viewport 算**防抖动、高度按 3:4 反推并按视口封顶，`videoClicked(index)`）
    - `QueueCard`+`QueueList`（下载队列，**宽屏两列窄屏单列**，封面随单元格自适应）
    - **右键任一卡片 →「重新加载」**（`_CardGridBase.contextMenuEvent` → `reload_url(url)`，六个网格通用）；加载失败的卡片还会亮出一个「↻」按钮直接可点（`_SpinnerMixin` 三态：`thumb_done` / `thumb_failed` / `thumb_restart`，回调由网格建卡时注入 `card._retry_cb`）。
    - 通用约定：`PackageCard`/`DressCard` **右上角**挂 `InfoBadge.success('已下载')`、**勾选框移到左上角**（两者同时显示不打架）；`DressCard` 名称 `setWordWrap` 两行 + 整卡 `ToolTipFilter` 兜底完整名。**所有卡片文字用主题化 `CaptionLabel`/`StrongBodyLabel`/`BodyLabel` + `setTextColor(light, dark)`，自动随主题切换**；选中背景用**类选择器**（如 `QueueCard { background-color: ... }`）限定自身，不级联子 label。
  - `page_scaffold.py`：**四页共用版式底座**——`PAGE_MARGIN=36` / `page_title` / `title_row`（缩进走布局边距）/ `CommandCard`（`SimpleCardWidget` + `add_row` / `add_row_widget` / `add_widget`）/ `SectionCard`（`HeaderCardWidget`，内容区边距收紧，`add_header_widget()` 把 Pivot 挂到卡头右侧并把卡头高度恢复成 48）/ **`BusyPushButton`**（带加载环的按钮，设置页的「测试」「检查更新」「测速」共用）/ **`version_badge` / `status_badge`**（胶囊：`InfoBadge` 本就画全圆角，但上游 qss 只给 `padding:1px 3px`，留白靠覆写 `sizeHint` 补——**不能 `setStyleSheet`**，它已注册进 `styleSheetManager`，切主题会重刷冲掉；`status_badge` 的颜色要显式给 `(亮,暗)`，因为上游暗色主题下 WARNING/ERROR 是浅底而 qss 把文字钉成白色，白字压浅底看不清）。卡片基类自带主题重绘，别自己写 QSS。
  - `updater.py` / `update_dialog.py` / `mirror_card.py`：检查更新与下载加速（详见 `docs/update_and_packaging.md`）。`updater` 只在 worker 线程调用：`fetch_latest_release()` 查 GitHub Release、`download_urls()` 按 `cfg.gh_mirror` 展开候选地址、`download_asset()` 流式下载并**校验 SHA-256**（校验和**固定直连**取，不经镜像——拿被校验方给的校验和校验它自己等于没校验），不符则删文件抛 `ChecksumMismatch` 且绝不运行；`probe_mirrors()` 并发测速（良好/一般/错误三档，4xx 也算通、只有连不上与镜像 5xx 算错误）。镜像**成员**在 `cfg.custom_mirrors`、**顺序**在 `cfg.mirror_order`，读取一律走 `all_mirrors()` / `orderable_mirrors()` / `mirror_chain()`——顺序表只记顺序不记成员（表里没有的补在后面，已删的自动失效）；**`cfg.gh_mirror` 不能用 `OptionsValidator`**（取值集合随用户增删而变）；**改地址要先算顺序再改成员**，反了会把改完的源排到末尾。`set_enabled(False)` 给屏幕外脚本关联网。`UpdateDialog`（`MessageBoxBase`）用组件库 `TextEdit` + `setMarkdown` 渲染更新说明，**`yesButton` 必须先 `clicked.disconnect()`**（上游直接 `accept()`，不断开点一下弹窗就没了），下完 `os.startfile` 再 `window.close()`（**不是 `QApplication.quit()`**，后者不触发 `closeEvent`，`video_cache` 临时目录会漏）。`mirror_card.MirrorSettingCard` 是 `ExpandGroupSettingCard`：**`addWidget` / `addGroupWidget` 各只能调一次**，展开区整块交给自管面板；**它没有 `setContent`**，副标题写 `self.card.setContent`；拖动排序手写（`QListWidget` 的 `InternalMove` 会弄丢 `setItemWidget` 的控件），做法是「把行 `removeWidget` 摘出布局 + 原位插等高占位」——不摘的话每次重新布局都会覆盖 `move()`，行跟不了鼠标。
  - `package_detail.py`（包详情视图，两个入口复用；头部卡 + `SectionCard("表情预览")`，`add_leading_widget()` 供「返回列表」嵌入）、`page_bar.py`（自制数字分页）、`image_viewer.py`（遮罩图片查看器，见下节）、`download_runner.py`（`start_download` + `download_package_batch`/`download_collection_batch`/`download_mixed_batch`）、`download_queue.py`（下载队列单例）、`dress_helpers.py`（收藏集类别判别 + dlc id 读取）、`cache.py`（全部表情包缓存）、`proxy_probe.py`（代理连通性自检，设置页「测试」按钮用，只在 worker 线程调用；导出 `PROBE_URL`/`PROBE_NAME` 供提示与 tooltip 展示「测的是哪个接口」）。
- `app/view/`：**五页统一 Fluent 卡片版式**（大标题 → 命令卡 → 内容，页边距 36，见 `docs/page_card_layout.md`）。
  - `home_page.py`：**启动默认页**（详见 `docs/home_page.md`）。`title_row` + `ScrollArea`（必须显式透明）内依次是 `_HeroCard`（logo/名称/版本/简介 + 状态行 + 主按钮，按 `cfg.cookie` 空否切「填写 Cookie」→设置页 / 「开始使用」→表情包页）、三张 `_FeatureCard`（`CardWidget`，整卡可点，`clicked` 无参；表情包 / 收藏集卡挂 `_ShowcaseStrip` 本地素材，下载卡挂 `_QueuePreviewStrip` 实时显示队列前 4 项封面 + `+N`）、`_QuickStartCard` / `_AboutCard`（`SectionCard`，宽窗两列）、`_RecentSearchCard`（读三个 namespace 的 `SearchHistory` 做胶囊，无记录整卡隐藏）。列数在 `resizeEvent → _reflow()` 里算，**列数没变直接 return**。
  - `emoji_page.py`：Pivot 双标签 + 命令卡；多选行按需显隐；详情「返回列表」在头部卡内。两个输入框都挂 `SearchHistoryPanel`（`emoji_id` / `emoji_filter`）；**过滤只在回车 / 点放大镜时触发**（不再是 `textChanged`，每敲一字重排整页太吵），点 × 走 `clearSignal` 恢复全部。另有供主页跳转的公开入口 `query_package_id(text)` / `filter_packages(kw)`（切 Pivot + 切页两句都要写；后者**只有已拉过全量时才真的过滤**，否则只回填关键词，不擅自发起需要 Cookie 的请求）。
  - `dress_page.py`：搜索命令卡（`kwEdit` 挂 `SearchHistoryPanel("dress")`）；详情头部卡 + `SectionCard("内容预览")`，**内容区是 `Pivot`（静态图片 / 动态视频）+ `QStackedWidget`**——图片页 `DressDetailGrid`、视频页**左 `CollectionVideoPlayer` + 右 `VideoStrip`**（宽度按 1:2 静态 stretch 分配，不做 resize 驱动的自适应）；无视频时视频 tab 禁用并强制回图片页；「仅看收藏集」**默认勾选** + `_last_summaries` 存原始结果、`toggled` 实时重过滤；详情 `_detail_summary` / `_detail_videos` 显式字段。另有供主页跳转的公开入口 `search_keyword(kw)`（先 `_go_back()` 回搜索页再搜）。
  - `download_page.py`：命令卡含计数/批量按钮/状态/进度条 + 队列列表。
  - `setting_page.py`：**Fluent 设置卡片版式**——顶部身份行（`IconWidget` logo + `TitleLabel("BiliEmojiDD")` + **版本胶囊 `version_badge`**）+ `ScrollArea`/`ExpandLayout` + 五个 `SettingCardGroup`（**关于** / 账号 / 下载 / 缓存 / 外观）；**「关于」组必须第一个 `_build_*` 调用**（`ExpandLayout` 按加入顺序排），含代码仓库 / 检查更新 / 自动检查更新 / **下载加速（`MirrorSettingCard`，见 `mirror_card.py`）** / 开源许可五张卡，开关与下拉都即时 `qconfig.set`；Cookie / 下载目录用 `ExpandGroupSettingCard`，其余用本地 `_WidgetSettingCard`（`SettingCard` 尾部挂控件）；代理行是「**开关** + 完整地址框 + **测试**」——开关关着时地址框与测试都 disable（`_sync_proxy_enabled`），**`_current_proxy()` 是唯一的取值/校验入口**（保存与测试共用：开关关 → `""`；开着但空 / 含空格 → 提示并 `None`；否则 `normalize_proxy`）；**横向 `Expanding` 的控件在 `_WidgetSettingCard` 里按 stretch 加而不是 `AlignRight`**（带对齐标志的项拿 sizeHint 宽度、不会被压缩，窄窗口会顶出卡片）；**代理即时生效**：开关 `checkedChanged`、地址框 `editingFinished` 各自 `qconfig.set`，不进「保存下载设置」（改完忘了保存 → 请求还用旧地址、报错显示的也是旧地址，看起来像代理没接进去，真踩过）；`_refresh_proxy_content()` 把**生效值**（读 `cfg`，密码打码）写进卡片副标题，与输入框里「正在编辑的值」区分开；「测试」失败**不走 `show_bili_error`** 而是 `_on_proxy_failed`（通用提示报的是「网络错误 + `cfg.proxy`」，而测试要报「`_probed_proxy` 那个刚填的值 + `PROBE_URL`」，否则测的和报的可能是两个地址）；「测试」按钮是本地 `_BusyPushButton`（内嵌 `IndeterminateProgressRing`，忙碌时文案变「测试中」+ 转圈 + disable；**空格数按空格实际宽度现算**、**宽度按忙碌态预留**、收环后重新对齐开关状态）；缓存组的上限 `SpinBox` 即时 `qconfig.set`，占用统计与清除都走 `run_task`（目录可能上万文件）；主题下拉带图标：`_sync_theme_icon` + `bind_theme`，外部切换后 `configChanged` 同步；外观组另有「字体渲染」下拉（`fontEngineCombo`，default/freetype），即时 `qconfig.set` 并提示**重启生效**。

## 图片查看器（`app/components/image_viewer.py`）

- 翻页按钮在**底部信息行**（`‹ 名称 3/20 ›`），上游那两个 16×38 的贴边小箭头已 `hide()`；关闭按钮贴**图片框右上角**、白图标 + 半透明深色圆底（`_OverlayToolButton`）。右键图片可「重新加载」。
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

### 线程与信号

- 所有网络 I/O（biliemoji 调用、下载、缩略图）必须在后台线程，结果经 Qt 信号回主线程；**worker 线程禁止直接改控件**。
- biliemoji 下载器的 `on_progress(done, total, result)` 在内部线程池调用 → 桥接成 Qt 信号（`run_task(..., needs_progress=True)` 自动处理）。
- **on_progress 统一协议 `(done, total, result)`**：`result is None` 表示下载准备阶段（读取包详情），`start_download` 据此显示状态文字；自定义下载闭包必须 `def task(on_progress=None):` 并透传给 biliemoji（缺参会抛 `TypeError`）。
- `QPixmap` 只能在主线程创建/使用；worker 线程只产 `QImage` 或字节数据。
- **`QDialog.finished` 发出时控件已经隐藏过了**：`VideoWidget.hideEvent` 会 `pause()`，所以在 `finished` 槽里读 `is_playing()` 永远是 False。要在 `done()` 里、`QDialog.done` 之前记状态。

### 布局与尺寸

- `FlowLayout.takeAt(index)` 返回 **widget**（不是 QLayoutItem）；清理布局用 `widget.setParent(None)` + `deleteLater()` 防幽灵残影。库自带的 `takeAllWidgets()` 会把布局里所有控件 `deleteLater`——**常驻控件（如历史面板的「清空」按钮）必须先 `removeWidget()` 摘出来**，否则下次访问就是野对象。
- **鼠标移到子控件上时，父控件会收到 `leaveEvent`**：在父控件的 `leaveEvent` 里直接隐藏子控件会导致「一悬停就消失、永远点不到」（历史胶囊的 × 踩过）。判据要加一层 `rect().contains(mapFromGlobal(QCursor.pos()))`。
- **hover 才出现的控件要恒定占位**：只在悬停时才给它留宽度，容器会在鼠标进出时来回跳。做法是覆写 `sizeHint()` 恒定加上那份宽度。
- **父级隐藏时子控件收到的是 `HideToParent` 而不是 `Hide`**：靠事件过滤器感知「所在页被切走」（如收起浮层）时两个都要接。
- **`QPushButton` 垂直 size policy 默认 `Fixed`**：`QVBoxLayout` 里加 `stretch=1` 也拉不撑（海报被压成 12px 的坑，多余空间全给文字 label）；需撑满时 `setSizePolicy(Expanding, Expanding)`。
- **有 QSS 的控件 `setContentsMargins` 会被忽略**：`QStyleSheetStyle` 按 QSS 盒模型重算 contentsMargins（`TitleLabel` 等组件库 Label 都注册了 QSS），缩进要走**布局边距**——设置页大标题曾因此贴在 x≈2 而不是 36。
- **`SpinBox` 右侧上下按钮占约 64px**：宽度给到 90 以下数字会被裁没（设置页端口 130 / 线程数 110）。
- **不换行的 `QLabel` 会把整页最小宽度顶起来**：`minimumSizeHint` 就是整串文字宽度，详情页长名一度让页面缩不到最小窗口（598px）。标题/元信息/提示类 Label 一律 `setWordWrap(True)`。
- **隐藏的子页不会重新布局**：`QStackedWidget` 非当前页、未 `show()` 的 Tab，几何停留在上次可见时的尺寸——写几何断言前先切到该页，否则量到过期数字「假通过」。
- **别在 `resizeEvent` 里写几何约束（`setMaximumWidth`/`setFixedSize`）来做「按内容比例自适应」**：离屏 `resize()` 一次就收敛、断言全过，但**交互式拖拽窗口时每帧会跑好几轮**「改约束 → 重新布局 → 又一次 resize」，叠上 `fitInView`、网格 `setGridSize` 重排就会画面畸形 + 明显卡顿（视频播放器踩过）。改用**静态 stretch 分配**，`resizeEvent` 里只做「可见时才更新」的轻量事。
- **`QGraphicsView` 的 `sizeHint()` 跟着单调增长的场景矩形走**：`QGraphicsScene` 没显式设过 sceneRect 时返回 `growingItemsBoundingRect`（**只涨不落**），而 `QGraphicsView.sizeHint()` = `transform.mapRect(sceneRect())`。上游 `VideoWidget.resizeEvent` 里 `videoItem.setSize(self.size())` 会把窗口放大时的尺寸永久写进去。它还**延迟发作**：改场景矩形时不调 `updateGeometry()`，等到真的加载视频（几何失效）那一刻虚高的 sizeHint 才一次性灌进上层布局，把整页顶高且缩不回来（实测收藏集详情页 sizeHint 663x707 → 853x967）。修法：`resizeEvent` 里 `setSceneRect` 钉住 + 覆写 `sizeHint`/`minimumSizeHint` 返回小常量。回归断言见 `scripts/check_video_tab.py` 第 8 节。

### 卡片网格（`_CardGridBase` 家族）

- **卡片下标不要靠载荷身份反查**：`(name, url)` 这类内容相同的元组字面量会被 CPython 常量折叠成**同一个对象**（`items[1] is items[2]` 为真），`is` 反查会把两项判成同一下标。`_CardGridBase` 用建卡时的 `partial(self._emit_clicked, index)` 闭包发 `itemClickedAt(index, item)`。
- **`QListView` 设了 `setGridSize()` 后忽略 `setSpacing()`**：步进就是 `gridSize.width()`，spacing 只会把**首列**卡片右移一格（其余列不动），于是第一、二列之间没有间隙、其他列有。所以 `_CardGridBase` 直接 `setSpacing(0)`，所有 `_cell_size()` 一律按 `(vw - _CARD_GUTTER) // 列数` 均分铺满整行；换行判据是 `列数 * cellW > 视口宽 - 1`（闭区间），算宽必须留余量，否则最后一列被挤到下一行、右侧反而空出一整格。选中高亮用 `_SEL_INSET` 的 QSS `margin` 从卡片边缘内缩来分隔相邻卡片。**首列与次列之间仍然没有间隙**（`setItemWidget` 只右移首列，改不掉），已知未修复，见 `docs/theme_grid_fixes.md` 第四节。
- **卡片高度正比于宽度的网格，宽度要按 `self.width()` 算而不是 `viewport().width()`**：`_CardGridBase` 把 `verticalScrollBar().rangeChanged` 接到了 `_layout_items`，跟着 viewport 走会「滚动条出现 → 变窄 → 变矮 → 不再需要滚动条 → 变宽」来回抖。固定预留一个滚动条宽度即可（`VideoStrip._SCROLL_RESERVE`）。
- **缩略图加载环 `_SpinnerMixin`**（`widgets.py`）：`_center_spinner` 的早退判据必须用 **`isHidden()` 而不是 `not isVisible()`** —— 卡片尚未 `show()` 时子控件 `isVisible()` 恒为 False，用它会把建卡阶段的定位全部跳过，之后没有 resize 就永远卡在左上角 (0,0)。收环三条路径缺一不可：`set_pixmap()`、`_CardGridBase` 转发 `thumbRawFailed`、`set_cards()` 里 **url 为空的卡片建完即收环**（永远等不到信号，否则空转）。

### 渲染、主题与样式

- **页面里放 `QScrollArea` 必须显式透明**：页面在 `FluentWindow` 的 `stackedWidget` 子树里靠「自己不画背景」透出窗口底色，原生 `QScrollArea` 不透明会在暗色下露出 palette 的 Base 色块。写法 `QScrollArea{border:none;background:transparent}` + `.QWidget{background:transparent}`（`.QWidget` **类选择器**只命中 viewport / scrollWidget 这类纯 QWidget，不级联到卡片）。
- **裸 `QListWidget` / `QToolButton` 等原生控件拿不到主题**：qfluentwidgets 靠 `updateStyleSheet()` 重刷 **已注册进 `styleSheetManager`** 的控件，原生控件从没注册过，背景色只能靠 `QPalette`——而全库从不调 `QApplication.setPalette`。列表用组件库 `ListWidget`（构造里 `FluentStyleSheet.LIST_VIEW.apply(self)` 自动注册），按钮用 `TransparentPushButton` 等，别自己写 QSS 兜。
- **主题化 Label**：文字优先用 `CaptionLabel`/`BodyLabel`/`StrongBodyLabel` + `setTextColor(light, dark)`，它们连 `qconfig.themeChanged` 自动切色；**不要**再给它们 `setStyleSheet` 设颜色（会覆盖主题色）。纯 QWidget 的背景/默认文字色依赖全局 palette（`theme.py` 已按主题应用）。
- **`qfluentwidgets` 的 `VideoWidget` 必须配纯黑背景，否则视频反色**：其内部 `GraphicsVideoItem.paint` 用 `QPainter.CompositionMode_Difference`（`|src - dst|`）画帧，**只有 dst 为纯黑时才是恒等变换**；而库里 QSS 给 `QGraphicsView` 设的是 `background: transparent`、`backgroundBrush` 是 `NoBrush`（两个主题实测），亮色下透出卡片近白底 → 整段视频反色。修法是 `setBackgroundBrush(QColor(0,0,0))`——用 `QGraphicsView` 属性而**不是 `setStyleSheet`**：`VideoWidget` 构造里 `FluentStyleSheet.MEDIA_PLAYER.apply(self)` 已注册进 `styleSheetManager`，每次切主题都会重刷 QSS 冲掉样式表。`scripts/check_video_tab.py` 有回归断言。
- **图形特效不要叠在会持续刷新的内容上**：`MaskDialogBase.showEvent`/`done()` 给整个 dialog 挂 `QGraphicsOpacityEffect` 做淡入淡出，里面若是刷帧的 `QGraphicsVideoItem`，整棵子树会走离屏合成 → 全屏切换卡顿。覆写这两个方法直接调 `QDialog` 的实现即可。

### qfluentwidgets 上游 API 陷阱

- **qfluentwidgets `ComboBox.addItem(text, icon, userData)`**：第二位置参数是 **icon** 不是 userData；要 `currentData()` 有值必须 `addItem('文本', userData=值)`（曾致下载模式 `mode.lower()` 崩、设置页代理/主题切换失效）。
- **`ComboBox` 闭合态不显示选中项图标**：`ComboBoxBase.setCurrentIndex` 只 `setText` 从不 `setIcon`，`item.icon` 只在展开菜单时用。要显示得自己 `setIcon(combo.itemIcon(i))`（ComboBox 继承 QPushButton，`paintEvent` 会调 `QPushButton.paintEvent` 画出来）。补图标的时机有三处：建卡后、`currentIndexChanged`、以及 `blockSignals` 内的同步——首次 `addItem` 库会自动 `setCurrentIndex(0)`，之后设同一索引会提前 return 不发信号。`FluentIcon` 按取用瞬间的主题取黑/白 svg，主题切换后须重新 `setIcon`（用 `bind_theme` 绑定）。
- **`NavigationInterface.addWidget(..., onClick=fn)` 已经会把 `fn` 连到 `widget.clicked`**（`NavigationPanel._registerWidget`）。再手动 `widget.clicked.connect(fn)` 就是连了两遍，一次点击跑两次——主题切换按钮曾因此「切了又切回」，看起来完全无效。
- **设置卡片四条（详见 `docs/setting_page_redesign.md`）**：① `SettingCard.hBoxLayout` 末尾是 `addStretch(1)`，续 `addWidget` 即靠右排（`_WidgetSettingCard` 就靠这个挂 ComboBox/SpinBox）；② `HeaderSettingCard.addWidget` **只能调一次**（每次都会重新把 `expandButton` 塞进布局），多控件先包无边距容器；③ `ExpandSettingCard` 是 `QScrollArea` 子类，**没有 `setContent`**，标题行在 `.card` 上（写 `self.setContent` 直接 `AttributeError`，`MirrorSettingCard` 踩过），且 `ExpandLayout.count()` 恒为 0（`addWidget` 进的是另一个列表）；④ `addGroupWidget` 的行必须 `setFixedHeight`（展开高度按 `viewLayout.sizeHint()` 算）。**展开区要动态增删行**就别逐行 `addGroupWidget`（它会自己往中间插分隔线，回头很难摘干净）——`addGroupWidget` 只调一次塞进自管容器，改完调 `_adjustViewSize()` 重算高度。
- **`InfoBar` 的 `duration=0` 是「立刻消失」不是「不消失」**：上游 `showEvent` 里 `if self.duration >= 0: QTimer.singleShot(self.duration, self.__fadeOut)`，**负数**才永不消失。写 0 的话诊断提示一闪而过、根本读不到。用 `notify.py` 的 `NEVER_DISMISS`。
- **`ExpandSettingCard` 收起动画的终值取自陈旧的滚动条 range**：`setExpand(False)` 用
  `verticalScrollBar().maximum()` 做动画终值，而同一个类**覆写 `resizeEvent` 时没调 `super()`**
  —— `QAbstractScrollArea.resizeEvent` 才是触发 `layoutChildren()/updateScrollBars()` 的地方，
  于是 range 一直停在构造期的值。**展开区高度是构造之后才撑起来的卡片**（如 `MirrorSettingCard`
  的行是 `reload()` 里加的）收起时会拿到偏小的终值，高度降不到底 —— 表现为「展开了收不回去」
  （实测停在 292 而不是 70）。修法见 `MirrorSettingCard.setExpand`：收起方向自己
  `expandAni.stop()` + 滚动条推到底 + `setFixedHeight(self.card.height())`。
- **`FlipView` 的翻页箭头是 16×38 且钉在控件最左 / 最右**（`flip_view.py:175/332`）：图一宽两个箭头就隔了半屏。`image_viewer` 已把它们 `hide()` 并把翻页挪到底部信息行 —— 上游 `enterEvent/leaveEvent` 只 `fadeIn/fadeOut` 改 opacity、**从不 `show()`**，所以藏一次就够。
- **遮罩层上的按钮必须自己钉死颜色**：`TransparentToolButton` 的图标按主题取色，亮色主题下是黑图标，压在纯黑遮罩上等于隐身（查看器关闭按钮「看不到」的根因）。用 `FluentIcon.X.icon(color=QColor("white"))` + 自绘半透明深色圆底，见 `image_viewer._OverlayToolButton`。
- **`FluentIcon` 枚举名是 `CONSTRACT` 不是 `CONTRACT`**（官方把 contrast 拼错成 constract），用错名直接 `AttributeError`。
- **`NavigationToolButton` 构造只有 `(icon, parent)`**（不像 `NavigationPushButton` 的 `(icon, text, isSelectable, parent)`）。
- **`Pivot` 的两个槽要自己 `setCurrentItem`**：`Pivot` 只在**用户点击**时移动指示条（`itemClicked → _onItemClicked → setCurrentItem`），程序化调用 `onClick` 槽不会同步指示条；反过来 `setCurrentItem` 也不触发 `onClick`。所以初始化要两句都写，且槽内主动 `setCurrentItem`（收藏集详情页换收藏集、断言脚本都会程序化调用这两个槽）。
- **改上游组件按钮的行为前先 `clicked.disconnect()`**：`StandardMediaPlayBar.__initWidgets` 已把两个 skip 按钮连到 `skipBack(10000)`/`skipForward(30000)`，直接再 connect 会一次点击跑两件事。
- **不要覆写组件库按钮的 `__init__`**：`PushButton.__init__` 是库自实现的 `singledispatchmethod`，`(text, parent)` 那个重载内部会**再调一次 `self.__init__(parent=parent)`**；子类若把 `text` 声明成必填位置参数，这次内部调用直接 `TypeError: missing 1 required positional argument`（`_HistoryChip` 崩过）。子类初始化一律走库留的 **`_postInit()`** 钩子——注意它在 `setText` 之前执行，依赖文本的东西（tooltip 等）只能建完对象再设。**`InfoBadge` 同源同坑**（`(text, parent, level)` 重载内部再调 `self.__init__(parent, level)`），且它**没有 `_postInit`**——`_PillBadge` 因此只覆写 `sizeHint`，别加 `__init__`。**`ToolButton` 与 `FluentLabelBase`（`BodyLabel` 等）也同源同坑**：`_OverlayToolButton` 走 `_postInit()`、`_HintLabel` 干脆只加信号与 `mousePressEvent`。
- **组件库播放条的播放/暂停图标只在 `mediaStatusChanged` 时刷**：任何不经过按钮的暂停（`hideEvent` 的自动 pause：切 tab、换父控件、切导航页）之后图标都不复位。接 `player.playbackStateChanged` 自己同步。
- **切页动画会把整页重绘十几帧**：`PopUpAniStackedWidget.setCurrentIndex` 每次切页跑 300ms 的整页 `pos` 动画（`deltaY=76`），主页/设置页单帧重绘就 11–12ms，肉眼卡。`MainWindow._set_current_interface` 跳过动画直接 `QStackedWidget.setCurrentIndex`，并**换掉 `stackedWidget` 实例上的 `setCurrentWidget` 方法**——切页有三个入口（侧栏点击 / `switchTo` / 标题栏返回按钮的 `qrouter.pop()`），只覆写 `switchTo` 盖不全。
- **`getFont()` 硬编码字体族**：`qfluentwidgets/common/font.py::getFont` 写死 `['Segoe UI', 'Microsoft YaHei', 'PingFang SC']`，组件库每个控件构造时都 `setFont(getFont(...))`，所以 `QApplication.setFont` 对它们无效。换字体必须打补丁，而且要扫 `sys.modules` 重绑——库里 21 个模块 `from ...common.font import getFont` 在导入时就绑死了函数对象（`setFont` 不用重绑，它在自己模块 globals 里查）。见 `app/common/font.py`。
- **换字体只打 `getFont` 补丁会漏一半控件：QSS 赢过 `setFont`**。上游 **23 个 qss** 写死 `font: 14px 'Segoe UI', 'Microsoft YaHei', 'PingFang SC'`（`BUTTON`/`CHECK_BOX`/`INFO_BAR`/`EXPAND_SETTING_CARD`/`DIALOG`…），`QStyleSheetStyle` polish 时按 QSS 族名重算字体，把补丁盖掉；`LINE_EDIT`/`COMBO_BOX` 里那两行是注释掉的，所以「输入框对、按钮和勾选框不对」。qss **编在 Qt 资源里**（磁盘 grep 不到），统一经 `getStyleSheetFromFile` 读出，`font.py::_patch_stylesheet_font()` 包一层正则替换。**量这个 bug 必须先 `ensurePolished()`**，否则 `widget.font()` 还是补丁后的值、看不出问题。
- **`InfoBarManager` 按 `infoBar.parent()` 的矩形算位置**：挂在子页上就会浮在页面中间，而且**切页后消息跟着被 `QStackedWidget` 藏掉**。统一挂 `window.stackedWidget`（`notify.py` 的 `_resolve_parent` 已归一），并 `raise_()`。

### 屏幕外断言脚本

- **断言脚本里的假图 URL 要预置 `QPixmapCache`**：否则每个 URL 排一个 15s 超时的下载任务，脚本跑完卡着退不出去。
- **验证 worker 信号时**：不要写"短暂 `processEvents()` 后结束脚本"的测试——脚本退出早于 worker 会看到 `Internal C++ object ... already deleted` **假象**（真实 app 里 `app.exec()` 常驻无此问题）。要轮询等任务完成再退出。
- **构造 `DownloadPage` 的屏幕外脚本必须 `content_meta.set_enabled(False)`**：队列卡片会为可见项懒加载内容数量，假 ID 会排一堆 15s 超时请求，脚本跑完退不出去。**碰收藏集详情页的脚本同理要 `video_cache.set_enabled(False)`**（假视频 URL 会排下载任务）。**构造 `MainWindow` 的脚本还要 `updater.set_enabled(False)`**（启动 3 秒后的自动检查会真发一次网络请求）——`check_improvements.py` / `check_shell.py` / `check_theme_switch.py` 都已加。

## 下载队列与下载设置（要点）

- **队列**：`download_queue`（`app/components/download_queue.py`）内存单例，**混合表情包 + 收藏集**，按 `item_key(item)` 去重（表情包 `("pkg", id)`；**收藏集 `("coll", "dlc:<act>:<lottery>")`**），`item_kind` 判类型；`changed` 信号驱动 `DownloadPage` 重建。**仅本次会话**，重启清空。
- **收藏集去重键不能用 `item_id`**：实测搜索接口里 **`item_id == properties.dlc_act_id`**，一个 dlc 活动下有多期 lottery（「2233的MBTI-能量之源」act=112667 lot=112709 与「2233的MBTI-ENFP」act=112667 lot=113521），每期都是独立的可下载收藏集。按 item_id 去重会把不同期判成同一项——多选加入时被悄悄丢掉、进详情页却因 `contains()` 命中显示「已加入」，和列表对不上（真实 Bug）。装扮（`type='ip'`，无 dlc id）退回 `item:`/`id:`/`name:` 前缀键。**别在别处硬编码键字面量**，一律 `item_key()`。
- **内容数量**：`QueueCard.contentLabel` 四态（`内容: N 张图片` / `内容: N 张图片 · M 个视频` / `内容读取中…` / `内容数量未知`），数据来自 `content_meta`，`QueueList._update_visible` 只为**可见**卡片 `request`、`contentMetaLoaded` 按 key 回填。
- **全部成功自动出队**：`download_*_batch` 返回 `BatchReport`（继承 biliemoji frozen `DownloadBatchResult`，多一个 `per_item: {item_key: ItemOutcome}`），`start_download(on_result=)` 把结果送回页面，`DownloadPage._on_batch_result` 移除 `all_ok` 的项。**SKIPPED 算成功**（文件已在本地）、**total==0 不算**（取详情失败 / 无可下文件）、**只在队列页批量下载触发**（详情页可只下图片或只下视频）。归属按 **`result.target.parent`**（`_resolve_target` 只改后缀不动父目录），不用下标对齐。
- **队列布局**：`QueueList._cell_size()` 响应式——`vw >= 2*min_w` 时两列 `(vw-_CARD_GUTTER)//2`，否则单列 `vw-_CARD_GUTTER`；配合 `_CardGridBase` 的 `rangeChanged` 联动在滚动条收窄视口后重排。`QueueCard` 封面随单元格自适应（`max(72, min(h-16, round(w*0.28)))`，值未变不动防递归）；名称 `setWordWrap(True)` 防截断；信息区右留 24px 防文字跑进勾选框。
- **详情页入队 / 已下载状态**：
  - 入队按钮状态走单一 `_sync_queue_btn`——每次打开详情重置「加入下载」禁用、`_show_detail`/`set_package` 后同步（已在队列 → 「已加入」禁用）、`download_queue.changed` 联动（移除/清空后恢复）、加入后自动「已加入」禁用；`_go_back` 清 `_detail_summary`。
  - 「已下载过」= `downloaded_exists(package_download_dir(...))`（目录存在且非空），目录命名与批量下载完全一致（`download_runner` 的 `package_download_dir` / `collection_download_dir` / `downloaded_exists`）。
  - **收藏集目录一律按 `summary.name` 命名**（`collection_download_dir(summary)`）——搜索结果卡片手上只有 summary，若按 `certain_lottery_typed` 取回的 `coll.name` 命名，卡片徽标永远判不出已下载。所以收藏集详情页的单个下载也走 `download_collection_batch([summary], ...)` 而不是 `Dress.download_collection`（顺带拿到显式 proxies），`_refresh_downloaded` 同时认 summary 名与 coll 名两个目录以兼容改名前下载的旧数据。
- **收藏集视频预览**（详见 `docs/collection_video.md`）：详情页「动态视频」tab 内嵌 `CollectionVideoPlayer` + `VideoStrip` 缩略图选择条。**视频每项只取 `video_list[0]`**，与 `download_collection_batch` 建任务、`collection_meta` 计数口径一致。播放前先经 `video_cache` 下到临时目录；`_adopt_downloaded_videos` 按 `collection_download_dir(...) / f"{sanitize_filename(name)}.mp4"` 探已下载的本地文件（同样两个目录都认）并 `video_cache.remember`，命中即秒开。
- **批量下载**：`download_runner.download_package_batch(ids, dest, *, gif=None, max_workers=None, on_progress=None)`（表情包）与 `download_collection_batch(collections, dest, *, mode='both', max_workers=None, on_progress=None)`（收藏集，目录 `collection_download_dir(summary)`，即按搜索结果名）同构；下载页 `download_mixed_batch` 按 `item_kind` 拆分、顺序执行两子批并合并 `DownloadBatchResult`。`max_workers` 传入值优先、None 才读 `cfg.max_workers.value`；逐项 `certain_*_typed`（**单个失败 `except Exception` 合成 FAILED 结果后继续**，不中断整批）；**一个 `Downloader` + 一个总进度条**；表情包目录 `包名[:60] [包ID]` 防同名覆盖、文件名截断。
- **`start_download` 返回 False** 表示下载目录不可用（未建任务、无 finished 信号）——调用点必须自行恢复按钮状态，否则按钮永久禁用。
- **卡片多选**（`PackageCard`/`DressCard`/`QueueCard` 同套路）：
  - 容器无 Layout（或外层布局 + 绝对定位勾选框）；图片是 `QPushButton(setFlat=True)`（点击整图切换勾选）；勾选框 `CheckBox` 用 `setGeometry` 钉在图片/卡片**左上角** + `raise_()`（右上角留给 `InfoBadge`「已下载」，两者同时显示）。
  - 选中背景通过 `toggled` 同步整卡样式表背景，**必须 `setAttribute(WA_StyledBackground)`**（普通 QWidget 默认不绘制 stylesheet 背景），且样式表必须用**类选择器**（`"QueueCard { background-color: ... }"`）限定自身——无选择器的通用规则会级联到子 label 造成文字区整块上色。
  - `DressCard` 是纯 QWidget（**不用 `CardWidget`**：其基类 `mouseReleaseEvent` 只发 0 参数 `clicked`，与 `Signal(object)` 冲突 → 点击死）。
  - 多选/懒加载逻辑统一在 `_CardGridBase`，卡片只需暴露 `.item` / `set_selectable` / `set_checked` / `is_checked` / `set_pixmap` / `set_cell` / `clicked` / `toggled`（`EmojiCard` 为表情展示，多选相关给占位实现）。
- **代理**：**新增联网代码一律走 `app/common/net.py` 的工厂**（`make_client`/`make_emoji`/`make_dress`/`make_downloader`），别再直接 new 上游对象。工厂保证两件事：代理只来自设置页、**`trust_env = False`**（否则 requests 会读 Windows 系统代理/环境变量并覆盖显式 `proxies`）。代理有总开关 `cfg.proxy_enabled`，关着就是真直连。联网入口七处：`api_cache`（三个）、`download_runner`（`Emoji`/`Dress` + `Downloader`）、`thumb`、`video_cache`、`proxy_probe`、设置页 Cookie 验证、`emoji_page` 全部表情包。worker 线程（`thumb`/`video_cache`）仍在主线程读好 `current_proxies()` 再显式传。要认证的代理把 `用户名:密码@` 写进地址。`scripts/check_proxy_hint.py` 会检查每个工厂产出的 session `trust_env is False`。详见 `docs/proxy_diagnostics.md`。
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
- **屏幕外脚本**（`QT_QPA_PLATFORM=offscreen`）：`scripts/` 下已有多个可直接跑的断言脚本（命令见「常用命令」）。新写脚本的套路：构建页面 + 注入假数据（假 `EmotePackage` / 预置 `QPixmapCache.insert(url, pm)` 绕开网络）+ 断言几何/信号/像素，失败 `sys.exit(1)`。
  - 涉及后台任务时**必须轮询等任务完成再退出**（见线程规则），不要 `processEvents()` 后立刻结束。
  - **等属性动画（展开/滚动）要等真实时间**：光 `processEvents()` 不推进时间，须 `processEvents()` + `time.sleep(0.01)` 轮询到目标状态（设置页展开断言曾因此假失败）。
  - 脚本从 `scripts/` 运行，开头需 `sys.path.insert(0, 项目根)` 才 import 得到 `app`。
  - **要写配置/缓存/历史的脚本必须先隔离 `APPDATA`**：`APP_CONFIG_DIR` 在 import 时按 `APPDATA` 计算，脚本要在 `import app.*` **之前** `os.environ["APPDATA"] = tempfile.mkdtemp(...)`，否则会写脏用户真实的 `config.json` / `search_history.json` / 缓存目录。
  - **量动画结果要等动画真正结束**：只等「高度 > 0」会量到中间帧（历史面板曾断言到 11px 而不是最终 42px），轮询 `QPropertyAnimation.state() != Running`。
  - **离屏平台窗口不激活，`setFocus()` 未必发 `FocusIn`**：验证焦点相关行为直接 `app.sendEvent(w, QFocusEvent(QEvent.Type.FocusIn))` 更稳。
  - 弹窗类组件用 `show()` 而非 `exec()`（offscreen 下 `exec()` 会阻塞脚本）。
- 真实 B 站网络流程（拉取、下载、收藏集搜索）依赖用户 Cookie，无法自动化，需人工验证。
- 每次改动后跑 `uv run ruff check .` 与导入自检（`uv run python -c "import app.MainWindow"`）。