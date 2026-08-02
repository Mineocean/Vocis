"""
Vocis — Real-time speech recognition + AI translation subtitle overlay.
"""

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from backend.config import app_dir, env_path
from backend.pipeline import SubtitlePipeline
from gui.main_window import MainWindow
from gui.overlay import SubtitleOverlay, SubtitleTray


def _setup_logging():
    log_dir = app_dir() / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "vocis.log"

    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%H:%M:%S"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(fh)

    if sys.stdout:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(fmt, datefmt))
        root.addHandler(ch)


_setup_logging()
logger = logging.getLogger("vocis")


def _needs_setup() -> bool:
    """Check if first-run setup is needed."""
    env = env_path()
    if not env.exists():
        return True
    from backend.config import read_env_file
    cfg = read_env_file()
    return not cfg.get("MIMO_API_KEY") and not cfg.get("DEEPSEEK_API_KEY")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Vocis")
    app.setQuitOnLastWindowClosed(False)

    # HuggingFace mirror for China
    import os
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

    # Load stylesheet
    qss_path = app_dir() / "assets" / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    # First-run setup
    if _needs_setup():
        from gui.setup_wizard import SetupWizard
        wizard = SetupWizard()
        if wizard.exec() != SetupWizard.DialogCode.Accepted:
            sys.exit(0)

    import dotenv
    dotenv.load_dotenv(env_path(), override=True)

    overlay = SubtitleOverlay()
    pipeline = SubtitlePipeline()
    main_window = MainWindow(pipeline=pipeline, subtitle_widget=overlay)
    tray = SubtitleTray(
        app, pipeline=pipeline, subtitle_widget=overlay, main_window=main_window
    )
    main_window.tray_manager = tray
    pipeline.on_subtitle(overlay.subtitle_signal.emit)
    pipeline.on_subtitle_stream(overlay._stream_signal.emit)

    if not pipeline.start():
        tray.tray.hide()
        sys.exit(1)

    logger.info("Vocis started")

    # Check for updates in background
    from backend.updater import check_update_async
    from gui.i18n import tr
    from gui.notification import notify_info

    def _on_update(latest: str | None):
        if latest:
            def _notify():
                notify_info(
                    tr("update_available", version=latest),
                    tr("update_download", url=f"https://github.com/Mineocean/Vocis/releases/tag/{latest}"),
                )
                logger.info("Update available: %s", latest)
            # Qt 对象必须在主线程操作：排队回主线程执行
            QTimer.singleShot(0, _notify)

    try:
        from importlib.metadata import version as pkg_version
        current_ver = pkg_version("vocis")
    except Exception:
        current_ver = "0.4.0-alpha"
    check_update_async(current_ver, _on_update)

    # Keep event loop alive
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    app.aboutToQuit.connect(pipeline.stop)
    app.exec()


if __name__ == "__main__":
    main()
