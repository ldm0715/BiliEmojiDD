"""屏幕外验证「重新加载」：缓存作废、网格右键 / 失败态重试、视频缓存 forget。

用法：QT_QPA_PLATFORM=offscreen uv run python scripts/check_reload.py

不走网络：图片用预置的 QPixmapCache + 直接喂 signal_bus 的失败信号模拟；
视频侧把 video_cache 的联网关掉，只验状态机。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根

# 必须赶在 import app.* 之前隔离 APPDATA：缓存目录在 import 时就按它算好了
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="biliEmojiDD-check-")

from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.common.signal_bus import signal_bus
from app.components.content_meta import content_meta
from app.components.disk_cache import image_cache
from app.components.thumb import thumb_manager
from app.components.video_cache import _cache_dir, video_cache
from app.components.widgets import EmojiGrid

# 假 URL 会排一堆 15s 超时任务，脚本跑完退不出去
content_meta.set_enabled(False)
video_cache.set_enabled(False)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


URLS = [f"https://example.invalid/reload-{i}.png" for i in range(3)]
for url in URLS:
    pm = QPixmap(48, 48)
    pm.fill(QColor("#3478f6"))
    QPixmapCache.insert(url, pm)

print("== 1. thumb_manager.reload 作废内存 + 磁盘两层 ==")
url = URLS[0]
image_cache.put(url, b"fake-bytes")
check(image_cache.get(url) == b"fake-bytes", "前置：磁盘缓存里确实有这条")
thumb_manager.reload(url)
app.processEvents()
check(image_cache.get(url) is None, "reload 后磁盘缓存已删")
# reload 里 request() 会重新走网络（假 URL 必然失败），这里只关心缓存被清掉了
probe = QPixmap()
found = QPixmapCache.find(url, probe)
check(not found, "reload 后内存缓存已作废（否则 request 会同步 emit 旧图）")

print("== 1b. DiskCache.remove 对不存在的 key 不炸 ==")
image_cache.remove("https://example.invalid/never-cached.png")
check(True, "删一条没有的缓存安静返回")

print("== 2. 网格：失败 → 亮出重试按钮 → 重新加载 ==")
# 这一格故意不预置进 QPixmapCache：命中缓存的话 request() 会同步 emit、当场收环
failed_url = "https://example.invalid/reload-pending.png"
grid = EmojiGrid()
grid.resize(400, 300)
grid.set_cards([("e0", URLS[1]), ("e1", failed_url), ("e2", URLS[2])])
grid.show()
app.processEvents()

card = grid.itemWidget(grid.item(1))
check(not card._spinner.isHidden(), "建卡后加载环在转")
check(card._retryBtn.isHidden(), "还没失败时不显示重试按钮")

signal_bus.thumbRawFailed.emit(failed_url)
app.processEvents()
check(card._spinner.isHidden(), "失败后收环（别让灰底上一直转假的加载中）")
check(not card._retryBtn.isHidden(), "失败后亮出「↻」重试按钮")

grid._requested.discard(failed_url)
card._retryBtn.click()
app.processEvents()
check(card._retryBtn.isHidden(), "点重试后按钮收起")
check(not card._spinner.isHidden(), "点重试后加载环转回来")
check(failed_url in grid._requested, "重试已登记，_update_visible 不会再排一次重复请求")

print("== 2b. 右键菜单走的是同一条路径 ==")
signal_bus.thumbRawFailed.emit(failed_url)
app.processEvents()
check(not card._retryBtn.isHidden(), "前置：再失败一次")
grid.reload_url(failed_url)
app.processEvents()
check(card._retryBtn.isHidden() and not card._spinner.isHidden(), "reload_url 后回到加载中")
grid.reload_url("")  # 空 url 不该炸
check(True, "reload_url('') 安静返回")

print("== 2c. 图到位后重试按钮不会残留 ==")
pm = QPixmap(48, 48)
pm.fill(QColor("#22aa55"))
signal_bus.thumbLoaded.emit(failed_url, pm)
app.processEvents()
check(card._retryBtn.isHidden() and card._spinner.isHidden(), "加载成功后加载环与重试按钮都收起")

print("== 3. video_cache.forget ==")
video_url = "https://example.invalid/v1.mp4"
temp_file = _cache_dir() / "fake.mp4"
temp_file.write_bytes(b"x")
video_cache.remember(video_url, temp_file)
video_cache._failed.add(video_url)  # 模拟「本会话已失败」
check(video_cache.local_path(video_url) is not None, "前置：缓存里有这个视频")
video_cache.forget(video_url)
check(not video_cache.failed(video_url), "forget 清掉失败标记（否则本会话永不重试）")
check(video_cache.local_path(video_url) is None, "forget 清掉缓存路径")
check(not temp_file.exists(), "临时目录里的文件被删掉，下次真的重下")

print("== 3b. forget 不碰用户下载目录里的成品 ==")
download_dir = Path(tempfile.mkdtemp(prefix="biliEmojiDD-dl-"))
kept = download_dir / "已下载.mp4"
kept.write_bytes(b"x")
video_cache.remember(video_url, kept)
video_cache.forget(video_url)
check(kept.exists(), "下载目录里的 mp4 是下载产物不是缓存，不能删")
check(video_cache.local_path(video_url) is None, "但引用仍然摘掉了，会重新下到临时目录")
video_cache.forget(None)
check(True, "forget(None) 安静返回")

print("== 4. 播放器：失败态可点，缓冲态不可点 ==")
from PySide6.QtCore import Qt

from app.components.video_player import CollectionVideoPlayer

player = CollectionVideoPlayer()
player.resize(400, 400)
player.set_videos([("v1", video_url)])
player.show()
app.processEvents()

transparent = Qt.WidgetAttribute.WA_TransparentForMouseEvents
player._show_spinner("正在缓冲…")
check(player.hintLabel.testAttribute(transparent), "缓冲中提示鼠标穿透（点了也没意义）")
player._show_hint("视频加载失败", retry=True)
check(not player.hintLabel.testAttribute(transparent), "失败态提示可点击")
check("点击重试" in player.hintLabel.text(), f"失败文案带指引（{player.hintLabel.text()!r}）")
player._hide_overlay()
check(player.hintLabel.testAttribute(transparent), "收起覆盖层后状态不残留")

video_cache._failed.add(video_url)
player._index = 0
player.reload_current()
app.processEvents()
check(not video_cache.failed(video_url), "reload_current 会先 forget 再重播")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL PASSED")
