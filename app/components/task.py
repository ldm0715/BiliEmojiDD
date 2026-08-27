"""通用后台任务层：QRunnable + QThreadPool + 主线程亲和信号。

规则：
- Task 只持有一套 self.signals，主线程构造 → 信号亲和主线程；
  worker / biliemoji 内部线程只能 emit 该信号，绝不直接更新 QWidget。
- autoDelete(False)：避免 QThreadPool 在 run() 返回后立即删除 C++ 对象、
  导致尚未投递到主线程的队列信号丢失。
- TaskManager 持有所有运行中 Task 的 Python 引用，finished 后自动释放。
- 全局线程池最大并发 4，避免与 biliemoji 下载器内部并发叠加。
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from biliemoji import BiliError
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class TaskSignals(QObject):
    """Task 专属信号。created 于主线程，跨线程 emit 自动走 QueuedConnection。"""

    started = Signal()
    result = Signal(object)  # 成功载荷
    error = Signal(object)  # 异常对象（BiliError 子类等）
    progress = Signal(int, int, object)  # done, total, DownloadResult
    finished = Signal(bool)  # 是否成功


class Task(QRunnable):
    """把一个可调用对象放到后台线程执行，结果经信号回主线程。"""

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        needs_progress: bool = False,
        is_download: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.signals = TaskSignals()
        self._fn = fn
        self._args = args
        self._kwargs = dict(kwargs)
        self._needs_progress = needs_progress
        self.is_download = is_download  # 供 closeEvent 判断是否有下载在跑

    def run(self) -> None:
        kwargs = dict(self._kwargs)
        if self._needs_progress:
            kwargs["on_progress"] = self._progress_bridge()
        try:
            res = self._fn(*self._args, **kwargs)
        except BiliError as exc:
            self.signals.error.emit(exc)
            self.signals.finished.emit(False)
        except Exception as exc:  # noqa: BLE001 兜底，未知异常也转成信号而非崩溃
            self.signals.error.emit(exc)
            self.signals.finished.emit(False)
        else:
            self.signals.result.emit(res)
            self.signals.finished.emit(True)

    def _progress_bridge(self) -> Callable[..., None]:
        """biliemoji 在 executor 线程调 on_progress → emit self.signals.progress。"""

        def bridge(done: int, total: int, res: Any) -> None:
            self.signals.progress.emit(done, total, res)

        return bridge


class TaskManager:
    """持有运行中 Task 的引用，finished 后自动移除；提供关窗前的状态查询。"""

    def __init__(self, max_threads: int = 4) -> None:
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(max_threads)
        self._active: set[Task] = set()
        self._lock = threading.Lock()

    def submit(self, task: Task) -> None:
        def _release(*_args: Any) -> None:
            with self._lock:
                self._active.discard(task)

        task.signals.finished.connect(_release)
        with self._lock:
            self._active.add(task)
        self._pool.start(task)

    @property
    def running_downloads(self) -> bool:
        with self._lock:
            return any(t.is_download for t in self._active)

    def clear_pending(self) -> None:
        """仅清除尚未开始的任务；对已运行中的下载无效。"""
        self._pool.clear()


task_manager = TaskManager()


def run_task(
    fn: Callable[..., Any],
    *args: Any,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    on_progress: Callable[[int, int, Any], None] | None = None,
    on_finished: Callable[[bool], None] | None = None,
    needs_progress: bool = False,
    is_download: bool = False,
    **kwargs: Any,
) -> Task:
    """提交一个后台任务并连接信号。返回 Task（引用已由 task_manager 持有）。"""
    task = Task(
        fn,
        *args,
        needs_progress=needs_progress,
        is_download=is_download,
        **kwargs,
    )
    signals = task.signals
    if on_success is not None:
        signals.result.connect(on_success)
    if on_error is not None:
        signals.error.connect(on_error)
    if on_progress is not None:
        signals.progress.connect(on_progress)
    if on_finished is not None:
        signals.finished.connect(on_finished)
    task_manager.submit(task)
    return task
