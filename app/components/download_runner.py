"""统一下载流程：目录校验 + 进度条 + 结果统计 + 「打开所在文件夹」。

注意：本模块不实现"运行中取消"——biliemoji 下载器不支持安全中断。
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qfluentwidgets import InfoBar, InfoBarPosition, PushButton

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.components.task import run_task


def open_in_explorer(path: Path, parent=None) -> None:
    try:
        os.startfile(str(path))  # Windows only
    except OSError as exc:
        InfoBar.error(
            "无法打开文件夹", str(exc), parent=parent, position=InfoBarPosition.TOP_RIGHT
        )


def start_download(
    task_fn: Callable[[], Any],
    progress_bar,
    on_finished: Callable[[], None] | None = None,
    parent=None,
) -> bool:
    """启动一个下载任务。

    task_fn：返回 DownloadBatchResult 的零参可调用对象（含 on_progress 参数预留）。
    progress_bar：本页面内的 QProgressBar（隐藏状态由本函数管理）。
    on_finished：下载结束后回调（用于恢复按钮等），无论成功失败都会调用。
    返回 False 表示目录不可用，未启动任务。
    """
    dest = Path(cfg.download_dir.value)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        InfoBar.error(
            "下载目录不可用",
            f"无法创建下载目录：{dest}\n请在「设置」中更换下载目录",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )
        return False
    except OSError as exc:
        InfoBar.error(
            "下载目录不可用", str(exc), parent=parent, position=InfoBarPosition.TOP_RIGHT
        )
        return False

    progress_bar.show()

    def _on_progress(done: int, total: int, _result: Any) -> None:
        progress_bar.setRange(0, max(total, 1))  # 防除零
        progress_bar.setValue(done)

    def _on_success(result: Any) -> None:
        folder = result.results[0].target.parent if result.results else dest
        summary = f"成功 {result.ok} · 失败 {result.failed} · 跳过 {result.skipped}"
        bar = InfoBar.success(
            "下载完成",
            summary,
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )
        open_btn = PushButton("打开所在文件夹")
        open_btn.clicked.connect(lambda: open_in_explorer(folder, parent))
        bar.addWidget(open_btn)
        if result.failed:
            InfoBar.warning(
                "部分文件下载失败",
                f"共 {result.failed} 个文件失败，可重新下载重试",
                parent=parent,
                position=InfoBarPosition.TOP_RIGHT,
                duration=5000,
            )

    def _on_error(exc: Exception) -> None:
        show_bili_error(exc, parent)

    def _on_finished(ok: bool) -> None:
        progress_bar.hide()
        if on_finished is not None:
            on_finished()

    run_task(
        task_fn,
        needs_progress=True,
        is_download=True,
        on_progress=_on_progress,
        on_success=_on_success,
        on_error=_on_error,
        on_finished=_on_finished,
    )
    return True
