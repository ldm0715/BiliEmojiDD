# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

B 站表情包 / 收藏集（装扮）下载器 GUI：PySide6 + QFluentWidgets 界面，`biliemoji==2.0.0` 提供 B 站接口能力。功能：表情包按 ID 查询 / 全量列表多选加入下载队列、包详情（GIF 开关）下载、收藏集关键词搜索 + **竖版四列卡片（收藏集/装扮类别徽标）+ 多选加入下载队列** + 详情预览（动态尺寸图片网格 + 视频折叠列表）+ image/video/both 下载、**下载队列 Tab**（会话级，**混合表情包 + 收藏集**，全选/删除/清空/批量下载）、**下载设置**（目录 + 代理 + 线程数）、缩略图懒加载、全部表情包本地缓存。中文 UI。

## 常用命令

```bash
uv sync                                   # 安装/重建依赖
uv run python main.py                     # 启动应用（会弹窗）
uv run ruff check .                       # lint（--fix 自动修复）
uv run python -c "import biliemoji, qfluentwidgets, PySide6"   # 导入自检
```

无测试框架（未配置 pytest）。GUI 逻辑用屏幕外脚本验证（见「验证」）。

## 环境约束（重要，勿改动）

- **Python 3.11**（`.python-version`）。**不要升级到 3.12**：qfluentwidgets 来自 GitHub fork `ldm0715/PyQt-Fluent-Widgets@PySide6`（v1.5.1），其 `setup.py` 要求 `PySide6<=6.4.2`，而 6.4.2 无 py3.12 wheel。代码禁用 PEP 701（f-string 内嵌同引号）等 3.12 专属语法——嵌套 f-string 请用 `('#' + str(x))` 之类写法。
- **不要**把 qfluentwidgets 换回官方 PyPI 版（`PySide6-Fluent-Widgets[full]`）。开源版（官方与 fork）都没有数字分页组件（`Pagination` 属 Pro 版），`app/components/page_bar.py` 的 `PageBar` 是自制组件。
- 依赖声明在 `pyproject.toml`，`[tool.uv] package=false`（应用非库）。

## 架构

- `main.py`：入口。**先建 `QApplication` 再导入 `MainWindow`**（保证控件/信号在主线程构造）；`setTheme(cfg.theme.value)` 应用主题；启动时 `proxy_env.remember()` + `apply(cfg.proxy.value)` 快照并应用代理环境变量。
- `app/MainWindow.py`：`FluentWindow` **四页导航**（表情包/收藏集/下载/设置，设置在 BOTTOM）。`closeEvent` 里：有运行中下载时弹确认（下载不支持安全中断，退出会残留 `.part`）；`task_manager.clear_pending()` 只清未开始任务。
- `app/common/`：
  - `config.py`：`AppConfig(QConfig)` 单例 `cfg`，**持久化到 `%APPDATA%/biliEmojiDD/config.json`**（不写项目目录）。项：`cookie`、`download_dir`、`default_gif`、`max_workers`(1–16)、`proxy`、`theme`。`theme` 项必须带 `EnumSerializer(Theme)`（否则 JSON 序列化崩）。
  - `signal_bus.py`：全局信号（缩略图、配置变更）。
  - `exception.py`：`show_bili_error(e, parent)` 统一 `BiliError` 子类 → 中文提示（`AuthRequired`→引导设置页、`DressNotFound`→"没有结果" 等）。提示走 `app/common/notify.py` 的 helper，不直接用 `InfoBar`。
  - `proxy.py`：`parse_proxy/split_proxy/build_proxy/proxy_scheme` + `ProxyEnvManager`（`remember` 快照 / `apply` 设置或清空恢复原值）。
  - `notify.py`：`notify_success/warning/error/info` —— **垂直布局 InfoBar**（标题一行/内容换行/按钮一行），全应用统一入口。
- `app/components/`：
  - `task.py`：**线程层核心**。`Task`(QRunnable) + `TaskManager`（持有引用，finished 自动释放）+ `run_task()`。信号对象在主线程构造（亲和主线程），worker 线程 emit 自动 QueuedConnection。`autoDelete(False)` 防 C++ 对象提前释放丢信号。全局线程池 max 4。
  - `thumb.py`：异步缩略图。worker 向**常驻 `signal_bus`** 发原始信号（`thumbRawLoaded`/`thumbRawFailed`），主线程转 `QPixmap` 写 `QPixmapCache` 再广播 `thumbLoaded`。emit 用 try/except 守卫（应用关闭时忽略）。
  - `widgets.py`：`EmojiCard`/`EmojiGrid`（表情网格）、`_CardGridBase`（QListWidget 网格基类：懒加载缩略图 + 多选 API + 动态单元格）、`PackageCard`+`PackageGrid`（表情包卡片/网格）、`DressCard`+`DressGrid`（收藏集竖版四列卡片）、`DetailCard`+`DressDetailGrid`（详情动态尺寸网格）、`QueueCard`+`QueueList`（下载队列横向混合卡片）。
  - `package_detail.py`（包详情视图，两个入口复用）、`page_bar.py`（自制数字分页）、`download_runner.py`（`start_download` + `download_package_batch`/`download_collection_batch`/`download_mixed_batch`）、`download_queue.py`（下载队列单例）、`dress_helpers.py`（收藏集类别判别 + dlc id 读取）、`cache.py`（全部表情包缓存）。
- `app/view/`：`emoji_page.py`（Pivot 双标签 + 多选工具栏）、`dress_page.py`、`download_page.py`（下载队列页）、`setting_page.py`。

## 线程与 GUI 规则（易踩坑）

- 所有网络 I/O（biliemoji 调用、下载、缩略图）必须在后台线程，结果经 Qt 信号回主线程；**worker 线程禁止直接改控件**。
- biliemoji 下载器的 `on_progress(done, total, result)` 在内部线程池调用 → 桥接成 Qt 信号（`run_task(..., needs_progress=True)` 自动处理）。
- **on_progress 统一协议 `(done, total, result)`**：`result is None` 表示下载准备阶段（读取包详情），`start_download` 据此显示状态文字；自定义下载闭包必须 `def task(on_progress=None):` 并透传给 biliemoji（缺参会抛 `TypeError`）。
- `QPixmap` 只能在主线程创建/使用；worker 线程只产 `QImage` 或字节数据。
- `FlowLayout.takeAt(index)` 返回 **widget**（不是 QLayoutItem）；清理布局用 `widget.setParent(None)` + `deleteLater()` 防幽灵残影。
- **`QPushButton` 垂直 size policy 默认 `Fixed`**：`QVBoxLayout` 里加 `stretch=1` 也拉不撑（海报被压成 12px 的坑，多余空间全给文字 label）；需撑满时 `setSizePolicy(Expanding, Expanding)`。
- **qfluentwidgets `ComboBox.addItem(text, icon, userData)`**：第二位置参数是 **icon** 不是 userData；要 `currentData()` 有值必须 `addItem('文本', userData=值)`（曾致下载模式 `mode.lower()` 崩、设置页代理/主题切换失效）。
- **验证 worker 信号时**：不要写"短暂 `processEvents()` 后结束脚本"的测试——脚本退出早于 worker 会看到 `Internal C++ object ... already deleted` **假象**（真实 app 里 `app.exec()` 常驻无此问题）。要轮询等任务完成再退出。

## 下载队列与下载设置（要点）

- **队列**：`download_queue`（`app/components/download_queue.py`）内存单例，**混合表情包 + 收藏集**，按 `item_key(item)`（`("pkg", id)` / `("coll", raw["item_id"])`）去重，`item_kind` 判类型；`changed` 信号驱动 `DownloadPage` 重建。**仅本次会话**，重启清空。
- **批量下载**：`download_runner.download_package_batch(ids, dest, *, gif=None, max_workers=None, on_progress=None)`（表情包）与 `download_collection_batch(collections, dest, *, mode='both', max_workers=None, on_progress=None)`（收藏集，目录 `dest/收藏集名`）同构；下载页 `download_mixed_batch` 按 `item_kind` 拆分、顺序执行两子批并合并 `DownloadBatchResult`。`max_workers` 传入值优先、None 才读 `cfg.max_workers.value`；逐项 `certain_*_typed`（**单个失败 `except Exception` 合成 FAILED 结果后继续**，不中断整批）；**一个 `Downloader` + 一个总进度条**；表情包目录 `包名[:60] [包ID]` 防同名覆盖、文件名截断。
- **`start_download` 返回 False** 表示下载目录不可用（未建任务、无 finished 信号）——调用点必须自行恢复按钮状态，否则按钮永久禁用。
- **卡片多选**（`PackageCard`/`DressCard`/`QueueCard` 同套路）：容器无 Layout（或外层布局 + 绝对定位勾选框）；图片是 `QPushButton(setFlat=True)`（点击整图切换勾选）；勾选框 `CheckBox` 用 `setGeometry` 钉在图片/卡片右上角 + `raise_()`；选中背景通过 `toggled` 同步整卡样式表背景，**必须 `setAttribute(WA_StyledBackground)`**（普通 QWidget 默认不绘制 stylesheet 背景）。`DressCard` 是纯 QWidget（**不用 `CardWidget`**：其基类 `mouseReleaseEvent` 只发 0 参数 `clicked`，与 `Signal(object)` 冲突 → 点击死）。多选/懒加载逻辑统一在 `_CardGridBase`，卡片只需暴露 `.item` / `set_selectable` / `set_checked` / `is_checked` / `set_pixmap` / `set_cell` / `clicked` / `toggled`。
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
- GUI 逻辑用屏幕外脚本验证（`QT_QPA_PLATFORM=offscreen` 构建页面 + 注入假 `EmotePackage` 数据 + 检查几何/信号/像素断言），但必须**等待后台任务完成**（见线程规则）。
- 真实 B 站网络流程（拉取、下载、收藏集搜索）依赖用户 Cookie，无法自动化，需人工验证。
- 每次改动后跑 `uv run ruff check .` 与导入自检（`uv run python -c "import app.MainWindow"`）。
