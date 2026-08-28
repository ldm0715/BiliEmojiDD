# 下载队列 + 下载设置（新增功能说明）

> **后续更新**：① 下载队列卡片 `QueueCard`/`QueueList` 改为**响应式布局**——宽视口两列、窄视口自动退回单列（`_cell_size` 数学保证不横向溢出），封面随单元格自适应方块、名称可换行防截断、信息区右侧预留勾选框空间；② 选中背景改用**类选择器**（如 `QueueCard { background-color: ... }`）限定自身，不再用通用 `*` 规则级联子 label（修复多选后文字区整块上色）；③ 所有文字标签改用 qfluentwidgets 主题化组件（`CaptionLabel`/`StrongBodyLabel`/`BodyLabel` + `setTextColor(light, dark)`），主题切换即时重刷；④ 补全深色主题（`app/common/theme.py` 全局调色板 + `bind_theme`）。

本次改动为应用新增了「下载队列」工作流，并补全了下载相关的设置项与若干关键修复。本文记录改动内容、关键实现与踩坑点，便于后续维护。

> **后续更新**：下载队列已扩展为**混合表情包 + 收藏集**（按 `(类型, ID)` 去重），下载页改用统一横向卡片 `QueueList`，并新增 `download_collection_batch` / `download_mixed_batch` 批量下载。详见 [collection_page.md](collection_page.md)。本文以下内容描述的是初版（仅表情包）实现。

## 一、背景

原应用只有「下载到本地」单包即时下载与收藏集下载，无法先挑选多个表情包、攒成队列再统一下载。本次新增：

1. 侧边栏「下载」Tab = **会话级下载队列**（内存，重启清空，按表情包 ID 去重）。
2. 表情包页支持**多选加入队列**；包详情页支持**一键加入队列**。
3. 下载队列页支持**全选 / 删除选中 / 清空 / 批量下载**（单进度条）。
4. 设置页新增**「下载」类别**：下载目录 + 代理（协议 / IP / 端口分栏）+ 下载线程数（1–16）。
5. 修复两个既有下载 Bug（见「四、修复的既有 Bug」）。

## 二、新增 / 修改文件

| 文件 | 说明 |
|---|---|
| `app/components/download_queue.py`（新） | 下载队列单例 `DownloadQueue` |
| `app/view/download_page.py`（新） | 「下载」Tab 页面 |
| `app/common/proxy.py`（新） | 代理解析 + HTTP(S)_PROXY 环境变量兜底管理 |
| `app/common/notify.py`（新） | 统一消息提示：垂直布局 InfoBar |
| `app/components/widgets.py` | `PackageCard`（卡片）+ `PackageGrid` 改为 `setItemWidget` 挂卡片 |
| `app/components/download_runner.py` | `start_download` 加状态文字；新增 `download_package_batch` 批量下载 |
| `app/view/emoji_page.py` | 全部表情包页多选工具栏；显式代理 |
| `app/components/package_detail.py` | 「加入下载」按钮；下载走批量 helper |
| `app/view/setting_page.py` | 「下载」设置卡（目录 / 代理 / 线程数） |
| `app/view/dress_page.py` | 修复下载闭包 + 显式代理 |
| `app/MainWindow.py` / `app/common/config.py` / `main.py` | 导航接入、`proxy` 配置项、启动应用代理环境 |

## 三、功能与实现要点

### 1. 下载队列 `DownloadQueue`

`app/components/download_queue.py`：

- `QObject` 子类，内存存储，按表情包 ID 去重；`changed = Signal()` 在增删改时发出。
- 方法：`add(pkg)->bool`（重复返回 False）、`add_many(pkgs)->int`、`remove(ids)`、`clear()`、`packages()`、`contains(id)`。
- **仅本次会话有效**，重启清空。

### 2. 下载队列页 `DownloadPage`

- 头部：数量标签 + `全选 / 删除选中 / 清空 / 下载选中`。
- 中部：`PackageGrid`（常开多选态）。
- 底部：`statusLabel`（下载准备状态）+ `ProgressBar`（隐藏）+ 空态提示。
- `_downloading` 门控：**下载中禁用 全选 / 删除 / 清空 / 下载**；完成后恢复。
- 队列项下载后**全部保留**（失败项保留、成功也不自动移除），可手动删除。

### 3. 多选加入（表情包页 / 下载页通用卡片）

`app/components/widgets.py`：

- `PackageCard`：容器**不设 Layout**；
  - 图片用 `QPushButton(setFlat=True)` —— 点击整图触发勾选 / 进入详情；
  - 勾选框 `CheckBox` 用 `setGeometry` 固定在**图片右上角**（内缩 4px）+ `raise_()` 置顶；
  - 文字 `QLabel` 居中且宽度对齐图片；
  - **选中背景**：`toggled` 信号同步整卡背景色（半透明主题色，含文字区）。需 `setAttribute(WA_StyledBackground)`，否则普通 QWidget 不绘制 stylesheet 背景。
- `PackageGrid`：`QListWidget` + `setItemWidget` 挂载卡片；缩略图仍按可视区**懒加载**（`_update_visible` → `thumb_manager.request`）；API 与旧版一致：`set_selectable` / `checked_packages` / `checked_count` / `set_all_checked` / `selectionChanged` / `packageClicked`。

### 4. 批量下载 `download_package_batch`

`app/components/download_runner.py`：

```python
download_package_batch(ids, dest, *, gif=None, max_workers=None, on_progress=None) -> DownloadBatchResult
```

- `max_workers`：传入值优先，仅 `None` 时读 `cfg.max_workers.value`。
- 逐包 `Emoji.certain_emoji_typed(id)` 取全量；**单个包失败（`except Exception`，非 BaseException）记录原始 ID 与异常、合成 `DownloadResult(status=FAILED)` 后继续**，不中断整批；空 ids / 全失败仍返回结构合法的 `DownloadBatchResult`。
- **一个 `Downloader` + 一个总进度条**；准备阶段以 `on_progress(i, n, None)`（result 为 None）标记，`start_download` 据此显示「正在读取表情包详情…（i/n）」。
- 文件名安全：目录 `dest / f"{清洗名[:60]} [{包ID}]"`（含包 ID 防同名覆盖、截断超长名），文件 `清洗名[:60] + ext`。

### 5. 下载设置（设置页「下载」卡）

- **下载目录**：沿用 `cfg.download_dir`。
- **代理**：协议 `ComboBox`（HTTP/HTTPS）+ 主机名 `LineEdit` + 端口 `SpinBox(1–65535)`，保存时拼装为 `scheme://host:port`；主机名为空表示不使用代理。socks 未安装 PySocks，不提供。
- **下载线程数**：`SpinBox(1–16)`，存 `cfg.max_workers`。

### 6. 代理机制

`app/common/proxy.py`：

- 解析：`parse_proxy` / `split_proxy` / `build_proxy` / `proxy_scheme`。
- **显式 proxies 为主**：所有 `Emoji` / `Dress` / `Downloader` 构造都传 `proxies=`（requests 2.34 中显式值优先于环境变量，实测确认）。
- **环境变量兜底**：biliemoji 的 `download_package` / `download_collection` 不会把 proxies 传给内部 `Downloader`，只能靠 `HTTP(S)_PROXY` 兜底。`ProxyEnvManager` 启动时 `remember()` 快照原值，`apply()` 设置 / 清空时**恢复原值**（不无条件删除）。
- **Windows 大小写坑**：`os.environ` 在 Windows 上大小写不敏感，`HTTP_PROXY` 与 `http_proxy` 是同一变量；清除时若先恢复大写再 pop 小写会误删。因此 Windows 只管理大写键，POSIX 才双写。

### 7. 消息提示 `notify.py`

- `notify_success / notify_warning / notify_error / notify_info`：统一使用 **垂直布局 InfoBar**（`orient=Qt.Vertical`）—— 标题一行 / 内容按父级宽度换行 / 按钮单独一行。
- 默认停留 4s。全应用 26 处 `InfoBar.*` 调用点已迁移到 helper。

## 四、修复的既有 Bug

| Bug | 表现 | 修复 |
|---|---|---|
| 下载闭包缺 `on_progress` 参数 | `start_download` 以 `needs_progress=True` 调用时注入 `on_progress`，`def task():` 抛 `TypeError`，下载必然失败 | 闭包改 `def task(on_progress=None):` 并透传 |
| `start_download` 返回 False 时按钮永久禁用 | 下载目录不可用返回 False，不触发 finished，按钮卡死 | 三个调用点（包详情 / 收藏集 / 下载页）在返回 False 时主动恢复按钮 |
| 选中背景不显示 | 普通 QWidget 需 `WA_StyledBackground` 才绘制 stylesheet 背景 | 卡片加该属性 |
| InfoBar 长文本压窄 | 给内容加 `wordWrap` 后最小宽度塌缩到 ~28px | 撤销 wordWrap 补丁，改用垂直布局 + 预换行 |

## 五、踩坑记录（Qt / PySide6）

1. **`index.data(CheckStateRole)` 返回 int**，而 `Qt.CheckState` 在 PySide6 不是 IntEnum，`2 != Qt.CheckState.Checked` 恒为 True → 需与 `.value` 比较。
2. **普通 `QWidget` 不绘制 stylesheet 的 `background-color`**，需 `setAttribute(WA_StyledBackground)`；`QLabel` / `QFrame` 无此问题。
3. **`QLabel` 开 `wordWrap` 后 `sizeHint` 的最小宽度会塌缩**，放进 `SetMinimumSize` 的布局会把标签压到极窄 → InfoBar 内容不要依赖 wordWrap，用 `TextWrap` 预换行 + 垂直布局。
4. **`os.environ` 在 Windows 大小写不敏感**。
5. **biliemoji typed 下载方法不转发 proxies** 到内部 `Downloader`（`emoji.py:188` / `dress.py:217`），文件下载代理只能靠环境变量兜底。

## 六、验证

- `uv run ruff check .` 通过；模块导入自检通过。
- 屏幕外脚本（`QT_QPA_PLATFORM=offscreen`）覆盖：代理解析 / `ProxyEnvManager` 快照恢复、卡片勾选与选中背景、队列 UI 状态、`download_package_batch` 空列表与失败合成、`on_finished` 三路径幂等（目录无效 / 异常 / 完成各恢复一次），共 50 项全部通过。
- 真实 B 站网络流程（拉取 / 下载 / 收藏集搜索）依赖用户 Cookie，需人工 `uv run python main.py` 验证。
