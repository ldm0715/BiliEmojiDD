# 架构与逻辑规范

## 分层与模块边界

- `app/common` → `app/components` → `app/view` 三层扁平，只允许上层依赖下层，无更深嵌套。
- 页面只做装配 + 信号槽：查询类走 `run_task`，下载类走 `start_download`，
  不要在页面里直接 new 上游对象。
- 新增功能页面：在 `app/view/` 建 `xxx_page.py` 并设非空 `objectName`
  → 在 `app/MainWindow.py::initNavigation()` 注册 `addSubInterface`。
- 新增静态资源一律从 `PROJECT_ROOT`（`app/common/resource.py`）起算，
  并在 `packaging/build.py` 加对应的 `--include-data-*`。
- 按需 / 懒加载的第三方模块必须在 `packaging/build.py` 里 `--include-module` 显式带上
  （`socks` 由 urllib3 在代理写 `socks5://` 时才 import）。
- 模型类从 `biliemoji.models` 导入（`EmotePackage` 等顶层不导出）；biliemoji API
  以其 2.0.0 实际签名为准（inspect 或读 `.venv/Lib/site-packages/biliemoji/`）。
- `app/components/api_cache.py` 的三个函数只在 worker 线程调用；
  `disk_cache` 全程持 `threading.RLock` 以支持 worker 并发。

## 线程与信号

- 所有网络 I/O 在后台线程，结果经 Qt 信号回主线程；worker 禁止直接操作控件。
- `Task(QRunnable)` 必须 `autoDelete(False)`、由 `TaskManager` 持有 Python 引用
  （finished 时释放），否则队列信号可能丢失。
- 信号对象（`TaskSignals`）必须在主线程构造；worker emit 时靠 Qt QueuedConnection 投递回主线程。
- 统一入口 `run_task(fn, on_success=, on_error=, on_progress=, on_finished=, needs_progress=)`；
  `needs_progress=True` 时自动把 `on_progress(done, total, result)` 桥接成 `progress` 信号。
- **下载类闭包必须写成 `def task(on_progress=None):` 并透传**，否则 `needs_progress=True`
  注入参数时抛 `TypeError`、下载必然失败。
- **「正在飞」标志的清理必须挂 `on_finished`**（成功与两条异常路都走它），只挂 `on_success`
  会让失败一次后永不重试。
- 全局线程池 max 4（`download_package` 内部另有并发，避免叠加打爆网络）。
- 下载流程统一走 `start_download(task_fn, progress_bar, on_finished, parent, status_label)`：
  目录校验（mkdir + PermissionError）、进度条 `setRange(0, max(total,1))` 防除零、结果统计、
  打开文件夹按钮。`start_download` 返回 False 时，**调用点必须主动恢复被禁用的按钮**
  （否则按钮永久卡死）。
- 批量下载三入口 `download_package_batch` / `download_collection_batch` / `download_mixed_batch`
  必须同构：单 `Downloader` + 单进度条 + 显式 `proxies` + 逐项 `except Exception` 合成 FAILED
  后继续，不中断整批。
- `download_package_batch(ids, dest, *, gif=None, max_workers=None, on_progress=None)`：
  传入的 `max_workers` 优先，仅 `None` 时读 `cfg.max_workers.value`；空 ids / 全失败仍返回结构
  合法的 `DownloadBatchResult`；准备阶段用 `on_progress(i, n, None)` 标记。
- 下载任务标记 `is_download=True`，供 `MainWindow.closeEvent` 退出保护判断。
- 缩略图用独立线程池 max 3、按 URL 去重（`_inflight`）；worker 只产 `QImage`，
  `QPixmap` 只在主线程创建 / 使用。
- 缩略图 worker 直接向常驻 `signal_bus` 发原始信号（`thumbRawLoaded` / `thumbRawFailed`），
  不要挂在任务对象持有的 QObject 上（应用关闭时会被提前释放）。主线程收到后
  `QPixmap.fromImage` → `QPixmapCache` → 广播 `thumbLoaded(url, pixmap)`。
- 收藏集视频走 `video_cache` 独立线程池（2），详见 `.claude/rules/qt-ui.md` 内嵌视频节。
- 缩略图 `reload(url)` 必须**先清内存再请求**：`QPixmapCache.remove(url)` →
  `image_cache.remove(url)` → `_inflight.discard(url)` → `request(url)`；顺序反了会命中旧
  `QPixmapCache` 同步 emit 旧图。
- `video_cache.forget(url)` 做三件事：清 `_failed`、清 `_cache`、删临时文件；删文件前必须判定
  是否自己 `mkdtemp` 出来的（`_temp_dir is None or _temp_dir not in target.parents` 就只摘引用不删）
  ——`_adopt_downloaded_videos` 登记进来的可能是用户下载目录里的成品 mp4。
- `reload_url(url)` 必须把 url 重新塞进 `_requested`（避免 `_update_visible` 再排重复请求），
  对所有用该 url 的卡片 `thumb_restart()`，最后调 `thumb_manager.reload(url)`。
- 失败态必须给出口：右键菜单（统一入口）+ 失败态直接可点；六个网格统一在 `_CardGridBase` 上实现。
- **带载荷的信号不能直接接无参槽**（`cookieStateChanged` 载 `str`，`connect(self.refresh)`
  会 `TypeError`），要包一层转发槽或 lambda。

## 联网与代理

- **所有 session 必须 `trust_env = False`**：不读环境变量与系统代理（Windows 上
  `urllib.request.getproxies()` 会读注册表 IE / 系统代理，并经 `merge_setting` 覆盖显式传入的
  `proxies`）。
- 新增联网代码一律走 `app/common/net.py` 的工厂（`current_proxies` / `make_client` /
  `make_emoji` / `make_dress` / `make_downloader` / `make_session` / `make_bili_session`），
  别直接 new `Emoji` / `Dress` / `BiliClient` / `Downloader`。
- 工厂的 `proxies` 参数默认值是哨兵 `_FROM_CFG` 而不是 `None`：漏传时自动读配置，
  不许静默变直连。`make_downloader` 用 `_NoEnvDownloader` 覆写 `_build_session()`。
- worker（`thumb` / `video_cache`）在主线程读好 `current_proxies()` 再显式传进去，worker 不碰 `cfg`。
- **`download_collection` / `download_package` 不把 `proxies` 传给内部 `Downloader`**，
  需要代理的批量下载必须走 `download_*_batch`。
- 不要再用 `ProxyEnvManager` / `HTTP(S)_PROXY` 环境变量兜底，代理只来自设置页。
- `proxy_enabled` 一律默认关，不写任何「老配置里有地址就自动置开」的迁移。
- 地址含空格视为无效（`_current_proxy()` 返回 `None` + 提示）；无协议前缀补 `http://`；
  scheme 指代理自身协议（`http` / `https` / `socks5` / `socks5h`），不是被代理流量的协议。
- `_current_proxy()` 是唯一的取值 / 校验入口：开关关 → `""`；开着地址为空 / 含空格 → `None` + 提示；
  其余 → `normalize_proxy(text)`。开关关着时地址框与「测试」按钮都要 disable，关开关不清空地址。
- 保留 `PySocks` 依赖（地址框写 `socks5://127.0.0.1:7891` 靠它，删了会变成 `InvalidSchema`）。
- **`redact_proxy` 必须按最后一个 `@` 切认证段**（`@` 是合法密码字符，`urlsplit` 按第一个切是错的）。
- 「测试」按钮走 `app/components/proxy_probe.py::probe_proxy(proxy_text)`，用**当前控件里的值**
  （不是已保存值）打一次不需要 Cookie 的收藏集搜索接口（超时 15s），`DressNotFound` 也算通；
  只在 worker 线程（`run_task`）调用。
- 探针 URL 要抄一份常量（`PROBE_URL`），**不要 import `biliemoji.dress._SEARCH_URL`**
  （上游改私有常量时最多文案过时，不会 `ImportError` 崩掉测试）。
- 代理修改即时生效：开关一拨、地址框 `editingFinished`（回车 / 焦点移开）就 `qconfig.set`；
  自动保存静默（地址含空格不写也不弹提示），空地址照写。
- 卡片副标题显示**当前生效的代理**（读 `cfg` 不是读输入框，密码打码），三态：关闭 → 「已关闭：
  所有请求直连，不读系统代理」；开启有地址 → `当前生效：http://u:***@1.2.3.4:8080`；
  开启空地址 → 「已开启但地址为空，仍是直连」。
- 代理测试失败不走通用 `show_bili_error`，用设置页自己的 `_on_proxy_failed`：按下「测试」时先
  `_autosave_proxy()`（保证测的就是生效的），提示写明 `_probed_proxy`（打码）与
  `测试接口：GET <PROBE_URL>`，并用 `duration=NEVER_DISMISS`。
- `_BusyPushButton`：给加载环腾位的空格数按空格**实际宽度现算**（不写死）；宽度按忙碌态预留
  （`reserve_busy`）防按钮变宽整行跳动；收环后调 `_sync_proxy_enabled(开关状态)`，
  不能无条件 `setEnabled(True)`。
- 下载加速镜像与「设置 → 下载 → 代理」互不影响、可同时用；镜像请求仍走 `make_session()`，
  照样受代理开关管、照样 `trust_env=False`。
- `download_urls` 候选顺序：`""` → `[原始地址]`；具体镜像 → **只走那一家**（失败不回退，
  让用户看出是镜像的问题）；`"auto"` → `[原始, 再按用户排的顺序逐个镜像]`。
  `fetch_latest_release`（API 请求）永远先直连，失败且配了镜像才用镜像重试。
- `orderable_mirrors()` 是唯一读取入口，规则是「顺序表只记顺序不记成员」：表里没有的源被过滤、
  没进表的按默认顺序补在后面；直连那行钉在最前不参与排序。
  **改自定义源地址时必须先算顺序再改成员**（`update_custom_mirror`），反了会让改完的源被排到末尾。
- 测速并发上限 8，`stream=True` 只取响应头，用**挂钟**计时（不用 `response.elapsed`，
  它不含 DNS 与握手）。分档：通了且 < `LATENCY_GOOD_MS`(1000ms) = 绿；通了更慢 = 橙；
  连不上 / 超时 / 镜像自身 5xx = 红；**4xx 也算通**。结果经 `run_task(needs_progress=True)`
  回主线程，每测完一个点亮一行。
- 拖动排序手写「摘出来 + 占位符」，**不要用 `QListWidget.InternalMove`**
  （`setItemWidget` 场景下移动时会丢 item widget）；`_on_drag_start` 必须把被拖行 `removeWidget`
  出布局（留在布局里每次重排都会覆盖 `move()` 结果）。

## 配置与校验器

- 配置持久化到 `%APPDATA%/biliEmojiDD/config.json`，不写项目目录（打包后不可写）。
- **只有 `qconfig.set(item, value)` 才落盘**；直接写 `cfg.item.value = v` 只改内存
  （迁移里的临时改动靠这个）。
- 设置项一律「改完即落库」（`editingFinished` / `valueChanged` / `checkedChanged` 里
  `qconfig.set`），**不做「点保存才生效」**；改完直接关窗的边角由 `MainWindow.closeEvent`
  → `SettingPage.commit_pending_edits()` 兜住。
- **新增枚举类配置项必须配 `EnumSerializer`**，否则 `qconfig.save()` 的 `json.dump` 抛 `TypeError`。
- **布尔项一律用 `config.py::_StrictBoolValidator(该项默认值)`，禁用上游 `BoolValidator`**：
  它是 `OptionsValidator([True, False])`，而 `OptionsValidator.correct()` 把非法值兜成 `options[0]`
  → 恒为 `True`（`proxyEnabled` 曾因此被自动读成「开」）。
- `OptionsValidator` 把非法值兜成 `options[0]`，所以 `scroll_fps` 的 `60` 必须排在 `120` 前面。
- `gh_mirror` 不能配 `OptionsValidator`：取值集合随用户增删而变，写死校验器会让自定义源
  一保存就被打回默认值。
- 新增普通字段不需要写迁移：`config.py::_ensure_persisted()` 启动时比一次「文件原文 vs 内存快照」，
  缺键就补写；默认值本身要能表达「没有」（如 `cookieCheckedAt=0` / `cookieCheckedHash=""`）。
- 只有需要「根据老数据推断新值」时才动 `CONFIG_SCHEMA`（+1）与 `_migrate()`，
  且迁移的熄火标记必须是显式 `schema_version`（`ConfigItem("App", "schema", 0)`）——
  **不能靠「文件里有没有这个键」**（`qconfig.set` 值没变时直接 return 不落盘，
  靠键存在会永久武装、把用户明确改过的设置反复翻回去）。
- `_migrate()` 只改内存、只在 `schema < CONFIG_SCHEMA` 时跑，落盘统一交给 `_ensure_persisted()`。
- 配置项范围：`max_workers` 1–16、`cache_limit_mb` 64–8192（默认 512）、`proxy_enabled` 默认关、
  `auto_check_update` 默认开、`font_engine` 取 `default`/`freetype`、`scroll_fps` 取 60/120。
- Cookie / 目录变更即时生效：每次操作现读 `cfg`。
- `account_name` / `account_mid` / `account_face` 只用于展示，启动时不联网刷新。

## 缓存与存储

- `DiskCache` 写 `.part` 再 `os.replace` 原子落盘。
- `DiskCache` **不写索引文件**：LRU 时间戳直接用文件 `mtime`（读命中时 `os.utime` 刷新）；
  TTL 与 LRU 冲突，只有 `touch_on_read=False` 的实例（`api_store`）才用 TTL。
- `DiskCache` 上限每次 `put` 时现读 `cfg.cache_limit_mb.value`（改设置立即生效、无需重启）；
  超限按 mtime 升序删到上限的 90%（留余量）。接口缓存单独封顶
  `max(8MB, min(64MB, 上限/8))`，不挤占图片配额。
- **缓存操作所有异常吞掉**：缓存坏掉最多多一次网络请求，绝不能把主流程带崩。
- `QPixmapCache` 上限设为 64 MB（`thumb.py::setCacheLimit`，单位 KB），默认 10 MB 会导致翻页重下。
- 图片三层缓存顺序固定：内存 `QPixmapCache` → 磁盘 `image_cache` → 网络；
  接口层：磁盘 `api_store`（TTL）→ biliemoji 请求。
- 只缓存成功结果（`AuthRequired` / `DressNotFound` 照常抛给 `show_bili_error`）；
  `api_cache` 的 key 不掺 cookie 指纹（这三个接口与账号无关，`all_packages` 是例外）。
- `api_cache` 的 key 与 TTL 固定：`search_dress(num, keyword)` → `dress:search:{num}:{keyword}` /
  6 小时；`emoji_package(pid)` → `emoji:pkg:{pid}` / 24 小时；
  `dress_collection(act, lot)` → `dress:coll:{act}:{lot}` / 24 小时。
- 缓存必须存对象自带的 `raw` 原始 dict、读回用 `from_dict` 无损重建
  （`EmotePackage` / `DressCollection` / `DressCollectionSummary` 都支持）。
- `all_packages` 结果按 cookie 指纹（`cache.cookie_fingerprint`）+ 24h TTL 存
  `%APPDATA%/biliEmojiDD/all_packages.json`。
- 收藏集视频**不进持久缓存**：维持会话临时目录、退出即删；已整包下载过的收藏集走
  `_adopt_downloaded_videos` 直接播本地文件。
- Cookie 有效性记录（`cookie_checked_at` / `cookie_checked_hash` / `cookie_checked_state`）用与
  缓存相同的指纹口径，另有自己的信任期（见 `.claude/rules/features.md`）。
- 搜索历史存 `%APPDATA%/biliEmojiDD/search_history.json`，按 namespace 分表
  （`dress` / `emoji_id` / `emoji_filter`），每表最多 10 条 MRU。
- 下载文件名安全：目录 `dest / f"{清洗名[:60]} [{包ID}]"`，文件 `清洗名[:60] + ext`
  （含包 ID 防同名覆盖、截断超长名）。**队列项文件名 / 目录以包 ID 为唯一判据**，
  不要靠包名去重。
- 下载目录命名只有一个来源：`download_runner.package_download_dir(pkg)` /
  `collection_download_dir(summary)` / `live_folder_name(pack)`，两处各写一份的话徽标永远判不出。
  表情包目录 = `清洗名[:60] [包ID]`，收藏集目录 = `sanitize_filename(summary.name)`，
  直播间 = `<主播名[:60]> [<room_id>]`。

## 错误处理与提示

- 消息提示统一走 `app/common/notify.py` 的 helper（`notify_success` / `notify_warning` /
  `notify_error` / `notify_info`），**不要裸用 `InfoBar.*`**。
- **`duration=0` 不是「不消失」而是「立刻淡出」**（上游 `InfoBar.showEvent` 里
  `if duration >= 0`），永不消失必须用负值；用 `notify.py::NEVER_DISMISS = -1`。
- **InfoBar 内容不要依赖 `wordWrap`**（`QLabel` 开 `wordWrap` 后 `sizeHint` 最小宽度塌缩到 ~28px），
  改用 `TextWrap` 预换行 + 垂直布局（`orient=Qt.Vertical`）。
- BiliError 子类到中文 InfoBar 的映射统一走 `app/common/exception.py::show_bili_error`。
  层次：`AuthRequired`(-101)、`EmojiNotFound` / `DressNotFound`(-404)、`NetworkError`、
  `DownloadError`、`ValidationError`。
- `biliemoji.client` 把所有 requests 异常压成 `NetworkError(f"网络错误：{类型名}")`，
  真因只留在 `__cause__`；`cause_hint` 沿 `__cause__` / `__context__` 最多走 6 层收集
  (类名, 消息) 翻成可行动中文。
- **`cause_hint` 的判定顺序：407（`Proxy Authentication Required` / `Tunnel connection failed: 407`）
  必须排在其它 ProxyError 判断之前**（两个特征会同时命中）。
- `cause_hint` 只用于「外层消息无用、真因埋在 `__cause__` 里」的 biliemoji 类异常；失败详情优先用
  updater 自己的消息（`update_dialog._failure_detail`），别让 `cause_hint` 顺着 `from exc` 链
  越权盖掉真正该说的那句。
- `_proxy_suffix()` 跟着开关走：关 → 「当前未使用代理（代理开关已关闭）」。
- 失败提示里的建议要分情况：没配加速源才说「选一个镜像」，已配就说「测速后调整源与顺序」。
- 自动检查更新失败彻底静默（`on_error=lambda exc: None`）；发现新版只出一条带「查看更新」按钮的
  InfoBar（`duration=NEVER_DISMISS`），不弹模态窗。
- **`UpdateDialog` 的 `yesButton` 必须先 `clicked.disconnect()`**（上游
  `MessageBoxBase.__onYesButtonClicked` 直接 `accept()` 关窗，不断开则点「下载并安装」弹窗当场消失）。
- **关闭应用走 `window.close()` 而不是 `QApplication.quit()`**（后者不触发 `closeEvent`，
  `video_cache.cleanup()` 的临时目录会漏在磁盘上）。
- 安装包放 `%TEMP%/biliEmojiDD-update/`，**不要挂进 `video_cache.cleanup()`**（它要活过应用退出）。
- 下载摘要不符时：删 `.part` 文件 + 抛 `ChecksumMismatch` + 弹窗报「安装包校验失败」，**绝不运行**。
  退回取 `SHA256SUMS.txt` 失败时抛 `UpdateError`（不是裸 requests 异常）并明确说不安装。

## biliemoji 2.0.0 接口要点

- `Emoji`：`certain_emoji_typed(ids)` 按包 ID 查（含完整 emote）、`all_packages()` 全量
  （**需 cookie**，且只有包元信息、**不含完整 emote**，进详情须另调前者）、
  `download_package(ids, dest, gif=, max_workers=, on_progress=)`。
- `Dress`：`search_dress_typed(num, keyword)`（空结果抛 `DressNotFound`）、
  `certain_lottery_typed(act_id, lottery_id)`、
  `download_collection(..., mode='image'|'video'|'both')`。
- **`DressCollectionSummary.is_collection` / `.dlc_act_id` / `.dlc_lottery_id` / `.id` 恒为
  `None`/`False`**（API 把 id 以字符串返回，`_optional_int` 拒收）。判别与取 id 一律走
  `app/components/dress_helpers.py` 读 `raw`。
- **没有关键词搜索表情包的接口**；「搜索表情包」= 按 ID 查询 + `all_packages` 本地过滤。
- 下载器 `on_progress(done, total, result)` 在 worker 线程回调，不要在回调里直接碰控件。

## 版本号与发版

- 版本号唯一来源 `pyproject.toml` 的 `[project] version`，运行时由
  `app/common/version.py::project_version()` 用 `tomllib` 读；`[tool.uv] package = false`，
  `importlib.metadata` 拿不到版本，只能读文件。
- 读不到版本文件时返回 `"unknown"`——故意选一个 `is_newer` 解析不出来的值，
  使检查更新安静地不提示而不是误报新版。
- `is_newer` 规则：剥前导 `v` → 取开头数字段 → 补零对齐后逐位比 → 核心段相同时
  「正式版 > 预发布版」（`1.0.0` 新于 `1.0.0-rc.1`）；不引入 `packaging` 依赖。
- 发版硬性步骤：改 `pyproject.toml` → 在 `CHANGES.md` 顶部补 `## [x.y.z] - YYYY-MM-DD` 一节
  → 本地 `uv run ruff check .` + `uv run python -c "import app.MainWindow"` +
  `uv run python packaging/changelog.py <ver>` → `git commit` → `git tag vX.Y.Z`
  → `git push && git push --tags`。
- `CHANGES.md` 是更新日志**唯一来源**，GitHub Release 正文与应用内弹窗共用同一份。
- `packaging/changelog.py::extract(version)` 找不到该版本必须抛异常、构建失败
  （发一个更新说明为空的 Release 比构建失败更糟）；`build.py` 必须在**编译之前**先跑一次 `extract`。
  `extract` 标题匹配兼容 `## 0.1.0` / `## [0.1.0]` / `## v0.1.0 - 2026-08-30`，取到下一个 `## ` 为止。
- tag 与 `pyproject.toml` 版本号之间不加强制门禁（刻意按需求不加）。

## 打包与 CI

- 打包命令：`uv run python packaging/build.py`（只编译）/ `--installer`（加 NSIS + 便携 zip +
  校验和）/ `--installer --skip-compile`（只重打包）。产物全在 `dist/`：`BiliEmojiDD/`、
  `BiliEmojiDD-Setup-<ver>.exe`、`BiliEmojiDD-<ver>-win64.zip`、`SHA256SUMS.txt`、`release_notes.md`。
- Nuitka 参数固定：`--standalone`、`--enable-plugin=pyside6`、`--windows-console-mode=disable`
  （Nuitka 2.x 写法，1.x 的 `--windows-disable-console` 已废弃）、`--include-data-dir=static=static`、
  `--include-data-files=pyproject.toml=pyproject.toml`、`--include-package=app`、
  `--include-module=socks`、`--include-qt-plugins=multimedia`、`--assume-yes-for-downloads`、`--lto=no`。
- `app/common/resource.py::_project_root()` 资源定位分两种情形：`"__compiled__" in globals()`
  或 `sys.frozen` → `Path(sys.executable).resolve().parent`；否则 `Path(__file__).resolve().parents[2]`
  （Nuitka 编译后 `__file__` 指向 dist 内虚拟路径，不能拿来回溯）。
- `build.py::ascii_workarounds()` 在检测到非 ASCII 家目录时自动启用：加
  `--experimental=force-dependencies-pefile` 换掉 `depends.exe` 扫描（它按 latin1 解码路径会
  `AssertionError`），并把 `NUITKA_CACHE_DIR` 挪到 `C:\nuitka-cache` 这类 ASCII 路径。
- 没装 MSVC 且家目录含中文导致 `ld.exe: cannot find -lpython311` 时：把解释器装到 ASCII 路径再编，
  这个 venv 只用于打包，日常仍用 `.venv`。
- 安装包与便携 zip 必须算 SHA-256 并写成 `sha256sum` 格式的 `SHA256SUMS.txt` 随 Release 上传。
- 期望摘要取用顺序：① Release JSON 里 asset 的 `digest`（`parse_digest`，走 `api.github.com`、
  零额外请求）→ ② `SHA256SUMS.txt`（`_expected_sum`，走 `github.com`、老 Release 的退路）；
  两条路都必须是 GitHub 官方给的、都不经镜像。
- `parse_digest` 只认 `sha256:` 前缀（GitHub 回大写十六进制，统一转小写）；字段缺失 / `null` /
  只有算法头 / 夹非十六进制字符一律当没有（否则会变成「永远校验失败」而不是退回老路）。
- NSIS 必须当前用户级安装：`RequestExecutionLevel user` + `$LOCALAPPDATA\Programs\BiliEmojiDD`，
  注册表只写 `HKCU`，装卸不弹 UAC。卸载默认保留用户数据 `%APPDATA%\biliEmojiDD`，
  只用一句 `MessageBox MB_YESNO` 问是否一并删除。
- `.github/workflows/release.yml` 在 push `v*` tag 时触发、跑 `windows-latest`：checkout
  → setup-uv → `uv python install 3.11` → `uv sync --all-groups` → Ensure NSIS
  （`Get-Command makensis` 找不到就 `choco install nsis`）→
  `packaging/build.py --installer --version ${{ github.ref_name }}` →
  `softprops/action-gh-release`（`body_path: dist/release_notes.md`）。
- 编译打包全部在 CI runner 上完成，本地 `build.py` 只是开发期试跑用。
- `workflow_dispatch` 手动触发时：`version` 输入留空就不传 `--version`、不建 Release
  （`Publish release` 有 `if: startsWith(github.ref, 'refs/tags/')`）、产物改走
  `actions/upload-artifact`；但仍会走 `write_notes()`，`CHANGES.md` 里必须有当前版本号那一节。
- CI 里 Python 锁死 3.11（qfluentwidgets fork 要求 `PySide6<=6.4.2`，6.4.2 没有 3.12 wheel）。
