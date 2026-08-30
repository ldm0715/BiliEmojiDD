# 架构设计

## 技术栈与依赖

| 组件 | 说明 |
|---|---|
| Python 3.11 | `uv` 管理环境；**不要升级到 3.12**（见下） |
| PySide6 6.4.2 | Qt 绑定，锁定版本 |
| qfluentwidgets 1.5.1 | UI 组件库，来自 GitHub fork `ldm0715/PyQt-Fluent-Widgets@PySide6`，非官方 PyPI |
| biliemoji 2.0.0 | B 站表情包 / 收藏集 SDK（功能基座，只依赖 requests） |
| ruff | 代码检查 |

### 依赖锁定原因（勿改）

- qfluentwidgets 的 fork 要求 `PySide6<=6.4.2`，而 PySide6 6.4.2 **没有 Python 3.12 wheel**，因此项目锁定 Python 3.11。
- 官方 / 开源版 qfluentwidgets 都**没有数字分页组件**（`Pagination` 属 Pro 版），因此 `PageBar` 是自制组件。

## 模块分层

```
main.py                 入口：先建 QApplication 再导入 MainWindow（线程亲和）
app/
├── MainWindow.py       FluentWindow 五页导航 + 启动后静默检查更新 + closeEvent 退出保护
├── common/
│   ├── config.py       AppConfig(QConfig) 单例，存 %APPDATA%/biliEmojiDD/config.json
│   ├── version.py      版本号：读 pyproject.toml + tag 比较（is_newer）
│   ├── resource.py     静态资源定位（编译后按 exe 目录找）
│   ├── signal_bus.py   全局信号（缩略图、配置变更）
│   ├── proxy.py        代理地址字符串工具（规范化 / 转 proxies 字典 / 打码）
│   ├── net.py          联网对象工厂：显式代理 + trust_env=False（不读系统代理）
│   ├── font.py         内置字体 + qfluentwidgets getFont 补丁 + 渲染后端切换
│   ├── notify.py       统一消息提示（垂直布局 InfoBar）
│   └── exception.py    show_bili_error：BiliError 子类 → 中文 InfoBar
├── components/
│   ├── task.py         线程层核心：Task(QRunnable) + TaskManager + run_task
│   ├── thumb.py        异步缩略图（独立线程池 + QPixmapCache）
│   ├── widgets.py      _CardGridBase 网格基类；Package/Dress/Queue/Detail 卡片与网格
│   ├── page_scaffold.py 页面版式底座 + 版本号胶囊 version_badge
│   ├── package_detail.py  表情包详情视图（两个入口复用）
│   ├── image_viewer.py 遮罩图片查看器（FlipView lightbox + 左右翻页）
│   ├── page_bar.py     自制数字分页条
│   ├── updater.py      查 GitHub Release / 加速镜像 / 下载安装包 + SHA-256 校验
│   ├── update_dialog.py 更新弹窗（markdown 渲染 + 下载并运行安装程序）
│   ├── download_runner.py 统一下载流程 + 表情包/收藏集/混合批量下载
│   ├── download_queue.py  会话级下载队列（混合表情包 + 收藏集）
│   ├── dress_helpers.py   收藏集类别判别 + dlc id 读取（绕开 biliemoji typed 字段 bug）
│   └── cache.py        全部表情包本地缓存
└── view/
    ├── home_page.py    主页（启动默认页）
    ├── emoji_page.py   表情包页（Pivot 双标签）
    ├── dress_page.py   收藏集页（四列搜索 / 多选加入队列 / 详情）
    ├── download_page.py 下载队列页（混合横向卡片 / 批量下载）
    └── setting_page.py 设置页（关于 / 账号 / 下载 / 缓存 / 外观）

packaging/              打包（非运行时代码，见 docs/update_and_packaging.md）
├── build.py            Nuitka 编译 + NSIS + 便携 zip + SHA256SUMS + release_notes
├── changelog.py        按版本号抽取 CHANGES.md 的小节
└── installer.nsi       NSIS 安装脚本（当前用户级安装）
```

## 线程模型

**核心原则：所有网络 I/O 在后台线程执行，结果经 Qt 信号回主线程；worker 线程禁止直接操作控件。**

```
UI 线程（主线程）              后台线程（QThreadPool / Python 线程）
┌──────────────────────┐      ┌──────────────────────────┐
│ 页面控件（QWidget）    │      │ biliemoji 调用            │
│ 信号对象（亲和主线程）  │◄────►│ 下载器 on_progress 回调    │
│ QPixmap / QPixmapCache│ 信号  │ QImage / 字节数据         │
└──────────────────────┘      └──────────────────────────┘
```

### 通用任务层（`components/task.py`）

- `Task(QRunnable)`：把可调用对象放到线程池执行，`autoDelete(False)` + `TaskManager` 持有 Python 引用（finished 自动释放），避免 C++ 对象提前释放导致队列信号丢失。
- 信号对象（`TaskSignals`）在**主线程构造**（亲和主线程），worker 线程 emit 时 Qt 自动 QueuedConnection 投递回主线程。
- 全局线程池 max 4（`download_package` 内部还有并发，避免叠加打爆网络）。
- `run_task(fn, on_success=, on_error=, on_progress=, on_finished=, needs_progress=)` 是统一入口；`needs_progress=True` 时自动把 biliemoji 的 `on_progress(done, total, result)` 桥接成 `progress` 信号。

### 缩略图（`components/thumb.py`）

- worker 直接向**常驻 `signal_bus`** 发原始信号（`thumbRawLoaded` / `thumbRawFailed`），避免任务对象持有的 QObject 在应用关闭时被提前释放。
- 主线程收到后：`QPixmap.fromImage` → `QPixmapCache` 缓存 → 广播 `thumbLoaded(url, pixmap)`。
- 独立线程池 max 3，按 URL 去重（`_inflight`）；worker 只产 `QImage`，`QPixmap` 仅主线程。

### 下载流程（`components/download_runner.py`）

`start_download(task_fn, progress_bar, on_finished, parent, status_label)` 统一处理：目录校验（mkdir + PermissionError）、进度条（防除零 `setRange(0, max(total,1))`）、结果统计（成功/失败/跳过）、「打开所在文件夹」按钮。下载任务标记 `is_download=True`，供 `closeEvent` 判断退出保护。

批量下载三个入口：`download_package_batch`（表情包）、`download_collection_batch`（收藏集）、`download_mixed_batch`（混合，下载页「下载选中」用）。三者同构：单 `Downloader` + 单进度条 + 显式 `proxies` + 逐项 `except Exception` 合成 FAILED 继续不中断整批。

## 数据流示例

**按 ID 查询表情包**：`_IdQueryTab` → `run_task(Emoji.certain_emoji_typed(ids))` → `Task` 后台请求 → `result` 信号 → `PackageDetailView.set_package(pkg)` → `EmojiGrid.set_emotes` → 逐卡 `thumb_manager.request(url)` → 缩略图 worker 下载解码 → `thumbLoaded` → 卡片图标。

**全部表情包**：`_AllPackagesTab._on_fetch` → 优先读本地缓存 → 未命中则 `run_task(Emoji.all_packages())` → 成功后 `cache.save_all_packages_cache` 落盘 → `_repopulate` 本地关键词过滤 + `PageBar` 分页（每页 20）→ 点击卡片 → `run_task(Emoji.certain_emoji_typed(id))` 拉完整详情（all_packages 只含元信息）。

**收藏集搜索与详情**：`DressPage` → `run_task(search_dress_typed)` → `DressGrid` 四列卡片（类别徽标读 `dress_helpers`，绕开 biliemoji `is_collection` bug）→ 点击 → `dlc_ids(summary)` 取字符串 id → `run_task(certain_lottery_typed)` → 内容预览卡按 `Pivot` 分两页：`DressDetailGrid`（卡片尺寸按视口/数量动态计算）与「动态视频」（`CollectionVideoPlayer` 内嵌播放器 + `VideoStrip` 缩略图选择条）。

**收藏集视频播放**：`video_cache` 独立线程池（2）→ `Downloader` 下到会话临时目录（显式 proxies）→ `signal_bus.videoRawReady`（worker）→ 主线程写缓存 → `videoReady` → `CollectionVideoPlayer` 校验 `_pending_url` 后 `setVideo(QUrl.fromLocalFile(...))`。不流式播远程 URL：`QMediaPlayer` 走系统代理、不读应用内代理设置（详见 `docs/collection_video.md`）。

**混合下载队列**：表情包 / 收藏集页多选「加入下载」→ `download_queue.add_many`（按 `item_kind`/`item_key` 去重）→ 下载页 `QueueList` 统一横向卡片 → 「下载选中」→ `download_mixed_batch` 按类型拆分顺序执行两子批并合并结果。

## 配置与缓存

- 配置：`AppConfig(QConfig)`，`qconfig.load` 持久化到 `%APPDATA%/biliEmojiDD/config.json`。`theme` 项带 `EnumSerializer(Theme)`（否则 `json.dump` 崩）。Cookie / 目录变更即时生效（每次操作现读 `cfg`）。
- 缓存：`all_packages` 结果按 cookie 指纹 + 24h TTL 存 `%APPDATA%/biliEmojiDD/all_packages.json`；用 `EmotePackage.raw`（完整原始 dict）持久化、`from_dict` 无损重建。
- 版本号：**唯一来源是 `pyproject.toml` 的 `[project] version`**，`app/common/version.py::project_version()` 用 `tomllib` 在运行时读（`[tool.uv] package=false` 拿不到 `importlib.metadata`）。编译后该文件随 exe 一起分发。读不到时返回 `"unknown"`——一个解析不出来的值，使检查更新安静地不提示而不是误报有新版。
