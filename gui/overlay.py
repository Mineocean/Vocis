"""GUI module exports."""

from gui.subtitle_widget import SubtitleWidget
from gui.tray import TrayManager
from gui.notification import notify, notify_error, notify_warning, notify_info

SubtitleOverlay = SubtitleWidget
SubtitleTray = TrayManager

__all__ = [
    "SubtitleWidget",
    "TrayManager",
    "SubtitleOverlay",
    "SubtitleTray",
    "notify",
    "notify_error",
    "notify_warning",
    "notify_info",
]
