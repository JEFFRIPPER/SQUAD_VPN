"""Draw the SQUAD VPN app icon (MD3 tonal shield) into app/icon.ico."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
PRIMARY = (67, 85, 185, 255)  # #4355B9
CONTAINER = (222, 224, 255, 255)  # #DEE0FF


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)
    canvas.rounded_rectangle((16, 16, SIZE - 16, SIZE - 16), radius=120, fill=PRIMARY)
    # Shield: top edge, sides, pointed bottom (scaled from a 24px glyph).
    s = SIZE / 24
    shield = [(12, 3), (19, 5.6), (19, 11), (17.6, 15.8), (12, 21), (6.4, 15.8), (5, 11), (5, 5.6)]
    canvas.polygon([(x * s, y * s) for x, y in shield], fill=CONTAINER)
    check = [(8.6, 11.8), (11, 14.2), (15.6, 9.6)]
    canvas.line([(x * s, y * s) for x, y in check], fill=PRIMARY, width=int(1.7 * s), joint="curve")
    return image


if __name__ == "__main__":
    target = Path(__file__).with_name("icon.ico")
    draw().save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"icon: {target}")
