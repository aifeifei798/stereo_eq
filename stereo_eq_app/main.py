from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from .ui import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Stereo EQ")
    window = MainWindow()
    window.show()
    try:
        return app.exec()
    except RuntimeError as error:
        QMessageBox.critical(window, "启动失败", str(error))
        return 1
