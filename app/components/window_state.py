"""窗口几何的持久化：记住上次关闭时窗口在哪块屏幕的哪个位置、多大。

**用 Qt 自带的 `saveGeometry()` / `restoreGeometry()`，不手写 x/y/w/h 四个字段。**
那一个不透明的 blob 里连**最大化状态**、**所在屏幕**与 **DPI** 一起编码了，恢复时 Qt
还会自己把跑到屏幕外的窗口拉回来——副屏拔掉、分辨率变小、外接显示器换位置都属于
这一类。手写字段就得自己处理 `normalGeometry()`、屏幕归属与 DPI 换算，三件事都有
微妙的坑，换来的只是配置文件里多几个看得懂的数字。

写盘只发生在 `MainWindow.closeEvent`：应用退出一律走 `window.close()` 而不是
`QApplication.quit()`（见 `.claude/rules/architecture.md`），所以这条路径一定跑得到。
反过来，**不做 `moveEvent` / `resizeEvent` 上的防抖落盘**——拖动窗口时会反复写盘，
而收益只是「被任务管理器强杀也能记住」。
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QWidget
from qfluentwidgets import qconfig

from app.common.config import cfg


def save_window_state(window: QWidget) -> None:
    """把窗口的位置 / 大小 / 最大化状态写进配置。

    **必须走 `qconfig.set`**：直接写 `cfg.window_geometry.value = ...` 只改内存不落盘
    （见 `.claude/rules/architecture.md` 的配置一节）。
    """
    blob = bytes(window.saveGeometry().toBase64()).decode("ascii")
    qconfig.set(cfg.window_geometry, blob)


def restore_window_state(window: QWidget) -> bool:
    """恢复窗口几何，返回是否恢复成功。

    调用方在返回 `False` 时用自己的默认尺寸。**这条路径不抛异常**，最坏结果就是
    回到默认尺寸——配置文件被手改坏不该让应用起不来。

    三种挡在 `restoreGeometry` 之前的情况：键不是字符串（被改成数字）、空串
    （从没记录过）、非 ASCII（有人往那个键里填了中文，`encode` 会抛）。
    剩下的一律交给 `restoreGeometry`：它内部会校验 blob 的 magic 与窗口尺寸字段，
    认不出来自己返回 `False`。
    """
    raw = cfg.window_geometry.value
    if not isinstance(raw, str) or not raw:
        return False
    try:
        data = QByteArray.fromBase64(raw.encode("ascii"))
    except UnicodeEncodeError:
        return False
    if data.isEmpty():
        return False
    return bool(window.restoreGeometry(data))
