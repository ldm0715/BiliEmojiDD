# 帧率与滚动性能

把应用的帧率从实测 ~20 fps 拉到 60–120 fps 的一整轮优化：三个真凶、各自的实测数字、
改法与回退过的尝试。**改动集中在 `app/components/widgets.py` 与
`app/components/page_scaffold.py`。**

## 一、本机的真实绘制规模（先量准，再谈优化）

| 项 | 值 |
|---|---|
| 显示器 | H27T22S，2560×1440，**200 Hz** |
| Windows 缩放 | **125%** |
| Qt 视角 | 逻辑 2048×1152，**`devicePixelRatio = 1.25`** |
| 窗口 | 1100×760 逻辑 → 1375×950 物理像素 |

`main.py:28` 把高 DPI 舍入策略设成 `PassThrough`，所以 **dpr 就是 1.25**、不是 1 或 2。
后果：一屏要画的像素是 1.25² = **1.56 倍**，而且非整数缩放让位图绘制走插值路径。

**所以离屏基准必须带 `QT_SCALE_FACTOR=1.25`**，否则 dpr=1.0，数字会乐观 1.56 倍，
跟真机对不上（`docs/development.md` 那条「不要用截图判断性能」的同源要求）。

## 二、三个真凶

### 真凶 ①：加载环在给看不见的卡片空转

`_SpinnerMixin._init_spinner` 建卡时无条件 `self._spinner.start()`；只有
`thumb_done()` / `thumb_failed()` / 无封面 url 才会收环。而缩略图**只对可见项请求**，
所以滚出视口的卡、隐藏页里的卡，环永远转下去。离屏实测（`PackageGrid`，全部环在转
与全停的 CPU 差）：

| 卡数 | 环在转 | 环全停 | 环的代价 |
|---|---|---|---|
| 18（一页） | 29.9% | 3.9% | **26.0% 单核** |
| 150 | 41.7% | 0.0% | **41.7%** |
| 300 | 46.9% | 0.0% | **46.9%** |

**不是「转个圈而已」**。1 秒内的 `Paint` 事件统计（150 卡 / 24 可见）：

```
28x28   : 4464 次  ← 每次 tick 有 3 个控件重画同一小块（卡片 / imageBtn / 环）
905x559 : 124 次   ← 整块网格重绘，每秒 124 次
```

环每次 tick 都让**整块 viewport 重绘**（网格背景一遍 + viewport 内容一遍），
合计约 7 ms/tick × 62 tick/s ≈ **0.44 s/s**。机制是 Qt 的脏区向上合并：一个非不透明子控件
`update()` 之后，脏区会一路并到最近的「不透明祖先」，而那个祖先就是网格 viewport。

拆开量（150 卡、24 个可见环在转）：

| 场景 | CPU |
|---|---|
| 环在转 + 正常绘制 | 40.4% |
| 环在转、但 `paintEvent` 不画东西（脏区机制照旧） | 29.9% |
| 全部停环 | 0.0% |

即：**弧线绘制本身 ~10 个点，脏区放大带来的整块重绘 ~30 个点**。

### 真凶 ②：`QListView` 的 IconMode 每次滚动整块重绘

`_CardGridBase` 是 `qfluentwidgets.ListWidget`（`ListBase` + 裸 `QListWidget`）
+ `setItemWidget`。实测滚动一步的绘制区域就是 `(1072, 620)` **整个视口**，
不是暴露出来的那 60 px 条带 —— IconMode 没有 blit 优化。

| 场景（dpr 1.25，300 卡） | 滚动一步 |
|---|---|
| PackageGrid（18 可见） | 12.7 ms → 79 fps 上限 |
| EmojiGrid（32 可见） | 18.8 ms → 53 fps 上限 |

每步还隐含两笔：

* `QAbstractItemView::updateEditorGeometries()` 会对**全部 item**（`setItemWidget` 造出的
  持久编辑器）跑一遍，回调进 qfluentwidgets 的 `ListItemDelegate.updateEditorGeometry`：
  150 项 **1.30 ms/次**、300 项 2.6 ms/次。这就是 `docs/app_shell.md` 里记的
  `TableItemDelegate` O(n²)（300 项 45150 次）那个根。
* **网格页从没调过 `tune_scroll`**（此前全仓库唯一调用点是 `home_page.py`），
  一直用库默认的 400 ms 平滑滚动 = 一格滚轮摊成 **24 帧**，每帧整块重绘。

### 真凶 ③：`_update_visible` 每个滚动像素步全量遍历

老实现 `for i in range(self.count())` 逐项 `visualItemRect` 求交集：N=300 时
**0.71 ms/次**，而 `scrollContentsBy` 每个像素步都要跑一次；`QueueList` 再叠一遍。

顺带（同源、非帧率）：卡片 `resizeEvent` 无条件 `_apply_pixmap()`，
内部 `pm.scaled(..., SmoothTransformation)` 且没有「上次目标尺寸」记忆
⇒ 窗口宽度一变就全量重排 + 每卡重缩放。

## 三、改了什么

### A. 加载环的启停归网格管

卡片级契约**保持不变**（`_init_spinner` 仍然 `start()`，`check_*.py` 里直接建卡断言
「建卡即在转」的用例照旧通过），新增网格级策略：

* `_SpinnerMixin` 增 `_spinner_wanted` / `_thumb_pending` 两个状态位与
  `set_spinner_wanted()` / `waiting_thumb()` / `_show_spinner()`。
  `thumb_done()` / `thumb_failed()` 清 `_thumb_pending`；`thumb_restart()` 置回并
  **尊重 `_spinner_wanted`**（右键「重新加载」不会把视口外的卡重新点着）。
* `_CardGridBase._sync_spinners(first, last)` 只对**差集**动手：要转的 = 可见 ∩ 还在等图。
  建卡后记账从「全都在转」起算（`self._ringed = set(range(count))`），
  否则视口外的环没人关。
* 网格 `hideEvent` 停掉全部并清账，`showEvent` 重新对齐 —— `QStackedWidget` 切页只发
  hide/show，这是隐藏页不空转的唯一入口。
* 判据继续用 `isHidden()` 而非 `isVisible()`：卡片未 `show()` 时后者恒为 False
  （`_center_spinner` 的注释记过这个坑）。

**视觉无变化**：滚出视口 / 隐藏页的环本来就看不见；滚进新区域的卡在 `_update_visible`
那一拍立刻开环。

### B. 滚动路径

* `_visible_index_range()`：拿 `indexAt(QPoint(1, 1))` 当种子，向两侧**有界游走**。
  **不能拿 `indexAt` 取两端** —— IconMode 下右下角逐点常落在最后一列右边的空隙里
  （1072 / 177 = 6.05 列），返回无效 index。游走判据与老的全量遍历是同一条
  `visualItemRect(...).intersects(viewport)`，行为等价是构造出来的。
  实测 `_update_visible` 单次 **847 µs → 147 µs**（5.8×）。
* `tune_scroll` 扩成同时认 `ScrollArea` 的 `scrollDelagate`（上游拼错）与
  `ListBase` 的 `scrollDelegate`，`_CardGridBase.__init__` 里统一调一次。
  一格滚轮 400 ms / 24 帧 → 200 ms / 12 帧，实测净 CPU **156 → 31 ms**（PackageGrid）。
* `_apply_scaled_icon` / `_apply_scaled_pixmap` / `_rescale`：把四处逐字重复的
  `_apply_pixmap` 收敛成一个 memo 过的缩放（比 `is` 而不是内容相等 ——
  `QPixmap.__eq__` 要逐像素比，那比重缩放还贵）。窗口宽度变化
  **81 → 49 ms**。

### C. 建卡 / 翻页

`_apply_card_bg()` 一处收敛三种卡片的 `_apply_bg`，并做成**幂等**：建卡时它会连着被调三次
（`__init__` / `set_selectable` / `bind_theme` 的首次回调），30 张卡里 `setStyleSheet`
占建卡总耗时（461 ms 的 profile）的 **30%**。幂等后：

| 卡片数 | 建卡耗时 |
|---|---|
| 20 | 248 → 176 ms |
| 30 | 427 → 320 ms |
| 100 | 1941 → 1612 ms |

## 四、实测总账（离屏，`QT_SCALE_FACTOR=1.25`）

`scripts/bench_grid_scroll.py`，EmojiGrid 300 卡：

| 指标 | 改动前 | 改动后 |
|---|---|---|
| 在转的加载环 | 300 | 24 |
| 网格隐藏后空闲 CPU | 141 ms/s（14.1% 单核） | **16 ms/s（1.6%）** |
| 滚动一步（有环） | 15.4 ms | 12.5 ms |
| 滚动一步（无环） | 9.5 ms | 9.5 ms |
| 窗口宽度变化一次 | 45 ms | 46 ms |
| 一格滚轮净 CPU | 266 ms | 156 ms |

PackageGrid 300 卡：滚动一步 9.9 → 7.5 ms，一格滚轮 203 → 62 ms，
窗口宽度变化 49 → 45 ms。

**稳态**（缩略图全部到位、环全停）时 `--mode idle` 实测**零次重绘**，
主线程空闲 CPU 0%。

## 五、试过并回退的

| 尝试 | 结果 |
|---|---|
| 网格去掉逐项 `item.setSizeHint(cell)`（已 `setUniformItemSizes(True)` + `setGridSize`） | **横向溢出**：`check_improvements.py` 的「无横向溢出」在 900 / 420 两档都漏。`setSizeHint` 确实参与布局，不能省 |
| item delegate 换成裸 `QStyledItemDelegate` | 滚动一步 -2.28 ms，但**逐像素比对有 0.75% 不同**：库的 `ListItemDelegate` 会画列表项底部分隔线 / 焦点框。另外 `ListBase._setHoverRow` 会 `AttributeError`。属「有可见副作用」，未做 |
| 卡片设 `WA_OpaquePaintEvent` | 33.9% → 16.9%，但只把脏区从「整块视口」收到「单张卡」，而卡本来就铺满视口，结构性收益有限；且卡片未选中时**完全透明**，填色取错就是可见色块。未做 |
| 把网格套进外层 `QScrollArea` 借它的 blit | **更慢**：8850 px 高的 backing store → 24 ms/步 |
| 卡片不透明化 / 环自成脏区边界（环自己填背景） | 背景色取不到：`QPalette` 全黑（qfluentwidgets 用 QSS 上色），网格背景由网格自己画；且 EmojiCard 的图标区还有一层灰色叠加。不成立 |
| 「用 OpenGL 承载关键视图」 | 误诊。Qt Widgets 是 CPU 软件光栅，GPU 不参与；把子树塞进 `QOpenGLWidget` 只是多一层离屏渲染 + 纹理上传，子控件仍走 raster，**更慢**。瓶颈是白烧的动画，GPU 帮不上 |

## 六、滚动帧率是设置项（60 / 120）

**滚动帧率的上限取决于设置里的「滚动帧率」**：`SmoothScroll.__smoothMove` 由 `QTimer`
驱动，周期 `int(1000 / fps)`，`fps` 默认 60 ⇒ 16 ms。渲染再快也封顶在那里 ——
所以「要到 120」只有一个开关：`SmoothScroll.fps`。已做成设置项
**设置 → 外观 → 滚动帧率**（`cfg.scroll_fps`，60 默认 / 120）。

**真机实测（`bench_app_fps.py --mode scroll --fake 300 --no-net`，8 s，dpr 1.25，200 Hz）：**

| 设置 | 重绘频率（实到 / 反推） | 单帧重绘 中位 / p99 | 绘制占用 |
|---|---|---|---|
| 60 档（默认） | 87.1 / 96.3 fps | 4.04 ms / 11.2 ms | 36.6% 单核 |
| 120 档 | **102.1 / 107.6 fps** | 3.86 ms / 8.7 ms | 41.7% 单核 |

> ⚠️ 早先量到的「所有场景都顶在 58–59.5 fps」是**脚本自己的 bug**：测量循环用
> `processEvents` + `time.sleep(0.002)`，而 Windows 会把 2 ms 的休眠放大到 ~15.6 ms，
> 循环每秒只转 60 来次，把**可测**帧率卡在 ~64 fps。改成 `app.exec()` + `QTimer`
> 之后才是上面这两个数。**别再用手写 processEvents 循环量 >60 帧**。
>
> 「重绘频率」是代理指标：它数的是「每秒重绘几拍」，其中既有平滑滚动的插值步，
> 也有随之而来的额外重绘，所以会高于动画本身的步频（60 档 12 步/格、120 档 24 步/格）。

- `fps` 决定一格滚轮摊成几帧：`步骤数 = fps * duration / 1000`，`duration` 固定 200 ⇒
  60 → 12 帧、120 → 24 帧。位移不变，只是插值更密。
- **网格里一格滚轮 = 一行卡片**，`tune_scroll` 靠 `SmoothScroll.stepRatio` 定：
  `位移 = angleDelta * stepRatio * wheelScrollLines * singleStep / 120`，而 ItemView 的
  `singleStep` 就是一行卡片的像素高，所以取 `stepRatio = 1 / wheelScrollLines` 正好一行。
  上游默认 `stepRatio = 1.5`（把 120 角度放大成 180 的那一层），乘出来是 4.5 行 ——
  实测 PackageGrid 一格 **845 px ≈ 4.9 行**，一屏半就过去了。改完 189 px = 1.10 行
  （多出的 10% 来自上游 `acceleration` 连滚最多 ×2，长列表快速翻页仍然有用）。
  整页 `ScrollArea` 的 `singleStep` 是 20px 文本行，一格 96 px 本来就是对的，`stepRatio`
  保持 1.5 不动。断言见 `scripts/check_wheel_step.py`。
- **两档都必须整除**：`60×200 = 12000`、`120×200 = 24000`，都满足
  `fps * duration % 1000 == 0`。这是硬约束 —— 不整除时 `stepsTotal` 是小数，
  `__smoothMove` 每帧 `-1` 永远减不到 0，那一格滚轮会**永久留在队列里**、
  定时器再也不停（`tune_scroll` 直接 `raise ValueError`）。
- **改完即时生效，不需要重启**：`tune_scroll` 每次现读配置（新建的滚动区域天然跟随），
  已经存在的那些由 `page_scaffold.apply_scroll_fps()` 遍历
  `QApplication.allWidgets()` 刷一遍（`ScrollArea.scrollDelagate` 与
  `ListBase.scrollDelegate` 两种属性名都认）。
- **`OptionsValidator` 的兜底顺序要紧**：它把非法值兜成 `options[0]`，所以省 CPU 的
  `60` 必须排第一（`config.SCROLL_FPS`）—— 配置文件被改坏时回落到省 CPU 那档，
  而不是突然翻成费 CPU 的 120。这与 `_StrictBoolValidator` 那条坑同源。
- 代价：一格滚轮的绘制量成正比（12 → 24 帧）。按真机实测单帧 5.27 ms 算，一格滚轮约
  126 ms CPU / 200 ms 墙钟，稳态单帧仍远在 8.3 ms 预算内。

## 七、还没做的（都有可见 / 可感的副作用，需先确认）

| 项 | 收益 | 副作用 |
|---|---|---|
| 滚动进行中冻结环动画（停滚 ~180 ms 后恢复） | 切断「滚到新区域 → 一批卡开始加载 → 每帧整块重绘」这条链路，约 30 个点 | 滚动时新暴露的卡要等停下才显环 |
| 延迟 ~250 ms 才开环（快请求不闪环） | 减少同时在转的环数量 | 环出现时机变晚 |
| 环的绘制预渲染成帧表 + blit | 弧线绘制 ~10 个点（单环 80 µs，`render()` 量到 470 µs） | 帧表要和上游动画的 (start, span) 轨迹完全对齐，做偏了环的观感就变了 |
| item delegate 换裸的 | 滚动一步 -2.28 ms；`updateEditorGeometries` 那 O(N) 也一并消失，滚动与建卡都受益 | 列表项底部分隔线 / 焦点框消失（0.75% 像素） |

**现状：稳态（图都加载完）滚动一步 9.5 ms（≈105 fps 上限，真机扣掉合成预计 60–90 fps）；
等图窗口期因为上面第一条，可见环仍在拖整块重绘。**

## 八、怎么验

```bash
# 离屏 A/B（可复现，改动前后同进程对比）
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 uv run python scripts/bench_grid_scroll.py --legacy

# 真机帧率（要窗口，别带 QT_QPA_PLATFORM）
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --seconds 10 --warmup 6 --no-net
uv run python scripts/bench_app_fps.py --mode scroll --page emoji --fake 300 --seconds 8 --scroll-fps 120 --warmup 6 --no-net
uv run python scripts/bench_app_fps.py --mode idle   --page emoji --fake 300 --seconds 6 --warmup 6 --no-net

# 新设置项的行为断言（配置项 / 即时生效 / 整除约束 / 设置页接线）
QT_QPA_PLATFORM=offscreen uv run python scripts/check_scroll_fps.py
```

`bench_app_fps.py` 覆写 `QApplication.notify` 给每个 `Paint` 计时，把「一次事件循环拍里
连续交付的一组 Paint」算作一帧；**测量走 `app.exec()` + `QTimer`，不要用手写
`processEvents` + `sleep` 循环**（Windows 上会把可测帧率卡在 ~64 fps）。输出里的
**绘制占用**是「这一档滚动到底花多少 CPU 去画」，也是唯一不依赖测量方式的数。
`--warmup ≥ 2 s` 是必要的：启动后的静默预拉取
（Cookie 检测 / 读 `all_packages.json` / 查更新）都挤在前几秒。

行为回归看 `scripts/check_*.py`，重点是 `check_reload.py`（环的启停时机）、
`check_download_improvements.py`（建卡即转 / 收环 / 无 url 不空转）、
`check_improvements.py`（网格几何与无横向溢出）、`check_grid_click.py`（点击下标）。
