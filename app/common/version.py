"""版本号：从 `pyproject.toml` 读取，以及 tag 与本地版本的比较。

**版本号只维护一处**——`pyproject.toml` 的 `[project] version`。`[tool.uv] package=false`
（应用不是安装包）导致 `importlib.metadata` 拿不到版本，所以运行时直接读那个文件；
编译后靠 `--include-data-files=pyproject.toml=pyproject.toml` 把它带到 exe 旁边
（路径解析见 `app/common/resource.py::_project_root`）。

比较部分只服务于「检查更新」：把 GitHub Release 的 tag（`v0.2.0` / `0.2.0-beta.1`）与
本地版本比一下。刻意不引入 `packaging` 依赖——需求就这么点，多一个运行时依赖反而要在
Nuitka 那边多操心一份。

**解析不出来一律当作「不是新版」**：宁可漏提示，也不能因为某个脏 tag 让用户天天
被弹「有新版本」。
"""
from __future__ import annotations

import re
import tomllib

from app.common.resource import PYPROJECT_PATH

# 版本号里的数字段：`1.2.3` / `1.2` / `v1.2.3.4` 都只取这一串
_CORE_RE = re.compile(r"\d+(?:\.\d+)*")

# 读不到 pyproject.toml 时的兜底。**故意不是一个能比较的版本号**：
# `is_newer` 解析失败即返回 False，于是「检查更新」会安静地不提示，
# 而不是把每个 release 都当成新版天天弹窗。
_UNKNOWN = "unknown"


def project_version(path=None) -> str:
    """读 `pyproject.toml` 里的 `[project] version`；读不到返回 `"unknown"`。"""
    try:
        with open(path or PYPROJECT_PATH, "rb") as fp:
            data = tomllib.load(fp)
    except Exception:  # noqa: BLE001 文件缺失 / 格式坏都不该让应用起不来
        return _UNKNOWN
    version = data.get("project", {}).get("version")
    return version if isinstance(version, str) and version.strip() else _UNKNOWN


def parse_version(text: str) -> tuple[tuple[int, ...], str]:
    """`'v1.2.3-beta.1'` -> `((1, 2, 3), 'beta.1')`。

    认不出数字段时返回 `((), '')`——调用方据此判定「无法比较」。
    """
    raw = (text or "").strip().lstrip("vV").strip()
    match = _CORE_RE.match(raw)
    if match is None:
        return (), ""
    core = tuple(int(part) for part in match.group(0).split("."))
    # 核心段之后的东西一律算预发布/构建标记，去掉引导的 - 或 +
    suffix = raw[match.end():].lstrip("-+").strip()
    return core, suffix


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """补零对齐，让 `1.2` 与 `1.2.0` 可比。"""
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)), b + (0,) * (size - len(b))


def is_newer(remote: str, local: str) -> bool:
    """`remote` 严格新于 `local` 才为 True。

    核心段逐位比；核心段相同时按 semver 惯例「正式版 > 预发布版」
    （`1.0.0` 新于 `1.0.0-rc.1`，反之则不是）。任一侧解析失败返回 False。
    """
    remote_core, remote_pre = parse_version(remote)
    local_core, local_pre = parse_version(local)
    if not remote_core or not local_core:
        return False
    left, right = _pad(remote_core, local_core)
    if left != right:
        return left > right
    # 核心段相同：无后缀视为正式版，正式版比预发布新
    return not remote_pre and bool(local_pre)
