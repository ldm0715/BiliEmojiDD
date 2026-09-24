# 功能模块领域规范

## 扫码登录

- 用 B 站 **web 端**扫码登录接口，不要用 TV 端那套（返回 `access_token`，不是 Cookie）：
  `GET https://passport.bilibili.com/x/passport-login/web/qrcode/generate` 取 `data.url` 与
  `data.qrcode_key`；`GET .../web/qrcode/poll?qrcode_key=...` 取 `data.code`。
  三个 URL 是 `app/components/bili_login.py` 的模块常量，改动只动那一处。
- 二维码密钥 180 秒过期（`QRCODE_TTL_SECONDS`）。`data.code` 映射固定：`86101`→`WAITING`、
  `86090`→`SCANNED`、`0`→`CONFIRMED`、`86038`→`EXPIRED`；**认不出的码与 `data` 缺 `code`
  一律按 `EXPIRED` 处理**，不要停在「等待扫码」。
- Cookie 提取两条路：`_cookie_from_headers`（响应头 `SESSDATA`/`bili_jct`/`DedeUserID`/
  `DedeUserID__ckMd5`/`sid`）优先，`_cookie_from_cross_domain`（成功响应 `data.url` 的 query）兜底。
  **兜底路径刻意不做 URL 解码**（`SESSDATA` 里的 `%2C` 解码后与 `Set-Cookie` 取值对不上，
  拼出来登不上去）。
- Cookie 按固定顺序 `SESSDATA → bili_jct → DedeUserID → DedeUserID__ckMd5 → sid` 拼成
  `"k=v; k=v"`（`_COOKIE_FIELDS` / `_join_cookie`），只收已知且非空的键。
- 扫码必须用 `net.make_bili_session()`：浏览器 UA + `Referer: https://www.bilibili.com/`；
  **不要把它的 UA 与 `make_session` 的 `BiliEmojiDD/<版本>` 合并**（后者只给 GitHub 检查更新用，
  打 passport 接口会被风控）。
- 不能用 `BiliClient.get_json()` 做扫码（只返回 `resp.json()`，够不着 `Set-Cookie` 响应头）；
  但所有联网仍走 `net.py` 唯一工厂。
- 网络层 `bili_login.py` 不 import 任何 Qt 控件。
- 轮询用一个 `QTimer(1000ms)` 同时管倒计时文案与每 2 秒一次 poll，每次 poll 是独立 `run_task`，
  结果经信号回主线程。**必须加 `_polling` 守卫**（上一次 poll 未返回就跳过这次 tick，
  否则网络慢时每 2 秒叠一个任务）。
- **必须加 `_closed` 守卫**：`_on_poll` / `_on_qr_ready` / `_on_poll_failed` 开头都判
  （`run_task` 起飞后取消不掉，关窗时在飞的请求还会回来）。
- `_shutdown()` 幂等挂在四个出口：`reject` / `accept`（必须同步收，上游 `done()` 挂了淡出动画，
  等 `hideEvent` 会晚一拍）、`closeEvent`、`hideEvent`（父窗口关闭时 Qt 只隐藏子窗口，
  其余回调一个都不走）。
- 轮询失败**不弹全局 InfoBar**，只在对话框内显示「网络不稳，正在重试…」，下一次 tick 自然重试。
- `proxies` 由调用方在**主线程**读 `current_proxies()` 后再传给对话框，worker 线程不碰 `cfg`。
- 二维码用 `segno` 的 `matrix_iter(scale=1, border=4)` 取 0/1 矩阵，`_QrCodeView` 用 `QPainter`
  自绘，不引 Pillow、不做 PNG 解码。**`border=4` 的 quiet zone 不能省**；配色恒为白底黑块，不接主题。
- 矩阵先预渲染进一张 `QPixmap`（按 `devicePixelRatio` 放大），`paintEvent` 只做一次 blit；
  不要用 `FluentIcon.QRCODE` 或 `PixmapLabel` 承载。
- `data.url` 只当二维码内容**原样编码，从不解析**（换域名 / 路径不影响）；
  会解析的只有登录成功响应里的 crossDomain `data.url`。
- 账号区只有一张「B 站账号」卡，按登录态切形态；**三个按钮各自连自己的槽靠显隐切换**，
  不做「一个按钮换文案换行为」。
- `_apply_cookie()` 是扫码 / 手动填写 / 退出登录三条路的**唯一汇合点**：落盘 + 刷卡片 +
  发 `configChanged` + 异步取账号。
- 「退出登录」只清 `cookie` 与 `account_*`，不动下载目录、图片缓存、已下载文件。
- 「验证」验 `cfg.cookie`（生效值），不读某个输入框。
- 手动填写对话框用组件库 `LineEdit`（没有 `setError`），空输入用「保存」禁用表达错误态。
  **手动粘贴 Cookie 的入口必须一直留着**；接口失效时先确认手动粘贴仍可用，再去对接口。
- `fetch_account()` 打 `https://api.bilibili.com/x/web-interface/nav`，读
  `data.isLogin`/`uname`/`mid`/`face`，存进 `account_name` / `account_mid` / `account_face`。
- 启动时不联网刷新账号信息，设置页只显示缓存；取账号时机只有扫码成功、保存、验证，
  都走 `_refresh_account`。取账号失败静默（`on_error=lambda _e: None`）；`_on_account(None)`
  不覆盖已有昵称。
- 换账号时 `_apply_cookie` 在 Cookie 值变了的情况下**先清 `account_*` 三项**
  （避免新 nav 回来前显示上一个账号昵称）。
- 头像没图就 `setVisible(False)` 整个藏起来（含「有 Cookie 但还没拿到 face」的中间态），
  不做灰色占位图。
- `AccountAvatar._adopt()` 喂完图**必须 `setFixedSize(SIZE, SIZE)` 钉回控件尺寸**——
  `ImageLabel.setImage` 会无条件 `setFixedSize(self.image.size())`，非正方形大图会把控件撑变形。
- **`MessageBoxBase.yesButton` 默认连 `accept()`，改成「刷新二维码」必须先 `clicked.disconnect()`。**
- **`LoginDialog` 的 `parent` 是必填位置参数**，传 `page.window()`（`MaskDialogBase.__init__`
  直接读 `parent.width()`，`None` 会 `AttributeError`）。对话框必须留引用（`self._loginDialog`），
  只 `show()` 不持有会被 Python 回收。
- 不要覆写 `AvatarWidget.__init__`，用 `_postInit()` 钩子。
- `_WidgetSettingCard` 副标题文案要短（窄窗口约 600px 下与头像、按钮并排会被顶出卡片）。
- 涉及显隐的断言必须先 `show()` 再 `hide()`（`hide()` 对没显示过的控件是 no-op）。

## Cookie 状态机

- 五态：`NO_COOKIE` / `CHECKING` / `VALID` / `INVALID` / `UNKNOWN`；**`CHECKING` 只在内存，
  不落盘**。
- 区分两个读法：`known_state()`（读记录 + 算指纹 + 比信任期，零网络，供 `ensure_checked()` 决策）
  与 `current_state()`（界面该显示的，探针在飞时恒为 `CHECKING`）；英雄卡读 `current_state()`，
  **不可退化成 `known_state()`**。`ensure_checked()` 开头「不是 UNKNOWN 就直接 return」不是 bug，别删。
- 信任期：`VALID` = **7 天**，`INVALID` = **30 分钟**；网络失败**不写记录**。
  **失效档不能给 7 天**：`nav` 在风控下会返回 HTTP 200 + 空 `data`，假报「没登录」，
  一旦误判就再也纠正不过来。
- 探针统一用 `bili_login.fetch_account(cookie, proxies=...)`：返回 `Account`→`VALID` 写记录；
  返回 `None`→`INVALID` 写记录；抛异常→`UNKNOWN` 不写记录。`_payload` 刻意不看业务 code。
- **`nav` 是唯一能写出 `INVALID` 的地方**；任何需登录操作吃到 `AuthRequired`
  （表情包页拉全量、直播间表情）都调 `invalidate()`，**不直接判红**。
- 设置页「验证」仍用 `all_packages()`（证明的是表情包访问权限）：成功 → `note(VALID)` **只提升**；
  失败遇 `AuthRequired` → `invalidate()` 作废记录。
- `note(state, cookie)` 收**发起请求时的 Cookie 快照**，与当前 Cookie 不一致就不写记录。
- `_apply_cookie` 里**重填同一个 Cookie 也要 `invalidate()`，不看值有没有变**
  （「我又填了一遍」意图就是重新验证）。
- 记录项 `cookieCheckedAt` / `cookieCheckedHash` / `cookieCheckedState` 定义在
  `app/common/config.py`；**不要在 `known_state()` 的非 UNKNOWN 路径上调 `note()`**，
  否则每次进主页都写盘。
- 状态灯映射是 `home_page.cookie_light(state)` 纯函数（模块级 `_COOKIE_LIGHT` 字典），
  断言脚本直接读它，不从 `QLabel` 回读像素。五态文案 / 颜色：`NO_COOKIE`「● 未配置 Cookie」
  / `ORANGE_TEXT`；`CHECKING`「● 正在检测 Cookie…」/ `SECONDARY_TEXT`；`VALID`「● Cookie 有效」
  / `SUCCESS_TEXT`；`INVALID`「● Cookie 已失效」/ `DANGER_TEXT`；`UNKNOWN`
  「● Cookie 已配置（未验证）」/ `SECONDARY_TEXT`。颜色用 `SUCCESS_TEXT` / `DANGER_TEXT`
  （暗色一侧已提亮），不照抄 `mirror_card` 的胶囊深底色。
- `UNKNOWN` 文案刻意保留「已配置」；主按钮只看「填没填」，不随状态灯变。
- `HomePage.showEvent` → `cookie_status.ensure_checked()`：记录新鲜只广播一次结论、零请求；
  过期 / 换号则广播 `CHECKING` 并起一次 nav 探针。
- 有效后静默预拉取：`cookie_status.emit(VALID)` → `MainWindow._on_cookie_state` 二次核对
  `known_state()`（防迟到回调）→ `QTimer.singleShot(0, emojiPage.ensure_all_packages)`；
  **不切页**，也不弹「已使用本地缓存」InfoBar。
- `_AllPackagesTab.ensure_loaded()` 必须**幂等**：有数据 / 正在拉 / 没 Cookie 都直接返回。
- 标签顺序固定「全部表情包」第一且默认页、「按 ID 查询」第二；**别把默认项改成第二项**。
- `_inflight` / `_loading` 必须在 `on_finished` 里清；`refreshBtn` 统一在 `on_finished` 里按
  「有没有数据」恢复启用。

## 直播间表情

- 只用三个接口：表情列表 `xlive/web-ucenter/v2/emoticon/GetEmoticons?platform=pc&room_id=<id>`
  （匿名不可用）、房间→uid `room/v1/Room/get_info?room_id=<id>` 读 `data.uid`、
  uid→昵称 / 头像 `live_user/v1/Master/info?uid=<uid>` 读 `data.info.uname` / `data.info.face`。
- **不要用 `xlive/web-room/v1/index/getInfoByRoom`**（实测匿名一律 `code:-352` 风控，
  带 `buvid3` 也拦）；主播信息两步都失败静默降级。
- `GetEmoticons` 返回 `code == -101` → 抛 `AuthRequired`（复用 `show_bili_error` 的登录分支），
  并在调用点调 `cookie_status.invalidate()`。
- 解析**不假定 `data` 形状**：深度遍历整棵树，凡键名为 `emoticons` 的列表收下其元素后
  不再往里递归（`parse_emoticons` → `_iter_emoticon_dicts`）。
- 房间归属判定用 `emoticon_unique.startswith(f"room_{room_id}_")`，**不能用
  `startswith(f"room_{room_id}")`**（会把 `room_52363911_1` 误判为本房间）。
- `live_emoji.normalize_url` 把 `*.hdslb.com` 的 `http://` 改 `https://`，只动 B 站自己的 CDN；
  `image_cache` 的键就是 URL，归一化保证缩略图与下载同键。
- 显示口径（网格角标 + 悬浮播放）用 `emote_is_gif(url)`：**纯 URL 后缀白名单 `.gif` / `.webp`**；
  **接口的 `is_dynamic` 绝对不能当判据**（实测标 `is_dynamic=1` 的 19 条全是 162×162 静态 PNG）。
  显示白名单**不能收 `.apng`**（PySide6 6.4.2 `QMovie.supportedFormats() == ['gif','webp']`）。
- 落盘口径 `LiveEmote.ext()` / `expected_ext()` 只认 URL 后缀（白名单更宽，含 `.png`/`.jpg`）；
  **不能用 `is_gif` 反推**——`Downloader` 拿到 `expected_ext` 后与实际魔数不符会**直接判 FAILED**，
  不是自动改正后缀。认不出的后缀（如 `.apng`）给 `expected_ext=None`；**不能靠「给 None +
  目标名写 `.png`」绕过**。
- 队列键 `("live", room_id)`，一个房间一个队列项，整包加入（网格只做预览，不做逐张勾选）。
- **`item_kind` 是唯一判别入口，判别顺序有语义：live 必须最先判**（`is_live_pack` 走 `isinstance`），
  漏进二分会被静默当成收藏集且不报错。
- 新增队列类型要同步五个位置：`download_queue.py`（`item_kind` / `item_key` / `item_cover_url`）、
  `content_meta.py`（`cached()` 同步推导 + `_MetaTask.run` 加显式早退）、`download_runner.py`
  （`live_folder_name` / `live_download_dir` / `download_live_batch`，`download_mixed_batch`
  加第三子批）、`widgets.py`（`QueueCard._refresh_text` / `_refresh_badge`）、`download_page.py`。
- 直播间表情是唯一「零额外请求」的子批：循环里不取任何详情，`on_progress(i, n, None)` 只报位置；
  `cached()` 同步算 `ContentMeta(len(emotes), 0)`，永远走不到 `_MetaTask`。
- `live_folder_name(pack)` = `"<主播名> [<room_id>]"`（截断 60 + `sanitize_filename`）；
  `live_download_dir`（「已下载」徽标判定）与 `download_live_batch`（建目录）**必须用同一个名字**。
- 版式照 `_IdQueryTab` + `PackageDetailView`：命令卡只有 `SearchLineEdit roomEdit`（宽 260）
  + `PrimaryPushButton fetchBtn` + `addStretch(1)`，**信息类文字不要塞进这一行**。
- 详情卡四态文案：初始「尚未获取直播间表情」；获取中「正在获取「<room_id>」…」；成功
  「房间号: <room_id> · N 个专属表情」（空则「· 该直播间没有专属表情」）；失败「获取失败」。
- `roomEdit` 挂 `SearchHistoryPanel(self.roomEdit, "live_room")`；`returnPressed` / `searchSignal` /
  `fetchBtn.clicked` 三条路都走 `_on_fetch`。`SearchLineEdit.searchSignal` 带 `str` 载荷，
  槽里仍从输入框现读文本。
- 不做 Cookie 预拉取，`MainWindow._on_cookie_state` 不动这个标签页。
- 详情卡两个 Label 都要 `setWordWrap(True)`。
- `_loading` 与按钮恢复都挂在 `on_finished` 上（只在成功路径清会导致「获取」按钮永久禁用）。
- 构造后立刻 `AccountAvatar.setFixedSize(AccountAvatar.SIZE, AccountAvatar.SIZE)`，
  钉死尺寸防主播行高度跳动。

## 收藏集判别

- 类别与 id 一律从 `summary.raw` 读，**不信 biliemoji 的 typed 字段**（真实键是 `item_id`）。
- 判别用 `props(summary)["type"]`：`"dlc_act"` = 收藏集、`"ip"` = 装扮。
- `dlc_ids(summary)` 返回字符串形式的 `(dlc_act_id, dlc_lottery_id)`，可直接传
  `certain_lottery_typed`；`is_collection(summary)` / `category_name(summary)` 供卡片徽标、
  详情入口、批量下载共用（`app/components/dress_helpers.py`）。
- `DressCard` 用纯 `QWidget` + 自写 `mousePressEvent`，**弃用 `CardWidget`**——
  基类 `clicked.emit()` 是 0 参，子类重声明 `Signal(object)` 会在运行时抛 `TypeError`
  且被 PySide 静默吞掉。
- 网格统一走 `_CardGridBase(QListWidget)`，内置懒加载缩略图 + 多选 API + 动态单元格。
- `DressGrid` 恰好 4 列，单元格宽 = `(视口宽 - 3×间距) // 4`，海报 3:4。
- 海报用的 `QPushButton` 必须 `setSizePolicy(Expanding, Expanding)`。
- 收藏集详情走 `dlc_ids` → `run_task(certain_lottery_typed)`；视频区是**可播放的「动态视频」
  标签页**（内嵌播放器 + 缩略图选择条），折叠列表已移除。
- 详情页「加入下载」状态与队列联动统一走 `_sync_queue_btn`（打开详情重置、已存在 / 加入后
  「已加入」禁用、队列移除后恢复）。
- 「已下载过」提示按下载目标目录是否非空判断（`downloaded_exists(folder)` = 目录存在且非空）。
- 「仅看收藏集」默认勾选，取消 / 勾选可实时过滤当前结果，无需重新搜索。
- 详情页单个下载改走 `download_collection_batch([summary], ...)`，
  **禁止用 `Dress.download_collection`**（后者不转发 `proxies`）。
- 详情页 `_refresh_downloaded(collection=None)` 必须同时认 summary 名与 `coll.name` 两个目录
  （兼容改名前的旧数据）。
- 「已下载」徽标**只在建卡时查一次目录**，同一网格里下载完成不会自动刷新（重新搜索 / 翻页才更新）；
  `PackageCard.refresh_downloaded()` / `DressCard.refresh_downloaded()` 已写好但未接线。

## 下载队列

- 队列是**会话级内存队列**：`DownloadQueue`（`QObject` 子类，`changed = Signal()`，
  方法 `add` / `add_many` / `remove` / `clear` / `packages` / `contains`），重启清空。
- 按 `item_key` 去重：表情包 `("pkg", id)`、收藏集 `("coll", f"dlc:{act_id}:{lottery_id}")`、
  直播间 `("live", room_id)`。
- **收藏集不能用 `raw["item_id"]` 去重**：`item_id == properties.dlc_act_id`，同一 dlc 活动下
  多期 lottery 各自是独立收藏集，会被判成同一项（`add_many` 悄悄丢弃、详情页 `contains()`
  却显示「已加入」）。
- 非收藏集装扮（`type='ip'`，无 dlc id）退回 `item:{item_id}` / `id:{id}` / `name:{name}`，
  **各自带前缀**防跨方案撞车（字符串 `"5"` 与数字 `5`）。
- **不要在别处硬编码键字面量**，测试里用 `item_key(summary)`。
- 队列项**不再全部保留**：下载队列页批量下载后，全部成功的项自动移出队列。
- 队列页 `_downloading` 门控：下载中禁用全选 / 删除 / 清空 / 下载，完成后恢复。
- 队列卡片响应式布局：宽视口两列、窄视口退回单列，`_cell_size` 数学保证不横向溢出；
  封面随单元格自适应方块、名称可换行；信息区右侧预留勾选框空间。

## 下载页

- 表情包详情页「下载动图 (GIF)」选项行的判据是 `any(em.gif_url for em in pkg.emote)`，
  **不用 `pkg.is_gif`**（后者只看 `meta.label_text`，与 `download_package_batch` 里
  `if use_gif and em.gif_url` 的实际取用不同步）。
- GIF 选项整行用 `CommandCard.add_row_widget()` 包成独立容器再 `setVisible`
  （裸 `add_row()` 返回 `QHBoxLayout`，只隐藏 `gifCheck` 会留空行）；`show_loading()` / `clear()`
  里一并隐藏。
- `content_meta.cached(item)`：缓存命中则能同步推导就同步推导（详情页加入的完整 `EmotePackage`
  自带 `emote`，零请求），否则返回 `None`。
- `content_meta.request(item)` **只在卡片可见时调**（覆写 `QueueList._update_visible`），
  走独立 `QThreadPool(2)`，不占 `task_manager` 那 4 个线程。
- worker 只发 `signal_bus.contentMetaRaw(key, meta)`，主线程槽写完缓存再广播
  `contentMetaLoaded`；载荷 `None` 表示取不到。
- 内容数量失败**不写缓存**，记进 `_failed` 集合，本会话不再重试（否则每次滚动经过都重发请求）。
- 数量口径必须与建下载任务逻辑一致：表情包数 = 「有 `gif_url or url` 的 emote」；
  收藏集数 = 「有 `card_img_download` 的项」+「有 `video_list` 的项」（视频每项只下第一个）。
- `PackageDetailView.set_package` 与 `DressPage._show_detail` 各调一次 `content_meta.remember()`，
  进过详情的项在队列页零请求。
- `QueueCard.contentLabel` 四态：`内容: N 张图片` / `内容: N 张图片 · M 个视频` / `内容读取中…` /
  `内容数量未知`；`QueueList._min_cell` 高度 `112 → 128`。
- 自动移除判据 `ItemOutcome(total, failed).all_ok` = `total > 0 且 failed == 0`。
  **SKIPPED 算成功**（文件确实在本地）；**`total == 0` 不算成功**（不能靠空集合真空成立）。
- **自动移除只在下载队列页的批量下载触发**，详情页可以只下静态图片或只下动态视频，
  半程移除会丢内容。
- 归属用 `result.target.parent`（建任务时记 `owners[folder] = item_key`），
  **不用结果下标对齐**（`Downloader._resolve_target` 只改后缀不动父目录，父目录是稳定归属键）。
- 取详情失败合成的结果落在 `dest` 根下，不属于任何目录，另行写 `ItemOutcome(1, 1)`。
- `BatchReport` **继承** biliemoji 的 frozen `DownloadBatchResult`（父类字段无默认值、子类新字段
  带默认值），结果经 `start_download(on_result=...)` 送到页面（`on_finished` 无参、拿不到结果）。
- 已知边界：同一批里两个同名收藏集共用下载目录，`owners` 后者覆盖前者，前者不会被自动移除
  （保守失败，不误删）。
- 加载环用 `IndeterminateProgressRing`（自带 `themeColor()`），28px + `strokeWidth=3` +
  `WA_TransparentForMouseEvents`；逻辑收在 `_SpinnerMixin`（纯 object mixin，不继承 `QObject`）。

## 剪贴板复制

- 原始字节来源走 `image_cache.get(url)`（`thumb.py` worker 下载时会 `image_cache.put(url, data)`），
  **不重新联网**。
- Windows 上「粘贴图片」走 **CF_DIB**（纯位图，结构里没有帧序列），只写位图则动图必然变静态首帧；
  Qt 把 `image/gif` 注册成自定义剪贴板格式，绝大多数 Windows 程序只枚举标准格式、根本不读。
  **能携带一个真正 .gif 文件的只有 CF_HDROP**（即 `text/uri-list`，Qt 转成文件拖放格式）。
- 载荷规则：动图（GIF8 / RIFF+WEBP）放「位图 + 原始 mime 字节 + 落成文件挂 `text/uri-list`」；
  静态图放位图（+ 确实是 PNG 时挂 `image/png`）。位图那份对动图**照旧一起留着**
  （CF_HDROP 在部分目标里会变成「一个文件」附件，两份都给让目标自己挑）。
- **`setImageData` 必须先调**（`QMimeData.formats()` 保持插入顺序，位图排前面最稳）。
- 动图判据用**字节魔数**（GIF8 / RIFF+WEBP），不用 URL 后缀；**WebP 必须一起认**
  （直播间那些真能播的 webp 只判 `GIF8` 会只剩首帧）。认不出的格式（jpg 等）**不冒充 PNG**。
- 剪贴板载荷放 `%APPDATA%/biliEmojiDD/clipboard/`，**不放 `cache/`**（设置页「清除缓存」
  会删掉用户正准备粘贴的动图）。
- CF_HDROP 传路径不传内容：文件**不能在应用退出时删**（否则「复制完退出再粘贴」就废了）。
  淘汰在**每次写入时**做：按 mtime 保留最近 `_KEEP_FILES`（32）个，最老的先走。
- 文件名取内容 sha1 + **正确扩展名**（目标程序靠扩展名认动图）；同一张表情复制多次只有一个文件。
  落盘沿用 `disk_cache` 的 `.part` + `os.replace` 套路；落盘失败**不是错误**，退回「只有位图」。
- 三层降级（`_CardGridBase.copy_url`）：① `image_cache.get(url)` 原始字节（全分辨率 +
  完整 GIF/WebP）；② `QPixmapCache.find(url)` → `toImage()` 全尺寸位图（动图只剩首帧）；
  ③ `thumb_manager.request(url)` + `_copy_wait`，字节落盘后回信号再走 ①。
- ③ 必须复用缩略图流水线、不另开网络路径（`request()` 自带按 URL 去重、worker emit 前已
  `image_cache.put`，`clipboard.py` 因此不需要 `cfg` / `net` / `task`）。
- **`_copy_wait` 的成功与失败两条路都要清**，`set_cards` 里也要清（否则失败一次后右键复制
  永远卡在「等字节」）。
- 失败静默：①② 同步成功**不弹提示**；③ 异步成功 `notify_success`；任何路径失败 `notify_warning`。
- **`loadFromData` 解不出来时完全不碰剪切板、返回 `False`**（不能让一次失败冲掉用户上一条
  复制内容）。
- 范围只到 `EmojiGrid`：基类 `_copyable = False`、`EmojiGrid._copyable = True`，
  用**类属性**而不是 `isinstance` 或覆写 `contextMenuEvent`。闸门在**菜单和 `copy_url` 两处都挡**。
  不加 `_copyable` 的：`PackageGrid`、`DressGrid` / `DressDetailGrid`、`QueueList`、`image_viewer`。
- 菜单抽成 `_context_url(pos)`（空白处返回 `None`）/ `_build_context_menu(url)`（只建不弹）/
  `contextMenuEvent(event)`；菜单项顺序：复制在前、重新加载在后。

## 主页

- 主页禁止直接发请求；展示图一次性抓好裁好存 `static/showcase/`（`emoji/` 正方形 128px、
  `collection/` 3:4 宽 144 JPEG q85 + `manifest.json`）；`showcase_images()` 在目录缺失时
  返回 `[]` 并隐藏整条缩略图带。
- 主页所有图必须走 `_FlatImageLabel` + `_fit_image()`（预缩放到恰好 `逻辑尺寸 × dpr`、
  圆角一次性烤进 alpha、`paintEvent` 只 `drawImage(0,0,self._flat)` 纯 blit）；
  非方图必须先裁到目标比例，否则缩放照样每帧发生。
- `_FlatImageLabel` 与网格卡片图标的 `_apply_scaled_icon` / `_rescale` 是**两套并存机制**
  （主页 `ImageLabel` / 卡片 `QPushButton.setIcon`），不要互相替换。
- **主页每屏 20 个 `ImageLabel` 且滚动时每帧全跑一遍，禁止在此页新增上游 `ImageLabel`**。
- 队列预览显示前 4 项封面，不足 4 项少显示、多出显示 `+N`；
  队列封面 URL 口径统一在 `download_queue.item_cover_url(item)`，主页与 `QueueList` 必须共用。
- 主页的 `QScrollArea` / `ScrollArea` 必须显式透明，并用 `tune_scroll` 下调滚动步数。
- 主页只发信号、由 `MainWindow` 负责 `switchTo`，**页面不得反向引用主窗口**。
- 抓取脚本必须过滤非 http 的 `emote.url`（纯颜文字包的 `url` 字段是颜文字本身）。
- 「最近搜索」卡与 `_FlowHolder` 已整卡删除，禁止恢复；`EmojiPage.query_package_id` /
  `filter_packages` / `DressPage.search_keyword` 保留为公开入口。
