# 详情页图片查看器（新增功能说明）

本次改动为两个详情页新增「点击图片全屏查看」能力：窗口内遮罩 lightbox + 左右翻页。本文记录改动内容、关键实现与踩坑点，便于后续维护。

## 一、背景

两个详情页都只能看缩略图，无法查看原图：

- **收藏集详情**（`DressDetailGrid`）：卡面图挤在动态网格里，`DetailCard` 早已声明 `clicked = Signal(object)`，但 `imageBtn.clicked` **从未接线**，是个半成品。
- **表情包详情**（`EmojiGrid`）：`EmojiCard` 是 72×72 图标，完全没有点击信号。

需求：点击任意图片 → 弹出遮罩层居中大图，可用左右箭头 / 方向键 / 滚轮切换上下张，Esc 或点击遮罩空白处关闭。

**关键决策：不自研轮播组件。** qfluentwidgets 1.5.1 已内置所需的全部零件：

| 需求 | 复用的现成组件 |
|---|---|
| 轮播 + 悬浮左右翻页按钮 + 滚轮 + 平滑滚动动画 | `HorizontalFlipView`（`components/widgets/flip_view.py`） |
| 窗口内半透明遮罩层（随主窗口缩放） | `MaskDialogBase`（`components/dialog_box/mask_dialog_base.py`） |
| 页码点 | `HorizontalPipsPager`（`components/widgets/pips_pager.py`） |
| 图片加载 + 缓存 + 后台线程 | 项目已有的 `thumb_manager` + `signal_bus.thumbLoaded` |

详情页给出的 URL（收藏集 `item.card_img_download`、表情 `em.gif_url or em.url`）**本身就是原图地址**，全尺寸 `QPixmap` 已由 `thumb_manager` 缓存在 `QPixmapCache` —— 查看器命中缓存即刻显示，未命中自动走后台线程池，**零新增网络代码**。

## 二、新增 / 修改文件

| 文件 | 说明 |
|---|---|
| `app/components/image_viewer.py`（新） | 遮罩图片查看器，唯一入口 `show_image_viewer(items, index, parent)` |
| `app/components/widgets.py` | `EmojiCard`/`EmojiGrid` 新增点击信号与 `items()`；`DetailCard` 补上缺失接线；`_CardGridBase` 新增 `_items` 与 `itemClickedAt(int, object)` |
| `app/view/dress_page.py` | 保存 `_detail_items`，接 `detailGrid.imageClicked` → `_open_image_viewer` |
| `app/components/package_detail.py` | 接 `grid.imageClicked` → `_open_image_viewer` |
| `scripts/check_image_viewer.py`（新） | 屏幕外验证：letterbox 尺寸、翻页、UI 同步、点遮罩关闭 |
| `scripts/check_grid_click.py`（新） | 屏幕外验证：两个网格的点击 → 索引接线，及其余网格未被改坏 |

## 三、功能与实现要点

### 1. 对外接口

```python
show_image_viewer(items, index, parent) -> None
# items: [(name, url), ...]；index: 初始显示下标；parent: 传 page.window()
```

两个详情页的调用路径完全同构：

```
EmojiGrid.imageClicked(int)      ┐
                                 ├→ 页面槽 → show_image_viewer(items, index, self.window())
DressDetailGrid.imageClicked(int)┘
```

`parent` 必须传 `page.window()`（主窗口）：`MaskDialogBase.__init__` 内部读 `parent.width()`，遮罩要铺满整个窗口。

### 2. 索引传递：不能靠载荷身份反查

最初的实现是 `index_of(item)` 用 `is` 在 `_items` 里反查下标。**这是错的**：`(name, url)` 这类内容相同的元组字面量会被 CPython **常量折叠成同一个对象**，重复卡面点击时索引串位（实测得到 `[0, 1, 1]` 而非 `[0, 1, 2]`）。

改为建卡时用闭包固定下标：

```python
# _CardGridBase.set_cards
card.clicked.connect(partial(self._emit_clicked, index))

def _emit_clicked(self, index: int, it) -> None:
    self.itemClicked.emit(it)          # 旧信号，其余网格继续用
    self.itemClickedAt.emit(index, it) # 新信号，附带下标
```

`EmojiGrid` 同理（`EmojiCard.index` 由网格填充）。`itemClicked` 保持原样，所以 `PackageGrid` / `DressGrid` / `QueueList` 的转发不受影响。

### 3. letterbox：让所有 item 尺寸恒等

`_ViewerFlipView` 覆写 `_adjustItemSize` 为固定 `sizeHint = itemSize`，并把图片预先等比缩放、居中合成到 `itemSize * dpr` 的透明画布（`_letterbox`）。

这样 `FlipImageDelegate.paint` 里的 `image.scaled(size * r, ...)` 成为**恒等变换** —— 不拉伸、DPI 正确、居中留白，且图片异步到位时 item 尺寸不变、滚动位置不会跑偏。绕过的两个上游坑见第五节。

小图不过度放大：目标框取「画布尺寸」与「原图尺寸 × `_MAX_UPSCALE`(=2)」的较小者。完全不放大会让一两百像素的表情在 700px 框里显得过小，放大太多则糊。

### 4. 图片加载与预取

- **必须先 `connect` 再 `request`**：`thumb_manager.request()` 命中 `QPixmapCache` 时是**同步 emit**，顺序颠倒会丢图。
- 只预取当前索引 ±`_PREFETCH`(=2)，`currentIndexChanged` 时继续预取邻居。一次性请求几十张会占满缩略图池（仅 3 线程）、拖慢背后网格。
- 未加载时显示 `_placeholder`（极淡的白画布），既提示「图片框」位置，又避开上游的空图除零。
- `finished` 信号里 `disconnect(self._on_thumb)`，避免遗留连接；dialog 设 `WA_DeleteOnClose`。

### 5. 交互

| 操作 | 实现 |
|---|---|
| 左右翻页 | **底部信息行的 `‹` / `›` 按钮** / 滚轮（组件自带）/ 方向键（dialog `keyPressEvent`） |
| 关闭 | Esc（QDialog 默认 reject，`MaskDialogBase.done` 自带淡出）/ 点击遮罩空白处 / **贴在图片框右上角的关闭按钮** |
| 重新加载 | 在图片上右键 →「重新加载」（`_reload_current`，走 `thumb_manager.reload`） |
| 页码 | 名称 + `"3 / 12"` 文字 + `HorizontalPipsPager`（>`_MAX_PIPS`(=15) 张时隐藏点，只留文字） |

`flipView` 与 `pips` 都设 `NoFocus`：FlipView 继承 QListWidget 会吞掉方向键去改 currentRow，pips 同理，方向键要交给 dialog。翻页按钮同样 `NoFocus`。

#### 翻页按钮为什么从图上挪到底部

上游 `FlipView` 自带的 `ScrollButton` 是 **16×38**（`flip_view.py:175`）且被 `resizeEvent`
（`:332`）钉在控件的**最左 / 最右两个极边**。查看器的图片框最宽 900px（`_MAX_W`），
于是两个 16px 宽的小箭头相隔近一屏 —— 又小又远又难找。现在：

- `_ViewerFlipView.__init__` 里 `preButton.hide()` / `nextButton.hide()` 一次性藏死。
  上游的 `enterEvent` / `leaveEvent` 只做 `fadeIn` / `fadeOut`（改 `opacity` 属性），
  **从不调 `show()`**，所以藏一次就不会自己冒出来，不需要再覆写这两个事件。
- 底部信息行改成 `‹  名称  3 / 20  ›`，两个 36×36 的按钮紧挨着页码；
  首尾禁用在 `_sync_ui()` 里跟着索引一起刷（原来那句 `flipView.sync_arrows()` 的位置）。

#### 关闭按钮：跟着图片走 + 固定白图标

原先钉在**整个窗口**右上角（`self.width() - 52, 16`），窗口越大离图片越远；更要命的是
`TransparentToolButton` 的图标**按主题取色**，亮色主题下是黑图标压在纯黑遮罩上，
基本等于隐身 —— 「有时候甚至看不到」就是这么来的。现在：

- `_place_close_button()` 按 `self.widget`（居中内容容器）的几何算位置，贴在图片框右上角外侧，
  并用 `min` / `max` 夹住防止窄窗口下出界。`self.widget` 的几何要等布局跑完才有，
  所以 `resizeEvent` 之外还在 `showEvent` 里补摆一次（构造期那次量到的是 0 尺寸）。
- 翻页与关闭统一用本文件的 `_OverlayToolButton`：`setIcon` 把 `FluentIconBase` 换成
  **白色 svg**（`FluentIcon.CLOSE.icon(color=QColor("white"))`），`paintEvent` 先画一层
  半透明深色圆底再交给上游画图标。这样任何主题、任何图片底色上都看得见。
  它**不覆写 `__init__`**（`ToolButton.__init__` 是 `singledispatchmethod`，见第五节第 9 条），
  尺寸/光标全放在 `_postInit()`。

## 四、修复的既有问题

| 问题 | 表现 | 修复 |
|---|---|---|
| `DetailCard.clicked` 从未接线 | 信号已声明，`imageBtn.clicked` 没连接任何槽，点击卡面无反应 | 接 `_on_image_clicked` + `mousePressEvent`（文字区同样触发）+ 手型光标 |
| 载荷身份反查下标串位 | 内容相同的 `(name, url)` 被常量折叠成同一对象，`is` 反查把两项判成同一下标 | 改用建卡时的闭包下标，新增 `itemClickedAt` |

## 五、踩坑记录（qfluentwidgets 上游坑，**勿"修回去"**）

1. **`FlipView._adjustItemSize` 按图片宽高比算 sizeHint**，两个真实问题：
   - 图片未加载时 `QImage()` 高为 0 → `KeepAspectRatio` 分支 `image.width() * h / image.height()` **ZeroDivisionError**；
   - 图片异步到位后 sizeHint 变化，而 `scrollToIndex` 按前序 item 宽度**累加**算滚动量 → 已显示的图**跑偏**。

   → 覆写为固定 sizeHint + 预先 letterbox。
2. **`MaskDialogBase.setMaskColor` 的 B/G 参数写反**（`rgba(red, blue, green, alpha)`）。用纯黑遮罩正好绕过（R=G=B=0），别改成彩色。
3. **`MaskDialogBase` 把 `self.widget` 无对齐地塞进 `_hBoxLayout`** → 铺满整个 dialog，「点击遮罩空白处关闭」永远判不出来。须按 `MessageBoxBase` 的做法 `removeWidget` 后 `addWidget(self.widget, 1, Qt.AlignCenter)` 重新居中。
4. **`PipsPager.setCurrentIndex` 会发 `currentIndexChanged`**（经 `scrollToItem`）。与 FlipView 双向绑定时要么加 guard、要么依赖 `FlipView.setCurrentIndex` 的同值早退；`setPageNumber` 内部也会 `setCurrentIndex(0)` 发一次信号，**接线要放在它之后**。
5. **`FlipView.setCurrentIndex` 在 `index == currentIndex()` 时早退不发信号**，而 `addImages` 已把 `_currentIndex` 置为 0 → 初始索引为 0 时必须**手动同步一次** UI，不能依赖信号。
6. **`FlipView` 的 `ScrollButton` 淡入淡出是 `QPropertyAnimation`**：直接 `setOpacity` 会被正在跑的动画盖掉。本组件已改为 `hide()` 藏死（`fadeIn` / `fadeOut` 不调 `show()`，藏了就不会自己回来），翻页移到底部信息行。
7. **`closeBtn` 在基类 `setGeometry` 之后创建**，之后未必再触发 `resizeEvent` → 须在 `__init__` 主动摆一次位置；它现在还依赖 `self.widget` 的布局结果，所以 `showEvent` 里要再摆一次。
8. **`FlowLayout.itemAt(i)` 返回 `QWidgetItem`**（要 `.widget()`），而 `takeAt(i)` 直接返回 widget —— 两者不一致，写测试时容易踩。
9. **`ToolButton.__init__` 是 `singledispatchmethod`**：`(icon, parent)` 那个重载内部会再调一次 `self.__init__(parent=parent)`，子类覆写 `__init__` 直接 TypeError（同 `PushButton` / `InfoBadge`）。`_OverlayToolButton` 因此只用 `_postInit()` 钩子，图标着色走覆写 `setIcon`。
10. **`TransparentToolButton` 的图标按主题取色**：亮色主题下是黑图标。压在纯黑遮罩上就是隐身，遮罩层上的按钮必须自己钉死颜色。

## 六、已知限制

- **GIF 只显示首帧**。`FlipView` 存的是 `QImage`，`QImage.loadFromData` 只解第一帧；动图需要 `QMovie`，而 `FlipView` 的 delegate 不支持。表情包详情沿用与网格相同的 `em.gif_url or em.url`，观感与网格缩略图一致（网格本来也是首帧静图）。
- 不含缩放 / 拖拽 / 另存，本次只做浏览与翻页。

## 七、验证

- `uv run ruff check .` 通过；`uv run python -c "import app.MainWindow"` 导入自检通过。
- `QT_QPA_PLATFORM=offscreen uv run python scripts/check_image_viewer.py` —— 断言全过，其中关键结论：
  - 三张源图（1600×900 / 600×1400 / 64×64）letterbox 后画布与 `sizeHint` **完全一致**（793×602），证明滚动不会跑偏；
  - `widget` 为 793×650 而 dialog 为 1280×860，证明内容区未铺满遮罩，**点击遮罩关闭确实可用**（第五节第 3 条）；
  - 上游两个贴边小箭头确实藏住了，底部 `‹` / `›` 能驱动 flipView 且首尾自动禁用；
  - 关闭按钮在 1280×860 与 598×520 两种尺寸下都落在图片框右上角且**完全在遮罩内**；
  - pips 双向绑定、方向键、点遮罩关闭、右键重新加载后内存缓存作废均正确。
- `QT_QPA_PLATFORM=offscreen uv run python scripts/check_grid_click.py` —— 11 项断言全过，覆盖：`EmojiGrid` 空 url 过滤后索引对齐、载荷为**同一对象**时 `DressDetailGrid` 仍各自定位、`PackageGrid` / `QueueList` 转发未被基类改动破坏。
- 真实 B 站网络流程依赖用户 Cookie，需人工 `uv run python main.py` 验证：两个详情页点图、翻页、GIF 首帧、窗口缩放后重开、深/浅主题各一次。
