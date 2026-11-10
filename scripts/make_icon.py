# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Draw the app icon (windows/notetaker.ico): a white microphone on a blue tile.
Needs Pillow; only for regenerating the committed icon.

    python scripts/make_icon.py
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLUE = (45, 108, 223, 255)
WHITE = (255, 255, 255, 255)
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 1024
    d.rounded_rectangle([32 * s, 32 * s, 992 * s, 992 * s], radius=200 * s, fill=BLUE)
    # Microphone capsule
    d.rounded_rectangle([392 * s, 180 * s, 632 * s, 600 * s], radius=120 * s, fill=WHITE)
    # Holder: a U around the capsule
    width = int(56 * s)
    d.arc([300 * s, 330 * s, 724 * s, 730 * s], start=0, end=180, fill=WHITE, width=width)
    d.line([300 * s + width / 2, 470 * s, 300 * s + width / 2, 530 * s], fill=WHITE, width=width)
    d.line([724 * s - width / 2, 470 * s, 724 * s - width / 2, 530 * s], fill=WHITE, width=width)
    # Stand and base
    d.line([512 * s, 730 * s, 512 * s, 830 * s], fill=WHITE, width=width)
    d.rounded_rectangle([392 * s, 812 * s, 632 * s, 868 * s], radius=28 * s, fill=WHITE)
    return img


def main():
    out = os.path.join(ROOT, "windows", "notetaker.ico")
    draw().save(out, sizes=[(n, n) for n in SIZES])
    print(f"wrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
