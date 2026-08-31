"""GIF 判定与动图播放的共用入口。

两条职责，刻意分开口径：

- **角标判定走数据字段**（`pkg.is_gif` / `em.gif_url`）：不必等图片下载完就能显示，
  列表页翻页时角标是即时的。
- **播放走原始字节**：`thumb.py` 把下载到的字节解成 `QImage` 后就丢了（只留 QPixmap），
  但落盘那一层 `image_cache` 还留着**原始 GIF 字节**（`thumb.py` 未命中时 put 进去）。
  所以主线程可以直接把字节喂给 `QMovie`，不用改线程层、也不用重新联网。

字节拿不到（磁盘缓存被 LRU 淘汰而内存 `QPixmapCache` 仍在）时一律返回 None，静默不播 ——
动图播不了顶多回到原来的静态观感，不值得为它再发一次请求。
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QObject
from PySide6.QtGui import QMovie

from app.components.disk_cache import image_cache


def package_has_gif(pkg) -> bool:
    """表情包里有没有动图。

    两个判据取并集：`meta.label_text`（B 站给的 GIF 标记，全量列表里只有它）与
    包内任一表情的 `gif_url`（按 ID 查询回来的包才有 emote）。
    与 `download_package_batch` 里 `if use_gif and em.gif_url` 的实际取用口径一致。
    """
    if pkg is None:
        return False
    if getattr(pkg, "is_gif", False):
        return True
    return any(em.gif_url for em in getattr(pkg, "emote", ()) or ())


def movie_from_cache(url: str | None, parent: QObject | None = None) -> QMovie | None:
    """用磁盘缓存里的原始字节造一个 QMovie；不是多帧动图则返回 None。

    `QMovie` 不接管 device 的生命周期：QBuffer 挂在 movie 上（parent 可能先销毁），
    字节交给 QBuffer 自己的内部缓冲（`setData` 是拷贝，不用另外保命）。
    """
    if not url:
        return None
    try:
        data = image_cache.get(url)
    except Exception:  # noqa: BLE001 缓存坏掉不该把界面带崩
        return None
    if not data:
        return None

    # 必须无参构造：`QMovie(None)` 在 PySide6 6.4.2 下会命中 `QMovie(QIODevice*)`
    # 那个重载、拿到一个空 device，之后 frameCount() 直接段错误。parent 单独设。
    movie = QMovie()
    if parent is not None:
        movie.setParent(parent)
    buffer = QBuffer(movie)
    buffer.setData(QByteArray(data))
    if not buffer.open(QBuffer.OpenModeFlag.ReadOnly):
        return None
    movie.setDevice(buffer)
    # frameCount() 对单帧图（PNG/JPG）返回 1，对损坏数据返回 0
    if not movie.isValid() or movie.frameCount() <= 1:
        return None
    return movie
