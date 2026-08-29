# 主页（欢迎页）

## 一、背景

应用启动落在**表情包页的「按 ID 查询」标签**：没有 ID 就没有任何内容，整页是空的。
第一眼既不好看，也没有回答「这个应用能做什么、我该从哪一步开始」。

于是在侧栏最上方（表情包之上）新增 **主页**，作为启动默认页。四个设计决定：

| 决定 | 选择 | 理由 |
|---|---|---|
| 版式 | 英雄卡 + 三张带图功能卡 + 快速上手 / 关于 / 最近搜索 | 信息密度与引导性最好 |
| 展示图 | 一次性抓好裁好存进 `static/showcase/` 并入库 | **主页零网络请求**，离线可用、无 Cookie 依赖、断言脚本可直接跑 |
| 组件 | 全部取自 qfluentwidgets | 主题切换自动跟随，不写自定义 QSS |
| 导航 | 主页只发信号，`MainWindow` 负责 `switchTo` | 主页不反向引用主窗口 |

## 二、新增 / 修改文件

| 文件 | 内容 |
|---|---|
| `app/view/home_page.py` | 新增。页面主体与五个私有卡片类 |
| `app/common/resource.py` | 加 `SHOWCASE_DIR` / `showcase_images()` / `showcase_names()` 与两个依赖徽标路径 |
| `app/components/download_queue.py` | 加 `item_cover_url(item)`，与队列卡共用取图口径 |
| `app/components/widgets.py` | `QueueList._cover_url` 改为复用 `item_cover_url` |
| `app/MainWindow.py` | 主页放第一位 + `_navigate` / `_search_from_home` 接线 |
| `app/view/emoji_page.py` | 加 `query_package_id()` / `filter_packages()` 公开入口 |
| `app/view/dress_page.py` | 加 `search_keyword()` 公开入口 |
| `scripts/fetch_showcase.py` | 新增。一次性抓取展示图（不是运行时代码） |
| `scripts/check_home_page.py` | 新增。屏幕外断言 |
| `static/showcase/` | 新增素材（8 张表情 + 6 张收藏集封面 + `manifest.json`，共约 250 KB） |

## 三、版式与模块

```
主��                                     ← page_title + title_row（36px 页边距，与其余四页一致）
┌───────────────────────────────────────┐
│ [logo] BiliEmojiDD  v0.1.0  [开始使用] │  _HeroCard
│ 一句话简介          [打开下载文件夹]     │  · 主按钮随 Cookie 状态变文案与去向
│ ● Cookie 已配置 · 队列 3 项            │  · 下载目录单独一行且 wordWrap
└───────────────────────────────────────┘
┌─────────┐ ┌─────────┐ ┌─────────┐        _FeatureCard ×3，响应式 3 / 2 / 1 列
│ 表情包   │ │ 收藏集   │ │ 下载     │
│ ▣▣▣▣    │ │ ▮▮▮▮    │ │ 队列封面 │      ← 前两张读 static/showcase，第三张实时读队列
│   进入 → │ │   进入 → │ │   进入 → │
└─────────┘ └─────────┘ └─────────┘
┌────────────┐ ┌────────────────┐          SectionCard，宽窗两列 / 窄窗一列
│ 快速上手 3 步│ │ 关于（含依赖徽标）│
└────────────┘ └────────────────┘
┌───────────────────────────────────────┐  _RecentSearchCard，无记录时整卡隐藏
│ (2233) (小电视) (53) …                 │
└───────────────────────────────────────┘
```

用到的组件一律来自组件库：`SimpleCardWidget` / `CardWidget` / `HeaderCardWidget`（经
`SectionCard`）/ `ScrollArea` / `FlowLayout` / `ImageLabel` / `IconWidget` /
`PillPushButton` / `PrimaryPushButton` / `TransparentPushButton` / `HyperlinkButton` /
`TitleLabel` `SubtitleLabel` `StrongBodyLabel` `BodyLabel` `CaptionLabel`。
原生 Qt 只出现在布局容器（`QWidget` + `QVBoxLayout` / `QHBoxLayout` / `QGridLayout`），
与其余四页的写法一致。

### 队列预览（`_QueuePreviewStrip`）

下载卡实时显示队列**前 4 项**封面（不足 4 项就少显示几个，多出来的显示 `+N`），
走和卡片网格同一套 `thumb_manager` + `signal_bus.thumbLoaded`。
取图口径统一在 `download_queue.item_cover_url()`，`QueueList` 也改为复用它，
保证主页预览与下载页队列卡显示同一张图。

### 最近搜索（`_RecentSearchCard`）

直接 new `SearchHistory("dress" / "emoji_id" / "emoji_filter")` 读记录（该类不依赖浮层面板），
合并成胶囊。点击发 `searchRequested(namespace, keyword)`，由 `MainWindow` 路由到对应页
并调用新加的公开入口执行搜索。

## 四、静态素材

```
static/showcase/
  emoji/01.png … 08.png        正方形居中裁剪，128px，保留透明通道
  collection/01.jpg … 06.jpg   3:4 居中裁剪，宽 144，JPEG q85
  manifest.json                {"emoji":[{file,name,package_id}], "collection":[{file,name}]}
static/qfluentwidget.png       「关于」卡的依赖徽标
static/qtforpython.png
```

`scripts/fetch_showcase.py` 生成，只在需要更新素材时手工跑一次：

```bash
uv run python scripts/fetch_showcase.py            # 默认：全量表情包前 8 个 + 搜「2233」
uv run python scripts/fetch_showcase.py --dry-run  # 只打印要抓什么
uv run python scripts/fetch_showcase.py --keyword 小电视 --emoji-ids 53 105
```

取数全部复用现成入口（`api_cache.emoji_package` / `api_cache.search_dress` /
`Emoji.all_packages`），字节走 `BiliClient.get_bytes`（同 `thumb.py`）。
`showcase_images()` 在目录缺失时返回 `[]`，主页据此隐藏整条缩略图带——**素材没入库也能正常跑**。

## 五、踩坑

### 1. `ImageLabel` 每帧都在做平滑缩放（性能）

`ImageLabel.paintEvent` 里是：

```python
image = self.image.scaled(self.size() * self.devicePixelRatioF(),
                          Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
```

**每一次重绘都要平滑缩放一遍源图**。主页一屏十几张图，叠上卡片 hover 动画与滚动重绘，
实测整页重绘 ~20ms/帧（60fps 的预算是 16.6ms）。其他页面的卡片走 `QPushButton.setIcon`，
缩放只做一次，所以没有这个问题。

修法见 `_fit_image()`：把图**预先缩放到恰好 `逻辑尺寸 × dpr`** 再交给 `ImageLabel`，
之后把控件 `setFixedSize` 回逻辑尺寸。`QImage::scaled` 在目标尺寸与自身相同时
`return *this`（隐式共享、零像素开销），于是 paintEvent 里那次缩放变成恒等操作。
与 `image_viewer._letterbox` 让 delegate 的 `scaled` 成为恒等变换是同一招。

非方图要先裁到目标比例（`_cover_square` / 抓取脚本），否则尺寸对不上，缩放照样每帧发生。

### 2. `FlowLayout` 的 sizeHint 只有一行高 → 胶囊重叠

`FlowLayout.sizeHint()` 直接返回 `minimumSize()`，而 `minimumSize()` 是**最大单项的尺寸**，
与实际换了几行无关。把它的容器塞进卡片布局，卡片只会分配一行的高度，
第二行往后的胶囊全部溢出、压在下方内容上（最近搜索一度就是这样重叠的）。

`search_history.py` 的浮层面板没暴露这个问题，是因为它**不进任何布局**、
自己 `setGeometry` 并显式调 `heightForWidth`。

修法是 `_FlowHolder`：容器覆写 `hasHeightForWidth()` / `heightForWidth()` / `sizeHint()`，
并把 size policy 的 `setHeightForWidth(True)` 打开，父布局才会按当前宽度问出真实高度。
`refresh_geometry()` 里**行数没变就不 `updateGeometry()`**，避免 resize → updateGeometry →
resize 自激。

### 3. 定尺寸子项会把整张卡的最小宽度顶起来

展示图是 8 张固定 52px 的 `ImageLabel`，`QHBoxLayout` 默认会把「全部排一行」的宽度
（8×52 + 7×6 = 458px）回写成容器的最小宽度，再往上顶成功能卡的最小宽度——
窄窗口下卡片被**裁掉**而不是缩小。

修法：`layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)` 让布局不再回写
控件最小尺寸，放不下的图交给 `_ShowcaseStrip._fit()` 隐藏。

### 4. 响应式改成离散列数切换

功能卡与底部两卡的列数在 `resizeEvent → _reflow()` 里算，**列数没变直接 return**。
这是离散的重排，不是「在 resizeEvent 里写几何约束做按比例自适应」——后者在拖拽窗口时
每帧要跑好几轮「改约束 → 重排 → 又一次 resize」（视频播放器踩过，见 `collection_video.md`）。
展示图的 `_fit()` 同理，只做 `setVisible` 增减。

### 5. `SmoothScroll.duration` 必须让步数为整数（**踩过，已放弃调整**）

主页内容只比视口高一点点（实测常见窗口下可滚范围 0～300px），
上游一次滚轮把位移摊成 400ms / 24 帧，范围小的时候前几帧就撞到底、剩下时间空转，
主观上是「粘滞感」。曾试图把本页的 `SmoothScroll.duration` 调到 160ms，**结果更糟**：

```python
self.stepsTotal = self.fps * self.duration / 1000     # 60 * 160/1000 = 9.6 ← 非整数
...
while self.stepsLeftQueue and self.stepsLeftQueue[0][1] == 0:   # 精确等于 0 才出队
```

`stepsLeft` 从 9.6 每 tick 减 1 → 9.6, 8.6 … 0.6, **-0.4, -1.4 …永远等不到 0**，
任务出不了队、定时器永不停止；而 `__subDelta` 的 `(m - x)` 在 `stepsLeft` 转负后变成负数
→ **每帧往回滚，页面被一直往上拽、根本滚不到底**。上游默认 400ms 恰好是 24.0 步才没暴露。

结论：**要改就只能取 `1000/fps` 的整数倍**（fps=60 → 200 / 250 / 300ms）。
当前版本已把这段调整整个撤掉，保持上游默认行为——手感与其他页面一致，也不冒这个险。

### 6. 其他

- `CardWidget.clicked` 是**无参**信号（`Signal()`），整卡可点用它即可，不必自造。
- 页面里的 `QScrollArea` 必须显式透明，否则暗色下露出 palette 的 Base 色块（同设置页）。
- `HeaderCardWidget.viewLayout` 是 `QHBoxLayout`，多行内容要先包一个容器再 `add_widget()`。
- `FluentWindowBase.addSubInterface` 在 `stackedWidget.count() == 1` 时自动
  `setCurrentItem` + `setDefaultRouteKey`，所以**主页放第一位就是启动页**，无需额外 `switchTo`。
- 抓取脚本要过滤非 http 的 `emote.url`：纯颜文字包（如 #4）的 `url` 字段是颜文字本身。

## 六、验证

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_home_page.py
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py   # 生成 home_page_{light,dark}.png
```

`check_home_page.py` 覆盖：版式与页边距、三张功能卡的点击路由、英雄卡随 Cookie/队列刷新、
队列预览张数与 `+N`、展示图能读出来 + 素材缺失时的降级、最近搜索胶囊与跳转载荷、
响应式列数 3/2/1 与整页最小宽度、**滚轮能滚到底并停住**、目标页公开入口（用 monkeypatch
拦掉 `run_task`，脚本不联网）、主题切换存活。

真实 B 站网络流程（抓取素材）依赖 Cookie，需人工跑 `scripts/fetch_showcase.py`。
