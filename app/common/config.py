"""全局配置：qconfig 持久化到 %APPDATA%/biliEmojiDD/config.json。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from qfluentwidgets import (
    BoolValidator,
    ConfigItem,
    EnumSerializer,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    RangeConfigItem,
    RangeValidator,
    Theme,
    qconfig,
)

from app.common.version import project_version

APP_NAME = "biliEmojiDD"
# 版本号唯一来源是 pyproject.toml 的 [project] version——改版本只改那一处。
# （[tool.uv] package=false，应用不是安装包，importlib.metadata 取不到）
APP_VERSION = project_version()
APP_CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_FILE = APP_CONFIG_DIR / "config.json"

# 代码仓库：设置页「关于」组与检查更新都读这里
REPO_OWNER = "ldm0715"
REPO_NAME = "BiliEmojiDD"
REPO_SLUG = f"{REPO_OWNER}/{REPO_NAME}"
REPO_URL = f"https://github.com/{REPO_SLUG}"
RELEASES_URL = f"{REPO_URL}/releases"
LICENSE_URL = f"{REPO_URL}/blob/main/LICENSE"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"

# GitHub 下载加速镜像（(下拉文案, 取值)）。
# 这三家是**前缀式反代**：把原始 URL 整个接在镜像后面，形如
#     https://gh-proxy.com/https://github.com/owner/repo/releases/download/v1/x.exe
# 与「设置 → 下载 → 代理」是两套独立机制——代理改的是 requests 的 proxies=，
# 镜像改的是 URL 本身，两者可以同时生效。
# 用户还能在设置页自己加（存 cfg.custom_mirrors），完整清单走 updater.all_mirrors()。
GH_MIRRORS = (
    ("不使用（直连 GitHub）", ""),
    ("自动（直连失败后依次尝试）", "auto"),
    ("gh-proxy.com", "https://gh-proxy.com/"),
    ("ghproxy.net", "https://ghproxy.net/"),
    ("ghfast.top", "https://ghfast.top/"),
)
GH_MIRROR_AUTO = "auto"
GH_MIRROR_VALUES = tuple(value for _, value in GH_MIRRORS)
# 「自动」时按顺序尝试的内置镜像（不含直连与 auto 本身；用户自定义的由 updater 追加）
GH_MIRROR_CHAIN = tuple(v for v in GH_MIRROR_VALUES if v.startswith("http"))

# 字体渲染后端（见 app/common/font.py::apply_font_engine）。
# 只有这两项：Qt 6.4.2 的 Windows 插件不认 `fontengine=gdi`（实测输出与默认逐像素相同）。
FONT_ENGINES = ("default", "freetype")

# 配置结构版本：一次性迁移靠它熄火（见 _migrate）。加新迁移时 +1。
CONFIG_SCHEMA = 1


class AppConfig(QConfig):
    """应用配置。所有字段为可序列化的基本类型。"""

    # 配置结构版本，只给迁移用，界面上不出现
    schema_version = ConfigItem("App", "schema", 0)
    cookie = ConfigItem("Account", "cookie", "")
    download_dir = ConfigItem(
        "Download", "dir", str(Path.home() / "Downloads" / "biliemoji")
    )
    default_gif = ConfigItem("Download", "gif", True)
    max_workers = RangeConfigItem("Download", "maxWorkers", 8, RangeValidator(1, 16))
    # 代理总开关：关 = 彻底直连（应用也不读系统代理，见 app/common/net.py）
    proxy_enabled = ConfigItem("Download", "proxyEnabled", False, BoolValidator())
    proxy = ConfigItem("Download", "proxy", "")
    # 磁盘缓存上限（MB）：图片字节 + 接口响应，超限按 LRU 淘汰
    cache_limit_mb = RangeConfigItem("Cache", "limitMB", 512, RangeValidator(64, 8192))
    theme = OptionsConfigItem(
        "Appearance",
        "theme",
        Theme.AUTO,
        OptionsValidator(Theme),
        EnumSerializer(Theme),
    )
    font_engine = OptionsConfigItem(
        "Appearance", "fontEngine", "default", OptionsValidator(list(FONT_ENGINES))
    )
    # 启动时静默检查一次新版本；无新版 / 失败都不打扰，不想联网的用户一拨即关
    auto_check_update = ConfigItem("Update", "autoCheck", True, BoolValidator())
    # GitHub 下载加速镜像。"" = 直连，"auto" = 直连失败后依次试内置 + 自定义镜像。
    # **不用 OptionsValidator**：用户可以自己加源，取值集合是动态的
    gh_mirror = ConfigItem("Update", "ghMirror", "")
    # 用户自己加的镜像地址（前缀式反代），一个 str 列表
    custom_mirrors = ConfigItem("Update", "customMirrors", [])
    # 加速源的显示 / 尝试顺序（内置 + 自定义混排，用户可拖动调整）。
    # 只记顺序不记成员：列表里没有的源按默认顺序补在后面，删掉的源自动失效
    mirror_order = ConfigItem("Update", "mirrorOrder", [])


cfg = AppConfig()
qconfig.load(str(CONFIG_FILE), cfg)
# 同步 qfluentwidgets 主题模式到应用配置，避免配置文件里残留的
# QFluentWidgets.ThemeMode 覆盖应用当前主题（导致亮暗反色）
qconfig.set(qconfig.themeMode, cfg.theme.value, save=False)


def _raw_config() -> dict:
    """磁盘上的配置原文。缺失 / 损坏都当作空——不该让应用起不来。"""
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 首次运行没有文件；损坏也照样走默认值
        return {}
    return raw if isinstance(raw, dict) else {}


def _migrate(raw: dict) -> None:
    """一次性迁移。**只改内存**，落盘统一交给 `_ensure_persisted`。

    代理开关是后加的：老配置里填过代理地址的，视为「已启用」（升级不断网）。

    熄火靠 `schema_version` 这个显式标记，**不能靠「写完盘那个键就存在了」**——
    `qconfig.set` 在值没变化时直接 return、根本不落盘（上游 `config.py:299`）。
    于是一旦出现「内存里已经是 True 而文件里仍没有 proxyEnabled 键」，旧写法就
    永远处于武装状态：此后任何一次配置回落到默认值（`qconfig.load` 被
    `@exceptionHandler` 静默吞掉的解析失败、文件被外部改坏 / 清空、换安装目录）
    都会在下次启动被它把用户明确关掉的开关重新翻成「开」。真实报障就是这条。
    """
    if cfg.schema_version.value >= CONFIG_SCHEMA:
        return
    download = raw.get("Download")
    if isinstance(download, dict) and "proxyEnabled" not in download and cfg.proxy.value:
        cfg.proxy_enabled.value = True
    cfg.schema_version.value = CONFIG_SCHEMA


def _ensure_persisted(raw: dict) -> None:
    """让磁盘上的配置始终是**全量**的。

    `QConfig.toDict()` 本来就 dump 全部字段，只是从来没有人在启动时触发它——
    于是新加的配置项在用户主动改动它之前，文件里一直缺席，迁移判据也就一直读到
    「键不存在」。这里比一次原文与内存快照，不一致就补写（首次运行、新增字段、
    文件被改坏之后各写一次），之后自然收敛，不会每次启动都写。
    """
    if raw != qconfig.toDict():
        qconfig.save()


_raw = _raw_config()
_migrate(_raw)
_ensure_persisted(_raw)
