# 帧率测试怎么做

给「帧率到底达没达标」这件事的一份操作手册。**为什么改、改了什么**见
[performance.md](performance.md)，这篇只讲**怎么跑、看哪几行、怎么判**。

真机帧率**必须人工跑**：离屏脚本只能做相对的 A/B，量不出 DWM 合成、vblank 与真实调度
下的绝对帧率。

---

## 一、真机帧率（要弹出窗口）

在项目根目录，**Git Bash**：

```bash
cd /f/My_Project/biliEmojiDD
export PYTHONIOENCODING=utf-8          # Windows 终端默认 GBK，中文输出会崩

# ① 稳态：缩略图立即命中、不联网、不依赖 Cookie —— 可复现的基准
uv run python scripts/bench_app_fps.py --mode idle   --page emoji --fake 300 --seconds 6  --warmup 6 --no-net
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --seconds 10 --warmup 6 --no-net
uv run python scripts/bench_app_fps.py --mode switch --seconds 10 --warmup 6 --no-net
uv run python scripts/bench_app_fps.py --mode resize --seconds 8  --warmup 6 --no-net

# ② 等图窗口期：缩略图延迟 800 ms 才到，加载环真的转起来 —— **本轮优化真正见效的场景**
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --thumb-delay 800 --seconds 8 --warmup 2 --no-net
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --thumb-delay 800 --seconds 8 --warmup 2 --no-net --legacy   # 改动前

# ③ 真实状态：走你自己的 Cookie / 缓存
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --seconds 12 --warmup 3
```

PowerShell 把第一句换成 `$env:PYTHONIOENCODING="utf-8"`，其余照抄。

**五个硬要求，少一个数字就没意义：**

1. **不要带 `QT_QPA_PLATFORM=offscreen`** —— 这条就是要真窗口。
2. **窗口别最小化、别被别的窗口盖住** —— 被盖住就不重绘了。
3. **`--warmup` 要够**：启动后的静默预拉取（Cookie 检测 / 读 `all_packages.json` /
   查更新）都挤在前几秒；配 `--fake 300` 时要 **≥5 s**（注入 300 张卡本身要好几秒，
   不留够预热会把注入的尾巴算进测量窗口，看着像「长停顿」）。
4. **`--no-net`**：不关掉联网组件的话，更新检查 / Cookie 探测 / 内容数量 / 直播会自己
   开任务，把 idle 也弄得一堆重绘（实测：关掉后 idle 是 0 次重绘，不关就上百次）。
5. `--fake 300` 是为了可复现；**不加 `--fake` 就是测你的真实仓库状态** —— 注意本脚本
   按项目规矩隔离了 `APPDATA`，所以**读不到你的 Cookie，真实卡片会是 0 张**
   （头部那行会打印「卡片 0」并提示你）。想测真实卡片请用 ③，并接受它不可复现。

---

## 二、看哪三行

```
实到帧率              xx.x fps                    ← 你要的帧率
帧间隔 / 反推帧率     中位 xx ms / xx fps          ← 与「实到」互相对照，差很多说明有停顿
单帧重绘耗时      中位 x.xx ms  p90 ... p99 ...   ← p99 决定主观卡不卡
绘制占用           x.xx s / N s（= xx% 单核）      ← 这一档设置到底花多少 CPU 去画
```

`bench_app_fps.py` 覆写 `QApplication.notify` 给每个 `Paint` 计时，把「一次事件循环拍里
连续交付的一组 Paint」算作一帧（相邻 Paint 间隔 > 2 ms 即下一帧）。

**判据**（按 200 Hz 屏 + 125% 缩放给；不是按 200 要求 —— Qt Widgets 是 CPU 软件光栅，
120 就是现实上限）：

| 场景 | 达标 |
|---|---|
| `--mode idle` | **重绘 0 次**。只要不是 0，看下面「重绘来源」那几行点名是谁，把输出贴回来 |
| `--mode scroll --fake 300` | 反推帧率 **≈60**，单帧重绘 中位 **≤ 8 ms**、p99 **≤ 16 ms** |
| `--mode switch` | 全程没有 > 100 ms 的停顿 |
| `--mode resize` | 单次宽度变化 ≤ 60 ms |
| `--thumb-delay 800` | 看当前 vs `--legacy` 的差值 —— 唯一能体现本轮优化的场景 |

> **`--mode scroll` 的上限取决于设置里的「滚动帧率」**（设置 → 外观 → 滚动帧率）。
> 上游 `SmoothScroll` 的定时器周期是 `int(1000 / fps)`，`fps` 默认 60 ⇒ 16 ms ⇒ 封顶 60。
> 所以默认档下「稳态滚动 59 fps」**就是达标**，不是没优化到位；想超过 60 请把设置项调到
> 120（即时生效，不用重启），那时上限才变成 120。详见 [performance.md](performance.md) 第六节。

---

## 三、结果怎么解读

**① 等图窗口期 —— 本轮优化的主战场，但它**不是**滚动时掉帧的原因**

缩略图还在转圈的那几秒，可见的加载环每个 tick 都会把**整块网格 viewport** 拖进重绘。
但实测下来要分清两种情形：

| 情形 | 环的额外开销 |
|---|---|
| **停在页面上不动**（idle，环在转） | **很大**：150 张卡常驻 41.7% 单核；关掉后 0.0% |
| **正在滚动** | **几乎为零**：滚动本来就在每帧重绘整块网格，环的 `update()` 被合并进去 |

真机 + 离屏两边量到的滚动帧率，环开与环关的差都只有几个百分点。所以**如果你的
「20 多帧」是滚动时的手感，环不是主因**。环真正伤的是「不动的时候白烧 CPU」——
那部分已修（14.1% → 1.6% 单核，实测）。

**② idle 量到重绘 / 切换与缩放出现 ~200 ms 周期性停顿**

`--no-net` 没加的话，更新检查 / Cookie 探测 / 内容数量 / 直播会自己开任务，idle 也会
一堆重绘（离屏实测：加 `--no-net` 是 0 次，不加则上百次，而且**这两种离屏都复现不出
真机上的 2555 次**）。先加 `--no-net` 重测；仍非 0 就看输出末尾的「重绘来源」，它会
点名是哪个控件在画（例如 `PackageCard` / `IndeterminateProgressRing` / `QStackedWidget`）。

**② `--mode scroll` 的 p99 偶尔一次几百 ms 的尖峰**

先看 `绘制占用` 那行：**它远小于测量时长的对应比例**（比如 8 s 里只占 1 s）说明尖峰不是
绘制造成的，多半是启动期的静默预拉取（把 `--warmup` 加大、加 `--no-net` 重测）。
绘制占用本身很高（接近测量时长）才是画面真的重。

> ⚠️ **不要用手写 `processEvents` + `time.sleep` 循环去量帧率**（本脚本早期版本踩过）：
> Windows 会把 2 ms 的休眠放大到 ~15.6 ms，循环每秒只转 60 来次，**可测帧率被卡在
> ~64 fps**，120 帧那档永远量不出来。本脚本已改成 `app.exec()` + `QTimer`。

**③ 不要调小 `--rate`**

默认 `--rate 0.2`（每秒 5 次，接近真人连续滚动）。调到 0.1 以下会把 Qt 上游
`SmoothScroll` 的步进队列喂爆（它按队列里每条事件各自插值，喂得比消费快就会堆起来），
那种长批次是脚本造的，真人不会遇到。

**④ 想和改动前对比**

```bash
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 PYTHONIOENCODING=utf-8 \
  uv run python scripts/bench_grid_scroll.py
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 PYTHONIOENCODING=utf-8 \
  uv run python scripts/bench_grid_scroll.py --legacy
```

`--legacy` 在**同一进程**里还原改动前的三项行为（环启停策略 / 滚动时长 / 缩放 memo），
是真 A/B，不是拿两次运行的数字对着猜。参考值（EmojiGrid 300 卡）：

| 指标 | 改动前 | 改动后 |
|---|---|---|
| 在转的加载环 | 300 | 24 |
| 滚动一步 | 15.4 ms | 12.5 ms |
| 网格隐藏后空闲 CPU | 141 ms/s（14.1% 单核） | 16 ms/s（1.6%） |
| 一格滚轮净 CPU | 266 ms | 156 ms |

> **离屏基准必须带 `QT_SCALE_FACTOR=1.25`**：本机 Windows 缩放 125%，真实绘制是 1.25 倍
> 像素。不带时 dpr=1.0，数字乐观约 1.56 倍，跟真机对不上。

---

## 四、贴回来的时候带上

1. 四条命令的**完整输出**（含头部那行「页面 / 网格 / 卡片 / 在转的加载环 / dpr / 屏幕 Hz」）。
2. 跑的时候**窗口多大、有没有被别的窗口盖住**。
3. 是加了 `--fake 300` 还是跑的你的真实状态。
4. 主观感受（如果有）：滚起来跟手吗？哪一页最卡？翻页有没有明显的顿？

---

## 五、跑不动 / 结果怪时先查这几条

| 现象 | 原因 |
|---|---|
| `UnicodeEncodeError` | 没设 `PYTHONIOENCODING=utf-8` |
| 重绘 0 次、`--mode scroll` 也不动 | 窗口被盖住 / 最小化了 |
| `idle` 一堆重绘 | 先加 `--no-net`；仍非 0 就看末尾「重绘来源」点名了谁 |
| 头部打印「卡片 0」 | 隔离 APPDATA 里没有 Cookie；加 `--fake 300`，或接受真实状态不可复现 |
| 第 1 秒就有几百 ms 的停顿 | `--warmup` 不够（配 `--fake 300` 要 ≥5 s） |
| `--fake 300` 后卡片数还是 0 | 那一页的网格不吃假数据（自己建卡 / 走队列数据），脚本会打印提示 |
| 卡在最后不退 | 假 URL 没预置进 `QPixmapCache` 时会各排一个 15 s 超时任务；脚本已预置，正常不会发生 |
| 数字比自己预想的差很多 | 先确认没带 `QT_QPA_PLATFORM=offscreen`、`--warmup` 够、窗口在前台 |
| 滚动怎么都过不了 60 fps | 看设置里的「滚动帧率」是不是 60（默认档上限就是 60） |

## 附：真机实测记录（2026-09-24，Windows / dpr 1.25 / 200 Hz / 1080×620 网格 300 卡）

> ⚠️ **下面第一张表的 fps 列是脚本 bug 下的数字，只用来比当前 / `--legacy` 的相对差**：
> 当时的测量循环用 `processEvents` + `time.sleep(0.002)`，Windows 把 2 ms 休眠放大到
> ~15.6 ms，循环每秒只转 60 来次 ⇒ **可测帧率被卡在 ~64 fps**。已改成 `app.exec()` +
> `QTimer`（第二张表是修好之后量的）。

**滚动 A/B（`--no-net`，同一台机器，当前 vs `--legacy`）：**

| 场景 | 在转的环 | 实到 fps | 单帧重绘 中位 | p99 |
|---|---|---|---|---|
| 稳态（图全到位）· 当前 | 0 | **58.5** | **5.27 ms** | 9.5 ms |
| 稳态 · `--legacy` | 285 | 50.0 | 5.92 ms | 13.5 ms |
| 等图窗口期（`--thumb-delay 800`）· 当前 | 15 | **59.5** | 5.08 ms | 11.8 ms |
| 等图窗口期 · `--legacy` | 300 | 58.2 | 4.98 ms | 11.9 ms |

**修好测量循环后（`--scroll-fps` 两档，稳态 300 卡）：**

| 滚动帧率设置 | 重绘频率（实到 / 反推） | 单帧重绘 中位 / p99 | 绘制占用 |
|---|---|---|---|
| 60（默认） | 87.1 / 96.3 fps | 4.04 ms / 11.2 ms | 36.6% 单核 |
| 120 | **102.1 / 107.6 fps** | 3.86 ms / 8.7 ms | 41.7% 单核 |

**读数：**

1. **稳态下环的修复值 +8.5 fps**（50.0 → 58.5，第一张表）、单帧绘制 5.92 → 5.27 ms。
   `--legacy` 里 285 个视口外的环仍在白烧，把帧率压在 50。
2. **等图窗口期两者基本无差**（58.2 vs 59.5）。滚动本来每帧就整块重绘，环的 `update()`
   被合并进去了 —— **环不是滚动掉帧的原因**，它伤的是「不动的时候」。
3. **「滚动帧率」设置项真的有用**：120 档把重绘频率从 87 抬到 102（反推 96 → 108），
   代价是绘制占用 36.6% → 41.7% 单核。单帧 3.86 ms 仍远在 8.3 ms 预算内。
4. `--mode idle --fake 300 --no-net`：**0 次重绘**。同样是真机、不关联网时曾量到
   2555 次重绘 + 开头 3.4 s 停顿 —— 那是更新检查 / Cookie 探测 / 内容数量 / 直播
   这些联网组件在刷，不是网格。
5. 每帧另有约 1.3 次**整页**重绘（`QStackedWidget` + 它的 viewport 各 ~79/s）：
   脏区从网格继续往上传播到了页面容器。收益不大，未处理。

> 结论：本轮改动修掉的是「白烧的 CPU」与「建卡 / 重排耗时」（空闲 14.1% → 1.6% 单核、
> 建卡快 25–30%、`_update_visible` 847 → 147 µs、窗口拉宽 81 → 49 ms）；
> 滚动帧率的上限由**设置项「滚动帧率」**决定，两档实测 87 / 102 fps。


```
PS F:\My_Project\biliEmojiDD> uv run python scripts/bench_app_fps.py --mode idle   --page emoji --fake 300 --seconds 5  --warmup 2

📢 Tips: QFluentWidgets Pro is now released. Click https://qfluentwidgets.com/pages/pro to learn more about it.

页面 emoji｜网格 PackageGrid｜卡片 300｜在转的加载环 0｜dpr 1.25｜屏幕 200 Hz

测量 5.0 s｜重绘 2555 次｜成帧 83 个
事件循环占用        1.35 s / 5.0 s（27%；剩下的是脚本自己的 sleep）
实到帧率            17.4 fps（83 帧 / 4.77 s，只算有重绘的时段）
帧间隔            中位  13.07 ms  p90  35.94 ms  p99 3416.76 ms
反推帧率          中位   76.5 fps
单帧重绘耗时      中位   4.79 ms  p90  17.80 ms  p99  31.60 ms
单帧重绘上限       208.7 fps（只算绘制，不合成的理论上限）
最长停顿：
              3417 ms  出现在第   0.0 s
               122 ms  出现在第   4.6 s
                63 ms  出现在第   3.7 s

对表：离屏基准里同一网格的「滚动一步 / 纯绘制单帧」见 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py
PS F:\My_Project\biliEmojiDD> uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --seconds 10 --warmup 2

📢 Tips: QFluentWidgets Pro is now released. Click https://qfluentwidgets.com/pages/pro to learn more about it.

页面 emoji｜网格 PackageGrid｜卡片 300｜在转的加载环 0｜dpr 1.25｜屏幕 200 Hz

测量 10.0 s｜重绘 21336 次｜成帧 574 个
事件循环占用        6.29 s / 10.0 s（63%；剩下的是脚本自己的 sleep）
实到帧率            57.6 fps（574 帧 / 9.97 s，只算有重绘的时段）
帧间隔            中位  16.90 ms  p90  27.76 ms  p99  60.26 ms
反推帧率          中位   59.2 fps
单帧重绘耗时      中位   4.94 ms  p90   7.58 ms  p99  15.00 ms
单帧重绘上限       202.3 fps（只算绘制，不合成的理论上限）
最长停顿：
               326 ms  出现在第   7.0 s
               324 ms  出现在第   4.5 s
               314 ms  出现在第   9.5 s

对表：离屏基准里同一网格的「滚动一步 / 纯绘制单帧」见 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py
PS F:\My_Project\biliEmojiDD> uv run python scripts/bench_app_fps.py --mode switch --seconds 10 --warmup 2

📢 Tips: QFluentWidgets Pro is now released. Click https://qfluentwidgets.com/pages/pro to learn more about it.

页面 emoji｜网格 PackageGrid｜卡片 0｜在转的加载环 0｜dpr 1.25｜屏幕 200 Hz
提示：这个页面没有卡片，帧率数字会失真 —— 加 --fake 300 再测一次。

测量 10.0 s｜重绘 2378 次｜成帧 100 个
事件循环占用        1.48 s / 10.0 s（15%；剩下的是脚本自己的 sleep）
实到帧率            10.3 fps（100 帧 / 9.67 s，只算有重绘的时段）
帧间隔            中位  20.46 ms  p90 207.21 ms  p99 220.90 ms
反推帧率          中位   48.9 fps
单帧重绘耗时      中位   5.14 ms  p90  17.69 ms  p99  25.19 ms
单帧重绘上限       194.4 fps（只算绘制，不合成的理论上限）
最长停顿：
               221 ms  出现在第   0.2 s
               214 ms  出现在第   5.4 s
               212 ms  出现在第   1.2 s

对表：离屏基准里同一网格的「滚动一步 / 纯绘制单帧」见 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py
PS F:\My_Project\biliEmojiDD> uv run python scripts/bench_app_fps.py --mode resize --seconds 8  --warmup 2

📢 Tips: QFluentWidgets Pro is now released. Click https://qfluentwidgets.com/pages/pro to learn more about it.

页面 emoji｜网格 PackageGrid｜卡片 0｜在转的加载环 0｜dpr 1.25｜屏幕 200 Hz
提示：这个页面没有卡片，帧率数字会失真 —— 加 --fake 300 再测一次。

测量 8.0 s｜重绘 2362 次｜成帧 86 个
事件循环占用        1.25 s / 8.0 s（16%；剩下的是脚本自己的 sleep）
实到帧率            11.0 fps（86 帧 / 7.80 s，只算有重绘的时段）
帧间隔            中位  21.10 ms  p90 207.42 ms  p99 210.78 ms
反推帧率          中位   47.4 fps
单帧重绘耗时      中位   7.42 ms  p90  10.19 ms  p99  14.29 ms
单帧重绘上限       134.8 fps（只算绘制，不合成的理论上限）
最长停顿：
               211 ms  出现在第   6.1 s
               211 ms  出现在第   0.4 s
               210 ms  出现在第   7.4 s

对表：离屏基准里同一网格的「滚动一步 / 纯绘制单帧」见 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py
PS F:\My_Project\biliEmojiDD> uv run python scripts/bench_app_fps.py --mode scroll --page emoji --seconds 10 --warmup 3

📢 Tips: QFluentWidgets Pro is now released. Click https://qfluentwidgets.com/pages/pro to learn more about it.

页面 emoji｜网格 PackageGrid｜卡片 0｜在转的加载环 0｜dpr 1.25｜屏幕 200 Hz
提示：这个页面没有卡片，帧率数字会失真 —— 加 --fake 300 再测一次。

测量 10.0 s｜重绘 1292 次｜成帧 52 个
事件循环占用        1.38 s / 10.0 s（14%；剩下的是脚本自己的 sleep）
实到帧率             7.5 fps（52 帧 / 6.93 s，只算有重绘的时段）
帧间隔            中位  13.75 ms  p90  30.76 ms  p99 3937.68 ms
反推帧率          中位   72.7 fps
单帧重绘耗时      中位   5.34 ms  p90  11.73 ms  p99  16.28 ms
单帧重绘上限       187.4 fps（只算绘制，不合成的理论上限）
最长停顿：
              3938 ms  出现在第   0.2 s
              2220 ms  出现在第   4.7 s
               168 ms  出现在第   4.5 s

对表：离屏基准里同一网格的「滚动一步 / 纯绘制单帧」见 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25
```

