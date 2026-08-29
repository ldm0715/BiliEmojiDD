# 搜索历史 + 磁盘缓存 + 应用标识

本篇记录三件互相独立、但都指向「应用把每次操作都当第一次」的改动：搜索框有了记忆、
图片与接口响应会落盘复用、窗口和设置页有了统一的应用标识。

## 一、改动前的问题

1. **搜索框没有记忆**。收藏集页每次都要重新敲关键词，表情包 ID 查询同理。
2. **缓存只做了一处**。`app/components/cache.py` 缓存了「全部表情包列表」（24h JSON），
   除此之外：
   - 缩略图走 `QPixmapCache`，那是**纯内存、Qt 默认上限只有 10 MB**——翻几页卡片就被挤掉，
     回头再看要重下，重启后全部重下；
   - 收藏集搜索、表情包详情、收藏集详情**完全没缓存**，同一个关键词搜两次就是两次网络请求。
3. **没有应用标识**。标题栏无图标、标题写着「B 站表情包下载器」，设置页顶部只有一个「设置」。
4. 附带发现两个交互问题：
   - 三个 `SearchLineEdit` 都没接 `searchSignal`，**点放大镜图标毫无反应**
     （库内部只把按钮连到自己的 `search()`，信号得使用方自己接）；
   - 「全部表情包」的关键词过滤接的是 `textChanged`，**每敲一个字就重排整页**。

## 二、搜索历史（`app/components/search_history.py`）

### 形态：浮层下拉，不是常驻行

第一版做成了命令卡里的常驻胶囊行，问题是**它会挤占页面版面**、把结果区往下推。
改成浮层面板：

- 面板的 parent 是**顶层窗口**（`edit.window()`），几何自己 `setGeometry` 管理、
  **不进任何布局**，因此完全不参与父级的尺寸计算——命令卡高度在有无记录时完全一致；
- 点搜索框（`FocusIn` / `MouseButtonPress`）展开，失焦或鼠标移出收起，动画直接动 `geometry`；
- 内容是胶囊形记录（悬停出现 × 删除单条）+ 末尾「清空」。

```
SearchHistory        %APPDATA%/biliEmojiDD/search_history.json，按 namespace 分表
                     （dress / emoji_id / emoji_filter），每表最多 10 条 MRU
_HistoryChip         PillPushButton + setCheckable(False) + 悬停出现的 TransparentToolButton(×)
SearchHistoryPanel   SimpleCardWidget 浮层：FlowLayout 装胶囊 + 「清空」，
                     构造时给 edit 装事件过滤器，展开/收起全自动
```

页面侧只有三行接线：建面板、`activated` 接回填 + 触发搜索、真正发起搜索时 `record()`。

### 三处踩坑

- **不要覆写 `PillPushButton.__init__`**。`PushButton.__init__` 是库自己实现的
  `singledispatchmethod`，`(text, parent)` 那个重载内部会**再调一次
  `self.__init__(parent=parent)`**；子类若把 `text` 声明成必填位置参数，这次内部调用直接
  `TypeError: __init__() missing 1 required positional argument: 'text'`（真实崩过）。
  子类初始化一律走库留的 `_postInit()` 钩子——注意它在 `setText` 之前执行，
  依赖文本的东西（如 tooltip）只能建完对象再设。
- **鼠标移到子控件上，父控件会收到 `leaveEvent`**。删除按钮是胶囊的子控件，
  在 `leaveEvent` 里直接 `hide()` 会导致「一悬停 × 就消失、永远点不到」。
  判据要加一层「指针是否仍在自己的矩形内」（`rect().contains(mapFromGlobal(QCursor.pos()))`）。
- **× 必须恒定占位**。只在 hover 时才给它留宽度，胶囊会在鼠标进出时来回跳。
  做法是覆写 `sizeHint()` 恒定 `+ (按钮宽 + 2×边距)`。
- **`FlowLayout.takeAt(index)` 返回 widget 不是 QLayoutItem**：清空用库自带的
  `takeAllWidgets()`（内部已 `deleteLater`）。但**「清空」按钮是常驻的**，重建前必须先
  `removeWidget(clearBtn)` 把它摘出来，否则会被一起 `deleteLater`，下次访问就是野对象。
- **父级隐藏时子控件收到的是 `HideToParent` 而不是 `Hide`**：切换导航页要收起浮层，
  两个事件都得接。
- 尺寸：库按钮默认 32~34 高、字号 14，塞进下拉面板显得比搜索框还笨重。
  胶囊固定 26 高 + `setFont(chip, 12)`，单行面板 42 高（搜索框 33），才算小巧。

### 触发时机统一

三个搜索框现在都是「**回车 / 点放大镜 / 点主按钮**才发起」，不再有输入即触发：

| 搜索框 | 触发 | namespace |
|---|---|---|
| 收藏集页 `kwEdit` | 搜索按钮 / 回车 / 放大镜 | `dress` |
| 表情包页 `idEdit` | 查询按钮 / 回车 / 放大镜 | `emoji_id` |
| 全部表情包 `filterEdit` | 回车 / 放大镜（点 × 清空则恢复全部） | `emoji_filter` |

## 三、磁盘缓存

### 分层

```
缩略图：  内存 QPixmapCache  →  磁盘 image_cache  →  网络
接口：    磁盘 api_store（TTL） →  biliemoji 请求
```

`QPixmapCache` 的上限从默认 10 MB 提到 64 MB（`thumb.py` 里 `setCacheLimit`，单位 KB）——
这是「同一批卡片来回翻页要重下」的直接原因。

### `app/components/disk_cache.py`

```python
class DiskCache:
    def __init__(name, *, limit_fn=None, ttl=None, touch_on_read=True)
    get(key, *, ttl=None) -> bytes | None
    put(key, data)      # 写 .part 再 os.replace 原子落盘
    size() / clear()

image_cache = DiskCache("images")                       # 无 TTL，纯 LRU
api_store   = DiskCache("api", touch_on_read=False)     # TTL 由调用方给
```

实现取舍：

- **不写索引文件**。LRU 时间戳直接用文件 `mtime`（读命中时 `os.utime` 刷新），
  没有索引就没有「索引与实际文件不一致 / 索引损坏」这类问题，代价只是淘汰时扫一次目录。
  注意 TTL 与 LRU 冲突，所以 `touch_on_read=False` 的实例才用 TTL——否则读一次就永不过期。
- **上限每次 `put` 时现读 `cfg.cache_limit_mb.value`**，改设置立即生效，无需重启。
  超限后按 mtime 升序删到上限的 90%（留出余量，避免每次 put 都扫目录）。
- 接口缓存单独封顶（`max(8MB, min(64MB, 上限/8))`），不挤占图片配额。
- 全程 `threading.RLock`（worker 线程并发调用），**所有异常吞掉**——缓存坏掉最多多一次
  网络请求，绝不能把主流程带崩（沿用 `cache.py` 的约定）。

### `app/components/api_cache.py`

三个函数替换掉页面里直接 new `Emoji` / `Dress` 的写法，**只在 worker 线程调用**：

| 函数 | key | TTL |
|---|---|---|
| `search_dress(num, keyword)` | `dress:search:{num}:{keyword}` | 6 小时 |
| `emoji_package(pid)` | `emoji:pkg:{pid}` | 24 小时 |
| `dress_collection(act, lot)` | `dress:coll:{act}:{lot}` | 24 小时 |

能这么做的前提：`EmotePackage` / `DressCollection` / `DressCollectionSummary` 都带 `raw`
原始 dict 与 `from_dict`，缓存存 raw、读回来**无损重建**。
**只缓存成功结果**——`AuthRequired` / `DressNotFound` 照常抛给 `show_bili_error`。
key 不掺 cookie 指纹：这三个接口的返回与账号无关（`all_packages` 是例外，仍在 `cache.py`）。

调用点：`dress_page`（搜索 / 详情）、`emoji_page`（ID 查询 / 列表进详情）、
`content_meta._MetaTask`（队列页的内容数量）。顺带的收益是**队列页与详情页共用同一份缓存**，
进过详情的项在队列里零请求。

### 为什么视频不进持久缓存

收藏集视频单个几十 MB，进配额会瞬间挤掉成千上万张图片，收益却只对「反复看同一个收藏集」
有效。维持 `video_cache.py` 现状：会话临时目录、退出即删；已整包下载过的收藏集仍然走
`_adopt_downloaded_videos` 直接播本地文件。

### 设置项

`cfg.cache_limit_mb`（`RangeConfigItem`，64–8192，默认 512）。设置页新增「缓存」分组：

- **缓存上限**：`SpinBox`（步长 64，宽度 140——四位数加上下按钮，给窄了会被裁），
  `valueChanged` 即时 `qconfig.set`；
- **缓存占用**：副标题显示 `已用 x.x MB / 上限 y MB` + 「清除缓存」按钮。
  扫目录与清除都走 `run_task`（文件可能上万，别卡主线程），`showEvent` 与清除完成后各刷一次。

## 四、应用标识

- 图标文件：`static/logo.ico`，定位走 `app/common/resource.py`
  （`STATIC_DIR` 按本文件位置回溯两级；文件缺失返回空 `QIcon`，不抛）。
- 窗口：`MainWindow.initWindow` 里 `setWindowIcon(app_icon())` + `setWindowTitle("BiliEmojiDD")`。
  **不需要自定义标题栏**——`FluentTitleBar` 自带 `iconLabel` + `titleLabel`，
  且已连好 `windowIconChanged` / `windowTitleChanged`，设这两项即可。
- `main.py` 里 `app.setWindowIcon(...)`，任务栏与弹窗继承。
- 设置页顶部换成身份行：`IconWidget`(36) + `TitleLabel("BiliEmojiDD")` +
  `CaptionLabel("v0.1.0")`。版本号来自 `app/common/config.APP_VERSION`
  （与 `pyproject.toml` 手工对齐：`[tool.uv] package=false`，拿不到 `importlib.metadata`）。
  缩进仍走**布局边距**，不用 `setContentsMargins`（组件库 Label 套了 QSS，会被重算掉）。

## 五、验证

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_search_cache.py
```

覆盖：`SearchHistory` 的 MRU/上限/持久化/namespace 隔离、面板不占布局 + 展开收起时机 +
胶囊尺寸、`DiskCache` 的往返/TTL/淘汰顺序、`api_cache` 第二次调用零请求、
三个搜索框的触发时机、设置页身份头与缓存分组。

写这类断言时的两个注意点：

- **配置目录要隔离**：`APP_CONFIG_DIR` 在 import 时按 `APPDATA` 算，脚本必须在
  `import app.*` **之前**把 `APPDATA` 指到临时目录，否则会写脏用户真实配置与历史。
- **等动画要等真实时间**：`processEvents()` 不推进时钟，且只等「高度 > 0」会量到动画中间帧
  （曾断言到 11px 而不是最终的 42px）。要轮询等 `QPropertyAnimation.state() != Running`。
- 离屏平台窗口不激活，`setFocus()` 未必发 `FocusIn`，直接 `sendEvent(QFocusEvent(...))` 更稳。
