"""屏幕外验证「复制表情」：纯函数、网格接线、三层降级、失败静默、`_copy_wait` 清理。

用法：QT_QPA_PLATFORM=offscreen PYTHONIOENCODING=utf-8 uv run python scripts/check_clipboard.py

不走网络：字节预置进 `image_cache` / `QPixmapCache`，第 ③ 档用 `signal_bus` 直接驱动。
所有假 URL 都预置 `QPixmapCache`（否则每个 URL 会排一个 15s 超时任务、脚本退不出去）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 必须赶在 import app.* 之前隔离 APPDATA：缓存目录在 import 时就按它算好了
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtCore import QBuffer, QPoint
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import app.components.clipboard as clipboard_mod
import app.components.widgets as widgets_mod
from app.common.config import APP_CONFIG_DIR
from app.common.signal_bus import signal_bus
from app.components.clipboard import copy_image, copy_image_bytes
from app.components.disk_cache import image_cache
from app.components.thumb import thumb_manager
from app.components.widgets import (
    DressDetailGrid,
    DressGrid,
    EmojiGrid,
    PackageGrid,
    QueueList,
    VideoStrip,
)

clip = QGuiApplication.clipboard()

# 通知一律以模块全局名调用才打得中（见 check_proxy_hint.py 同一手法）
bars: list[tuple] = []
widgets_mod.notify_success = lambda title, content, **kw: bars.append((title, content))
widgets_mod.notify_warning = lambda title, content, **kw: bars.append((title, content))

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def formats() -> list[str]:
    return list(clip.mimeData().formats())


def set_sentinel() -> list[str]:
    """把剪切板置成一个已知状态，用来验「没被碰过」。"""
    clip.setText("sentinel")
    return formats()


# ---- 取样 ----

def png_bytes(size: int = 6) -> bytes:
    return _encode(size, "PNG")


def webp_bytes(size: int = 4) -> bytes:
    return _encode(size, "WEBP")


def _encode(size: int, fmt: str) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor("#3478f6"))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    assert img.save(buf, fmt), f"本机 Qt 写不出 {fmt}"
    return bytes(buf.data())


# 1x1 GIF89a：Qt 能读不能写，只能硬编码
GIF_BYTES = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c"
    "00000000010001000002024401003b"
)

URLS = [f"https://example.invalid/copy-{i}.png" for i in range(8)]
for url in URLS:
    pm = QPixmap(64, 64)
    pm.fill(QColor("#22aa55"))
    QPixmapCache.insert(url, pm)  # 预置：建卡时 request() 同步命中，不排网络任务

print("== 1. 纯函数：copy_image_bytes ==")
check(copy_image_bytes(GIF_BYTES), "GIF 字节复制成功")
check(clip.mimeData().hasImage(), "剪切板里有位图那份")
check(bytes(clip.mimeData().data("image/gif")) == GIF_BYTES, "原始 GIF 字节可原样取回")

fmts = formats()
check(
    "application/x-qt-image" in fmts
    and "image/gif" in fmts
    and fmts.index("application/x-qt-image") < fmts.index("image/gif"),
    f"位图排在 image/gif 之前（保序，不是集合比较）：{fmts}",
)

png = png_bytes(6)
check(copy_image_bytes(png), "PNG 字节复制成功")
img = clip.mimeData().imageData()
check(not img.isNull() and img.width() == 6, f"imageData 是原尺寸不是缩略图（{img.width()}px）")
check("image/gif" not in formats(), f"复制 PNG 后不残留 image/gif：{formats()}")

check(copy_image_bytes(webp_bytes()), "WebP 字节复制成功")
check(
    "image/webp" in formats() and bytes(clip.mimeData().data("image/webp")).startswith(b"RIFF"),
    f"WebP 挂 image/webp 而不是只给位图：{formats()}",
)

print("== 1b. 动图落文件走 CF_HDROP（唯一能真带动画的通道） ==")
check(clipboard_mod._CLIP_DIR.parent == APP_CONFIG_DIR,
      "剪贴板载荷不在 cache/ 下（否则「清除缓存」会删掉已复制好的动图）")
check(copy_image_bytes(GIF_BYTES), "前置：GIF 复制成功")
check("text/uri-list" in formats(), f"动图挂了文件通道（{formats()}）")
urls = clip.mimeData().urls()
check(len(urls) == 1, f"只挂一个文件（{len(urls)}）")
gif_path = Path(urls[0].toLocalFile()) if urls else None
check(gif_path is not None and gif_path.exists(), f"文件真的落盘了（{gif_path}）")
check(gif_path is not None and gif_path.suffix == ".gif", "扩展名是 .gif（目标靠它认动图）")
check(gif_path is not None and gif_path.read_bytes() == GIF_BYTES,
      "文件内容是**原始** GIF 字节，动画未损")
check(clip.mimeData().hasImage(), "位图那份同时保留（粘进画图 / Word 仍出图）")

files_before = {p.name for p in clipboard_mod._CLIP_DIR.iterdir()}
copy_image_bytes(GIF_BYTES)
check(Path(clip.mimeData().urls()[0].toLocalFile()) == gif_path,
      "同内容复用同一个文件，不重复堆积")
check({p.name for p in clipboard_mod._CLIP_DIR.iterdir()} == files_before,
      "重复复制没有多出文件")

copy_image_bytes(webp_bytes())
webp_path = Path(clip.mimeData().urls()[0].toLocalFile())
check(webp_path.suffix == ".webp", f"WebP 同样走文件通道（{webp_path.suffix}）")

print("== 1c. 静态图不挂文件通道 ==")
files_before = {p.name for p in clipboard_mod._CLIP_DIR.iterdir()}
check(copy_image_bytes(png), "前置：PNG 复制成功")
check("text/uri-list" not in formats(), f"静态图只给位图（{formats()}）")
check({p.name for p in clipboard_mod._CLIP_DIR.iterdir()} == files_before,
      "静态图不产生剪贴板文件（位图粘到哪都是内嵌图，不需要文件）")

print("== 1d. 剪贴板文件按 mtime 淘汰 ==")
for p in clipboard_mod._CLIP_DIR.iterdir():
    p.unlink()
for i in range(40):
    f = clipboard_mod._CLIP_DIR / f"f{i}.gif"
    f.write_bytes(b"x")
    os.utime(f, (1000 + i, 1000 + i))  # i 越大越新
clipboard_mod._prune()
left = sorted(p.name for p in clipboard_mod._CLIP_DIR.iterdir())
check(len(left) == clipboard_mod._KEEP_FILES,
      f"淘汰到 {clipboard_mod._KEEP_FILES} 个（实际 {len(left)}）")
check("f39.gif" in left, "最新的那份保住（正在被剪切板引用的就是它）")
check("f7.gif" not in left and "f8.gif" in left, "淘汰的是最老的那批")

print("== 1e. 纯函数：失败路径无副作用 ==")
before = set_sentinel()
check(not copy_image_bytes(b"<html>404</html>"), "解不成图的字节返回 False")
check(formats() == before, "失败时完全不碰剪切板")
check(not copy_image_bytes(b""), "空字节返回 False 不炸")
check(formats() == before, "空字节同样没碰剪切板")
check(not copy_image(QImage()), "copy_image(空图) 返回 False")
check(formats() == before, "copy_image(空图) 没碰剪切板")
check(not copy_image(None), "copy_image(None) 返回 False")
check(formats() == before, "copy_image(None) 没碰剪切板")

print("== 2. 网格接线：只有表情网格开复制 ==")
check(EmojiGrid._copyable is True, "EmojiGrid 开 _copyable")
for cls in (PackageGrid, DressGrid, DressDetailGrid, QueueList, VideoStrip):
    check(cls._copyable is False, f"{cls.__name__} 不开 _copyable")

grid = EmojiGrid()
grid.resize(400, 300)
grid.set_emotes([("e0", URLS[0]), ("e1", URLS[1]), ("e2", URLS[2])])
grid.show()
app.processEvents()

menu = grid._build_context_menu(URLS[0])
texts = [a.text() for a in menu.actions()]
check(texts == ["复制表情", "重新加载"], f"表情网格菜单项与顺序（{texts}）")
menu.deleteLater()

other = PackageGrid()
other.resize(400, 300)
app.processEvents()
menu2 = other._build_context_menu(URLS[0])
texts2 = [a.text() for a in menu2.actions()]
check(texts2 == ["重新加载"], f"其他网格没有复制项（{texts2}）")
menu2.deleteLater()

center = grid.visualItemRect(grid.item(0)).center()
check(grid._context_url(center) == URLS[0], "_context_url 取到该格的 url")

blank = QPoint(grid.viewport().width() - 2, grid.viewport().height() - 2)
check(grid.itemAt(blank) is None, "前置：取的确实是空白点")
check(grid._context_url(blank) is None, "空白处右键不弹菜单（返回 None）")

print("== 2b. 菜单项真的接到复制路径 ==")
image_cache.put(URLS[0], GIF_BYTES)
QPixmapCache.remove(URLS[0])
menu3 = grid._build_context_menu(URLS[0])
menu3.actions()[0].trigger()  # 不 exec()，绕开嵌套事件循环
check(bytes(clip.mimeData().data("image/gif")) == GIF_BYTES, "触发菜单项后剪切板里是原始 GIF")
menu3.deleteLater()

print("== 3. 三层降级 ==")
print("-- 3a. ① 磁盘缓存的原始字节（同步） --")
url = URLS[1]
image_cache.put(url, GIF_BYTES)
QPixmapCache.remove(url)
grid.copy_url(url)
check(bytes(clip.mimeData().data("image/gif")) == GIF_BYTES, "①②同步路径拿到原始 GIF 字节")
check(grid._copy_wait is None, "同步成功不进等待态")

print("-- 3b. ② 内存位图兜底（磁盘那份被淘汰） --")
url = URLS[2]
image_cache.remove(url)
pm = QPixmap(64, 64)
pm.fill(QColor("#cc3344"))
QPixmapCache.insert(url, pm)
grid.copy_url(url)
img = clip.mimeData().imageData()
check(not img.isNull() and img.width() == 64, f"兜底拿的是全尺寸位图（{img.width()}px，不是 72px 图标）")
check("image/gif" not in formats(), "这条路径只有位图，不谎报动图")
check(grid._copy_wait is None, "兜底成功也不进等待态")

print("-- 3c. ③ 两处都没有：委派缩略图流水线 --")
url = URLS[3]
image_cache.remove(url)
QPixmapCache.remove(url)
# 既模拟「worker 正在飞」，又让 request() 早退 —— 否则假 URL 会排一个 15s 超时任务
thumb_manager._inflight.add(url)
before = set_sentinel()
grid.copy_url(url)
check(grid._copy_wait == url, "登记了等待中的 url")
check(formats() == before, "字节还没到时不碰剪切板")

print("-- 3d. ③ 完成：重读磁盘仍保住动图口径 --")
image_cache.put(url, GIF_BYTES)
signal_bus.thumbLoaded.emit(url, QPixmap(8, 8))
app.processEvents()
check(bytes(clip.mimeData().data("image/gif")) == GIF_BYTES, "回来时重读磁盘，动图字节还在")
check(grid._copy_wait is None, "完成后清掉等待标志")
check(len(bars) == 1 and bars[0][0] == "已复制", f"异步完成才提示（{bars}）")

print("-- 3e. ③ 完成但磁盘那份没落成：退回位图 --")
bars.clear()
url = URLS[4]
image_cache.remove(url)
QPixmapCache.remove(url)
thumb_manager._inflight.add(url)
grid.copy_url(url)
check(grid._copy_wait == url, "前置：确实进了等待态")
set_sentinel()  # 清掉上一轮的残留，否则下面断言量到的是旧剪切板
QPixmapCache.insert(url, pm)  # 真实情况下 ThumbManager 发信号前刚 insert 过
signal_bus.thumbLoaded.emit(url, pm)
app.processEvents()
check(clip.mimeData().hasImage(), "磁盘那份没有时退回内存位图")
check("image/gif" not in formats(), f"这条路径不谎报动图（{formats()}）")
check(grid._copy_wait is None, "标志照样清掉")

print("-- 3f. ③ 失败：清标志 + 提示（否则之后永远卡在等字节） --")
bars.clear()
url = URLS[5]
image_cache.remove(url)
QPixmapCache.remove(url)
thumb_manager._inflight.add(url)
grid.copy_url(url)
signal_bus.thumbRawFailed.emit(url)
app.processEvents()
check(grid._copy_wait is None, "失败也清掉等待标志")
check(len(bars) == 1 and bars[0][0] == "复制失败", f"失败弹一条提示（{bars}）")

print("-- 3g. 失败静默：同步成功不弹任何提示 --")
bars.clear()
url = URLS[6]
image_cache.put(url, GIF_BYTES)
QPixmapCache.remove(url)
grid.copy_url(url)
check(clip.mimeData().hasImage(), "前置：确实复制成功了")
check(bars == [], f"同步成功保持静默（{bars}）")

print("== 4. 边界 ==")
before = set_sentinel()
grid.copy_url("")
check(formats() == before, "copy_url('') 安静返回")
grid.copy_url(None)
check(formats() == before, "copy_url(None) 安静返回")
check(grid._copy_wait is None, "边界路径不留等待态")

image_cache.put(URLS[7], GIF_BYTES)
QPixmapCache.remove(URLS[7])
before = set_sentinel()
PackageGrid().copy_url(URLS[7])
check(formats() == before, "非复制网格的 copy_url 也挡着（闸门不只在菜单里）")

for url in URLS:
    thumb_manager._inflight.discard(url)  # 清掉 3c/3e/3f 我们自己塞的假状态，否则退不出去

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
