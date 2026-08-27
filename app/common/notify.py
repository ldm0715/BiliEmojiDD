"""统一消息提示：垂直布局 InfoBar（标题一行 / 内容换行 / 按钮单独一行）。

fork 版 InfoBar 默认水平布局（标题与内容并排），长文本会被压窄；
垂直布局让标题、内容、按钮各占一行，内容按父级宽度预换行完整显示。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from qfluentwidgets import InfoBar, InfoBarPosition

_DEFAULT_DURATION = 4000


def _show(kind: str, title: str, content: str, parent, duration: int, position) -> InfoBar:
    return getattr(InfoBar, kind)(
        title,
        content,
        orient=Qt.Orientation.Vertical,
        isClosable=True,
        duration=duration,
        position=position,
        parent=parent,
    )


def notify_success(title: str, content: str, *, parent=None, duration: int = _DEFAULT_DURATION,
                   position=InfoBarPosition.TOP_RIGHT) -> InfoBar:
    return _show("success", title, content, parent, duration, position)


def notify_warning(title: str, content: str, *, parent=None, duration: int = _DEFAULT_DURATION,
                   position=InfoBarPosition.TOP_RIGHT) -> InfoBar:
    return _show("warning", title, content, parent, duration, position)


def notify_error(title: str, content: str, *, parent=None, duration: int = _DEFAULT_DURATION,
                 position=InfoBarPosition.TOP_RIGHT) -> InfoBar:
    return _show("error", title, content, parent, duration, position)


def notify_info(title: str, content: str, *, parent=None, duration: int = _DEFAULT_DURATION,
                position=InfoBarPosition.TOP_RIGHT) -> InfoBar:
    return _show("info", title, content, parent, duration, position)
