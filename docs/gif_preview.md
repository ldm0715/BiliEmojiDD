# GIF 标识与动图预览

## 问题

GIF 表情包在界面上曾经完全不可辨：

1. 表情包卡片只显示封面**首帧**，是不是动图包必须进详情页看那行「GIF 动图包」文字才知道。
2. 进了详情也还是静图 —— `thumb.py` 走 `QImage.loadFromData` → `QPixmap`，只解首帧；
   图片查看器同理（`_ViewerFlipView` 存的是 `QImage`，`FlipImageDelegate` 不认 `QMovie`）。
   点开大图看到的仍是一张不动的图。

现在：**卡片左下角挂「GIF」角标**，表情详情网格**悬浮即播**，图片查看器**打开即播**。

## 一、两套判定口径，故意不统一

| 用途 | 判据 | 为什么 |
|---|---|---|
| 角标显隐 | 数据字段（`pkg.is_gif` / `em.gif_url`） | 不必等图片下载完，翻页时角标是即时的 |
| 能不能播 | 原始字节（`QMovie.frameCount() > 1`） | 只有真拿到多帧数据才播得起来 |

两者都在 `app/components/gif.py`：

- `package_has_gif(pkg)`：`pkg.is_gif`（即 `meta.label_text` 非空）**或**包内任一 `em.gif_url`。
  取并集是必须的 —— 走 `all_packages()` 的「全部表情包」列表**不含 emote**，只有 `label_text`
  可用；而按 ID 查询回来的包两者都有。这个口径与 `download_package_batch` 里
  `if use_gif and em.gif_url` 的实际取用一致。
- `movie_from_cache(url, parent)`：返回可播的 `QMovie`，不是多帧就返回 `None`。

## 二、原始字节从哪来：`image_cache` 是唯一出口

`thumb.py` 的 worker 拿到字节后解成 `QImage` 就把字节丢了（主线程只拿得到 `QPixmap`）。
但它在未命中时会 `image_cache.put(url, data)` —— **落盘那一层留着原始 GIF 字节**。

所以播放这条路是：

```
image_cache.get(url) → QByteArray → QBuffer → QMovie
```

不需要改线程层、不需要再发一次网络请求，主线程读一个几十 KB 的小文件即可。

字节拿不到（磁盘缓存被 LRU 淘汰而内存 `QPixmapCache` 还在）时一律返回 `None`、静默不播 ——
动图播不了顶多回到原来的静态观感，不值得为它专门补一次下载。

### 坑：`QMovie(None)` 会段错误

PySide6 6.4.2 下 `QMovie(parent)` 传 `None` 会命中 `QMovie(QIODevice*)` 那个重载、拿到一个空
device，之后 `frameCount()` 直接段错误（不是异常，是进程没了）。必须**无参构造再 `setParent`**。

`QBuffer` 挂在 movie 上（不是挂 parent —— parent 可能先销毁，而 `QMovie` 不接管 device 的
生命周期）。字节本身交给 `QBuffer` 自己的内部缓冲，`setData` 是拷贝，不用另外保命。

## 三、角标：小、左下角、跟着图片区走

`widgets.py` 的 `_make_gif_badge()` + `_GifBadgeMixin`，`PackageCard` 与 `EmojiCard` 共用。

**必须 `setFixedSize` 收窄**：上游 qss 给 `InfoBadge` 的 `min-width` 会把「GIF」三个字撑到
50px，压在 80px 见方的表情图上等于横贯大半张图 —— 看着像盖在正中间，还跟加载环叠在一起。
尺寸按 `fontMetrics()` 现算（换字体后仍贴合）。**不能用 `setStyleSheet` 改**：`InfoBadge`
构造时 `FluentStyleSheet.INFO_BADGE.apply(self)` 已注册进 `styleSheetManager`，切主题会重刷冲掉
（与 `page_scaffold._PillBadge`、`VideoWidget` 黑背景同一个坑）。

四角分工（`PackageCard`）：左上勾选框、右上「已下载」、**左下 GIF** —— 三者互不重叠。

**定位不能只靠卡片自己的 `resizeEvent`**：`set_cell()` 是「先 `setFixedSize(卡片)` 再
`setFixedSize(图片区)`」，卡片那次 resize 触发重钉时量到的还是**旧的图片区几何**，之后图片区
变大就没人再钉一次了 —— 角标停在按小图算出来的位置，看着就在图中间。所以 `_GifBadgeMixin`
直接给图片区装事件过滤器，监听它自己的 `Resize`/`Move`。

## 四、items 加第三位

`EmojiGrid.set_emotes` 的载荷从 `(text, url)` 变成 `(text, url, is_gif)`。
两条数据流填第三位的口径**不同源，都别改**：

- 表情详情 / 按 ID：`package_detail.set_package` 按 `bool(em.gif_url)` 填 —— 与它挑
  `url`（`em.gif_url or em.url`）的口径同源，有独立动图地址才算。
- 直播间表情：`emoji_page._LiveEmoteTab` 填 `LiveEmote.is_gif`，那是**纯 URL 后缀白名单**
  `.gif`/`.webp`（`live_emoji.emote_is_gif`）。**接口的 `is_dynamic` 不能当判据** ——
  实测标 1 的全是静态 PNG，会挂出播不了的假角标，详见 `docs/live_emoji.md` 第 3 节。

**加第三位不会破坏既有取值**：`_CardGridBase` 走 `_cover_url(item)`（取 `item[1]`），
`image_viewer` 也一律 `self._items[i][1]`。两元组的老调用照常能用（缺省视作静态图），
收藏集详情的 `DetailCard` 仍是两元组、不受影响。

## 五、播放

### 表情详情网格：悬浮才播

`EmojiCard.enterEvent` 起 movie、`leaveEvent` 停并退回静态图。只播鼠标底下那一张 ——
一屏几十个动图同时解码没有意义。

命中判据收敛在 `EmojiCard._hovered()`（`leaveEvent` 与每帧复核共用一份）：

- 卡片可见、光标落在卡片矩形内、且命中点还在视口里。鼠标移到子控件上时父控件也会收到
  `leaveEvent`，不判会「一进去就停」（历史胶囊的 × 踩过同一个坑）。
- **不能只靠 `leaveEvent`**：查看大图的遮罩（`MaskDialogBase`）盖住父窗口期间 Qt 不给宿主
  窗口发 enter / leave，遮罩关掉之后也不补发 —— 只信事件的话 movie 会一直转下去，直到用户
  重新悬停再移开。所以 `_on_frame` 每帧用真实光标位置复核一次，事件丢了也能自己停（最多多
  放一帧）。卡片被滚出视口时同理：它的 rect 跟着移出视口，光标早就不在卡上。

`hideEvent` 与 `set_cell` 里也停一次：卡片滚出视口、单元格尺寸变化后，movie 的 `scaledSize`
已经过期，停掉等下次悬浮重来。

停播时要**先丢掉缩放 memo（`_pixmap_memo = None`）再退静态图**：`_rescale` 命中 memo 会直接
返回 None、不设 pixmap，卡片就停在动图最后一帧上，看着像没退回去。

### 图片查看器：打开即播

`FlipView` 存 `QImage`，delegate 不认 `QMovie`，所以自己驱一个 movie：每帧
`_letterbox(movie.currentPixmap(), ...)` 合成后 `setItemImage` 顶回去。复用现成的 `_letterbox`，
不新写合成逻辑。

只播**当前那一项**，翻页即换（`_on_index_changed` 先停旧的再起新的）。`_stop_movie()` 会把该项
退回静态首帧 —— 翻走的那一页不该停在动图的随机某帧。

三个触发点缺一不可：构造末尾、翻页、以及 `_on_thumb`（**字节刚落盘那一刻**才真的播得起来 ——
打开查看器时图片可能还在下）。`_on_finished` 里必须停，别让 movie 活过 dialog。

性能：每帧一次 `SmoothTransformation` 缩放到 ≤900px 画布。表情 GIF 通常 ≤200px、约 10fps，
实测可接受；真掉帧再降成 `FastTransformation`。

## 六、验证

`scripts/check_gif.py`（屏幕外断言）：

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_gif.py
```

覆盖：两个判定入口（含「PNG 不算动图」「未缓存返回 None」）、角标在图片区左下且
**够小 / 不压中心 / 不与勾选框和「已下载」重叠**、悬浮起停 movie 并退回静态图、
查看器打开即播 / 翻页停播 / 关闭释放。

脚本要写 `image_cache`，**开头必须先隔离 `APPDATA`** 再 import `app.*`。
两帧 GIF 是把一段 1x1 单帧 GIF 的「GCE + 图像描述符 + LZW 数据」再接一份拼出来的
（不引入 PIL 依赖）。查看器关闭那条断言要**轮询等真实时间** ——
`MaskDialogBase.done` 先跑淡出动画才 `QDialog.done`，`finished` 是延迟发的。

真实动图观感（悬浮跟不跟手、查看器帧率）只能人工跑 `uv run python main.py` 看。
