# 开发与维护

## 环境准备

```bash
# 安装 uv（若未装）后：
uv sync                          # 用 pyproject.toml / uv.lock 重建环境（Python 3.11）
uv run python main.py            # 启动应用
uv run ruff check .              # 代码检查
```

> **不要** `uv add PySide6-Fluent-Widgets` 或改 `pyproject.toml` 的 qfluentwidgets 依赖——它来自 GitHub fork，且锁定 `PySide6==6.4.2`、Python 3.11（见 architecture.md）。

## 代码约定

- `ruff` 是唯一检查工具；提交前 `uv run ruff check .` 通过。常见自动修复：`uv run ruff check . --fix`（import 排序等）。
- 中文 UI / 注释；代码标识符英文。
- `from __future__ import annotations` 用于所有模块（Python 3.11 兼容）。
- **禁用 Python 3.12 专属语法**：如 f-string 内嵌同引号表达式（PEP 701）。嵌套时用 `('#' + str(x))` 替代 `f'#{x}'`。

## 关键坑点

1. **线程与信号**
   - worker 线程（QRunnable / biliemoji 内部线程池）禁止直接改控件；只 emit 主线程构造的信号对象。
   - `QPixmap` 只能在主线程创建/使用；worker 只产 `QImage` 或字节。
   - `Task` / 缩略图任务务必 `autoDelete(False)` 并由 Manager 持有引用，否则队列信号可能丢失。
   - **带载荷的信号不能直接接无参槽**：`signal_bus.cookieStateChanged` 载着一个 `str`，`connect(self.refresh)` 会 `TypeError`，得包一层转发的槽（或 lambda）。
   - **清「正在飞」标志必须挂 `on_finished`**：成功与两条异常路都会走它，只挂 `on_success` 会让失败一次之后永远不再重试（探针、预拉取都踩过）。屏幕外脚本里的 `run_task` 桩同理，**必须回调 `on_finished`**。
2. **测试脚本陷阱**
   - 验证后台任务信号时，不要写「短暂 `processEvents()` 后结束脚本」的测试——脚本退出早于 worker 会看到 `Internal C++ object ... already deleted` 假象（真实 app 里 `app.exec()` 常驻无此问题）。应轮询等待任务完成再退出。
3. **布局**
   - qfluentwidgets `FlowLayout.takeAt(index)` 返回 **widget**（不是 QLayoutItem）；清理用 `widget.setParent(None)` + `deleteLater()`，防止脱离布局后残影绘制。而 `FlowLayout.itemAt(index)` 返回的是 **QWidgetItem**（要 `.widget()`）—— 两者不一致，写测试时容易踩。
   - `FluentWindow.addSubInterface` 要求页面 `objectName` 非空。
   - **`QPushButton` 垂直 size policy 默认 `Fixed`**：在 `QVBoxLayout` 里 `stretch=1` 也拉不撑，按钮会停在 sizeHint 高度、多余空间全给相邻控件（海报被压成 12px 的坑）。需要撑满时 `setSizePolicy(Expanding, Expanding)`。
4. **卡片下标不要靠载荷身份反查**
   - `(name, url)` 这类内容相同的元组字面量会被 CPython **常量折叠成同一个对象**（`items[1] is items[2]` 为真），用 `is` 反查会把两项判成同一下标（实测点击重复卡面得到 `[0, 1, 1]`）。
   - `_CardGridBase` 在建卡时用 `partial(self._emit_clicked, index)` 闭包固定下标，发 `itemClickedAt(index, item)`。
5. **配置**
   - 配置存 `%APPDATA%/biliEmojiDD/config.json`，不写项目目录（打包后不可写）。
   - 新增枚举类配置项必须配 `EnumSerializer`，否则 `qconfig.save()` 的 `json.dump` 抛 `TypeError`。
   - **新增普通字段不用写迁移**：新键由 `config.py::_ensure_persisted()` 启动时自动补写，默认值本身要能表达「没有」（如 `cookieCheckedAt=0` / `cookieCheckedHash=""`）。只有需要**根据老数据推断新值**时才动 `CONFIG_SCHEMA`（+1）和 `_migrate`，而且迁移的熄火标记必须是那个显式版本号——**不能靠「文件里有没有这个键」**：`qconfig.set` 在值没变时根本不落盘（上游 `config.py:299`），靠这个判据会永久武装、把用户明确改过的设置反复翻回去。踩坑全过程见 [proxy_diagnostics.md](proxy_diagnostics.md)。
   - `qconfig.set(item, value)` 才落盘；直接写 `cfg.item.value = v` 只改内存（迁移里的临时改动就靠这个，落盘统一交 `_ensure_persisted`）。
6. **biliemoji**
   - 模型类从 `biliemoji.models` 导入（`EmotePackage` 等顶层不导出）。
   - `all_packages()` 返回的包**不含完整 emote**（只含元信息），进详情必须另调 `certain_emoji_typed(id)`。
   - 无关键词搜索表情包接口；"搜索表情包" = ID 查询 + `all_packages` 本地过滤。
   - **收藏集 typed 字段不可信**：`DressCollectionSummary.is_collection` / `dlc_act_id` / `dlc_lottery_id` / `id` 因 API 返回字符串被 `_optional_int` 拒收而恒 `None`/`False`。判别与取 id 一律走 `app/components/dress_helpers.py` 从 `raw` 读（`properties.type`：`"dlc_act"`=收藏集、`"ip"`=装扮）。
   - `download_collection` / `download_package` 不会把 `proxies` 传给内部 `Downloader`；需要显式代理的批量下载用 `download_collection_batch` / `download_package_batch`。
7. **qfluentwidgets 控件签名**
   - **`ComboBox.addItem(text, icon, userData)`**：第二位置参数是 `icon`，不是 userData！要 `currentData()` 读到值必须 `addItem("文本", userData="值")`；否则 data 恒 `None`（曾导致下载模式 `mode.lower()` 崩、代理协议/主题切换失效）。
8. **`FlipView` / `MaskDialogBase` / `PipsPager` 上游 bug**
   - `FlipView._adjustItemSize` 空图除零、sizeHint 变化致滚动跑偏；`MaskDialogBase.setMaskColor` 的 B/G 参数写反；`MaskDialogBase` 把 `self.widget` 无对齐塞进布局导致「点遮罩关闭」失效；`PipsPager.setCurrentIndex` 会回发信号。
   - 这些都已在 `app/components/image_viewer.py` 里绕过并注释，**勿"修回去"**。完整清单见 [image_viewer.md](image_viewer.md) 第五节。
9. **打包（Nuitka）**
   - **资源路径分两种情形**：源码运行按 `__file__` 回溯项目根，编译后（模块里有 `__compiled__`）取 `sys.executable` 所在目录。`app/common/resource.py::_project_root()` 已处理，新增静态资源一律从 `PROJECT_ROOT` 起算并在 `packaging/build.py` 里加对应的 `--include-data-*`。
   - **懒加载的模块 Nuitka 看不见**：`socks`（urllib3 只在代理写 `socks5://` 时才 import）必须 `--include-module=socks` 显式带上。同理新增按需 import 的第三方模块要检查是否进了 dist。
   - **中文用户名会让 Nuitka 崩两处**：`depends.exe` 输出按 latin1 解析（DLL 扫描 assert 失败）、MinGW 工具链解压路径乱码。`build.py::ascii_workarounds()` 检测到非 ASCII 家目录时自动换 pefile 扫描器 + 把 `NUITKA_CACHE_DIR` 挪到 ASCII 路径。**若本机没装 MSVC**，MinGW 还会因为 Python 导入库路径含中文而 `cannot find -lpython311`——那只能把解释器装到 ASCII 路径下再编（CI 的 windows runner 全 ASCII + 自带 MSVC，不受影响）。详见 [update_and_packaging.md](update_and_packaging.md)。

## 修改指南

### 新增一个功能页面

1. 在 `app/view/` 新建 `xxx_page.py`，页面设 `objectName`；
2. 在 `app/MainWindow.py` 的 `initNavigation()` 注册 `addSubInterface`；
3. 网络请求用 `run_task`（查询类）或 `start_download`（下载类），信号槽更新 UI。

### 调整 biliemoji 调用

- 以 `biliemoji==2.0.0` 实际 API 为准（读 `uv run python -c "import biliemoji, inspect; print(inspect.signature(...))"` 或包源码 `.venv/Lib/site-packages/biliemoji/`）。
- 下载器 `on_progress(done, total, result)` 在 worker 线程回调，经 `run_task(needs_progress=True)` 桥接；不要在回调里直接碰控件。

### 改版本号 / 发版

**版本号只在 `pyproject.toml` 的 `[project] version` 一处维护**——运行时
`app/common/version.py::project_version()` 读它，`packaging/build.py` 也读它，界面上三处
显示（主页英雄卡 / 主页关于卡 / 设置页身份行）都走 `APP_VERSION`。别在任何地方硬编码版本串。

发版：改 `pyproject.toml` → 在 `CHANGES.md` 补一节 → 打 tag `vX.Y.Z` 推上去，
`.github/workflows/release.yml` 会编译、打包、建 Release。完整流程与打包细节见
[update_and_packaging.md](update_and_packaging.md)。

### 修改后验证

1. `uv run ruff check .`
2. `uv run python -c "import biliemoji, qfluentwidgets, PySide6"`
3. `uv run python main.py` 启动确认不崩溃；
4. 跑一遍屏幕外断言脚本（改动涉及的至少各跑一次，收尾跑全量）：

   ```bash
   QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_xxx.py
   # 全量批跑（Windows 终端默认 GBK，中文断言文案要 PYTHONIOENCODING=utf-8）
   for s in scripts/check_*.py; do printf "%-40s" "$s"; \
     QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python "$s" >/tmp/o.txt 2>&1; tail -1 /tmp/o.txt; done
   ```

   **要写配置 / 缓存 / 历史的脚本必须先隔离 `APPDATA`**，**会联网的脚本必须关掉对应开关**
   （`content_meta` / `video_cache` / `updater` / `bili_login` / `cookie_status` 的 `set_enabled(False)`）——
   `check_shell.py` 开头那段是现成范本。
5. 依赖真实 B 站网络 + 用户 Cookie 的流程（拉取、下载、收藏集搜索、Cookie 失效）需人工验证。
6. **AI 不要自己截图判断 UI 或性能**：`scripts/screenshot_pages.py` 的产物是给人工比对的，
   离屏渲染跟真机对不上。量不出来的就如实说「这条需要人工看」。
