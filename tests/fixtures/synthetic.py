"""SYNTHETIC reference fixtures — drawn with code, not real photographs.

The three reference scenarios from the brief are reproduced as stand-ins so the pipeline can be tested
without the client's image sets:

  1. Richard Mille RM 67-01 — "edited" set: clean white studio background, tonneau case.
  2. MB&F                    — "raw camera" set: large, noisy, uneven light, camera EXIF (Sony).
  3. H. Moser & Cie.         — "WhatsApp" set: 1200×1600, heavy JPEG compression, no EXIF, WA file name.
  plus a caseback frame with an engraved serial number, a blurred frame and a tiny frame.

Final visual acceptance testing with the real image sets is still outstanding (see docs/LIMITATIONS.md).
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
]


def font(size: int):
    for p in FONT_CANDIDATES:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _background(w: int, h: int, kind: str, rng: np.random.Generator) -> Image.Image:
    if kind == "white":
        return Image.new("RGB", (w, h), (255, 255, 255))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if kind == "wood":
        base = np.array([120, 84, 52], np.float32)
        grain = np.sin(xx / 7.0 + np.sin(yy / 60.0) * 3) * 10
        light = 0.75 + 0.45 * (1 - (xx / w) * 0.8) * (1 - (yy / h) * 0.3)
        img = base * light[..., None] + grain[..., None]
    else:  # fabric
        base = np.array([96, 104, 118], np.float32)
        weave = (np.sin(xx / 2.2) * np.sin(yy / 2.2)) * 8
        light = 0.85 + 0.25 * (1 - yy / h)
        img = base * light[..., None] + weave[..., None]
    img += rng.normal(0, 6, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def draw_watch(size=(2000, 3000), *, background="white", shape="tonneau", dial=(30, 30, 34), brand_text="RICHARD MILLE",
               domes=False, seed=1, caseback_serial: str | None = None, scale=1.0) -> Image.Image:
    rng = np.random.default_rng(seed)
    w, h = size
    img = _background(w, h, background, rng)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2
    s = min(w, h) * 0.30 * scale
    strap = (24, 24, 26)
    d.rounded_rectangle([cx - s * 0.62, cy - s * 2.15, cx + s * 0.62, cy - s * 0.6], radius=int(s * 0.18), fill=strap)
    d.rounded_rectangle([cx - s * 0.62, cy + s * 0.6, cx + s * 0.62, cy + s * 2.15], radius=int(s * 0.18), fill=strap)
    for k in range(6):
        y = cy + s * (0.85 + k * 0.2)
        d.ellipse([cx - 9, y - 9, cx + 9, y + 9], fill=(60, 60, 64))
    if shape == "tonneau":
        d.rounded_rectangle([cx - s, cy - s * 1.15, cx + s, cy + s * 1.15], radius=int(s * 0.55), fill=(176, 178, 182),
                            outline=(225, 226, 228), width=int(s * 0.05))
        d.rounded_rectangle([cx - s * 0.78, cy - s * 0.93, cx + s * 0.78, cy + s * 0.93], radius=int(s * 0.42), fill=dial)
    else:
        d.ellipse([cx - s * 1.08, cy - s * 1.08, cx + s * 1.08, cy + s * 1.08], fill=(184, 186, 190),
                  outline=(228, 228, 230), width=int(s * 0.05))
        d.ellipse([cx - s * 0.86, cy - s * 0.86, cx + s * 0.86, cy + s * 0.86], fill=dial)
    d.rectangle([cx + s * 1.02, cy - s * 0.14, cx + s * 1.22, cy + s * 0.14], fill=(200, 200, 204))
    if caseback_serial:
        f = font(int(s * 0.16))
        for i, line in enumerate(["SWISS MADE", "SAPPHIRE", caseback_serial, "WATER RESISTANT"]):
            tw = d.textlength(line, font=f)
            d.text((cx - tw / 2, cy - s * 0.55 + i * s * 0.32), line, font=f, fill=(238, 238, 240))
    else:
        for k in range(12):
            a = k / 12 * 2 * np.pi
            r0, r1 = s * 0.62, s * 0.74
            d.line([cx + r0 * np.sin(a), cy - r0 * np.cos(a), cx + r1 * np.sin(a), cy - r1 * np.cos(a)],
                   fill=(235, 235, 235), width=max(3, int(s * 0.025)))
        if domes:
            for dx in (-0.38, 0.38):
                d.ellipse([cx + s * dx - s * 0.26, cy - s * 0.5, cx + s * dx + s * 0.26, cy + 0.02 * s],
                          fill=(70, 120, 170), outline=(220, 220, 230), width=4)
        f = font(int(s * 0.11))
        tw = d.textlength(brand_text, font=f)
        d.text((cx - tw / 2, cy + s * 0.32), brand_text, font=f, fill=(225, 225, 225))
        d.line([cx, cy, cx + s * 0.45, cy - s * 0.35], fill=(240, 240, 240), width=max(4, int(s * 0.03)))
        d.line([cx, cy, cx - s * 0.2, cy - s * 0.58], fill=(240, 240, 240), width=max(3, int(s * 0.02)))
    return img


def _jpeg(img: Image.Image, quality=92, exif: Image.Exif | None = None) -> bytes:
    buf = io.BytesIO()
    kw = {"quality": quality}
    if exif is not None:
        kw["exif"] = exif.tobytes()
    img.save(buf, "JPEG", **kw)
    return buf.getvalue()


def camera_exif(make="SONY", model="ILCE-7RM4") -> Image.Exif:
    ex = Image.Exif()
    ex[0x010F] = make
    ex[0x0110] = model
    return ex


def rm6701_edited() -> list[tuple[str, bytes]]:
    """Scenario 1 (SYNTHETIC): edited studio set on pure white."""
    front = draw_watch((2000, 3000), background="white", shape="tonneau", seed=1)
    side = draw_watch((2000, 3000), background="white", shape="tonneau", seed=2, scale=0.85)
    side = side.rotate(12, fillcolor=(255, 255, 255))
    return [("RM6701_front_edited.jpg", _jpeg(front, 95)), ("RM6701_angle_edited.jpg", _jpeg(side, 95))]


def mbf_raw() -> list[tuple[str, bytes]]:
    """Scenario 2 (SYNTHETIC): raw camera frames — big, noisy, uneven light, Sony EXIF."""
    a = draw_watch((4000, 3000), background="wood", shape="round", dial=(28, 52, 88), brand_text="MB&F", domes=True, seed=3)
    b = draw_watch((4000, 3000), background="wood", shape="round", dial=(28, 52, 88), brand_text="MB&F", domes=True,
                   seed=4, scale=0.9)
    noisy = Image.fromarray(np.clip(np.asarray(a).astype(np.int16) + np.random.default_rng(5).normal(0, 9, (3000, 4000, 3)),
                                    0, 255).astype(np.uint8))
    return [("DSC09812.JPG", _jpeg(noisy, 90, camera_exif())), ("DSC09813.JPG", _jpeg(b, 90, camera_exif()))]


def moser_whatsapp() -> list[tuple[str, bytes]]:
    """Scenario 3 (SYNTHETIC): WhatsApp-forwarded phone photos — small, compressed, no EXIF."""
    img = draw_watch((1200, 1600), background="fabric", shape="round", dial=(40, 92, 70),
                     brand_text="H. MOSER & CIE", seed=6)
    return [("IMG-20261012-WA0003.jpg", _jpeg(img, 68))]


def caseback_with_serial(serial="No. 4827193") -> tuple[str, bytes]:
    img = draw_watch((2000, 2000), background="white", shape="round", dial=(120, 122, 126), seed=7,
                     caseback_serial=serial, scale=1.25)
    return ("caseback.jpg", _jpeg(img, 95))


def blurred_frame() -> tuple[str, bytes]:
    img = draw_watch((2000, 3000), background="white", shape="tonneau", seed=8).filter(ImageFilter.GaussianBlur(18))
    return ("RM6701_blurred.jpg", _jpeg(img, 92))


def tiny_frame() -> tuple[str, bytes]:
    img = draw_watch((400, 600), background="white", shape="tonneau", seed=9)
    return ("tiny.jpg", _jpeg(img, 92))


def png_with_transparency() -> tuple[str, bytes]:
    img = draw_watch((1200, 1800), background="white", shape="tonneau", seed=10).convert("RGBA")
    arr = np.asarray(img).copy()
    white = (arr[:, :, :3] > 250).all(axis=-1)
    arr[white, 3] = 0
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, "PNG")
    return ("RM6701_cutout.png", buf.getvalue())


def write_reference_sets(dest: Path) -> list[Path]:
    """Write every synthetic set to `dest` (used by scripts/make_demo_fixtures.py)."""
    out = []
    sets = {"1_RM6701_edited_SYNTHETIC": rm6701_edited(), "2_MBF_raw_SYNTHETIC": mbf_raw(),
            "3_Moser_whatsapp_SYNTHETIC": moser_whatsapp(),
            "extras_SYNTHETIC": [caseback_with_serial(), blurred_frame(), tiny_frame(), png_with_transparency()]}
    for folder, files in sets.items():
        (dest / folder).mkdir(parents=True, exist_ok=True)
        for name, data in files:
            p = dest / folder / name
            p.write_bytes(data)
            out.append(p)
    return out
