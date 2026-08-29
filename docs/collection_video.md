# 收藏集视频预览

收藏集详情页的「动态视频」标签页：内嵌播放器 + 缩略图选择条，视频先下到会话临时目录再播本地文件。

## 背景

B 站收藏集（`dlc_act`）的每张卡都有两份内容：静态图 `card_info.card_img_download` 与动态视频
`card_info.video_list`。改造前详情页只把视频做成一个**折叠文字列表**（`videoToggle` + `videoList`），
列出 `▶ 名称` 但点了没反应——收藏集的卖点恰恰是动态卡，"只能下载不能预览"是这一页最大的缺口。

| 改造前 | 改造后 |
|---|---|
| 图片网格 + 视频折叠文字列表（不可播放） | `内容预览` 卡头挂 `Pivot`：`静态图片 N` / `动态视频 M` |
| 视频只能下载后用外部播放器看 | 切到视频页即播：左播放器 + 右视频网格，点封面切换 |
| — | 控制条移到画面下方，上一个 / 下一个 / 全屏 |
| 无视频时整张视频卡隐藏 | 无视频时视频 tab 禁用，强制停在图片页 |

## 涉及文件

| 文件 | 作用 |
|---|---|
| `app/components/video_cache.py`（新） | 视频会话级本地缓存：后台下到临时目录 + 失败不重试 + 退出清理 |
| `app/components/video_player.py`（新） | `CollectionVideoPlayer`（播放器 + 覆盖层 + 控制条改造）、`VideoLightbox`（全屏遮罩） |
| `app/components/widgets.py` | `VideoCard`（`DetailCard` + 播放角标 + 高亮）、`VideoStrip`（右侧多栏视频网格） |
| `app/components/page_scaffold.py` | `SectionCard.add_header_widget()`：把 Pivot 挂到卡头右侧 |
| `app/view/dress_page.py` | 详情页内容区改成 `Pivot` + `QStackedWidget`，删掉折叠视频列表 |
| `app/common/signal_bus.py` | 新增 `videoRawReady` / `videoReady` |
| `app/MainWindow.py` | `closeEvent` 里 `video_cache.cleanup()` |
| `scripts/check_video_tab.py`（新） | 视频页屏幕外断言 |

## 一、版式：左播放器 + 右视频网格

```
┌ 内容预览                          [ 静态图片 12 ][ 动态视频 5 ] ┐
│ ┌──────────┐  ┌─────┐┌─────┐┌─────┐┌─────┐                │
│ │          │  │ ▶   ││ ▶   ││ ▶   ││ ▶   │                │
│ │ 竖屏画面  │  │封面1 ││封面2 ││封面3 ││封面4 │  ← VideoStrip │
│ │          │  └─────┘└─────┘└─────┘└─────┘                │
│ └──────────┘  ┌─────┐                                     │
│ ┌──────────┐  │ ▶   │                                     │
│ │🔊 ◀ ▶ ▶  ⤢│  │封面5 │                                     │
│ └──────────┘  └─────┘                                     │
└───────────────────────────────────────────────────────────┘
```

图片页保持原样（`DressDetailGrid` + 点击开 lightbox）。视频页是**内嵌播放器**而不是
"卡片网格 → 点击弹全屏播放器"，两个理由：

1. **零额外点击**。视频是这个 tab 的主体内容，进来就该看到。
2. 全屏另有入口（控制条上的 ⤢ 按钮），不必强制走全屏才能看。

三条尺寸规则，都是围绕「收藏集动态卡是**竖屏**的」这一点：

- **左右按 1:2 静态分配**（`_PLAYER_STRETCH` / `_STRIP_STRETCH`）。竖屏画面用不了太多
  宽度，播放器只拿三分之一，剩下的全给右侧网格。
- **绝对不要在 `resizeEvent` 里按画面比例写播放器宽度**。曾经这么干过
  （`_apply_aspect` + `setMaximumWidth`），离屏断言里几何是收敛的，但**交互式拖拽窗口时
  每帧会跑好几轮**「改宽 → 重新布局 → 又一次 resize → `fitInView` + 整条选择条
  `setGridSize` 重排」，实测表现为画面畸形 + 明显卡顿。现在播放器没有任何宽度约束，
  `CollectionVideoPlayer.resizeEvent` 也只在覆盖层可见时才动几何。
- **`aspect_ratio()` 只在全屏遮罩打开的那一刻用一次**（算容器尺寸），不参与内嵌布局。

Pivot 用法与 `emoji_page.py` 一致：`addItem(routeKey=..., onClick=...)`，
**`setCurrentItem` 不会触发 `onClick`**，所以初始化时切页与切 Pivot 两句都要写。
反过来，`_show_image_tab` / `_show_video_tab` 里也要主动 `setCurrentItem`——这两个槽
除了被点击触发，还会被换收藏集、断言脚本程序化调用，只有走点击时 Pivot 才会自己移动指示条。

## 二、取流：先下到临时目录，再播本地文件

**不用** `QMediaPlayer.setSource(QUrl(远程地址))` 流式播放。`QMediaPlayer` 在 Windows 上走
Media Foundation 自己的网络栈：

- 它读 **Windows 系统代理**，应用内「设置 → 代理」对它完全无效。结果是下载能用、播放却失败，
  且没有任何线索。项目的既定约束是"所有 `Emoji/Dress/Downloader` 显式传 `proxies=`"。
- 无法自定义 UA（`biliemoji` 的 `Downloader` 带 Chrome UA），B 站 CDN 若校验 UA 会直接 403。

改为复用 `biliemoji.Downloader.download(DownloadTask(...))` 单文件同步下载，白拿重试、
`.part` 原子落盘和 `_is_mp4` 魔数校验。收藏集动态卡通常 1~3MB，首次点开约 1 秒，期间转加载环。

`video_cache.py` 的结构与 `content_meta.py` / `thumb.py` 完全一致：

- 独立 `QThreadPool(2)`，不占 `task_manager` 的 4 个线程；
- worker 只下载，经常驻的 `signal_bus` 发 `videoRawReady`；主线程槽写缓存后再广播
  `videoReady`（载荷 None = 取不到）；
- `_failed` 记失败，本会话不重试，防请求风暴；
- 临时目录是 `tempfile.mkdtemp(prefix="biliEmojiDD-video-")`，`cleanup()` 在
  `MainWindow.closeEvent` 里 `shutil.rmtree(ignore_errors=True)`——播放中的文件在 Windows 上
  可能仍被占用，删不掉就交给系统临时清理。

### 已下载过的收藏集：零等待

`_adopt_downloaded_videos()` 按 `collection_download_dir(summary) / f"{sanitize_filename(name)}.mp4"`
探本地文件（与 `download_collection_batch` 建任务的命名完全一致），命中就
`video_cache.remember(url, path)`。同时认 summary 名与 `coll.name` 两个目录，
与 `_refresh_downloaded` 的兼容逻辑一致（见 `docs/theme_grid_fixes.md` 收藏集目录命名那节）。

### 晚到信号必须校验 URL

`play(index)` 未命中缓存时记 `self._pending_url = url` 再 `request`；
`signal_bus.videoReady` 的槽里**必须 `if url != self._pending_url: return`**。
用户可能在缓冲期间点了别的缩略图，晚到的信号不能顶掉当前画面。

## 三、上游坑：`VideoWidget` 必须配纯黑背景，否则视频反色

`qfluentwidgets/multimedia/video_widget.py` 里：

```python
class GraphicsVideoItem(QGraphicsVideoItem):
    def paint(self, painter, option, widget):
        painter.setCompositionMode(QPainter.CompositionMode_Difference)
        super().paint(painter, option, widget)
```

`CompositionMode_Difference` 是 `|src - dst|`。**只有背景是纯黑（dst = 0）时才是恒等变换**。
而实测两个主题下：

```
Theme.LIGHT | backgroundBrush style = NoBrush | qss = QGraphicsView { background: transparent; }
Theme.DARK  | backgroundBrush style = NoBrush | qss = QGraphicsView { background: transparent; }
```

背景透明 → 透出的是卡片底色，亮色主题下近白 → **整段视频反色**。

修法是 `_VideoView` 子类里 `setBackgroundBrush(QColor(0, 0, 0))`。用
`backgroundBrush`（`QGraphicsView` 属性）而**不是 `setStyleSheet`**：`VideoWidget` 构造里
`FluentStyleSheet.MEDIA_PLAYER.apply(self)` 已把自己注册进 `styleSheetManager`，
每次 `setTheme` 都会 `updateStyleSheet` 重刷 QSS，把自定义样式表冲掉。

`scripts/check_video_tab.py` 第 6 节对两个主题都断言了 `SolidPattern` + `(0,0,0)`，
防止有人"顺手改回去"。

## 四、控制条改造：上一个 / 下一个 / 全屏

上游 `StandardMediaPlayBar` 的两个 skip 按钮是「后退 10 秒 / 前进 30 秒」，
而收藏集动态卡都是几秒的循环短片，±10s/30s 毫无意义——播放列表里前后切换才是真需求。
`CollectionVideoPlayer._rebuild_play_bar()` 把它们改掉：

- **必须先 `clicked.disconnect()`**：上游在 `StandardMediaPlayBar.__initWidgets` 里已经
  把它们连到 `skipBack(10000)` / `skipForward(30000)`，不断开就是一次点击跑两件事；
- 图标换成 `CARE_LEFT_SOLID` / `CARE_RIGHT_SOLID`（原来的 `SKIP_BACK/FORWARD` svg 上
  画着「10」「30」字样），接到 `play_prev` / `play_next`；
- **首尾禁用**（`_sync_nav_buttons`，在 `play()` 与 `set_videos()` 里同步）。槽本身也做
  边界判断，越界就直接 return，不抛异常；列表为空时连全屏按钮一起禁掉。
- 全屏按钮塞进 `bar.rightButtonLayout`（`StandardMediaPlayBar` 的右侧容器本来是空的）。
  注意它的 `parent()` 是 `rightButtonContainer` 而不是 `bar`。

### 控制条从画面里挪出来

上游把 `playBar` 绝对定位在画面底部、按 hover 淡入淡出——竖屏视频下正好压住内容。
`_VideoView` 覆写三个方法把它解绑：

- `resizeEvent` 直接调**祖父类** `QGraphicsView.resizeEvent`，只保留画面自适应，
  跳过上游那两行 `playBar.move(...)` / `playBar.setFixedSize(...)`；
- `enterEvent` / `leaveEvent` 同样调祖父类，不再 `fadeIn` / 起定时器 `fadeOut`。

然后 `CollectionVideoPlayer` 把 `self.view.playBar` 直接 `addWidget` 到自己的竖直布局里，
排在画面下方常显。`VideoWidget.play/pause/player` 都是转发到同一个 `playBar` 对象，
搬家后照常工作。

## 五、全屏：把播放器搬进遮罩，而不是新建一个

`VideoLightbox`（`MaskDialogBase` 子类，遮罩坑与 `image_viewer.py` 同源，改前先读
`docs/image_viewer.md`）**复用现有的播放器实例**：记下它在原布局里的下标与 stretch，
`addWidget` 搬进遮罩容器，关闭时 `insertWidget` 原样搬回。

不新建播放器的原因：那会多一个 `QMediaPlayer` / `QAudioOutput`，声音重叠、进度还从头开始。

三个必须处理的细节：

- **搬家会触发 `VideoWidget.hideEvent` 里的 `pause()`**。所以搬之前记 `is_playing()`，
  搬完 `resume()`（`pause` 不重置进度，位置不丢）。
  关闭方向尤其要注意：**`finished` 发出时播放器早就被暂停了**（dialog 先隐藏、才发信号），
  在那里读 `is_playing()` 永远是 False。正确的钩子是覆写 `done()`，在
  `QDialog.done` 之前把状态记下来。
- **跳过上游的淡入淡出**。`MaskDialogBase.showEvent` / `done()` 会给整个 dialog 挂
  `QGraphicsOpacityEffect` 做 200ms / 100ms 动画，而 dialog 里是一路在刷帧的
  `QGraphicsVideoItem`——图形特效会把整棵子树走离屏合成，全屏切换明显卡顿。
  覆写这两个方法直接调 `QDialog` 的实现即可。
- **容器尺寸跟着遮罩走**：`_resize_content()` 在 `resizeEvent` 里按遮罩高度 + 画面比例
  重算。方向是单向的（遮罩尺寸由基类的 `eventFilter` 按外部窗口设定），不会反向影响。

### 播放/暂停图标必须接 `playbackStateChanged`

上游 `MediaPlayBarBase` 只在 `mediaStatusChanged` 时刷 `playButton` 的图标，于是任何
**不经过按钮的暂停**（`hideEvent` 里的自动 pause：切 tab、全屏搬家、切导航页）之后，
按钮都还停在「暂停」图标上，看起来像还在播。`CollectionVideoPlayer` 把
`player.playbackStateChanged` 接到 `_sync_play_button`，一次性覆盖所有路径。

关闭方式与图片查看器一致：Esc、点击遮罩空白处、右上角关闭按钮；方向键切上一个 / 下一个。

## 六、`VideoStrip`：右侧多栏视频网格

复用 `_CardGridBase`（懒加载缩略图 / 主题跟随 / `itemClickedAt` 下标全部白拿），
自己只管尺寸：

- **栏数动态**：`avail // _TARGET_CELL_W`，但只要塞得下就至少两栏（单栏读着累），
  且项目数少于栏数时收敛到项目数——否则 2 个视频挤在左边、右侧空一大片。
- **卡片宽度按栏均分、高度按竖版 3:4 反推**，再按视口高度封顶（1 个视频时不封顶会算出
  比视口还高的卡）。多出来的横向空间由 `DetailCard` 的图片按钮居中吸收，同 `DressDetailGrid`。
- **宽度按 `self.width()` 算，不是 `viewport().width()`**：卡片高度正比于宽度，跟着
  viewport 走会出现「滚动条出现 → 变窄 → 变矮 → 不再需要滚动条 → 变宽」的来回抖动
  （基类把 `verticalScrollBar().rangeChanged` 接到了 `_layout_items`）。索性固定预留
  `_SCROLL_RESERVE` 的滚动条宽度，单元格尺寸与滚动条有无无关。
  `check_video_tab.py` 第 3c 节用「强制开/关滚动条，单元格必须一致」盯着这条。

`VideoCard` 继承 `DetailCard`，加两样：

- 图片区中央的播放角标（`QLabel` + `FluentIcon.PLAY_SOLID.icon(Theme.DARK)` 的白色 pixmap，
  半透明黑圆底）。必须 `WA_TransparentForMouseEvents`，否则吃掉点击。
- `set_active(bool)` 高亮。样式表**必须用类选择器** `VideoCard { ... }` 限定自身——
  无选择器的通用规则会级联到子 label，把文字区整块上色（与 `QueueCard._apply_bg` 同款坑）。

`VideoStrip` 的 `items` 是 `(name, 封面 url)`，**视频地址由页面按下标持有**
（`DressPage._detail_videos`）。两个列表在 `_show_detail` 里同一次循环构建，下标一一对应；
点击走 `itemClickedAt` 的下标闭包，不靠载荷身份反查（内容相同的元组字面量会被 CPython
常量折叠成同一个对象，见 `docs/development.md`）。

## 七、播放状态的生命周期

| 时机 | 动作 |
|---|---|
| 进入新收藏集详情 / `_show_detail` | `_reset_video_tab()`：停播 + 清空两个列表 + 回到图片页 |
| 切到「静态图片」页 | `videoPlayer.release()`——停播并 `setSource(QUrl())` 释放文件句柄 |
| 切到「动态视频」页 | 仅当 `is_idle()`（没在播也没在缓冲）时加载 `max(0, current_index())` |
| 进 / 出全屏 | 覆写 `done()` 在隐藏前记 `is_playing()`，搬回后 `resume()` |
| 返回搜索页 `_go_back` | `videoPlayer.release()` |
| 关闭窗口 | `video_cache.cleanup()` 删临时目录 |

`is_idle()` 这个判据让"离开再回来"续播上次选中的那个，而"正在播时再点一次 tab"不会重头来。

**视频每项只取 `video_list[0]`**——与 `download_collection_batch` 建下载任务、
`content_meta.collection_meta` 计数的口径严格一致，页面上显示的视频数就是会落盘的文件数。

## 八、验证

```bash
QT_QPA_PLATFORM=offscreen uv run python scripts/check_video_tab.py      # 视频页
QT_QPA_PLATFORM=offscreen uv run python scripts/check_pages_layout.py   # 三页版式回归
QT_QPA_PLATFORM=offscreen uv run python scripts/screenshot_pages.py     # 亮/暗截图
```

`check_video_tab.py` 断言 10 组：Pivot 结构与数量文字、左右版式与播放器宽度收敛、
控制条在画面下方且不重叠、上一个/下一个的首尾禁用与越界不报错、全屏搬进搬回后版式复原、
选择条点击与高亮同步、离开再回来的续播、单元格与滚动条无关、无视频的 tab 禁用、
已下载文件被登记进缓存、两个主题下的黑背景、窄窗口不越界。

**屏幕外脚本必须 `video_cache.set_enabled(False)`**（与 `content_meta.set_enabled(False)` 同理），
否则假 URL 会排一堆 15s 超时的下载任务，脚本跑完退不出去。
等 `MaskDialogBase` 关闭要**轮询真实时间**（`done()` 是 100ms 淡出动画，动画结束才发
`finished` → 才会把播放器搬回来），光 `processEvents()` 不推进时间。

真实播放（能播、不反色、切换不串播、全屏正常、代理生效）依赖 Cookie 与真实网络，需人工验证。
