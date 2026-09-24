# 命令、验证与屏幕外断言脚本

## 常用命令

```bash
uv sync                                   # 安装/重建依赖
uv run python main.py                     # 启动应用（会弹窗，需人工看）
uv run ruff check .                       # lint（--fix 自动修复）
uv run python -c "import app.MainWindow"  # 导入自检（连带验证 biliemoji/qfluentwidgets/PySide6）
```

**改动后的标准收尾**（lint + 导入自检 + 全部断言脚本）：

```bash
uv run ruff check . && uv run python -c "import app.MainWindow" && \
for s in scripts/check_*.py; do printf "%-40s" "$s"; \
  QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python "$s" >/tmp/o.txt 2>&1; tail -1 /tmp/o.txt; done
```

- **Windows 终端默认 GBK，中文断言文案会 `UnicodeEncodeError`——单跑脚本也要加
  `PYTHONIOENCODING=utf-8`。**
- 无测试框架（没配 pytest），GUI 逻辑全靠 `scripts/check_*.py`，每个自成一体、失败 `exit 1`。
- `scripts/` 不得写进 `.gitignore`（ruff 默认尊重 `.gitignore`，会导致脚本从未被 lint）。
- 打包 / 基准 / 素材抓取 / 截图命令见各脚本 docstring 与 `docs/usage.md`。

## 验证纪律

- **不要自己截图验证 UI。** `scripts/screenshot_pages.py` 的产物是给用户人工比对的——
  离屏渲染跟真实观感对不上，看图下结论只会得出错误判断（**AI 不要跑**）。
  一律用 `scripts/check_*.py` 那种可断言的屏幕外脚本（量几何、量状态、量信号）；
  量不出来的部分如实说「这条需要人工看」，不要假装验证过。
- 真实 B 站网络流程（拉取、下载、收藏集搜索、Cookie 失效、重试链路、镜像与直连组合）
  依赖用户 Cookie，**无法自动化，需人工验证**。
- 完全未验证的改动要明说，别用「应该没问题」糊过去。

## 屏幕外断言脚本规范

- **脚本要先隔离 `APPDATA`**：在 `import app.*` **之前**
  `os.environ["APPDATA"] = tempfile.mkdtemp(...)`，否则写脏用户真实的 `config.json` /
  历史 / 缓存（`APP_CONFIG_DIR` 是 import 时按 `APPDATA` 算的）。
- **假图 URL 要预置 `QPixmapCache.insert(url, 假图)`**，否则每个 URL 排一个 15s 超时任务、
  脚本退不出去。第 ③ 档剪贴板异步路径还要 `_inflight.add(url)`，收尾清掉假状态。
- **按涉及面关掉联网开关**：`content_meta` / `video_cache` / `updater` / `bili_login` /
  `cookie_status` / `live_emoji` 的 `set_enabled(False)`——构造 `MainWindow` 或显示主页的脚本
  必须关前几个（`updater` 启动 3 秒后的自动检查会排真实网络请求）。
- **涉及后台任务必须轮询等任务完成再退出**（否则看到 `Internal C++ object already deleted`
  假象；真实 app 里 `app.exec()` 常驻无此问题）；屏幕外脚本里的 `run_task` 桩同理必须回调
  `on_finished`。
- **等属性动画 / `QMovie` 帧都要等真实时间**（`processEvents()` 不推进时钟）：用
  `wait_until(cond, timeout)` = `processEvents()` + `time.sleep(0.01)` 轮询，
  并轮询 `QPropertyAnimation.state() != Running`；只等「高度 > 0」会量到中间帧。
  量悬停播放还要：offscreen 下 `QCursor.pos()` 恒为 (0, 0)，替掉 `widgets._cursor_pos` 才能模拟
  光标位置；自制测试 GIF 要带 Netscape 循环扩展，否则放完一遍就 `NotRunning`。
- **隐藏的 Tab 不参与布局，几何断言前先切到该页**，并加 `page.width() == 600` 这类自检——
  `QStackedWidget` 里非当前 / 未 `show()` 的 Tab 几何停留在过期值，会「假通过」。弹窗用
  `show()` 而非 `exec()`（`exec()` 阻塞事件循环，脚本调不了）。
- 临时对象要留引用（如 `QueueCard`），否则被 GC 后读 `nameLabel.text()` 抛
  `Internal C++ object already deleted`。
- 涉及显隐的断言必须先 `show()` 再 `hide()`（`hide()` 对没显示过的控件是 no-op）。
- 离屏平台窗口不激活，`setFocus()` 未必发 `FocusIn`，直接 `sendEvent(QFocusEvent(...))` 更稳。
- `setTheme` 必须在 `import app.*` 之后调用；字体回归断言必须 `ensurePolished()` 之后再量。

## 帧率测试

- **真机帧率必须人工跑**（离屏只能做相对的 A/B，量不出 DWM 合成、vblank 与真实调度下的绝对帧率）。
- 命令前两句固定：`cd /f/My_Project/biliEmojiDD`、`export PYTHONIOENCODING=utf-8`；
  PowerShell 换成 `$env:PYTHONIOENCODING="utf-8"`。
- 五档命令：`--mode idle --page emoji --fake 300 --seconds 6 --warmup 6 --no-net`、
  `--mode scroll --page emoji --fake 300 --seconds 10 --warmup 6 --no-net`、
  `--mode switch --rate 0.4 --seconds 10 --warmup 6 --no-net`、
  `--mode theme --rate 1.0 --seconds 10 --warmup 6 --no-net`、
  `--mode resize --seconds 8 --warmup 6 --no-net`；
  等图窗口期加 `--thumb-delay 800 --seconds 8 --warmup 2` 并与 `--legacy` 同参数对比；
  真实状态 `--mode scroll --seconds 12 --warmup 3`（接受不可复现）。
- `--mode switch` 默认 `--rate 0.2` 会把 300ms 的切页动画一路打断，比真人操作密得多，
  量动画就加 `--rate 0.4`；`--mode theme` 每 tick 切一次主题，建议 `--rate 1.0`，
  看的是「最长停顿」那一笔（切主题是同步卡主线程，不是掉帧那么温和）。
- 五个硬要求：**不要带 `QT_QPA_PLATFORM=offscreen`**；窗口别最小化、别被其他窗口盖住；
  配 `--fake 300` 时 `--warmup` ≥ 5 s；**必须加 `--no-net`**；`--fake 300` 是为可复现
  （不加 `--fake` 时因隔离 `APPDATA` 读不到 Cookie，真实卡片会是 0 张）。
- 看这几行：`实到帧率`、`帧间隔 / 反推帧率`（与实到互相对照，差很多说明有停顿）、
  `单帧重绘耗时`（p99 决定主观卡不卡）、`绘制占用`。
- 判据（按 200 Hz 屏 + 125% 缩放）：idle **重绘 0 次**；scroll `--fake 300` 反推帧率 **≈60**、
  单帧重绘中位 **≤ 8 ms**、p99 **≤ 16 ms**；switch 看**单帧重绘耗时**（滑快照 1~3 ms，
  改前移动真页面是 5~18 ms）——它的「最长停顿」会把两次切换之间的空闲算进去，别当卡顿；
  theme 看「最长停顿」那一笔；resize 单次宽度变化 **≤ 60 ms**。
- **`--mode scroll` 上限由设置项「滚动帧率」决定**：上游 `SmoothScroll` 定时器周期
  `int(1000 / fps)`，默认 60 ⇒ 16 ms ⇒ 封顶 60，所以默认档下稳态 59 fps **就是达标**；
  想超过 60 要调到 120（即时生效，不用重启）。
- **不要用手写 `processEvents` + `time.sleep` 循环量帧率**：Windows 把 2 ms 休眠放大到
  ~15.6 ms，循环每秒只转 60 来次，**可测帧率被卡在 ~64 fps**；脚本已改成 `app.exec()` + `QTimer`。
- **不要调小 `--rate`**：默认 `--rate 0.2`（每秒 5 次，接近真人连续滚动），调到 0.1 以下会喂爆
  `SmoothScroll` 的步进队列。
- 离屏基准必须带 `QT_SCALE_FACTOR=1.25`（本机缩放 125%）；不带时 dpr=1.0，
  数字乐观约 1.56 倍，跟真机对不上。
- **加载环不是滚动掉帧的原因**（滚动本来每帧整块重绘，环的 `update()` 被合并）；
  环伤的是「不动的时候」：idle 时 150 张卡常驻 **41.7% 单核**，关掉后 **0.0%**。
- 参考结论值：稳态 300 卡下 60 档重绘 87.1 / 反推 96.3 fps、单帧 4.04 ms / p99 11.2 ms、
  绘制占用 36.6% 单核；120 档 **102.1 / 107.6 fps**、3.86 / 8.7 ms、41.7% 单核；
  idle `--fake 300 --no-net` 为 0 次重绘（不关联网曾量到 2555 次 + 开头 3.4 s 停顿）。
- 排查：`UnicodeEncodeError` → 没设 `PYTHONIOENCODING`；重绘 0 次且 scroll 也不动 →
  窗口被盖住 / 最小化；idle 一堆重绘 → 先加 `--no-net`，仍非 0 就看输出末尾「重绘来源」点名了谁；
  头部打印「卡片 0」→ 隔离 `APPDATA` 里没有 Cookie；第 1 秒就有几百 ms 停顿 → `--warmup` 不够；
  卡在最后不退 → 假 URL 没预置进 `QPixmapCache`。
- 贴结果时带上：四条命令的完整输出（含头部「页面 / 网格 / 卡片 / 在转的加载环 / dpr / 屏幕 Hz」）、
  跑时窗口多大与是否被盖住、是否加了 `--fake 300`、主观感受。
