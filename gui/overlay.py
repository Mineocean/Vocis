"""GUI module exports."""

from gui.notification import notify, notify_error, notify_info, notify_warning
from gui.subtitle_widget import SubtitleWidget
from gui.tray import TrayManager

SubtitleOverlay = SubtitleWidget
SubtitleTray = TrayManager

__all__ = [
    "SubtitleOverlay",
    "SubtitleTray",
    "SubtitleWidget",
    "TrayManager",
    "notify",
    "notify_error",
    "notify_info",
    "notify_warning",
]
