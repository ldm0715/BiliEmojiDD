# CLAUDE.md

B 站表情包 / 收藏集（装扮）下载器 GUI。Python 3.11 + PySide6 6.4.2 + QFluentWidgets（fork 版）
+ `biliemoji==2.0.0`，中文界面，五页：主页（默认）/ 表情包 / 收藏集 / 下载 / 设置。

本文件是常驻上下文，只放跨领域约束与索引。**专题规范在 `.claude/rules/`，按需读，别全量翻。**
`docs/` 是给用户看的说明，**默认不作为输入材料**，除非我明确指明某一篇。

## 不可改动的约束

- **Python 3.11**（`.python-version`）。禁止升 3.12：qfluentwidgets 来自 GitHub fork
  `ldm0715/PyQt-Fluent-Widgets@PySide6`(v1.5.1)，要求 `PySide6<=6.4.2`，6.4.2 无 py3.12 wheel。
  禁用 PEP 701 等 3.12 专属语法：嵌套 f-string 写 `('#' + str(x))`。
- **禁止换回官方 PyPI 版 qfluentwidgets**：开源版无数字分页组件（`Pagination` 属 Pro 版），
  `app/components/page_bar.py::PageBar` 是自制的。
- **版本号唯一来源是 `pyproject.toml` 的 `[project] version`**（`app/common/version.py::project_version()`
  用 `tomllib` 读）。界面一律走 `APP_VERSION`，任何地方不得硬编码版本串；`packaging/build.py` 直接读文件、
  不 import 应用模块。
- **许可 GPL-3.0-or-later**（义务而非偏好）：`PySide6-Fluent-Widgets` 以 GPLv3 授权，本项目链接并分发
  二进制，整体必须同样 GPLv3；这不解除上游商业限制（商用仍需向 zhiyiYo 购买授权）。
- `ruff` 是唯一检查工具，提交前 `uv run ruff check .` 必须通过。所有模块加
  `from __future__ import annotations`。中文 UI / 注释，标识符英文。
- 新增联网代码一律走 `app/common/net.py` 工厂；网络 I/O 一律在后台线程，worker 禁止碰控件。

## 分层

`app/common`（config / net / notify / theme / font / signal_bus / proxy / resource / version / exception）
→ `app/components`（widgets / page_scaffold / thumb / video_cache / content_meta / disk_cache /
api_cache / download_runner / download_queue / bili_login / image_viewer / updater / mirror_card …）
→ `app/view`（home_page / emoji_page / dress_page / download_page / setting_page）。
只允许上层依赖下层，无更深嵌套。页面只做装配 + 信号槽：查询走 `run_task`，下载走 `start_download`。

## main.py 时序（固定，勿调）

`apply_font_engine()` → `QApplication(sys.argv)` → `apply_app_font(app)` → `setWindowIcon(app_icon())`
→ `setTheme(cfg.theme.value)`（必须在 splash 之前）→ `SplashWindow().start()` → `import app.MainWindow`
→ `MainWindow(on_progress=splash.set_message)` → `window.show()` + `splash.finish(window)`。

## 规则索引

| 改什么 | 读哪篇 |
|---|---|
| 页面版式、卡片网格、主题取色、上游组件坑、字体渲染、滚动性能、图片查看器、GIF、内嵌视频、设置页、应用外壳 | `.claude/rules/qt-ui.md` |
| 线程与信号、联网与代理、配置与校验器、缓存与存储、错误提示、biliemoji 接口口径、版本与发版、打包与 CI | `.claude/rules/architecture.md` |
| 扫码登录、Cookie 状态机、直播间表情、收藏集判别、下载队列与下载页、剪贴板复制、主页 | `.claude/rules/features.md` |
| 命令、验证流程、屏幕外断言脚本、帧率测试 | `.claude/rules/testing.md` |

## 硬性文档约定

- `CLAUDE.md` 与 `.claude/rules/*.md` 一律**覆盖修改**：规则变了改写原句，**严禁在末尾追加
  「某次更新修复了…」这类历史记录**。历史过程不属于规则文件。
- 版本变更只写根目录 `CHANGES.md`（Keep a Changelog 格式，`packaging/changelog.py` 抽小节，
  GitHub Release 正文与应用内弹窗共用）。禁止新建 `CHANGELOG.md` / `docs/history/`。
- 新增规则写进对应 `.claude/rules/*.md` 的分节内并同步上表；不要往本文件塞细节。
