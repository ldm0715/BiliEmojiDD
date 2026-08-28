# 下载体验优化 + 收藏集去重键修复

本批改动围绕「下载」这条链路：详情页选项按实际内容显隐、队列项显示内容体量、下载完成后队列自动收敛、缩略图加载态可见；外加一个用户报上来的收藏集队列去重 Bug（同一活动的不同期会被吃掉）。

## 一、背景

| # | 问题 | 现象 |
|---|---|---|
| 1 | 表情包详情页恒显示「下载动图 (GIF)」 | 静态包里没有任何 `emote.gif_url`，勾了也只会回退 PNG，选项形同虚设 |
| 2 | 队列卡片看不出内容体量 | 只有名称 / 类别 / ID+价格，不知道这一项要下几张图、几个视频 |
| 3 | 下载完成后队列不收敛 | 已全部下完的项仍留在队列，下次批量下载重复走一遍 |
| 4 | 缩略图未到位时是灰块 | 缩略图池只有 3 线程，一屏几十张图要排队，灰块看着像「加载失败」 |
| 5 | **收藏集多选加入，部分项进不了队列** | 加入后列表里没有，点进详情却显示「已加入」 |

## 二、改动文件

| 文件 | 说明 |
|---|---|
| `app/components/content_meta.py`（新） | 下载项内容概要（图片 / 视频数）：内存缓存 + 后台懒加载 |
| `app/common/signal_bus.py` | 新增 `contentMetaRaw` / `contentMetaLoaded` |
| `app/components/download_queue.py` | **`item_key` 收藏集改用 `dlc:<act>:<lottery>`**（Bug 5） |
| `app/components/download_runner.py` | `ItemOutcome` / `BatchReport` / `_collect_outcomes`；`start_download(on_result=)` |
| `app/components/package_detail.py` | GIF 选项整行显隐；喂内容缓存 |
| `app/components/widgets.py` | `_SpinnerMixin` 加载环（五个卡片）；`QueueCard` 内容行；`QueueList` 懒加载回填 |
| `app/view/download_page.py` | 全部成功的项自动移出队列 |
| `app/view/dress_page.py` | 详情拉到收藏集后喂内容缓存 |
| `scripts/check_download_improvements.py`（新） | 本批断言脚本（26 条） |

## 三、实现要点

### 1. GIF 选项按实际内容显隐

判据是 **`any(em.gif_url for em in pkg.emote)`**，不是 `pkg.is_gif`——后者只看 `meta.label_text`，与 `download_package_batch` 里 `if use_gif and em.gif_url` 的实际取用不同步（存在标了 GIF 包却没有任何 `gif_url` 的数据）。

整行用 `CommandCard.add_row_widget()` 包成独立容器再 `setVisible`：裸 `add_row()` 返回的是 `QHBoxLayout`，只隐藏 `gifCheck` 会留下一条空行的间距。`show_loading()` / `clear()` 里一并隐藏，不继承上一个包的状态。

### 2. 内容数量：懒加载 + 缓存（`content_meta.py`）

队列项大多不带明细——`all_packages()` 只返回包元信息（`emote` 为空元组），收藏集搜索只给 summary。要显示「多少图片 / 多少视频」必须再调一次详情接口，所以结构完全对照 `thumb.py`：

- **`cached(item)`**：缓存命中 → 能同步推导就同步推导（详情页加入的完整 `EmotePackage` 自带 `emote`，零请求）→ 否则 `None`。
- **`request(item)`**：只在卡片**可见**时调（`QueueList._update_visible` 覆写），走独立 `QThreadPool(2)`——不占 `task_manager` 那 4 个线程，免得和真正的下载抢。
- worker 只发 `signal_bus.contentMetaRaw(key, meta)`，主线程槽写完缓存再广播 `contentMetaLoaded`。**载荷 `None` 表示取不到**，省掉一对 failed 信号。
- **失败不写缓存，记进 `_failed` 集合，本会话不再重试**——否则每次滚动经过都会重发请求。
- 数量口径与建下载任务的逻辑严格一致：表情包数「有 `gif_url or url` 的 emote」，收藏集数「有 `card_img_download` 的项」+「有 `video_list` 的项」（视频每项只下第一个），显示的数字就是会落盘的文件数。
- 详情页顺手喂缓存：`PackageDetailView.set_package` / `DressPage._show_detail` 各调一次 `remember()`，进过详情的项在队列页零请求。

> **`set_enabled(False)`**：屏幕外断言脚本必须关掉，否则假 ID 会排一堆 15s 超时请求，脚本跑完卡着退不出去（`check_pages_layout.py` / `screenshot_pages.py` / `check_download_improvements.py` 开头都关了）。

`QueueCard` 多一行 `contentLabel`，四态：`内容: 24 张图片` / `内容: 12 张图片 · 3 个视频` / `内容读取中…` / `内容数量未知`。`QueueList._min_cell` 高度随之 `112 → 128`（名称换两行时也放得下）。

### 3. 全部成功自动移出队列

```python
ItemOutcome(total, failed).all_ok  # total > 0 且 failed == 0
BatchReport(DownloadBatchResult)   # 多一个 per_item: {item_key: ItemOutcome}
```

三个决定：

- **SKIPPED 算成功**。下载器对已存在的文件返回 SKIPPED 不重下，文件确实在本地，视为完成。
- **`total == 0` 不算成功**。取详情失败、或该项压根没有可下文件时，「全部成功」不能靠空集合真空成立。
- **只在下载队列页的批量下载触发**。详情页可以只下「静态图片」或只下「动态视频」，半程移除会丢内容。

归属用 **`result.target.parent`**（建任务时记 `owners[folder] = item_key`），不是「结果下标对齐任务下标」：`Downloader._resolve_target` 只可能改后缀、绝不动父目录，父目录是稳定归属键；下标对齐则依赖上游 `download_many` 的返回顺序，上游一改就静默错位。取详情失败合成的结果落在 `dest` 根下，不属于任何目录，另行写 `ItemOutcome(1, 1)`。

`BatchReport` **继承** biliemoji 的 frozen `DownloadBatchResult`（父类两个字段无默认值，子类新字段带默认值，合法），`ok/failed/skipped/results` 全部保留，`start_download` 与两个详情页调用点一行都不用改。结果送到页面靠 `start_download(on_result=...)`——现有 `on_finished` 无参、拿不到结果。

> 已知边界：同一批里两个**同名**收藏集会共用下载目录，`owners` 里后者覆盖前者，前者不会被自动移除（保守失败，留在队列，不会误删）。

### 4. 缩略图加载环

组件库的 `IndeterminateProgressRing`（自带 `themeColor()` 取色，不用自己适配主题），28px + `strokeWidth=3`，`WA_TransparentForMouseEvents` 让点击穿透到图片按钮。逻辑收在 `_SpinnerMixin`（纯 object mixin，不继承 QObject，避免多重继承的元类纠缠），五个卡片各自在 `__init__` / `resizeEvent` / `set_pixmap` 里调三个方法。

收环的三条路径缺一不可：

1. `set_pixmap()` —— 正常到位；
2. `_CardGridBase` 连 `signal_bus.thumbRawFailed` → 派发 `thumb_done()` —— 下载失败别一直转；
3. `set_cards()` 里 **`url` 为空的卡片建完即收环** —— 压根不会发请求，否则永久空转。

> **坑**：`_center_spinner` 的早退判据必须用 `isHidden()` 而不是 `not isVisible()`。卡片尚未 `show()` 时子控件 `isVisible()` 恒为 False，用它会把建卡阶段的定位全部跳过，之后没有 resize 就再也不居中了（加载环卡在左上角 (0,0)）。

### 5. 收藏集去重键：`item_id` 不是唯一键（Bug 5 根因）

实测 `x/garb/v2/mall/home/search` 的返回：

```
name                      item_id   dlc_act_id   dlc_lottery_id
2233的MBTI-能量之源       112667    112667       112709
2233的MBTI-ENFP           112667    112667       113521      ← item_id 相同
2233的元素协议-侵蚀       107722    107722       107723
2233的元素协议-寻迹       107722    107722       108795      ← item_id 相同
```

**`item_id == properties.dlc_act_id`**：一个 dlc 活动下有多期 lottery，每期都是独立的可下载收藏集。旧 `item_key` 用 `raw["item_id"]` 去重，于是同活动的不同期被判成同一项——`add_many` 悄悄丢掉后面几期，而详情页 `contains()` 命中同一个键，显示「已加入」，和列表对不上。

改为 **`("coll", f"dlc:{act_id}:{lottery_id}")`**，正是 `certain_lottery_typed` / 下载用的那一对 id。非收藏集的装扮（`type='ip'`，无 dlc id）退回 `item:{item_id}` / `id:{id}` / `name:{name}`，**各自带前缀**防跨方案撞车（`item_id` 字符串 "5" 与 `id` 数字 5）。

> 键只活在内存队列里（会话级），改键无迁移成本。但**别在别处硬编码键字面量**——`scripts/check_improvements.py` 原来写死 `("coll", "999")`，已改成 `item_key(summary)`。

## 四、验证

```bash
uv run ruff check .
uv run python -c "import app.MainWindow"
QT_QPA_PLATFORM=offscreen uv run python scripts/check_download_improvements.py   # 本批 26 条
QT_QPA_PLATFORM=offscreen uv run python scripts/check_improvements.py            # 回归
QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py            # 回归
QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py              # 回归
```

`check_download_improvements.py` 五组断言：GIF 行四态、内容数量四态 + 广播回填、`_collect_outcomes` 归属与 `all_ok` 语义 + `DownloadPage._on_batch_result` 真的移除、加载环三条收环路径 + 居中、同活动不同期不被误去重。

真实网络链路（真下载后队列收敛、真实数量读取、真实缩略图加载环）需人工跑 `uv run python main.py` 验证。
