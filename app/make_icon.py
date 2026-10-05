"""Turn the SQUAD logo (assets/logo.jpg) into the app icon app/icon.ico.

Small sizes show only the pentagram in the middle: the full logo turns into
a red blur at 16-32 px.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "assets" / "logo.jpg"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def rounded(image: Image.Image, size: int) -> Image.Image:
    image = image.resize((size, size), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=size, fill=255)
    image.putalpha(mask.resize((size, size), Image.LANCZOS))
    return image


def frames() -> list[Image.Image]:
    logo = Image.open(LOGO).convert("RGB")
    w, h = logo.size
    side = min(w, h)
    full = logo.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    inset = side * 0.22
    centre = full.crop((inset, inset, side - inset, side - inset))
    return [rounded(centre if size <= 32 else full, size) for size in SIZES]


if __name__ == "__main__":
    target = Path(__file__).with_name("icon.ico")
    images = frames()
    images[-1].save(target, sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print(f"icon: {target}")
