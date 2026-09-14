# 右键「复制表情」

## 背景

表情包页面原来只能「看」和「下载」。想直接把一张表情发给别人，唯一的路是先下载到本地、
再去文件夹里找文件 —— 为了一张 20 KB 的图落一堆文件。

本次在**单个表情网格**上加一条不落盘的出口：右键 →「复制表情」→ 粘到聊天窗口。

两处落点：`package_detail.py` 的表情包详情 / 按 ID 查询，`emoji_page.py` 的直播间表情预览。
都是 `EmojiGrid`，所以能力开关挂在网格基类的类属性上（见第 6 节）。

## 涉及文件

| 文件 | 职责 |
|---|---|
| `app/components/clipboard.py` | 纯函数：字节 / QImage → 剪切板 + 动图落文件 |
| `app/components/widgets.py` | `_CardGridBase._copyable` / `copy_url` 三层降级 / `_build_context_menu` |
| `scripts/check_clipboard.py` | 屏幕外断言 |
| `docs/reload_media.md` | 第 2 节对 `contextMenuEvent` 的描述随本次抽函数一并更新 |

## 一、字节从哪来：还是 `image_cache`

与 `docs/gif_preview.md` 第 2 节同一条路：`thumb.py` 的 worker 下载缩略图时会把**原始字节**
`image_cache.put(url, data)`，主线程只拿得到 `QPixmap`。复制要的就是那份原始字节 ——
**不必重新联网，也不必改线程层**。

## 二、两条通道，只有一条能带动画

这是本功能最容易踩错的地方，先说结论：

**Windows 上「粘贴图片」走的是 CF_DIB —— 一张纯位图，数据结构里没有「帧序列」，
动画无处安放。** 微信 / QQ / 画图粘贴时读的就是它，所以**只写位图的实现，动图必然变静态
首帧**。这不是解码漏了，是那个格式装不下。

一开始的实现只写了位图 + `image/gif` 自定义格式，结果就是动图粘出来不动。原因是
Qt 在 Windows 上把 `image/gif` 通过 `RegisterClipboardFormat` 注册成一个**自定义剪贴板
格式**，而绝大多数 Windows 程序粘贴时只枚举标准格式（CF_DIB / CF_HDROP /
CF_UNICODETEXT…），根本不看自定义格式。那份字节确实躺在剪切板上，但没人读。

**能携带一个真正的 .gif 文件的只有 CF_HDROP**（文件拖放格式，即「把文件拖进窗口」用的
那条通道）。所以现在的做法是：

| 输入 | 放什么 |
|---|---|
| 动图（GIF8 / RIFF+WEBP） | 位图 + 原始 mime 字节 + **落成文件挂 `text/uri-list`**（Qt 转 CF_HDROP） |
| 静态图 | 位图（+ 确实是 PNG 时挂 `image/png`） |

位图那份对动图**照旧一起留着**：CF_HDROP 只在部分目标里会被当成内嵌图片，粘进画图 /
Word 可能变成「一个文件」；两份都给，让目标自己挑。**哪个优先由目标决定，我们控制不了**
（第 7 节）。

**`setImageData` 必须先调**：`QMimeData.formats()` 保持插入顺序，位图排前面最稳。

动图判据用**魔数**，不用 URL 后缀：这里手上已经是字节，而后缀那套口径
（`live_emoji.emote_is_gif`）是给「还没下载、只能看地址」的场景用的。

**WebP 必须一起认。** `emote_is_gif` 把 `.webp` 算动图、`movie_from_cache` 也认它；
只判 `GIF8` 的话，直播间表情里那些**真能播的 webp** 复制出去只剩首帧 ——
而直播间正是这个功能两个落点之一。

认不出来的格式（jpg 等）**不冒充** PNG：挂错 mime 比不挂更糟，位图那份照样能用。

## 三、剪贴板载荷放哪：`%APPDATA%/biliEmojiDD/clipboard/`

**不放 `cache/`**，尽管看着像缓存。设置页的「清除缓存」（`disk_cache.clear_all`）清的是
`cache/` 下的 `images` 与 `api`，那会把用户**已经复制好、正准备粘贴**的动图删掉。
这些东西不是缓存，是被剪切板引用着的**载荷**，得活到粘贴完为止。

于是有个硬约束：**CF_HDROP 传的是路径，不是内容，Windows 不复制文件。** 所以：

- 文件**不能**在应用退出时删 —— 否则「复制完退出再粘贴」就废了。这也意味着用户复制几次
  就会留下几个文件，需要淘汰策略。
- 淘汰在**每次写入时**做：按 mtime 保留最近 `_KEEP_FILES`（32）个，多出来的最老的先走。
  正在写的那份刚 `utime` 过，始终最新，不会被自己删掉。
- 文件名取内容 sha1 + 正确扩展名，所以同一张表情复制多次只有一个文件；
  **扩展名不能省** —— 目标程序靠它认「这是个动图」，没后缀的多半被当普通附件。
- 落盘沿用 `disk_cache` 的 `.part` + `os.replace` 套路，写一半被杀不会留半截文件。

落盘失败**不是错误**：退回「只有位图」，不让整次复制失败。

## 四、三层降级（`_CardGridBase.copy_url`）

| 档 | 来源 | 拿到什么 |
|---|---|---|
| ① | `image_cache.get(url)` | **原始字节**（全分辨率 + 完整 GIF/WebP） |
| ② | `QPixmapCache.find(url)` → `pm.toImage()` | 全尺寸位图，**动图只剩首帧** |
| ③ | `thumb_manager.request(url)` + `_copy_wait` | 字节落盘后回头发信号，再走 ① |

- ① 在 UI 线程同步读磁盘，与 `gif.py::movie_from_cache`（挂在 `EmojiCard.enterEvent` 上、
  每次悬浮都跑）同一取舍。代价不是「文件小」，而是 `DiskCache.put` 与淘汰扫描共用一把
  `RLock`，最坏情况要排在某个 worker 的一次全目录扫描后面。
- ② 的分辨率**没有**损失（`thumb.py` 存的是全尺寸，卡片显示时才缩放），差的只是动图能力。
- ③ **复用缩略图流水线，不另开网络路径**。四个好处：`request()` 自带按 URL 去重，不会与
  正在飞的请求并发重复；worker 在 emit 前已 `image_cache.put`（`thumb.py`），所以回调里
  重读 ① 通常仍拿得到**原始 GIF/WebP 字节**，动图口径在 ③ 也保得住；`clipboard.py` 因此
  不需要 `cfg`/`net`/`task`；脚本能用 `signal_bus` 驱动，完全确定性、不出网。

  这条与 `gif.py` 的「字节拿不到就静默降级、不值得为它补一次下载」**刻意不同**：
  那是自动播放，这是用户主动点的复制。顺带它还是「失败后手动重试一次」的出口 ——
  卡片失败后 `_requested` 挡着 `_update_visible` 不再重试，而这里显式 `request` 就是重来一次。

**`_copy_wait` 的两条路都要清**（成功与失败），否则失败一次之后右键复制永远卡在「等字节」
—— 同 `CLAUDE.md`「清『正在飞』标志必须挂 `on_finished`」那条坑。`set_cards` 里也要清，
换了一批卡片之后那个 url 已经没意义。

## 五、失败静默

- ①② 同步成功 → **不弹提示**。用户下一步就是粘贴，粘出来就是反馈；每次弹一条 4s 的
  InfoBar 只是噪音（同 `cookie_status` 的静默预拉取、`gif.py` 的「静默不播」）。
- ③ 异步成功 → `notify_success`。菜单早关了，中间隔了几百毫秒到几秒，不说一声不知道能粘了。
- 任何路径失败 → `notify_warning`。

失败路径还有个约束：`loadFromData` 解不出来时**完全不碰剪切板**，返回 `False` ——
不能让一次失败把用户上一条复制内容冲掉。

## 六、范围：只有 `EmojiGrid`

基类 `_copyable = False`，`EmojiGrid._copyable = True`。用**类属性**而不是
`isinstance(self, EmojiGrid)`（基类反向依赖子类，将来新增网格必漏判）或覆写
`contextMenuEvent`（两份菜单代码要同步维护）—— 它和 `_card_class` / `_min_cell` /
`_cover_url` / `_cell_size` 同族，都是编译期常量。

**闸门在菜单和 `copy_url` 两处都挡**：这样 `_copyable` 真的等于「这个网格永远不会碰
剪切板」，将来接快捷键 / 卡片级右键也不会漏。

不加的：`PackageGrid`（全部表情包列表的封面卡）、`DressGrid` / `DressDetailGrid`、
`QueueList`、以及 `image_viewer` —— 查看器被收藏集共用，无法区分来源，所以故意不做。

## 七、菜单抽成可断言的两半

```python
_context_url(pos)            # 右键落点 → 该格 url（空白处返回 None）
_build_context_menu(url)     # 只建不弹
contextMenuEvent(event)      # 取 url → 建 → exec
```

抽出来的理由是**可测**：`exec()` 会阻塞事件循环，屏幕外脚本没法调 `contextMenuEvent`，
但可以直接拿 `menu.actions()` 验项列表。`check_reload.py` 里那句「右键菜单走的是同一条
路径」其实只调了 `reload_url`，从来没碰过菜单 —— 本次之前这条路径是零覆盖的。

菜单项顺序：复制在前、重新加载在后。

## 八、已知限制（别当成 bug）

1. **动画能不能保留，取决于目标程序。** 位图（CF_DIB）和文件（CF_HDROP）两份都给了，
   但**哪个优先由目标自己挑**：认文件的（多数聊天软件）能粘出动图，认位图的（画图、
   部分编辑器）拿到静态首帧，还有些会把文件粘成「一个附件」而不是内嵌图片。
2. **② 兜底路径只能是静态图**（磁盘那份被 LRU 淘汰、内存还在时）。
3. **动态判据以字节魔数为准**：URL 是 `.gif` 但服务端给回 PNG 时按静态处理（反之亦然）。
4. **范围只到表情网格**：全部表情包封面卡 / 收藏集 / 下载队列 / 图片查看器故意不做。
5. **`%APPDATA%/biliEmojiDD/clipboard/` 会留文件**（最多 32 个）。这是 CF_HDROP 的必然
   代价，见第 3 节。设置页的「清除缓存」**不会**清它。

## 九、验证

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_clipboard.py
```

覆盖：纯函数（GIF / WebP / PNG 的 mime 与原始字节往返、位图排前、失败无副作用）、
**动图落文件**（挂上 `text/uri-list`、文件真的落盘且内容是原始字节、扩展名正确、
同内容复用同一文件、静态图不产生文件、`_prune` 按 mtime 淘汰且保留最新、载荷不在 `cache/` 下）、
网格接线（只有 `EmojiGrid` 开 `_copyable`、菜单项与顺序、空白处不弹、触发菜单项真的复制）、
三层降级（① 同步拿原始字节 / ② 全尺寸位图 / ③ 委派与三种收尾）、失败静默、
`_copy_wait` 成功失败都清。

脚本要写 `image_cache`，**开头必须先隔离 `APPDATA`** 再 `import app.*`（`_CLIP_DIR` 也是
import 时按它算的）；假 URL 一律预置 `QPixmapCache`，第 ③ 档还要 `_inflight.add(url)`
（既模拟「正在飞」，又让 `request()` 早退 —— 不然假 URL 会排一个 15s 超时任务、脚本退不
出去），收尾记得清掉这份假状态。

### 只能人工验证

`QT_QPA_PLATFORM=offscreen` 走的是 `QPlatformClipboard` 内存桩，**根本不经过
`QWindowsMimeRegistry`**。脚本能断言的只是 `QMimeData` 里放了什么，**放上去之后目标程序
怎么选、能不能动，一律测不出来**。真机要试：

1. 复制一张**动图**表情 → 粘进微信 / QQ，看是动图、静态图、还是一个文件附件。
2. 同一张粘进画图 / Word，确认**至少**还能拿到静态图（位图那份没被文件通道挤掉）。
3. 复制后**立刻退出应用**，再粘贴 —— 验 CF_HDROP 引用的文件确实还在。
4. 静态表情（PNG）粘一次，确认行为没变。
