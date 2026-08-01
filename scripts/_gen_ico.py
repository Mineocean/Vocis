"""
Vocis 图标生成脚本。

生成应用所需的全部图标资源（PNG + ICO）。
需要 Pillow: pip install Pillow
"""

import os

from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    """绘制 Vocis 图标：深色底 + 声波柱 + 字幕线"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    m = max(1, int(size * 0.10))
    r = max(2, int(size * 0.16))

    # 深色圆角背景
    d.rounded_rectangle(
        [m, m, size - m, size - m],
        radius=r,
        fill=(22, 22, 44, 255),
    )

    cx, cy = size / 2, size / 2
    accent = (74, 158, 255, 255)
    white = (255, 255, 255, 255)

    # 三条声波柱（左侧）
    bw = max(1, int(size * 0.055))
    gap = max(1, int(size * 0.035))
    heights = [0.28, 0.46, 0.26]
    base_x = cx - int(size * 0.18)
    for i, hf in enumerate(heights):
        h = max(3, int(size * hf))
        x0 = base_x + i * (bw + gap)
        y0 = int(cy - h / 2)
        d.rounded_rectangle(
            [x0, y0, x0 + bw, y0 + h],
            radius=bw // 2,
            fill=white,
        )

    # 字幕横线
    line_y = int(cy + size * 0.30)
    line_w = int(size * 0.30)
    line_h = max(2, int(size * 0.035))
    d.rounded_rectangle(
        [
            int(cx - line_w / 2),
            line_y,
            int(cx + line_w / 2),
            line_y + line_h,
        ],
        radius=line_h // 2,
        fill=accent,
    )

    return img


def main():
    os.makedirs("assets", exist_ok=True)

    # PNG 各尺寸
    sizes = [16, 24, 32, 48, 64, 128, 256]
    for s in sizes:
        img = draw_icon(s)
        img.save(f"assets/vocis_{s}.png")
        print(f"  assets/vocis_{s}.png  ({s}x{s})")

    # 单尺寸 ICO（Windows 兼容）
    img256 = draw_icon(256)
    img256.save("assets/vocis.ico", format="ICO", sizes=[(256, 256)])
    print("  assets/vocis.ico  (256x256)")

    # 复制 256 PNG 作为主文件
    img256.save("assets/vocis.png")
    print("  assets/vocis.png  (256x256)")

    print(f"\n共生成 {len(sizes) + 2} 个图标文件到 assets/ 目录")


if __name__ == "__main__":
    main()
