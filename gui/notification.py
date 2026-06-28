"""Unified error/warning notification — system tray bubbles and logging."""

import logging
from typing import Optional

from PySide6.QtWidgets import QSystemTrayIcon

logger = logging.getLogger(__name__)

_tray: Optional[QSystemTrayIcon] = None


def set_tray(tray: QSystemTrayIcon):
    """Set the system tray icon for notifications."""
    global _tray
    _tray = tray


def notify(title: str, message: str, level: str = "warning"):
    """
    Show a notification.

    :param title: Notification title
    :param message: Notification message
    :param level: "info", "warning", or "error"
    """
    log_func = getattr(logger, level, logger.warning)
    log_func("%s: %s", title, message)

    if _tray and _tray.supportsMessages():
        icon_map = {
            "info": QSystemTrayIcon.MessageIcon.Information,
            "warning": QSystemTrayIcon.MessageIcon.Warning,
            "error": QSystemTrayIcon.MessageIcon.Critical,
        }
        icon = icon_map.get(level, QSystemTrayIcon.MessageIcon.Warning)
        _tray.showMessage(title, message, icon, 5000)


def notify_error(title: str, message: str):
    """Convenience for error notifications."""
    notify(title, message, level="error")


def notify_warning(title: str, message: str):
    """Convenience for warning notifications."""
    notify(title, message, level="warning")


def notify_info(title: str, message: str):
    """Convenience for info notifications."""
    notify(title, message, level="info")