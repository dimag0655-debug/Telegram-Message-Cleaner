import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer, QLibraryInfo
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QPen
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.window import MainWindow
from utils.settings import data_dir


def app_icon():
    image = QPixmap(64, 64)
    image.fill(QColor("#151b2e"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#91a1ff"), 5))
    painter.drawRoundedRect(17, 21, 30, 33, 5, 5)
    painter.drawLine(12, 15, 52, 15)
    painter.drawLine(25, 8, 39, 8)
    painter.drawLine(27, 29, 27, 45)
    painter.drawLine(37, 29, 37, 45)
    painter.end()
    return QIcon(image)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", metavar="DIRECTORY", help="Offline packaged Qt startup test; no Telegram connection")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("TelegramMessageCleaner")
    app.setOrganizationName("TelegramMessageCleaner")
    app.setWindowIcon(app_icon())
    lock = QLockFile(str(data_dir() / "application.lock"))
    lock.setStaleLockTime(0)
    if not args.self_test and not lock.tryLock(0):
        QMessageBox.information(None, "Telegram Message Cleaner", "Приложение уже запущено. Используйте существующее окно.")
        return 1
    window = MainWindow(start_worker=not bool(args.self_test))
    window.show()
    if args.self_test:
        def smoke():
            target = Path(args.self_test)
            target.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(target / "login.png"))
            window.pages.setCurrentIndex(1)
            window.grab().save(str(target / "main.png"))
            payload = {"frozen": bool(getattr(sys, "frozen", False)), "python": sys.version,
                       "version": "1.0.1",
                       "executable": sys.executable, "prefix": sys.prefix,
                       "bundle": getattr(sys, "_MEIPASS", None),
                       "qt_plugins": QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath),
                       "qt": QLibraryInfo.version().toString(), "platform": app.platformName(),
                       "telegram_connected": False, "deletion_requests": 0,
                       "login_visible": True, "main_visible": True,
                       "preview_default": window.preview_only.isChecked(),
                       "delete_disabled": not window.delete_button.isEnabled()}
            (target / "self-test.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            window.close()
        QTimer.singleShot(600, smoke)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
