"""全局配置：qconfig 持久化到 %APPDATA%/biliEmojiDD/config.json。"""
from __future__ import annotations

import os
from pathlib import Path

from qfluentwidgets import (
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

APP_NAME = "biliEmojiDD"
APP_CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME


class AppConfig(QConfig):
    """应用配置。所有字段为可序列化的基本类型。"""

    cookie = ConfigItem("Account", "cookie", "")
    download_dir = ConfigItem(
        "Download", "dir", str(Path.home() / "Downloads" / "biliemoji")
    )
    default_gif = ConfigItem("Download", "gif", True)
    max_workers = RangeConfigItem("Download", "maxWorkers", 8, RangeValidator(1, 16))
    proxy = ConfigItem("Download", "proxy", "")
    theme = OptionsConfigItem(
        "Appearance",
        "theme",
        Theme.AUTO,
        OptionsValidator(Theme),
        EnumSerializer(Theme),
    )


cfg = AppConfig()
qconfig.load(str(APP_CONFIG_DIR / "config.json"), cfg)
# 同步 qfluentwidgets 主题模式到应用配置，避免配置文件里残留的
# QFluentWidgets.ThemeMode 覆盖应用当前主题（导致亮暗反色）
qconfig.set(qconfig.themeMode, cfg.theme.value, save=False)
