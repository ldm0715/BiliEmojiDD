"""BiliError 异常 → InfoBar 中文提示 的统一映射。"""
from __future__ import annotations

from biliemoji import (
    AuthRequired,
    BiliError,
    DownloadError,
    DressNotFound,
    NetworkError,
    NotFoundError,
    ValidationError,
)
from qfluentwidgets import InfoBarPosition

from app.common.notify import notify_error, notify_warning


def show_bili_error(exc: Exception, parent=None) -> None:
    """把 worker 线程冒出的异常映射为中文 InfoBar 提示。"""
    if isinstance(exc, AuthRequired):
        notify_error(
            "需要登录",
            "Cookie 缺失或已过期，请在「设置」页填写 Cookie",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )
    elif isinstance(exc, DressNotFound):
        notify_warning(
            "没有结果",
            "未找到相关收藏集",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, NotFoundError):
        notify_error(
            "未找到",
            str(exc) or "请求的对象不存在",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, NetworkError):
        notify_error(
            "网络错误",
            str(exc) or "网络请求失败，请检查网络后重试",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, DownloadError):
        notify_error(
            "下载失败",
            str(exc) or "文件下载失败",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, ValidationError):
        notify_warning(
            "参数错误",
            str(exc) or "输入参数不合法",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
        )
    elif isinstance(exc, BiliError):
        notify_error(
            "B 站接口错误",
            str(exc) or type(exc).__name__,
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )
    else:
        # 未知异常保留详情供排查，但 UI 不崩溃
        notify_error(
            type(exc).__name__,
            str(exc) or repr(exc),
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=0,
        )
