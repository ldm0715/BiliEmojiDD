"""检查更新：查 GitHub Release、下载安装包、校验 SHA-256。

**只在 worker 线程调用**（走 `app/components/task.py::run_task`），本模块不碰任何控件。

三件容易搞混的事：

1. **加速镜像 ≠ 代理。** 「设置 → 关于 → 下载加速」里的镜像是**前缀式反代**
   （`https://gh-proxy.com/` + 原始 URL），改的是 URL 本身；「设置 → 下载 → 代理」改的是
   requests 的 `proxies=`。两者互不影响，可以同时用。用户还能自己加源（`cfg.custom_mirrors`），
   所以「有哪些镜像」一律走 `all_mirrors()` / `mirror_chain()`，别直接读 `GH_MIRRORS`。
2. **校验和永远直连取。** 安装包可以走镜像加速，`SHA256SUMS.txt` 不行——用被校验方
   提供的校验和去校验它自己，等于没校验。
3. **下完就要自动运行**（见 `update_dialog.py`），所以校验不通过必须删文件并报错，
   绝不能只是提示一下就放行。
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from qfluentwidgets import qconfig

from app.common.config import (
    GH_MIRROR_AUTO,
    GH_MIRROR_CHAIN,
    GH_MIRRORS,
    LATEST_RELEASE_API,
    REPO_URL,
    cfg,
)
from app.common.net import make_session

# 校验和资产名：由 packaging/build.py 生成、随 Release 一起上传
SUMS_ASSET = "SHA256SUMS.txt"
# 安装包资产的后缀（便携 zip 不用来自动安装）
INSTALLER_SUFFIX = ".exe"

_API_TIMEOUT = 15
_DOWNLOAD_TIMEOUT = 30
_CHUNK = 256 * 1024

# 屏幕外断言脚本把它关掉：否则构造 MainWindow 就会排一个真实网络请求
_enabled = True


def set_enabled(flag: bool) -> None:
    """关掉后 `fetch_latest_release` 直接抛 `UpdateDisabled`，不发任何请求。"""
    global _enabled
    _enabled = flag


class UpdateError(Exception):
    """检查更新相关错误的基类（消息即可直接展示给用户）。"""


class UpdateDisabled(UpdateError):
    """联网被 `set_enabled(False)` 关掉了（只在屏幕外脚本里出现）。"""


class NoRelease(UpdateError):
    """仓库还没有发布过版本（GitHub 返回 404）。"""


class ChecksumMismatch(UpdateError):
    """下载到的文件与官方校验和不符——文件已删除，绝不运行。"""


@dataclass(frozen=True)
class ReleaseInfo:
    """一次 Release 查询的结果（只留界面与下载用得上的字段）。"""

    tag: str = ""
    name: str = ""
    notes: str = ""
    published: str = ""
    html_url: str = ""
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    sums_url: str = ""

    @property
    def has_installer(self) -> bool:
        return bool(self.asset_url)

    @property
    def size_text(self) -> str:
        if self.asset_size <= 0:
            return ""
        return f"{self.asset_size / (1024 * 1024):.1f} MB"


# ---- 镜像 ----

def normalize_mirror(text: str) -> str:
    """把用户输入的镜像地址规范化成可拼接的前缀；不合法返回空串。

    `gh-proxy.com` → `https://gh-proxy.com/`；已有 scheme 的保留；结尾补一个 `/`。
    只认 http(s)——前缀式反代就是拿 URL 拼的，别的协议拼不出东西。
    """
    value = (text or "").strip()
    if not value or " " in value:
        return ""
    if "://" not in value:
        value = "https://" + value
    if not value.startswith(("http://", "https://")):
        return ""
    if len(value.split("://", 1)[1].strip("/")) == 0:  # 只有个 scheme
        return ""
    return value.rstrip("/") + "/"


def custom_mirrors() -> list[str]:
    """用户自己加的镜像（读配置，脏数据一律过滤掉）。"""
    raw = cfg.custom_mirrors.value
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        value = normalize_mirror(item) if isinstance(item, str) else ""
        if value and value not in out:
            out.append(value)
    return out


def all_mirrors() -> list[tuple[str, str]]:
    """下拉里该有的全部选项：直连 / 自动 在前（它们不是「源」，不参与排序），
    其后是按用户顺序排好的内置 + 自定义源。返回 [(文案, 取值), ...]。
    """
    fixed = [(text, value) for text, value in GH_MIRRORS if not value.startswith("http")]
    labels = {value: text for text, value in GH_MIRRORS}
    return fixed + [(labels.get(v) or _host_of(v), v) for v in orderable_mirrors()]


def orderable_mirrors() -> list[str]:
    """可排序的加速源（内置 + 自定义），按 `cfg.mirror_order` 排。

    顺序表只记顺序不记成员：表里没有的源按默认顺序补在后面，已删除的源自动失效。
    这样加了新内置源、或用户删了自定义源，都不需要迁移配置。
    """
    known = list(GH_MIRROR_CHAIN) + [
        m for m in custom_mirrors() if m not in GH_MIRROR_CHAIN
    ]
    raw = cfg.mirror_order.value
    order = [m for m in raw if isinstance(m, str) and m in known] if isinstance(raw, list) else []
    return order + [m for m in known if m not in order]


def set_mirror_order(values) -> None:
    """持久化用户拖出来的顺序（只留真实存在的源）。"""
    known = set(GH_MIRROR_CHAIN) | set(custom_mirrors())
    qconfig.set(cfg.mirror_order, [v for v in values if v in known])


def _host_of(url: str) -> str:
    return url.split("://", 1)[-1].strip("/").split("/")[0] or url


def is_custom(value: str) -> bool:
    """是不是用户自己加的源（内置源不能改也不能删，但可以排序）。"""
    return value in custom_mirrors() and value not in GH_MIRROR_CHAIN


def add_custom_mirror(text: str) -> str:
    """加一个自定义镜像并落库，返回规范化后的地址。

    地址不合法抛 `ValueError`（消息可直接展示）；已存在的也抛。
    """
    value = normalize_mirror(text)
    if not value:
        raise ValueError("地址格式不对，应形如 https://gh-proxy.com/")
    if value in {v for _, v in GH_MIRRORS} or value in custom_mirrors():
        raise ValueError("这个加速源已经在列表里了")
    qconfig.set(cfg.custom_mirrors, [*custom_mirrors(), value])
    return value


def update_custom_mirror(old: str, text: str) -> str:
    """改一个自定义镜像的地址，返回新地址；**保持它在顺序里的位置**。

    地址不合法或与别的源撞车都抛 `ValueError`。
    """
    value = normalize_mirror(text)
    if not value:
        raise ValueError("地址格式不对，应形如 https://gh-proxy.com/")
    if value == old:
        return value
    if value in {v for _, v in GH_MIRRORS} or value in custom_mirrors():
        raise ValueError("这个加速源已经在列表里了")
    # **先算好新顺序再改成员**：`orderable_mirrors()` 会按当前成员过滤顺序表，
    # 成员改完再读的话，旧地址已经不在 known 里、直接被丢掉，新地址就被排到末尾了
    new_order = [value if m == old else m for m in orderable_mirrors()]
    qconfig.set(
        cfg.custom_mirrors, [value if m == old else m for m in custom_mirrors()]
    )
    set_mirror_order(new_order)
    if cfg.gh_mirror.value == old:  # 正在用它，跟着改过去
        qconfig.set(cfg.gh_mirror, value)
    return value


def remove_custom_mirror(value: str) -> None:
    """删掉一个自定义镜像；正在使用它的话退回直连。"""
    remaining = [m for m in orderable_mirrors() if m != value]
    qconfig.set(cfg.custom_mirrors, [m for m in custom_mirrors() if m != value])
    set_mirror_order(remaining)
    if cfg.gh_mirror.value == value:
        qconfig.set(cfg.gh_mirror, "")


def mirror_chain() -> list[str]:
    """`auto` 模式依次尝试的镜像——就是用户排好的那个顺序。"""
    return orderable_mirrors()


def mirrored(url: str, mirror: str) -> str:
    """前缀式反代拼接：`https://gh-proxy.com/` + `https://github.com/...`。

    镜像为空 / 是 `auto` 时原样返回（`auto` 由 `download_urls` 展开成具体镜像）。
    """
    if not mirror or mirror == GH_MIRROR_AUTO:
        return url
    return mirror.rstrip("/") + "/" + url


def download_urls(url: str) -> list[str]:
    """按 `cfg.gh_mirror` 把一个地址展开成候选列表，依次尝试。

    - `""`（直连）：只有原始地址
    - 具体镜像：**只走那个镜像**——用户明确选了它，失败就该看出是镜像的问题
    - `"auto"`：直连优先，再依次试内置与自定义镜像
    """
    mirror = cfg.gh_mirror.value
    if mirror == GH_MIRROR_AUTO:
        return [url] + [mirrored(url, m) for m in mirror_chain()]
    return [mirrored(url, mirror)]


# ---- 测速 ----

TIER_GOOD = "good"
TIER_FAIR = "fair"
TIER_ERROR = "error"
TIER_TEXT = {TIER_GOOD: "良好", TIER_FAIR: "一般", TIER_ERROR: "错误"}

# 分档阈值（毫秒）：低于它算「良好」，通了但更慢算「一般」，压根不通算「错误」
LATENCY_GOOD_MS = 1000
_PROBE_TIMEOUT = 8
# 测速打的地址：经镜像访问本仓库主页。**4xx 也算通**——哪怕 404（仓库还没建 / 改名），
# 也说明镜像确实把请求转给 GitHub 了；只有连不上与镜像自己 5xx 才算错误。
PROBE_TARGET = REPO_URL


@dataclass(frozen=True)
class MirrorSpeed:
    """一个镜像的测速结果。`ms < 0` 表示没测通。"""

    mirror: str
    ms: int = -1
    tier: str = TIER_ERROR
    detail: str = ""

    @property
    def text(self) -> str:
        """给界面直接显示的一句话，如「良好 · 312 ms」。"""
        label = TIER_TEXT.get(self.tier, TIER_TEXT[TIER_ERROR])
        return f"{label} · {self.ms} ms" if self.ms >= 0 else f"{label} · {self.detail}"


def probe_mirror(mirror: str) -> MirrorSpeed:
    """测一个镜像（空串 = 直连）到 GitHub 的往返延迟。**worker 线程调用。**

    用挂钟计时而不是 `response.elapsed`：后者不含 DNS 与握手，而对代理来说这两段
    恰恰是差距所在。`stream=True` 让 `get()` 一拿到响应头就返回，不下正文。

    **4xx 也算通**——仓库还没建 / 改过名时 GitHub 会回 404，但那说明镜像确实把请求
    转到 GitHub 了；只有连不上和镜像自己 5xx 才算错误。
    """
    url = mirrored(PROBE_TARGET, mirror)
    session = make_session()
    start = time.monotonic()
    try:
        with session.get(url, stream=True, timeout=_PROBE_TIMEOUT) as response:
            status = response.status_code
    except requests.RequestException as exc:
        return MirrorSpeed(mirror, -1, TIER_ERROR, _short_reason(exc))
    ms = int((time.monotonic() - start) * 1000)
    if status >= 500:  # 中转本身挂了（502 / 504 最常见）
        return MirrorSpeed(mirror, -1, TIER_ERROR, f"服务异常 {status}")
    tier = TIER_GOOD if ms < LATENCY_GOOD_MS else TIER_FAIR
    return MirrorSpeed(mirror, ms, tier)


def _short_reason(exc: Exception) -> str:
    name = type(exc).__name__
    if "Timeout" in name:
        return "超时"
    if "Proxy" in name:
        return "代理不通"
    if "SSL" in name:
        return "TLS 失败"
    if "ConnectionError" in name or "Connect" in name:
        return "连不上"
    return name


def probe_mirrors(mirrors, on_progress=None) -> list[MirrorSpeed]:
    """并发测一批镜像。**worker 线程调用**（走 `run_task(needs_progress=True)`）。

    每测完一个就 `on_progress(已完成数, 总数, MirrorSpeed)` 回报一次，界面可以逐行点亮
    而不用干等最慢的那个。并发度取镜像数（都是等网络，不占 CPU），上限 8。
    """
    targets = list(mirrors)
    if not targets:
        return []
    results: list[MirrorSpeed] = []
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = {pool.submit(probe_mirror, m): m for m in targets}
        for future in as_completed(futures):
            try:
                speed = future.result()
            except Exception as exc:  # noqa: BLE001 单个失败不该毁掉整批
                speed = MirrorSpeed(futures[future], -1, TIER_ERROR, _short_reason(exc))
            results.append(speed)
            if on_progress is not None:
                on_progress(len(results), len(targets), speed)
    return results


# ---- 查询 ----

def _release_info(data: dict) -> ReleaseInfo:
    assets = data.get("assets") or []
    installer = pick_asset(assets)
    sums = next(
        (a for a in assets if str(a.get("name", "")).lower() == SUMS_ASSET.lower()),
        None,
    )
    return ReleaseInfo(
        tag=str(data.get("tag_name") or ""),
        name=str(data.get("name") or ""),
        notes=str(data.get("body") or ""),
        published=str(data.get("published_at") or "")[:10],  # 只要 YYYY-MM-DD
        html_url=str(data.get("html_url") or ""),
        asset_name=str(installer.get("name") or "") if installer else "",
        asset_url=str(installer.get("browser_download_url") or "") if installer else "",
        asset_size=int(installer.get("size") or 0) if installer else 0,
        sums_url=str(sums.get("browser_download_url") or "") if sums else "",
    )


def pick_asset(assets: list[dict]) -> dict | None:
    """挑出可自动安装的资产：安装包 exe。没有就返回 None（界面退化成「打开发布页」）。"""
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name.endswith(INSTALLER_SUFFIX):
            return asset
    return None


def fetch_latest_release() -> ReleaseInfo:
    """查最新 Release。**worker 线程调用。**

    API 请求先直连；失败且配置了镜像时用镜像重试一次（这三家一般也代理
    `api.github.com`，不支持也只是多失败一次，不会更糟）。
    """
    if not _enabled:
        raise UpdateDisabled("检查更新已在本次会话中禁用")
    session = make_session(headers={"Accept": "application/vnd.github+json"})
    candidates = [LATEST_RELEASE_API]
    mirror = cfg.gh_mirror.value
    if mirror:
        candidates += [
            u for u in download_urls(LATEST_RELEASE_API) if u != LATEST_RELEASE_API
        ]

    last: Exception | None = None
    for url in candidates:
        try:
            response = session.get(url, timeout=_API_TIMEOUT)
        except requests.RequestException as exc:
            last = exc
            continue
        if response.status_code == 404:
            raise NoRelease("仓库还没有发布过版本")
        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise UpdateError("GitHub API 访问频率超限，请稍后再试")
        try:
            response.raise_for_status()
            return _release_info(response.json())
        except (requests.RequestException, ValueError) as exc:
            last = exc
    raise UpdateError("无法访问 GitHub 发布接口") from last


# ---- 下载 ----

def update_dir() -> Path:
    """安装包落脚点。

    **不能挂到 `video_cache.cleanup()` 上**：安装包要活过应用退出（下完就关应用装新版）。
    """
    path = Path(tempfile.gettempdir()) / "biliEmojiDD-update"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _expected_sum(info: ReleaseInfo, session: requests.Session) -> str:
    """从 `SHA256SUMS.txt` 里取本资产的校验和；仓库没发这个文件时返回空串。

    **固定直连**：校验和不能经镜像——拿被校验方给的校验和校验它自己等于没校验。
    """
    if not info.sums_url:
        return ""
    response = session.get(info.sums_url, timeout=_API_TIMEOUT)
    response.raise_for_status()
    return parse_sums(response.text, info.asset_name)


def parse_sums(text: str, name: str) -> str:
    """解析 `sha256sum` 格式（`<hex>  <文件名>`），取指定文件名那一行的摘要。"""
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            return parts[0].lower()
    return ""


def _stream_to(session: requests.Session, url: str, target: Path, on_progress) -> str:
    """流式下载到 `target.part` 并返回 SHA-256；调用方负责改名。"""
    part = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    with session.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(part, "wb") as fp:
            for chunk in response.iter_content(_CHUNK):
                if not chunk:
                    continue
                fp.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total, None)
    return digest.hexdigest()


def download_asset(
    info: ReleaseInfo,
    on_progress: Callable[[int, int, Any], None] | None = None,
) -> Path:
    """下载安装包并校验，返回本地路径。**worker 线程调用。**

    `on_progress(已下字节, 总字节, None)` —— 复用 `run_task(needs_progress=True)` 注入的
    桥接器，第三个参数在这里恒为 None（字节级进度，没有 per-file 结果）。

    候选地址来自 `download_urls`（可能带镜像），逐个尝试；校验和固定直连取。
    校验不过抛 `ChecksumMismatch` 并删除文件——下一步就要自动运行它，不能放行。
    """
    if not _enabled:
        raise UpdateDisabled("检查更新已在本次会话中禁用")
    if not info.has_installer:
        raise UpdateError("这个版本没有可自动安装的文件")

    session = make_session()
    expected = _expected_sum(info, session)
    target = update_dir() / info.asset_name

    # 上次下过同一个文件就别重下了（校验和对得上才算数）
    if expected and target.is_file() and _file_sum(target) == expected:
        if on_progress is not None:
            size = target.stat().st_size
            on_progress(size, size, None)
        return target

    part = target.with_suffix(target.suffix + ".part")
    last: Exception | None = None
    for url in download_urls(info.asset_url):
        try:
            actual = _stream_to(session, url, target, on_progress)
        except requests.RequestException as exc:
            last = exc
            part.unlink(missing_ok=True)
            continue
        if expected and actual != expected:
            part.unlink(missing_ok=True)
            raise ChecksumMismatch(
                f"文件校验和与官方发布不符（期望 {expected[:12]}…，实际 {actual[:12]}…）"
            )
        os.replace(part, target)
        return target
    raise UpdateError("安装包下载失败") from last


def _file_sum(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
