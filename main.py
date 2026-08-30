"""biliEmojiDD 入口。

Copyright (C) 2026 gcnanmu

本程序是自由软件：你可以依据自由软件基金会发布的 GNU 通用公共许可证（第 3 版，或者
你选择的任何更新版本）的条款重新发布与修改它。

发布本程序是希望它有用，但**不作任何担保**，甚至不包含适销性或特定用途适用性的默示
担保。详见 GNU 通用公共许可证。你应当已随本程序收到一份许可证副本（见根目录 LICENSE），
若没有，请查阅 <https://www.gnu.org/licenses/>。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme

from app.common.config import cfg
from app.common.font import apply_font_engine


def main() -> int:
    # 字体渲染后端是平台插件的启动参数，必须赶在 QApplication 构造之前设
    apply_font_engine()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)

    # 先创建 QApplication 再导入 MainWindow，确保控件/信号在主线程构造
    from app.common.font import apply_app_font
    from app.common.resource import app_icon

    # 字体必须在导入 MainWindow 之前应用：addApplicationFont 要有 QGuiApplication，
    # 而给 qfluentwidgets 打的 getFont 补丁要赶在页面控件构造之前生效
    apply_app_font(app)

    from app.MainWindow import MainWindow

    app.setWindowIcon(app_icon())  # 任务栏 / 弹窗继承应用图标
    setTheme(cfg.theme.value)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
