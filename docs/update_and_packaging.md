# 检查更新与打包发布

本文覆盖两件事：应用内怎么发现并安装新版本，以及仓库怎么把源码变成可分发的安装包。
两者由 `CHANGES.md` 串起来——写一次更新说明，GitHub Release 正文与应用内弹窗用的是同一份。

相关文件：

| 文件 | 职责 |
|---|---|
| `app/common/version.py` | 从 `pyproject.toml` 读版本号 + tag 比较（`project_version` / `is_newer`） |
| `app/common/net.py` | `make_session()`——GitHub 请求的会话工厂 |
| `app/components/updater.py` | 查 Release、镜像增删改排、下载资产、SHA-256 校验、测速 |
| `app/components/mirror_card.py` | 「下载加速」设置卡：选源 / 测速 / 管理自定义源 / 拖动排序 |
| `app/components/update_dialog.py` | `UpdateDialog`：渲染更新说明、下载并运行安装程序 |
| `app/view/setting_page.py` | 「关于」设置组（仓库 / 检查更新 / 自动检查 / 下载加速 / 许可） |
| `app/MainWindow.py` | 启动后静默自检 |
| `CHANGES.md` | 更新日志（唯一来源） |
| `packaging/changelog.py` | 按版本号抽取 `CHANGES.md` 的小节 |
| `packaging/build.py` | Nuitka 编译 + NSIS + 便携 zip + 校验和 |
| `packaging/installer.nsi` | NSIS 安装脚本 |
| `.github/workflows/release.yml` | 打 tag 触发发布 |
| `scripts/check_update.py` | 屏幕外回归断言（不联网） |

---

## 一、版本号只维护一处

`pyproject.toml` 的 `[project] version` 是唯一来源：

- **运行时**：`app/common/version.py::project_version()` 用 `tomllib` 读它，
  `APP_VERSION` 由此得来；主页英雄卡、主页「关于」卡、设置页身份行三处都用 `APP_VERSION`。
- **构建时**：`packaging/build.py::project_version()` 同样读它（用 `tomllib`，
  **不 import 应用模块**——构建脚本不该为了取版本号把整个 Qt 拉起来）。

`[tool.uv] package = false`（应用不是安装包），所以 `importlib.metadata` 拿不到版本，
只能读文件。编译后靠 `--include-data-files=pyproject.toml=pyproject.toml` 把它放到 exe 旁边，
路径解析见下面的「资源定位」。

读不到文件时返回 `"unknown"`。这是**故意选的一个解析不出来的值**：`is_newer` 遇到
无法解析的版本一律返回 False，于是「检查更新」会安静地不提示，而不是把每个 Release
都当成新版天天弹窗。

### `is_newer` 的规则

剥前导 `v` → 取开头的数字段 → 补零对齐后逐位比 → 核心段相同时「正式版 > 预发布版」
（`1.0.0` 新于 `1.0.0-rc.1`）。刻意不引入 `packaging` 依赖：需求就这么点，多一个运行时
依赖反而要在 Nuitka 那边多操心一份。

---

## 二、资源定位：源码运行 vs 编译后

`app/common/resource.py::_project_root()`：

```python
if "__compiled__" in globals() or getattr(sys, "frozen", False):
    return Path(sys.executable).resolve().parent   # 编译后：exe 所在目录
return Path(__file__).resolve().parents[2]          # 源码：项目根
```

**Nuitka 会给每个编译模块注入 `__compiled__`**，编译后 `__file__` 指向 dist 内的虚拟路径，
不能拿来回溯目录。`STATIC_DIR` 与 `PYPROJECT_PATH` 都从这个根算，与 build.py 里
`--include-data-dir=static=static` / `--include-data-files=pyproject.toml=...` 的落点一致。

---

## 三、检查更新的数据流

```
                    ┌── 手动：设置 → 关于 → 检查更新
触发 ────────────────┤
                    └── 自动：MainWindow 启动 3 秒后（cfg.auto_check_update）
                              ↓
        run_task(fetch_latest_release)          worker 线程
                              ↓
        GET api.github.com/repos/.../releases/latest
                              ↓  ReleaseInfo(tag, notes, asset_url, sums_url, ...)
                    is_newer(tag, APP_VERSION)?
                        ├── 否 → 手动：副标题写「已是最新」+ 提示；自动：完全安静
                        └── 是 → 手动：直接弹 UpdateDialog
                                 自动：InfoBar「发现新版本」+「查看更新」按钮
                                             ↓
                                    UpdateDialog（markdown 渲染 notes）
                                             ↓ 点「下载并安装」
                        run_task(download_asset, needs_progress=True)
                                             ↓
                        候选 URL（可能带镜像）逐个试 → 流式写 .part → SHA-256
                                             ↓
                        与 SHA256SUMS.txt（**直连取**）比对
                            ├── 不符 → 删文件 + 报错，绝不运行
                            └── 相符 → os.replace → os.startfile → 关闭应用
```

几个刻意的选择：

- **自动检查失败彻底静默**（`on_error=lambda exc: None`）。启动时没网、GitHub 不通都不该
  弹错——用户要查自会去设置页点那个按钮。
- **自动检查发现新版也不弹模态窗**，只出一条带「查看更新」按钮的 InfoBar
  （`duration=NEVER_DISMISS`，注意**不是 0**，0 是「立刻淡出」）。刚打开应用就被遮罩糊一脸很讨厌。
- **`UpdateDialog` 的 `yesButton` 必须先 `clicked.disconnect()`**。上游
  `MessageBoxBase.__onYesButtonClicked` 直接 `accept()` 关窗，不断开的话点「下载并安装」
  弹窗当场消失，进度条根本没机会露面。
- **关应用走 `window.close()` 而不是 `QApplication.quit()`**：后者不触发 `closeEvent`，
  `video_cache.cleanup()` 的临时目录就漏在磁盘上了。
- **安装包放 `%TEMP%/biliEmojiDD-update/`，不挂 `video_cache.cleanup()`**：它要活过应用退出。

---

## 四、下载加速镜像

设置页「关于 → 下载加速」是一张可展开的卡：收起时是「下拉选源 + 测速」，展开后每个源
一行，带**三色状态胶囊**，可拖动排序，自定义源还能改地址、删除。

内置三家前缀式反代：`gh-proxy.com` / `ghproxy.net` / `ghfast.top`。

### 与「设置 → 下载 → 代理」的区别

| | 下载加速（本节） | 代理（`docs/proxy_diagnostics.md`） |
|---|---|---|
| 改什么 | **URL 本身**：`https://gh-proxy.com/` + 原始地址 | requests 的 `proxies=` |
| 作用范围 | 只有 GitHub 请求 | 所有联网入口（B 站接口、下载、缩略图…） |
| 实现位置 | `updater.mirrored()` / `download_urls()` | `app/common/net.py` 的工厂 |

**两者互不影响，可以同时用。** 镜像走的仍是 `make_session()`，所以照样受代理开关管、
照样 `trust_env = False`。

### 候选顺序（`download_urls`）

- `""`（不使用）→ `[原始地址]`
- 具体镜像 → `[镜像地址]`。**只走那一家**——用户明确选了它，失败就该看出是镜像的问题，
  而不是被静默回退掩盖。
- `"auto"` → `[原始, 然后按用户排的顺序逐个镜像]`，试到第一个成功。

`fetch_latest_release`（API 请求）单独处理：**永远先直连**，失败且配了镜像才用镜像重试。
这三家一般也代理 `api.github.com`，不支持也只是多失败一次，不会更糟。

### 自定义源与顺序

三个配置项，各管一件事，互不重叠：

| 配置项 | 管什么 |
|---|---|
| `cfg.gh_mirror` | 当前选的是哪个（`""` / `"auto"` / 某个地址） |
| `cfg.custom_mirrors` | 用户加了**哪些**源（成员） |
| `cfg.mirror_order` | 所有源的**顺序**（内置 + 自定义混排） |

`cfg.gh_mirror` **不能用 `OptionsValidator`**：取值集合随用户增删而变，写死校验器会让
自定义源一保存就被打回默认值。

`orderable_mirrors()` 是唯一的读取入口，规则是「**顺序表只记顺序不记成员**」：表里不存在的
源被过滤，没进表的源按默认顺序补在后面。所以加内置源、删自定义源都不必迁移配置。

排序**有实际作用**：`mirror_chain()`（`auto` 模式的尝试顺序）就是它。测完速把快的拖到
前面是有意义的操作，不只是好看。直连那行钉在最前不参与排序——它本来就是「不经中转」。

**改地址时先算顺序再改成员**（`update_custom_mirror`）：反过来的话，`orderable_mirrors()`
会按新成员过滤顺序表，旧地址已不在其中直接被丢掉，改完的源就被排到末尾了（写完第一版
就踩了，回归断言见 `check_update.py` 第 3d 节）。

### 测速

「测速」并发（`ThreadPoolExecutor`，上限 8）经每个源 GET 一次 `PROBE_TARGET`（本仓库主页），
`stream=True` 只取响应头不下正文，用**挂钟**计时——不是 `response.elapsed`，后者不含 DNS 与
握手，而对代理来说这两段恰恰是差距所在。

| 档位 | 判据 | 颜色 |
|---|---|---|
| 良好 | 通了且 < `LATENCY_GOOD_MS`（1000 ms） | 绿 |
| 一般 | 通了但更慢 | 橙 |
| 错误 | 连不上 / 超时 / 镜像自己 5xx | 红 |

**4xx 也算通**：仓库还没建或改过名时 GitHub 回 404，但那说明镜像确实把请求转到 GitHub 了。
只有连不上和镜像自身 5xx（502 / 504）才算错误。

结果经 `run_task(needs_progress=True)` 的进度桥回主线程（载荷是 `MirrorSpeed`），
**每测完一个点亮一行**，不用干等最慢的那个。

三色胶囊走 `page_scaffold.status_badge(..., colors=(亮, 暗))`：组件库 `InfoBadge` 的
`InfoLevel` 只定语义，**颜色必须显式给**——上游暗色主题下 WARNING / ERROR 用的是浅底
（`#fff4ce` / `#ff99a4`），而 qss 把文字钉死成 `color: white`，白字压浅底根本看不清。
自定颜色走 `setCustomBackgroundColor`（`_backgroundColor()` 里优先级最高、每帧现算，
主题切换自动跟上），**不能用 `setStyleSheet`**：`InfoBadge` 已注册进 `styleSheetManager`，
切主题会重刷 qss 把样式表冲掉。

### 拖动排序是手写的

没用 `QListWidget` 的 `InternalMove`：那个在 `setItemWidget` 的场景下会在移动时把 item
widget 弄丢。行高固定，目标下标就是一次除法，反而更简单可控。

做法是经典的「摘出来 + 占位符」：`_on_drag_start` 把被拖的行 `removeWidget` 出布局
（**必须摘**，留在布局里的话每次重新布局都会覆盖掉 `move()` 的结果，行根本跟不了鼠标），
原位插一个等高占位；`_on_drag_move` 让行跟随鼠标并按中心位置把占位挪到目标下标，
布局自然把其余行让开；`_on_drag_finish` 落库后 `reload()` 重建，控件自动归位。

### 为什么必须有 SHA-256 校验

因为流程是「下载后**直接运行**安装程序」。经第三方镜像下载再自动执行，等于把二进制的
完整性交给镜像方——而现在用户还能自己加源，来源就更不可控了。所以：

- `packaging/build.py` 对安装包与便携 zip 算 SHA-256，写成 `sha256sum` 格式的
  `SHA256SUMS.txt`，随 Release 一起上传；
- `updater._expected_sum()` **固定直连**从 GitHub 取这个文件——**不走镜像**。
  拿被校验方给的校验和去校验它自己等于没校验；
- 边下边累加摘要，对不上就删掉 `.part` 并抛 `ChecksumMismatch`，弹窗报「安装包校验失败」
  且**不运行**该文件。

老版本 Release 没有 `SHA256SUMS.txt` 时跳过校验（`sums_url` 为空），这是向后兼容的退路。

---

## 五、CHANGES.md 与发版流程

`CHANGES.md` 是 Keep a Changelog 风格，每个版本一个 `## [x.y.z] - 日期` 小节。

`packaging/changelog.py::extract(version)` 匹配标题行（`## 0.1.0` / `## [0.1.0]` /
`## v0.1.0 - 2026-08-30` 都认），取到下一个 `## ` 为止。**找不到该版本就抛异常、构建失败**
——发一个更新说明为空的 Release 比构建失败更糟：用户点开弹窗一片空白，也没法回头补。

`build.py` 在**编译之前**先跑一次 `extract`，缺小节的话立刻失败，不用等十几分钟编译完。

### 发一个版本

```bash
# 1. 改版本号（唯一一处）
#    pyproject.toml: version = "0.2.0"

# 2. 在 CHANGES.md 顶部补一节 ## [0.2.0] - YYYY-MM-DD

# 3. 本地验一遍
uv run ruff check . && uv run python -c "import app.MainWindow"
uv run python packaging/changelog.py 0.2.0     # 看抽出来的内容对不对

# 4. 提交并打 tag
git commit -am "chore(release): 0.2.0"
git tag v0.2.0
git push && git push --tags
```

工作流随后自动编译、打包、建 Release 并上传三个产物。

> **tag 与 `pyproject.toml` 的版本号没有强制门禁**（按需求刻意不加）。忘了同步的话，
> 用户端会一直被提示「有新版本」——`CHANGES.md` 缺对应小节导致构建失败，算一层间接提醒。

---

## 六、打包

### 本地

```bash
uv sync                                        # 装上 nuitka（dev 组）
uv run python packaging/build.py               # 只编译，首次较慢
./dist/BiliEmojiDD/BiliEmojiDD.exe             # 直接跑跑看

uv run python packaging/build.py --installer   # 再加 NSIS + 便携 zip + 校验和
uv run python packaging/build.py --installer --skip-compile   # 只重打包，复用已编译结果
```

产物都在 `dist/`：`BiliEmojiDD/`（便携目录）、`BiliEmojiDD-Setup-<ver>.exe`、
`BiliEmojiDD-<ver>-win64.zip`、`SHA256SUMS.txt`、`release_notes.md`。

### Nuitka 参数逐条

| 参数 | 为什么 |
|---|---|
| `--standalone` | 产出可分发目录（不是 onefile：NSIS 要的就是一个目录，onefile 每次启动还要解压） |
| `--enable-plugin=pyside6` | Qt 的插件 / DLL 由这个插件处理 |
| `--windows-console-mode=disable` | GUI 应用别弹黑框。**Nuitka 2.x 起的写法**，1.x 是已废弃的 `--windows-disable-console` |
| `--include-data-dir=static=static` | 图标 / 内置字体 / 主页展示图，落到 exe 旁的 `static/` |
| `--include-data-files=pyproject.toml=pyproject.toml` | 版本号唯一来源，运行时要读 |
| `--include-package=app` | 页面是在 `main()` 里延迟 import 的，显式带上整个包更稳妥 |
| `--include-module=socks` | **PySocks 由 urllib3 在「代理写 socks5://」时才懒加载**，静态分析看不见它 |
| `--include-qt-plugins=multimedia` | 收藏集详情页的视频播放要 QtMultimedia 插件 |
| `--assume-yes-for-downloads` | CI 无人值守，别卡在「是否下载 ccache」的交互提示上 |
| `--lto=no` | MinGW 后端的 `lto-wrapper` 在 Windows 上很脆（实测「could not open symbol resolution file」直接断在链接阶段）。一百多 MB 里绝大部分是 Qt 的 DLL，LTO 能省的那点体积不值得冒险 |

### 中文用户名下的三个坑（本机踩过，CI 不受影响）

GitHub 的 windows runner 路径全 ASCII 且自带 MSVC，下面三条只在中文 Windows 上出现。
前两条 `build.py::ascii_workarounds()` 已自动处理（检测到非 ASCII 家目录才启用，CI 走默认路径）：

1. **DLL 依赖扫描崩**
   `nuitka/freezer/DllDependenciesWin32DependsExe.py:151` 把 `depends.exe` 的输出按 **latin1**
   解码，`C:\Users\某某某` 被拆成 `\x04` 之类的字节，接着 `assert os.path.isfile(dll_filename)`
   直接抛 `AssertionError`。→ 加 `--experimental=force-dependencies-pefile` 换成纯 Python 扫描器。

2. **MinGW 工具链解压失败**
   Nuitka 下载 MinGW 后解压进 `%LOCALAPPDATA%\Nuitka\...`，同样的路径问题让 Scons 后端起不来。
   → `NUITKA_CACHE_DIR` 指到 `C:\nuitka-cache` 这种全 ASCII 的路径。

3. **`ld.exe: cannot find -lpython311`（没有自动解法）**
   MinGW 的链接器拿不到含中文路径的 Python 导入库目录。**装了 Visual Studio Build Tools 的机器
   不会遇到**（Nuitka 优先用 MSVC，它认 UTF-16 路径）。没装 MSVC 的话，把解释器装到 ASCII 路径下再编：

   ```bash
   UV_PYTHON_INSTALL_DIR=C:/uvpy uv python install 3.11
   UV_PROJECT_ENVIRONMENT=C:/bdd-build-venv uv sync --all-groups \
       --python C:/uvpy/cpython-3.11.13-windows-x86_64-none/python.exe
   C:/bdd-build-venv/Scripts/python.exe packaging/build.py --installer
   ```

   （这个 venv 只用来打包，日常开发照旧用项目里的 `.venv`。）

### NSIS

`packaging/installer.nsi`，参数由 `build.py` 用 `/D` 传进去。两个刻意的选择：

1. **当前用户级安装**（`RequestExecutionLevel user` + `$LOCALAPPDATA\Programs\BiliEmojiDD`），
   装卸都不弹 UAC，注册表只写 `HKCU`。
2. **卸载默认保留用户数据**（`%APPDATA%\biliEmojiDD` 下的配置 / 缓存 / 搜索历史），
   只用一句 `MessageBox MB_YESNO` 问是否一并删除——重装或升级不该把 Cookie 和设置弄丢。

### 工作流

`.github/workflows/release.yml`，`push` 到 `v*` tag 时触发，`windows-latest`：

checkout → setup-uv → `uv python install 3.11` → `uv sync --all-groups` →
**Ensure NSIS**（runner 镜像是否自带各版本不一，`Get-Command makensis` 找不到就
`choco install nsis`）→ `packaging/build.py --installer --version ${{ github.ref_name }}` →
`softprops/action-gh-release`（`body_path: dist/release_notes.md`，上传三个产物）。

Python 锁死 3.11：qfluentwidgets 这个 fork 要求 `PySide6<=6.4.2`，而 6.4.2 没有 3.12 的
wheel（见 CLAUDE.md 环境约束）。

---

## 七、版本号胶囊

三处显示版本的地方（设置页身份行、主页英雄卡、主页「关于」卡）统一用
`page_scaffold.version_badge()`。它包的是组件库的 `InfoBadge`——`paintEvent` 里
`drawRoundedRect(rect, h/2, h/2)`，本身就是个胶囊，且 `InfoLevel.ATTENTION` 取主题色，
随亮暗主题自动换色。

两个坑：

- **上游 qss 只给了 `padding: 1px 3px`**，`v0.1.0` 会贴着圆角边缘。补留白**不能用
  `setStyleSheet`**：`InfoBadge` 构造时 `FluentStyleSheet.INFO_BADGE.apply(self)` 已把自己
  注册进 `styleSheetManager`，每次切主题都会重刷 qss 把样式表冲掉（`VideoWidget` 黑背景
  踩过同一个坑）。改为覆写 `sizeHint()` 加宽，并 `setAlignment(AlignCenter)` 让文字居中。
- **不能覆写 `__init__`**：`InfoBadge.__init__` 是 `singledispatchmethod`，`(text, parent,
  level)` 那个重载内部会**再调一次** `self.__init__(parent, level)`，子类若加必填位置参数
  直接 TypeError（与 `PushButton` 那个坑同源，见 `docs/search_and_cache.md`）。

---

## 八、验证

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_update.py
```

十节断言：版本号来源与比较、资产挑选、镜像展开、**自定义源增删改**、**顺序与 auto 链**、
**测速分档**、设置页「关于」组、**加速卡展开区（按钮显隐 / 行内编辑 / 拖动落库）**、
检查结果分支、更新弹窗（含「点了不关窗」与失败恢复）、`CHANGES.md` 抽取、
`make_session` 的 `trust_env`、SHA-256 校验、版本胶囊。
**全程不联网**（脚本开头 `updater.set_enabled(False)`）。

> **构造 `MainWindow` 的屏幕外脚本必须 `updater.set_enabled(False)`**：启动 3 秒后的自动
> 检查会排一个真实网络请求，脚本跑完退不出去。`check_improvements.py` /
> `check_shell.py` / `check_theme_switch.py` 都已加上，与 `content_meta` /
> `video_cache` 是同一个坑。

无法自动化、需人工验的部分：

- 真实点一次「检查更新」；点「测速」看四个源的实测延迟与分档是否合理；把「下载加速」
  分别切到直连与各镜像各下一次，确认都能拿到文件且校验通过；
- 加一个自定义源 → 测速 → 拖到最前 → 改地址 → 删除，确认每一步都即时生效；
- 编译产物：窗口起得来、**内置字体生效**、**收藏集视频能播**、主页展示图可见、
  表情包下载正常（certifi 证书随包）；
- 安装包：装完能从开始菜单启动，卸载后 `%APPDATA%\biliEmojiDD` 仍在。
