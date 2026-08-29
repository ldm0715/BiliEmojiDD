"""统一消息提示：垂直布局 InfoBar（标题一行 / 内容换行 / 按钮单独一行）。

fork 版 InfoBar 默认水平布局（标题与内容并排），长文本会被压窄；
垂直布局让标题、内容、按钮各占一行，内容按父级宽度预换行完整显示。

**父级统一解析成窗口的内容区**（`FluentWindow.stackedWidget`）：上游的
`InfoBarManager` 是按 `infoBar.parent()` 的矩形算位置的（TOP_RIGHT = 父级右上角内缩
24px），各页面各传各的子页时，消息会浮在命令卡中间，而且**页面一切走消息就看不见了**。
`FluentWindowBase` 把 `widgetLayout` 的上边距设成 48 再放 `stackedWidget`，所以
stackedWidget 恰好就是「标题栏以下、侧栏以右」的内容区——挂它上面位置天然正确，
调用点仍然照常传自己的页面 widget，由本模块归一。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarPosition

_DEFAULT_DURATION = 4000


def _resolve_parent(widget):
    """把任意页面 widget 归一成「消息该挂的那个父级」。

    找不到 FluentWindow（屏幕外脚本单独构页、控件还没进窗口）时原样返回，不抛。
    """
    if widget is None:
        return None
    window = widget.window()
    if window is None:
        return widget
    stacked = getattr(window, "stackedWidget", None)
    return stacked if isinstance(stacked, QWidget) else widget


def _show(kind: str, title: str, content: str, parent, duration: int, position) -> InfoBar:
    bar = getattr(InfoBar, kind)(
        title,
        content,
        orient=Qt.Orientation.Vertical,
        isClosable=True,
        duration=duration,
        position=position,
        parent=_resolve_parent(parent),
    )
    # InfoBar 不进 stackedWidget 的 QStackedLayout，只是它的普通子控件；
    # 显式 raise_() 保证盖在当前页之上
    bar.raise_()
    return bar


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
