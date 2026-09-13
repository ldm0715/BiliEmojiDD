# 直播间专属表情

「表情包」页的第三个标签：输入直播间 `room_id`，拉取该房间的**主播专属表情**，
网格预览 + 点开看大图，并把整个房间的表情作为**一个下载项**加入下载队列。

`biliemoji==2.0.0` 完全不覆盖直播间接口（`emoji.py` 的 `Business` 只有
`REPLY=0` / `DYNAMIC=1`，全包 grep `live` 零命中），所以这一套是自己解析的。

---

## 1. 三个接口（实测结论）

三个都是社区逆向记录下来的（bilibili-API-collect），不是官方公开 API，随时可能变。

| 用途 | 接口 | 匿名可用 | 取值 |
|---|---|---|---|
| 表情列表 | `xlive/web-ucenter/v2/emoticon/GetEmoticons?platform=pc&room_id=<id>` | **否**，`code:-101 账号未登录` | `data` 下各包/直属的 `emoticons[]` |
| 房间 → 主播 uid | `room/v1/Room/get_info?room_id=<id>` | 是，`code:0` | `data.uid` |
| uid → 昵称 / 头像 | `live_user/v1/Master/info?uid=<uid>` | 是，`code:0` | `data.info.uname` / `data.info.face` |

### 为什么主播信息要走两步

`xlive/web-room/v1/index/getInfoByRoom` 一次就能给出
`data.anchor_info.base_info.uname`，看起来更省事，但**实测匿名一律返回
`code:-352` 风控**（带上 `buvid3` 也照样拦）。上面那两个是 `code:0`，稳。
代价只是多一次请求，而且这两步都是**展示信息**，失败可以静默降级——只是头像和
昵称不显示，已经拿到的表情不受影响。

### GetEmoticons 需要登录

匿名请求它返回 `code:-101 账号未登录`。所以：

- `code == -101` → 抛 `biliemoji.errors.AuthRequired`，`show_bili_error` 有现成的
  「需要登录 / Cookie 缺失或已过期，请在「设置」页填写 Cookie」分支；
- 调用点同时调 `cookie_status.invalidate()` 作废信任期内的旧绿灯，但**不直接判红**
  （也可能是网络 / 风控，与「全部表情包」吃到 `AuthRequired` 时的处理一致）。

### 响应形状

一份很长的嵌套 JSON，`data` 下按包分组，包内是 `emoticons[]`。**同一份响应里
混着 B 站全局表情**，只有 `emoticon_unique` 以 `room_<room_id>_` 开头的才是这个
房间的（如 `room_5236391_109774`）。

解析刻意**不假定 `data` 的形状**（`parse_emoticons` → `_iter_emoticon_dicts`）：
深度遍历整棵树，凡是键名是 `emoticons` 的列表就收下它的元素，收下后不再往里递归。
这样「按包分组 / 直接给列表 / 换个包壳」三种形状都能解析，接口改版也不会一声不响
地返回空。`recently_used_emoticons` 是另一个键名，遍历会继续往下走，但它内部没有
`emoticons` 键，所以什么都不会收到。

**匹配用 `room_<room_id>_` 而不是 `startswith(f"room_{room_id}")`**：后者会把
`room_52363911_1`（另一个房间）也判成本房间。

---

## 2. 图片 URL 归一化

接口给的是 `http://i0.hdslb.com/...`，`live_emoji.normalize_url` 把
`*.hdslb.com` 的 `http://` 改成 `https://`：

- 缩略图与下载都走 https，不归一化则每次请求多一个 301 往返；
- `image_cache` 的键**就是 URL**，归一化保证「缩略图请求的键」与「下载取用的键」
  是同一个（GIF 悬浮播放是从 `image_cache` 取原始字节的）。

只动 B 站自己的 CDN，别的地址原样返回。

## 3. GIF 与文件后缀：两套口径，别混

- **显示口径**（网格角标 + 悬浮播放）：`emote_is_gif(url, is_dynamic)`，
  **`is_dynamic` 标记与 `.gif` 后缀取并集**。这一位喂给 `EmojiGrid.set_emotes` 的
  第三个元素。
- **落盘口径**：`LiveEmote.ext()` / `expected_ext()`，**只认 URL 后缀**。

落盘口径不能用 `is_gif` 反推，因为 `Downloader` 拿到 `expected_ext` 后若与实际内容
的魔数不符会**直接判 FAILED**（`biliemoji/downloader.py::download`），不是自动改正
后缀——猜错就等于该文件永远下不下来。URL 后缀是 CDN 上的真实类型。

认不出的后缀（如 `.apng`）要给 `expected_ext=None`：只有目标后缀也不在
`KNOWN_FORMATS` 里时，下载器才不校验格式、转而按内容嗅探并改正后缀
（`_resolve_target` 只改后缀不动父目录，所以逐项归属不受影响）。注意**不能靠
「给 None + 目标名写 `.png`」绕过**——`download` 里有
`expected = task.expected_ext or (target_ext if target_ext in KNOWN_FORMATS else None)`，
目标后缀是已知格式时那一路又会把断言补回来。

---

## 4. 队列第三类

一个房间 = 一个队列项，键 `("live", room_id)`。加入下载是**整包**（网格只做预览，
不做逐张勾选），与「全部表情包」按包多选一致。

`download_queue.item_kind` 原来是**二值函数**——有 `.emote` 就是 `"package"`，
否则一律 `"collection"`。直播间表情一旦漏进那个二分就会被静默当成收藏集：
`download_mixed_batch` 走错分支、`QueueCard` 读错字段，而且**不会报错**。
所以判别顺序是有意义的，**live 必须最先判**（`is_live_pack` 走 `isinstance`）。

新增一类要同步的**五个位置**（`item_kind` 是唯一判别入口，其余都是它的消费者）：

| 文件 | 改什么 |
|---|---|
| `download_queue.py` | `item_kind` 加 live 分支（排最前）、`item_key` 加 `("live", room_id)` 前缀、`item_cover_url` 加 live 支 |
| `content_meta.py` | `cached()` 对 live **同步推导** `ContentMeta(len(emotes), 0)`；`_MetaTask.run` 加显式 live 早退，别掉进收藏集分支 |
| `download_runner.py` | `live_folder_name` / `live_download_dir` / `download_live_batch`；`download_mixed_batch` 加第三个子批 |
| `widgets.py` | `QueueCard._refresh_text` 加 live 分支（名称=主播名、徽标=「直播间表情」、meta=`房间: <room_id>`）；`_refresh_badge` 让 live 复用 `SECONDARY_TEXT` |
| `download_page.py` | 「表情包 / 收藏集」字样补上「直播间表情」 |

**不用改**：`start_download`、`_collect_outcomes`（按 `target.parent` 归属，类型无关）、
`BatchReport` / `ItemOutcome`、`DownloadPage._on_batch_result`（只认
`per_item[].all_ok`）、`DownloadQueue` 本身。

### 直播间表情是唯一「零额外请求」的子批

`download_live_batch` 的形状与 `download_collection_batch` 同构（自己
`make_downloader`、自己建 `DownloadTask`、`owners[folder] = item_key(pack)`、
`_collect_outcomes` + `BatchReport`），但**循环里不取任何详情**——表情清单已经
随 pack 一起拿到了，`on_progress(i, n, None)` 只报个位置。内容数量同理，`cached()`
同步就能算出来，永远走不到 `_MetaTask`。

### 目录命名必须两处同名

```python
live_folder_name(pack)  # "<主播名> [<room_id>]"，截断 60 + sanitize_filename
live_download_dir(pack) # Path(cfg.download_dir.value) / live_folder_name(pack)
```

`live_folder_name` 单独抽出来就是为此：`live_download_dir`（「已下载」徽标判定）
与 `download_live_batch`（真正建目录）**必须用同一个名字**。两处各写一份的话，
改了一处徽标就永远判不出来——收藏集那边踩过（`collection_download_dir` 统一按
`summary.name` 命名就是那次修的）。

`check_live_emoji.py` 第 6 节用假下载器把批量下载的 `target.parent` 记下来，
直接断言它与 `live_download_dir` 相等——这条是**必须有的回归**。

---

## 5. 界面（`_LiveEmoteTab`）

版式**照「按 ID 查询」**（`_IdQueryTab` + `PackageDetailView`）：命令卡只有搜索框
与按钮，结果信息放在下面**独立的详情卡**里。三张卡自上而下：

1. **命令卡**：`SearchLineEdit roomEdit`（宽 260）+ `PrimaryPushButton fetchBtn`，
   后面接 `addStretch(1)`——**这一行只有这两个控件**。
2. **详情卡**（`CommandCard`）：`AccountAvatar` + 标题栏（`SubtitleLabel nameLabel`
   + `CaptionLabel detailLabel`）+ `status_badge("已下载", SUCCESS)` +
   `PrimaryPushButton addBtn`。状态全在这一张卡上流转：
   - 初始：「尚未获取直播间表情」/「输入直播间 room_id 后点击「获取直播间表情」」
   - 获取中：「正在获取「<room_id>」…」（同 `PackageDetailView.show_loading` 的写法）
   - 成功：主播名 /「房间号: <room_id> · N 个专属表情」（空则是「· 该直播间没有专属表情」）
   - 失败：「获取失败」/「请检查 room_id 与 Cookie 后重试」
3. **预览卡**（`SectionCard("表情预览")`）：`EmojiGrid`，`imageClicked` →
   `show_image_viewer(grid.items(), index, self.window())`。GIF 角标与悬浮播放随之
   白拿（`EmojiCard` 读 `set_emotes` 的第三位）。

`roomEdit` 挂 `SearchHistoryPanel(self.roomEdit, "live_room")`，点历史胶囊回填并立刻
拉取。`returnPressed` / `searchSignal` / `fetchBtn.clicked` 三条路都走 `_on_fetch`。
不做 Cookie 预拉取——这个标签页必须由用户给出 room_id 才成立，
`MainWindow._on_cookie_state` 不动。

### 坑

- **信息类文字别塞进搜索那一行**：塞进去看着就是输入框的一部分（「信息栏和搜索栏
  合并在一起」）。「按 ID 查询」之所以顺眼，就是因为它把信息全放在下面独立的详情卡里。
  `check_pages_layout.py` 与 `check_live_emoji.py` 都断言了**命令卡的直接子控件只有
  `[roomEdit, fetchBtn]`**，把这条锁住。
- **两个 Label 都要 `setWordWrap(True)`**：不换行的 QLabel 的 `minimumSizeHint` 就是
  整串文字宽度，详情行与初始提示会把整个表情包页的最小宽度顶到 816，
  `check_pages_layout.py` 的窄窗口断言当场立不住。`QStackedWidget` 的
  `minimumSizeHint` 取所有页的最大值，**隐藏的标签页一样参与**，代价会外溢到整页。
- **`_loading` 与按钮恢复都挂在 `on_finished` 上**：成功与两条异常路都会走它
  （`Task.run` 的 `except` 分支也 emit `finished(False)`）。只在成功路径清标志的话，
  一次失败之后「获取」按钮永久禁用——「全部表情包」的 `refreshBtn` 踩过。
- **`AccountAvatar` 的尺寸要提前钉死**：它只在图片到达时才 `setFixedSize`，在那之前
  是「可见但尺寸未定」的，会让主播行的高度在缩略图到位前后来回跳。构造后立刻
  `setFixedSize(AccountAvatar.SIZE, AccountAvatar.SIZE)`。
- **`SearchLineEdit.searchSignal` 带一个 `str` 载荷**，接无参槽由 PySide6 丢参；
  槽里仍从输入框现读文本，避免「点放大镜」与「按回车」两条路取值口径不一。
- **`QueueCard` 的渲染要留引用**：断言脚本里 `QueueCard(item).nameLabel.text()`
  会在临时对象被 GC 后抛 `Internal C++ object already deleted`。

---

## 6. 验证

```bash
QT_QPA_PLATFORM=offscreen uv run python scripts/check_live_emoji.py
```

九组断言：解析口径（含 `room_52363911_` 不被误收）/ `data` 形状 / `set_enabled(False)`
零请求 / 队列判别与键不撞车 / 内容数量零请求 / 目录命名一致性 / 结果归属 /
`QueueCard` 渲染 / 页面拉取与入队出队。

`check_pages_layout.py` 里有 `LIVE_NAMES` 的控件清点与「命令卡 + 表情预览卡」断言；
`check_cookie_status.py` / `check_home_page.py` 的 Pivot 标签顺序断言已同步成三项。

**需要人工看的部分**（离屏量不出来）：真实 Cookie 下拉取某个房间的实际观感、
主播头像的圆形裁剪效果、GIF 悬浮播放是否流畅。
