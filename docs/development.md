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
2. **测试脚本陷阱**
   - 验证后台任务信号时，不要写「短暂 `processEvents()` 后结束脚本」的测试——脚本退出早于 worker 会看到 `Internal C++ object ... already deleted` 假象（真实 app 里 `app.exec()` 常驻无此问题）。应轮询等待任务完成再退出。
3. **布局**
   - qfluentwidgets `FlowLayout.takeAt(index)` 返回 **widget**（不是 QLayoutItem）；清理用 `widget.setParent(None)` + `deleteLater()`，防止脱离布局后残影绘制。
   - `FluentWindow.addSubInterface` 要求页面 `objectName` 非空。
4. **配置**
   - 配置存 `%APPDATA%/biliEmojiDD/config.json`，不写项目目录（打包后不可写）。
   - 新增枚举类配置项必须配 `EnumSerializer`，否则 `qconfig.save()` 的 `json.dump` 抛 `TypeError`。
5. **biliemoji**
   - 模型类从 `biliemoji.models` 导入（`EmotePackage` 等顶层不导出）。
   - `all_packages()` 返回的包**不含完整 emote**（只含元信息），进详情必须另调 `certain_emoji_typed(id)`。
   - 无关键词搜索表情包接口；"搜索表情包" = ID 查询 + `all_packages` 本地过滤。

## 修改指南

### 新增一个功能页面

1. 在 `app/view/` 新建 `xxx_page.py`，页面设 `objectName`；
2. 在 `app/MainWindow.py` 的 `initNavigation()` 注册 `addSubInterface`；
3. 网络请求用 `run_task`（查询类）或 `start_download`（下载类），信号槽更新 UI。

### 调整 biliemoji 调用

- 以 `biliemoji==2.0.0` 实际 API 为准（读 `uv run python -c "import biliemoji, inspect; print(inspect.signature(...))"` 或包源码 `.venv/Lib/site-packages/biliemoji/`）。
- 下载器 `on_progress(done, total, result)` 在 worker 线程回调，经 `run_task(needs_progress=True)` 桥接；不要在回调里直接碰控件。

### 修改后验证

1. `uv run ruff check .`
2. `uv run python -c "import biliemoji, qfluentwidgets, PySide6"`
3. `uv run python main.py` 启动确认不崩溃；
4. 依赖真实 B 站网络 + 用户 Cookie 的流程（拉取、下载、收藏集搜索）需人工验证。
