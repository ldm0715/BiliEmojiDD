"""统一下载流程：目录校验 + 进度条 + 结果统计 + 「打开所在文件夹」。

注意：本模块不实现"运行中取消"——biliemoji 下载器不支持安全中断。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from biliemoji import (
    DownloadBatchResult,
    Downloader,
    DownloadResult,
    DownloadStatus,
    DownloadTask,
    Dress,
    Emoji,
    ValidationError,
)
from biliemoji.sanitize import sanitize_filename
from qfluentwidgets import InfoBarPosition, PushButton

from app.common.config import cfg
from app.common.exception import show_bili_error
from app.common.notify import notify_error, notify_success, notify_warning
from app.common.proxy import parse_proxy
from app.components.download_queue import item_kind
from app.components.dress_helpers import dlc_ids, is_collection
from app.components.task import run_task

logger = logging.getLogger("app.components.download_runner")


def open_in_explorer(path: Path, parent=None) -> None:
    try:
        os.startfile(str(path))  # Windows only
    except OSError as exc:
        notify_error(
            "无法打开文件夹", str(exc), parent=parent, position=InfoBarPosition.TOP_RIGHT
        )


def start_download(
    task_fn: Callable[[], Any],
    progress_bar,
    on_finished: Callable[[], None] | None = None,
    parent=None,
    status_label=None,
) -> bool:
    """启动一个下载任务。

    task_fn：返回 DownloadBatchResult 的零参可调用对象（含 on_progress 参数预留）。
    progress_bar：本页面内的 QProgressBar（隐藏状态由本函数管理）。
    on_finished：下载结束后回调（用于恢复按钮等），无论成功失败都会调用。
    status_label：可选的 QLabel，下载准备阶段（result 为 None 的 on_progress）显示状态文字。
    返回 False 表示目录不可用，未启动任务（此时不会触发 finished/on_finished）。
    """
    dest = Path(cfg.download_dir.value)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        notify_error(
            "下载目录不可用",
            f"无法创建下载目录：{dest}\n请在「设置」中更换下载目录",
            parent=parent,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
        )
        return False
    except OSError as exc:
        notify_error(
            "下载目录不可用", str(exc), parent=parent, position=InfoBarPosition.TOP_RIGHT
        )
        return False

    progress_bar.show()

    def _on_progress(done: int, total: int, result: Any) -> None:
        # 统一协议 (done, total, result)；result is None 表示准备阶段（读取详情）
        if result is None:
            if status_label is not None:
                status_label.setText(f"正在读取内容详情…（{done}/{total}）")
                status_label.show()
            return
        progress_bar.setRange(0, max(total, 1))  # 防除零
        progress_bar.setValue(done)

    def _on_success(result: Any) -> None:
        folder = result.results[0].target.parent if result.results else dest
        summary = f"成功 {result.ok} · 失败 {result.failed} · 跳过 {result.skipped}"
        bar = notify_success(
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
            notify_warning(
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
        if status_label is not None:
            status_label.clear()
            status_label.hide()
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


def _truncate(name: str, limit: int) -> str:
    """按字符截断（str 按码点切片，不会切坏 UTF-8）。"""
    name = name or ""
    return name if len(name) <= limit else name[:limit]


def package_download_dir(pkg) -> Path:
    """表情包下载目标目录（与 download_package_batch 命名完全一致）。"""
    name = _truncate(sanitize_filename(pkg.text or f"package_{pkg.id}"), 60)
    return Path(cfg.download_dir.value) / f"{name} [{pkg.id}]"


def collection_download_dir(summary) -> Path:
    """收藏集下载目标目录（与 download_collection_batch 命名一致）。"""
    return Path(cfg.download_dir.value) / sanitize_filename(summary.name or "收藏集")


def downloaded_exists(folder: Path) -> bool:
    """目标目录已存在且非空 → 视为已下载过。"""
    return folder.is_dir() and any(folder.iterdir())


def download_package_batch(
    ids,
    dest,
    *,
    gif: bool | None = None,
    max_workers: int | None = None,
    on_progress=None,
) -> DownloadBatchResult:
    """批量下载多个表情包：单 Downloader + 单进度条 + 聚合结果。

    - max_workers 传入时使用传入值，仅 None 时读 cfg.max_workers.value。
    - 显式 proxies（读取 cfg.proxy），元数据请求与文件下载都走代理。
    - 每个包先 certain_emoji_typed 取全量（准备阶段 on_progress(i, n, None)）；
      单个包失败（捕获 Exception，非 BaseException）合成 FAILED 结果后继续，
      不中断整批。
    - 目录名带包 ID（防同名覆盖）并对超长名截断。
    """
    max_workers = cfg.max_workers.value if max_workers is None else max_workers
    proxies = parse_proxy(cfg.proxy.value)
    emoji = Emoji(cookie=cfg.cookie.value, proxies=proxies)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    meta_failures: list[DownloadResult] = []
    tasks: list[DownloadTask] = []
    total = len(ids)
    for i, pid in enumerate(ids, 1):
        if on_progress is not None:
            on_progress(i, total, None)  # 准备阶段标记：result=None
        try:
            pkg = emoji.certain_emoji_typed(pid)
        except Exception as exc:  # noqa: BLE001 单个包失败不中断整批
            logger.warning("获取表情包 %s 详情失败：%r", pid, exc)
            meta_failures.append(
                DownloadResult(
                    url=f"表情包 {pid}",
                    target=dest / f"_fetch_failed_{pid}",
                    status=DownloadStatus.FAILED,
                    error=exc,
                )
            )
            continue

        use_gif = pkg.is_gif if gif is None else gif
        folder = dest / f"{_truncate(sanitize_filename(pkg.text or f'package_{pkg.id}'), 60)} [{pkg.id}]"
        for em in pkg.emote:
            if use_gif and em.gif_url:
                url, ext = em.gif_url, ".gif"
            elif em.url:
                url, ext = em.url, ".png"
            else:
                continue
            tasks.append(
                DownloadTask(
                    url=url,
                    target=folder
                    / f"{_truncate(sanitize_filename(em.text), 60)}{ext}",
                    expected_ext=ext,
                )
            )

    downloader = Downloader(max_workers=max_workers, on_progress=on_progress, proxies=proxies)
    result = downloader.download_many(tasks)
    # 真实结果在前，取详情失败在后；空批次时 download_many 返回空结果
    all_results = result.results + tuple(meta_failures)
    return DownloadBatchResult(results=all_results, elapsed=result.elapsed)


def download_collection_batch(
    collections,
    dest,
    *,
    mode: str = "both",
    max_workers: int | None = None,
    on_progress=None,
) -> DownloadBatchResult:
    """批量下载多个收藏集：单 Downloader + 单进度条 + 聚合结果。

    - collections：DressCollectionSummary 列表。
    - max_workers 传入时使用传入值，仅 None 时读 cfg.max_workers.value。
    - 显式 proxies（读取 cfg.proxy），元数据请求与文件下载都走代理
      （biliemoji 的 download_collection 不转发代理给内部 Downloader）。
    - 每个收藏集先 certain_lottery_typed 取全量（准备阶段 on_progress(i, n, None)）；
      单个失败（捕获 Exception）合成 FAILED 结果后继续，不中断整批。
    - 目录 dest / sanitize_filename(收藏集名)；图片 {名}.png、视频 {名}.mp4。
    """
    max_workers = cfg.max_workers.value if max_workers is None else max_workers
    proxies = parse_proxy(cfg.proxy.value)
    dress = Dress(cookie=cfg.cookie.value, proxies=proxies)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    meta_failures: list[DownloadResult] = []
    tasks: list[DownloadTask] = []
    total = len(collections)
    for i, summary in enumerate(collections, 1):
        if on_progress is not None:
            on_progress(i, total, None)  # 准备阶段标记：result=None
        act_id, lottery_id = dlc_ids(summary)
        if not is_collection(summary) or act_id is None or lottery_id is None:
            meta_failures.append(
                DownloadResult(
                    url=f"收藏集 {summary.name or '-'}",
                    target=dest / f"_fetch_failed_{i}",
                    status=DownloadStatus.FAILED,
                    error=ValidationError("该结果不是可下载收藏集"),
                )
            )
            continue
        try:
            coll = dress.certain_lottery_typed(act_id, lottery_id)
        except Exception as exc:  # noqa: BLE001 单个失败不中断整批
            logger.warning("获取收藏集 %s 详情失败：%r", summary.name, exc)
            meta_failures.append(
                DownloadResult(
                    url=f"收藏集 {summary.name or act_id}",
                    target=dest / f"_fetch_failed_{i}",
                    status=DownloadStatus.FAILED,
                    error=exc,
                )
            )
            continue

        folder = dest / sanitize_filename(coll.name)
        for item in coll.item_list:
            name = sanitize_filename(item.card_name or "unknown")
            if mode in ("image", "both") and item.card_img_download:
                tasks.append(
                    DownloadTask(
                        url=item.card_img_download,
                        target=folder / f"{name}.png",
                        expected_ext=".png",
                    )
                )
            if mode in ("video", "both"):
                vid = item.video_list[0] if item.video_list else None
                if vid:
                    tasks.append(
                        DownloadTask(
                            url=vid,
                            target=folder / f"{name}.mp4",
                            expected_ext=".mp4",
                        )
                    )

    downloader = Downloader(max_workers=max_workers, on_progress=on_progress, proxies=proxies)
    result = downloader.download_many(tasks)
    return DownloadBatchResult(
        results=result.results + tuple(meta_failures), elapsed=result.elapsed
    )


def download_mixed_batch(
    items,
    dest,
    *,
    gif: bool | None = None,
    mode: str = "both",
    max_workers: int | None = None,
    on_progress=None,
) -> DownloadBatchResult:
    """混合批量下载（下载队列页）：先表情包、后收藏集，顺序执行两个子批并合并结果。

    进度条在两个子批间会重新定程（start_download 的 on_progress 会 setRange）。
    """
    packages = [it for it in items if item_kind(it) == "package"]
    collections = [it for it in items if item_kind(it) == "collection"]
    parts: list[DownloadBatchResult] = []
    if packages:
        parts.append(
            download_package_batch(
                [p.id for p in packages],
                dest,
                gif=gif,
                max_workers=max_workers,
                on_progress=on_progress,
            )
        )
    if collections:
        parts.append(
            download_collection_batch(
                collections,
                dest,
                mode=mode,
                max_workers=max_workers,
                on_progress=on_progress,
            )
        )
    return DownloadBatchResult(
        results=tuple(r for part in parts for r in part.results),
        elapsed=sum(part.elapsed for part in parts),
    )
