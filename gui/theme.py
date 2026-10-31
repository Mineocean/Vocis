"""Vocis 深色主题调色板 —— GUI 与 QSS 共用的视觉常量。"""

# ── 基础色 ──────────────────────────────────────────
BG = "#0b0f14"
PANEL = "#121820"
PANEL_HOVER = "#161e28"
FIELD = "#0e141b"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
BORDER = "rgba(255, 255, 255, 0.08)"

# ── 强调色 ──────────────────────────────────────────
ACCENT = "#22d3ee"
ACCENT_2 = "#a78bfa"
SUCCESS = "#34d399"
WARNING = "#fbbf24"
ERROR = "#fb7185"

# ── 说话人配色（按 Speaker.color_index 取色） ─────────
SPEAKER_COLORS = [
    "#38bdf8",
    "#f472b6",
    "#fbbf24",
    "#34d399",
    "#a78bfa",
    "#fb7185",
]

# ── 字体 ────────────────────────────────────────────
FONT_FAMILIES = ["Microsoft YaHei UI", "Segoe UI Variable", "Segoe UI"]


def speaker_color(color_index: int) -> str:
    """Return the chip color for a speaker's color_index (0..5, wrapped)."""
    return SPEAKER_COLORS[int(color_index) % len(SPEAKER_COLORS)]
