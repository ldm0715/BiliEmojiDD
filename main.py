"""biliEmojiDD 入口。"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qfluentwidgets import setTheme

from app.common.config import cfg


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)

    # 先创建 QApplication 再导入 MainWindow，确保控件/信号在主线程构造
    from app.common.proxy import proxy_env
    from app.MainWindow import MainWindow

    setTheme(cfg.theme.value)
    # 快照原始代理环境变量，再应用应用内配置（清空时能恢复原值）
    proxy_env.remember()
    proxy_env.apply(cfg.proxy.value)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
