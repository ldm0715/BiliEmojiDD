"""把图片放进系统剪切板（右键「复制表情」的落点）。

字节来源与 `gif.py` 同源：`thumb.py` 下载缩略图时会 `image_cache.put(url, data)`，
**原始字节**（含完整 GIF / WebP）留在磁盘缓存里 —— 复制不必重新联网。

放 `components/` 而不是 `common/`：同性质的「原始字节 → 介质」先例 `gif.py` 在这里。
本模块只依赖 PySide6 与 `APP_CONFIG_DIR` 这个路径常量，不读 `cfg` 运行时状态、
不碰 `net` / `task`，所以可以直接在屏幕外断言里驱动。

## 两条通道，只有一条能带动图

Windows 上「粘贴图片」走的是 CF_DIB —— 一张**纯位图**，数据结构里没有「帧序列」，
动画无处安放。微信 / QQ / 画图粘贴时读的就是它，所以只写位图的话动图必然变静态首帧。

**能携带一个真正的 .gif 文件的只有 CF_HDROP**（文件拖放格式，即「把文件拖进窗口」用的
那条通道）。所以动图额外把字节落成文件、挂 `text/uri-list`（Qt 会转成 CF_HDROP）。

位图那份**照旧一起留着**：CF_HDROP 只在部分目标里会被当成内嵌图片，粘进画图 / Word
可能变成「一个文件」；两份都给，让目标自己挑。哪个优先由目标决定，我们控制不了。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QImage

from app.common.config import APP_CONFIG_DIR

# 动图判据用**魔数**，不跟 URL 后缀：这里手上已经是字节，而后缀那套口径
# （`live_emoji.emote_is_gif`）是给「还没下载、只能看地址」的场景用的。
#
# WebP 必须一起认 —— `emote_is_gif` 把 `.webp` 算动图、`movie_from_cache` 也认它，
# 只判 GIF 会让直播间表情里那些**真能播的 webp** 复制出去只剩首帧，
# 而直播间表情网格正是这个功能的两个落点之一。
_GIF_MAGIC = b"GIF8"  # GIF87a / GIF89a
_RIFF_MAGIC = b"RIFF"
_WEBP_MAGIC = b"WEBP"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# 要落成文件走 CF_HDROP 的那几种（mime → 扩展名）。
# **扩展名不能省**：目标程序靠它认「这是个动图」，没有后缀的剪贴板文件多半被当普通附件。
_FILE_MIME = {"image/gif": ".gif", "image/webp": ".webp"}

# 剪贴板载荷放 `clipboard/` 而**不是** `cache/`：设置页的「清除缓存」
# （`disk_cache.clear_all`）会清 `cache/`，那会把用户已经复制好的动图删掉 ——
# 这些东西不是缓存，是被剪切板引用着的**载荷**，得活到用户粘贴完为止。
_CLIP_DIR = APP_CONFIG_DIR / "clipboard"
_KEEP_FILES = 32  # 保留最近这些次复制的动图，多于这个数按 mtime 淘汰最老的


def _raw_mime(data: bytes) -> str | None:
    """原始字节该挂哪个 mime；认不出来就返回 None（只靠位图那份）。"""
    if data[:4] == _GIF_MAGIC:
        return "image/gif"
    if data[:4] == _RIFF_MAGIC and data[8:12] == _WEBP_MAGIC:
        return "image/webp"
    if data[:8] == _PNG_MAGIC:
        return "image/png"
    # 别的格式（jpg 等）**不冒充** PNG：挂错 mime 比不挂更糟，位图那份照样能用
    return None


def _stage_file(data: bytes, mime: str) -> Path | None:
    """把动图字节落成带正确扩展名的文件，返回路径；失败返回 None。

    文件名取内容 sha1，所以同一张表情复制多次只有一个文件（复用时 `utime` 刷新 mtime）。
    **落盘失败不是错误**：那只是退回「只有位图」，不该让整次复制失败。
    """
    path = _CLIP_DIR / (hashlib.sha1(data).hexdigest() + _FILE_MIME[mime])
    try:
        _CLIP_DIR.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # 与 disk_cache 同款：先写 .part 再 os.replace，写一半被杀不会留下半截文件
            tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        os.utime(path, None)
        _prune()
    except OSError:
        return None
    return path


def _prune() -> None:
    """按 mtime 淘汰到 `_KEEP_FILES` 以内（最久没复制的先走）。

    正在写的那份刚 `utime` 过，始终是最新的，不会被自己删掉。
    被淘汰的是更早的复制内容 —— 那些早就不在剪切板上了。
    """
    entries = []
    try:
        for entry in os.scandir(_CLIP_DIR):
            try:
                if entry.is_file():
                    entries.append((entry.stat().st_mtime, entry.path))
            except OSError:
                continue
    except OSError:
        return
    for _, path in sorted(entries)[:-_KEEP_FILES]:
        try:
            os.unlink(path)
        except OSError:
            pass


def copy_image_bytes(data: bytes) -> bool:
    """把原始字节放进剪切板；解不成图时返回 False 且**完全不碰剪切板**。

    位图（给只认位图的目标）+ 原始动图字节（给认 mime 的目标）+ **动图落文件走
    CF_HDROP**（唯一能真带动画的通道，见模块 docstring）。

    `setImageData` 必须**先**调：`QMimeData.formats()` 保持插入顺序，位图排前面最稳。
    """
    if not data:
        return False
    image = QImage()
    if not image.loadFromData(data):
        return False
    mime = QMimeData()
    mime.setImageData(image)
    raw = _raw_mime(data)
    if raw is not None:
        mime.setData(raw, QByteArray(data))
    if raw in _FILE_MIME:
        path = _stage_file(data, raw)
        if path is not None:
            mime.setUrls([QUrl.fromLocalFile(str(path))])
    QGuiApplication.clipboard().setMimeData(mime)
    return True


def copy_image(image: QImage) -> bool:
    """把已解码的图放进剪切板（磁盘缓存被 LRU 淘汰时的兜底）。

    这条路径只有位图，**没有原始动图字节**，所以动图只能粘出首帧。
    """
    if image is None or image.isNull():
        return False
    QGuiApplication.clipboard().setImage(image)
    return True
