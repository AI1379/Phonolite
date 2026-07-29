"""Entry point: ``python -m phonolite`` or ``uv run phonolite``."""

from __future__ import annotations

import os
import sys


def main() -> int:
    # Pin pyqtgraph to PySide6 before it gets imported anywhere downstream.
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

    from PySide6.QtWidgets import QApplication

    from phonolite.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Phonolite")
    app.setOrganizationName("Phonolite")

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
