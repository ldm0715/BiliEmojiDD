# 加载失败后的「重新加载」

## 背景

缩略图和收藏集视频都走「后台线程下载 → 信号回主线程」的路子，两边都对失败做了**记忆**：

- `thumb.py` 里失败的 URL 只是被移出 `_inflight`，而网格的 `_CardGridBase._requested`
  已经记下这个 URL，`_update_visible` 之后**再也不会重新 request**；卡片停在灰底。
- `video_cache.py` 更硬：失败的 URL 进 `_failed`，`request()` 直接早退，**本会话永不重试**
  （这是为了防请求风暴，本身没错）。播放器只显示一句「视频加载失败」。

结果就是：网络抖一下 / B 站偶发 5xx，用户除了退出重进整个应用，没有任何办法让它重来一次。
本次给这条路补上出口：**右键菜单**（统一入口）+ **失败态直接可点**（右键是隐藏功能，
真加载失败的人不一定会去试）。

## 涉及文件

| 文件 | 职责 |
|---|---|
| `app/components/disk_cache.py` | `DiskCache.remove(key)`：按 `_digest` 删一条缓存文件 |
| `app/components/thumb.py` | `ThumbManager.reload(url)`：作废三层缓存后重新请求 |
| `app/components/video_cache.py` | `VideoCacheManager.forget(url)`：清失败标记 + 临时文件 |
| `app/components/widgets.py` | `_SpinnerMixin` 的失败态「↻」按钮；`_CardGridBase._context_url` / `_build_context_menu` / `reload_url` |
| `app/components/image_viewer.py` | 查看器右键 →「重新加载」当前图 |
| `app/components/video_player.py` | 右键 / 点击失败提示 → `reload_current()` |
| `scripts/check_reload.py` | 屏幕外断言 |

## 一、缓存作废：顺序很要紧

图片有三层缓存：内存 `QPixmapCache` → 磁盘 `image_cache` → 网络。`reload()` 必须
**先清内存再 request**：

```python
def reload(self, url):
    QPixmapCache.remove(url)
    image_cache.remove(url)
    self._inflight.discard(url)
    self.request(url)
```

反过来写的话，`request()` 会命中还没清掉的 `QPixmapCache` 直接**同步 emit** 旧图，
看起来就像「点了重新加载但什么都没发生」。

视频侧 `forget(url)` 做三件事：清 `_failed`、清 `_cache`、**删临时文件**。第三件有个判据：

```python
if _temp_dir is None or _temp_dir not in target.parents:
    return   # 不是我们 mkdtemp 出来的，就只摘引用不删文件
```

因为 `remember()` 登记进来的可能是**用户下载目录里的成品 mp4**
（`_adopt_downloaded_videos` 会把已完整下载过的收藏集登记进来省掉重下）——
那是下载产物不是缓存，删掉就是删用户的文件。

Windows 上正在播放的文件被占用删不掉，`unlink` 的 `OSError` 直接吞掉即可：
`Downloader` 会覆盖重写。

## 二、网格：右键 + 失败态「↻」

统一在 `_CardGridBase` 上做，六个网格（表情 / 表情包 / 收藏集 / 详情 / 视频条 / 下载队列）
一次到位：

- `_context_url(pos)` / `_build_context_menu(url)` / `contextMenuEvent`：右键落点 → 取
  `UserRole` 里的封面 url（空白处返回 None、不弹菜单）→ `RoundMenu` 一项「重新加载」。
  建菜单与 exec 拆开是为了可断言（`exec()` 会阻塞事件循环，屏幕外脚本调不了）——
  详见 `clipboard_copy.md` 第 5 节，那边在同一个菜单里多了「复制表情」一项。
- `reload_url(url)`：把 url 重新塞进 `_requested`（reload 自己会发请求，别让
  `_update_visible` 再排一次重复的）、对所有用这个 url 的卡片 `thumb_restart()`、
  最后 `thumb_manager.reload(url)`。

`_SpinnerMixin` 从「只有加载环」扩成三态：

| 方法 | 场景 | 效果 |
|---|---|---|
| `thumb_done()` | 图到位 | 收环、藏重试按钮 |
| `thumb_failed()` | `thumbRawFailed` | 收环、**亮出「↻」按钮** |
| `thumb_restart()` | 重新加载 | 藏按钮、转回加载环 |

「↻」按钮**不能**设 `WA_TransparentForMouseEvents`（加载环设了，因为它盖在图片按钮上
不能吃掉点击；重试按钮反过来必须收得到点击）。卡片自己不知道自己对应哪个 url，
所以回调由网格在 `set_cards` 建卡时注入：`card._retry_cb = partial(self.reload_url, url)`。

**踩坑**：显隐切换之后要重新居中（`_relayout_overlay`）—— 卡片不一定会再收到 `resizeEvent`，
不补这一下按钮会停在 (0, 0)。判据仍然是 `isHidden()` 而**不是** `not isVisible()`，
原因见 `CLAUDE.md`「缩略图加载环」那条。

## 三、播放器：失败提示本身可点

`_show_hint(text, retry=True)` 时把 `WA_TransparentForMouseEvents` 摘掉、换手型光标、
文案补成「视频加载失败，点击重试」；`_show_spinner` 与 `_hide_overlay` 都会把它设回穿透
（缓冲中点了没意义，状态也不能残留到下一次）。

提示 Label 为此从 `BodyLabel` 换成本文件的 `_HintLabel`（多一个 `clicked` 信号）。
**不覆写 `__init__`**：`FluentLabelBase.__init__` 是 `singledispatchmethod`，
`(text, parent)` 那个重载内部会再调一次 `self.__init__(parent)`，子类改签名直接 TypeError
（同 `PushButton` / `InfoBadge` 的坑）。

`reload_current()` = `video_cache.forget(当前 url)` + `play(当前下标)`，右键菜单与
点击提示共用这一条路径。

## 四、验证

```bash
QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_reload.py
```

覆盖：内存 / 磁盘两层作废、`remove` 对不存在的 key 不炸、网格失败 → 亮按钮 → 点重试 →
转回加载环、右键路径与按钮路径一致、图到位后按钮不残留、`forget` 删临时文件但**不删**
下载目录里的成品、播放器失败态可点而缓冲态穿透。

图片查看器那一路的右键重载断言在 `scripts/check_image_viewer.py` 里。

真实的「网络失败 → 重试成功」需要人工断网 / 恢复网络验证，无法自动化。
