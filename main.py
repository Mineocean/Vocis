"""
Vocis — Real-time speech recognition + AI translation subtitle overlay.
"""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from backend.pipeline import SubtitlePipeline
from backend.config import get_config, env_path
from gui.overlay import SubtitleOverlay, SubtitleTray


def _setup_logging():
    log_dir = Path(__file__).parent / "logs"
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
    qss_path = Path(__file__).parent / "assets" / "style.qss"
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
    tray = SubtitleTray(app, pipeline=pipeline, subtitle_widget=overlay)
    pipeline.on_subtitle(overlay.subtitle_signal.emit)
    pipeline.on_subtitle_stream(overlay._stream_signal.emit)

    if not pipeline.start():
        tray.tray.hide()
        sys.exit(1)

    logger.info("Vocis started")

    # Check for updates in background
    from backend.updater import check_update_async
    from gui.notification import notify_info

    def _on_update(latest: str | None):
        if latest:
            notify_info(
                f"New version {latest} available",
                f"Download: https://github.com/Mineocean/Vocis/releases/tag/{latest}",
            )
            logger.info("Update available: %s", latest)

    try:
        from importlib.metadata import version as pkg_version
        current_ver = pkg_version("vocis")
    except Exception:
        current_ver = "0.2.1"
    check_update_async(current_ver, _on_update)

    # Keep event loop alive
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    app.aboutToQuit.connect(pipeline.stop)
    app.exec()


if __name__ == "__main__":
    main()
