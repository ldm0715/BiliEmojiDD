"""搜索历史：点击搜索框才下拉的浮层面板 + 本机持久化。

搜索框此前没有任何记忆，每次都要重新敲关键词。本模块提供：

- `SearchHistory`：按 namespace 分表的 MRU 列表（最多 10 条），存
  `%APPDATA%/biliEmojiDD/search_history.json`，读写失败一律静默（同 `cache.py` 约定）；
- `SearchHistoryPanel`：**浮在窗口上的下拉面板**——点搜索框展开、移开/失焦收起，
  里面是胶囊形记录（悬停出现 × 删除单条）+「清空」。

为什么是浮层而不是命令卡里的一行：记录行常驻会挤占页面版面、把结果区往下推。
面板的 parent 是**顶层窗口**、几何自己 `setGeometry` 管理、不进任何布局，
因此完全不参与父级的尺寸计算；展开/收起动画直接动 `geometry`。

胶囊用组件库的 `PillPushButton`（`PillButtonBase` 在未选中态就画中性胶囊底），
面板底用 `SimpleCardWidget`，删除按钮用 `TransparentToolButton`——都注册进了
`styleSheetManager`，主题切换自动重绘，**不要再给它们 setStyleSheet**（会被重刷冲掉）。
"""
from __future__ import annotations

import json

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FlowLayout,
    FluentIcon,
    PillPushButton,
    SimpleCardWidget,
    TransparentPushButton,
    TransparentToolButton,
    setFont,
)

from app.common.config import APP_CONFIG_DIR

_HISTORY_FILE = APP_CONFIG_DIR / "search_history.json"
MAX_ITEMS = 10

_CHIP_H = 26  # 胶囊高度：比搜索框（33）矮一圈，整块面板才显得小巧
_CHIP_FONT = 12
_CLOSE_SIZE = 14  # 删除按钮边长
_CLOSE_MARGIN = 4  # 删除按钮距胶囊右边缘
# 恒定预留删除按钮的位置：只在 hover 时才占位会让胶囊宽度跳动
_CHIP_EXTRA_W = _CLOSE_SIZE + _CLOSE_MARGIN * 2

_PANEL_PADDING = 8  # 面板内边距
_PANEL_GAP = 4  # 面板与搜索框的间隙
_PANEL_MIN_W = 240
_ANI_MS = 140


class SearchHistory:
    """按 namespace 分表的搜索历史（MRU，最多 MAX_ITEMS 条）。"""

    def __init__(self, namespace: str) -> None:
        self._ns = namespace

    # ---- 存取 ----
    @staticmethod
    def _read_all() -> dict:
        try:
            data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 缺失 / 损坏都当作空历史
            return {}

    @staticmethod
    def _write_all(data: dict) -> None:
        try:
            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _HISTORY_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 写失败不阻塞主流程
            return

    def items(self) -> list[str]:
        items = self._read_all().get(self._ns)
        if not isinstance(items, list):
            return []
        return [x for x in items if isinstance(x, str)][:MAX_ITEMS]

    def _save(self, items: list[str]) -> None:
        data = self._read_all()
        data[self._ns] = items[:MAX_ITEMS]
        self._write_all(data)

    # ---- 修改 ----
    def add(self, text: str) -> None:
        """插到队首；已存在则先去重（等于置顶），超出上限砍队尾。"""
        text = (text or "").strip()
        if not text:
            return
        items = [x for x in self.items() if x != text]
        items.insert(0, text)
        self._save(items)

    def remove(self, text: str) -> None:
        self._save([x for x in self.items() if x != text])

    def clear(self) -> None:
        self._save([])


class _HistoryChip(PillPushButton):
    """一条历史记录：胶囊 + 悬停显示的删除按钮。

    **不要覆写 `__init__`**：`PushButton.__init__` 是 `singledispatchmethod`，
    `(text, parent)` 那个重载内部会再调一次 `self.__init__(parent=parent)`——
    子类若把 text 声明成必填位置参数，这次内部调用直接 TypeError。
    子类初始化一律走库留的 `_postInit()` 钩子（它在 setText 之前执行）。
    """

    removeRequested = Signal(str)

    def _postInit(self) -> None:
        super()._postInit()  # ToggleButton._postInit：setCheckable(True)
        # 关掉可选中态，isChecked() 恒假 → PillButtonBase 一直画中性胶囊底
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 组件库按钮默认 32~34 高、字号 14，塞进下拉面板显得笨重
        self.setFixedHeight(_CHIP_H)
        setFont(self, _CHIP_FONT)

        self.closeBtn = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeBtn.setFixedSize(_CLOSE_SIZE, _CLOSE_SIZE)
        self.closeBtn.setIconSize(QSize(7, 7))
        self.closeBtn.setToolTip("删除这条记录")
        self.closeBtn.hide()
        self.closeBtn.clicked.connect(self._emit_remove)

    def _emit_remove(self) -> None:
        self.removeRequested.emit(self.text())

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        return QSize(size.width() + _CHIP_EXTRA_W, _CHIP_H)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.closeBtn.move(
            self.width() - _CLOSE_SIZE - _CLOSE_MARGIN,
            (self.height() - _CLOSE_SIZE) // 2,
        )

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.closeBtn.show()
        self.closeBtn.raise_()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        # 鼠标移到子控件（删除按钮）上时父控件也会收到 leaveEvent，直接隐藏会导致
        # 「一悬停 × 就消失、永远点不到」。指针仍在胶囊矩形内就不收起。
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            return
        self.closeBtn.hide()


class SearchHistoryPanel(SimpleCardWidget):
    """搜索框下方的浮层历史面板。

    生命周期全自动：构造时给 `edit` 装事件过滤器，聚焦/点击展开、失焦或鼠标移出收起。
    页面只需要接 `activated` 并在真正发起搜索时调 `record()`。
    """

    activated = Signal(str)  # 点了某条记录

    def __init__(self, edit: QWidget, namespace: str) -> None:
        # parent 用顶层窗口：面板要浮在页面之上，且不进任何布局
        super().__init__(edit.window())
        self._edit = edit
        self._history = SearchHistory(namespace)
        self._open = False

        self._content = QWidget(self)  # 固定几何，动画只动外层，内部不重排
        self._flow = FlowLayout(self._content, needAni=False)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setHorizontalSpacing(5)
        self._flow.setVerticalSpacing(5)

        self.clearBtn = TransparentPushButton(FluentIcon.BROOM, "清空", self._content)
        self.clearBtn.setToolTip("清除全部搜索记录")
        self.clearBtn.setFixedHeight(_CHIP_H)
        self.clearBtn.setIconSize(QSize(12, 12))
        setFont(self.clearBtn, _CHIP_FONT)
        self.clearBtn.clicked.connect(self._on_clear)

        self._ani = QPropertyAnimation(self, b"geometry", self)
        self._ani.setDuration(_ANI_MS)
        self._ani.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._ani.finished.connect(self._on_ani_finished)

        self.hide()
        edit.installEventFilter(self)
        self.reload()

    # ---- 数据 ----
    def items(self) -> list[str]:
        return self._history.items()

    def record(self, text: str) -> None:
        """记一条搜索（新的在最前，超过 10 条挤掉最老的）。"""
        self._history.add(text)
        self.reload()

    def reload(self) -> None:
        items = self._history.items()
        # 先把常驻的「清空」摘出来：removeWidget 只是从布局里取走（不销毁），
        # 而下面的 takeAllWidgets() 会把布局里剩下的胶囊 deleteLater
        self._flow.removeWidget(self.clearBtn)
        # FlowLayout.takeAt 返回的是 widget 不是 QLayoutItem，清空一律用库自带的
        # takeAllWidgets()（内部已 deleteLater），别自己遍历
        self._flow.takeAllWidgets()
        for text in items:
            chip = _HistoryChip(text, self._content)
            chip.setToolTip(text)  # _postInit 早于 setText，提示只能建完再设
            chip.clicked.connect(lambda _=False, t=text: self._on_activated(t))
            chip.removeRequested.connect(self._on_remove)
            self._flow.addWidget(chip)
        if items:
            self._flow.addWidget(self.clearBtn)
            self.clearBtn.show()
        else:
            self.clearBtn.hide()
        if not items:
            self.set_open(False, animate=False)
        elif self._open:
            self.set_open(True, animate=False)  # 内容变了，重算高度

    # ---- 展开 / 收起 ----
    def is_open(self) -> bool:
        return self._open

    def set_open(self, opened: bool, *, animate: bool = True) -> None:
        if opened and not self.items():
            opened = False  # 没记录就没什么可展开的
        if opened:
            self._show_panel(animate)
        else:
            self._hide_panel(animate)

    def open_panel(self) -> None:
        self.set_open(True)

    def close_panel(self) -> None:
        self.set_open(False)

    def _target_rect(self) -> QRect:
        """面板几何：贴着搜索框下沿、与搜索框同宽（不窄于 _PANEL_MIN_W）。"""
        host = self.parentWidget()
        top_left = self._edit.mapTo(host, QPoint(0, self._edit.height() + _PANEL_GAP))
        width = max(self._edit.width(), _PANEL_MIN_W)
        inner_w = width - _PANEL_PADDING * 2
        inner_h = self._flow.heightForWidth(inner_w)
        self._content.setGeometry(_PANEL_PADDING, _PANEL_PADDING, inner_w, inner_h)
        return QRect(
            top_left.x(), top_left.y(), width, inner_h + _PANEL_PADDING * 2
        )

    def _show_panel(self, animate: bool) -> None:
        # 窗口可能在构造之后才确定（页面先建后 addSubInterface），每次展开校正一次
        window = self._edit.window()
        if window is not self.parentWidget():
            self.setParent(window)
        target = self._target_rect()
        self._open = True
        self._ani.stop()
        if not animate:
            self.setGeometry(target)
            self.show()
            self.raise_()
            return
        start = QRect(target.x(), target.y(), target.width(), 0)
        self.setGeometry(start if self.isHidden() else self.geometry())
        self.show()
        self.raise_()
        self._ani.setStartValue(self.geometry())
        self._ani.setEndValue(target)
        self._ani.start()

    def _hide_panel(self, animate: bool) -> None:
        self._open = False
        self._ani.stop()
        if not animate or self.isHidden():
            self.hide()
            return
        rect = self.geometry()
        self._ani.setStartValue(rect)
        self._ani.setEndValue(QRect(rect.x(), rect.y(), rect.width(), 0))
        self._ani.start()

    def _on_ani_finished(self) -> None:
        if not self._open:
            self.hide()

    # ---- 交互 ----
    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit:
            kind = event.type()
            if kind in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
                self.set_open(True)
            elif kind == QEvent.Type.Enter and self._edit.hasFocus():
                # 从面板移回输入框：面板刚被 leaveEvent 收起，这里再放下来
                self.set_open(True)
            elif kind == QEvent.Type.FocusOut:
                # 焦点跑到面板里的胶囊上时不能收：那正是用户要点的东西
                if not self.underMouse():
                    self.set_open(False)
            elif kind in (QEvent.Type.Hide, QEvent.Type.HideToParent):
                # 页面被切走，面板不能留在屏幕上。父级隐藏时子控件收到的是
                # HideToParent 而不是 Hide，两个都要接
                self.set_open(False, animate=False)
        return super().eventFilter(obj, event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        # 「移出之后向上收起」。指针挪回搜索框时不收——那边的 Enter 事件会重新展开，
        # 一收一开会闪一下。
        if not self._edit.underMouse():
            self.set_open(False)

    def _on_activated(self, text: str) -> None:
        self.set_open(False)
        self.activated.emit(text)

    def _on_remove(self, text: str) -> None:
        self._history.remove(text)
        self.reload()

    def _on_clear(self) -> None:
        self._history.clear()
        self.reload()
