"""Stage 4c: compositing and crops.

The watch layer is always the (redacted, colour-corrected) photo itself, moved by one affine
transform (scale, optional rotation, translation). Backgrounds — local or AI — sit underneath, and
the watch is placed on top through its mask. Where the mask is solid, output pixels are the photo's
pixels; nothing generated ever covers the watch.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import cv2
import numpy as np

from app.imaging.backgrounds import DARK_STYLES, contact_shadow, fit_plate, make_background


@dataclass(frozen=True)
class Canvas:
    key: str
    label: str
    width: int
    height: int
    fill: float


CANVASES: dict[str, Canvas] = {
    "store_2x3": Canvas("store_2x3", "Store frame 2:3", 1600, 2400, 0.80),
    "square": Canvas("square", "Square 1:1", 2048, 2048, 0.80),
    "social_4x5": Canvas("social_4x5", "Social 4:5", 1080, 1350, 0.80),
}
MASTER_CANVAS = "store_2x3"

# Platform image sizes, derived from the three canvases by a deterministic resize.
PLATFORM_PRESETS: dict[str, tuple[str, int, int]] = {
    "shopify": ("square", 2048, 2048),
    "instagram": ("social_4x5", 1080, 1350),
    "facebook_page": ("social_4x5", 1080, 1350),
    "chrono24": ("square", 2048, 2048),
    "ebay": ("square", 1600, 1600),
    "facebook_marketplace": ("social_4x5", 1080, 1350),
    "facebook_groups": ("social_4x5", 1080, 1350),
    "moda_auction": ("social_4x5", 1080, 1350),
    "carousell": ("square", 1080, 1080),
    "whatsapp_groups": ("square", 1080, 1080),
    "reddit_watchexchange": ("store_2x3", 1600, 2400),
}


@dataclass
class Plan:
    pre_scale: float          # INTER_AREA resize before the warp (≤ 1)
    warp_scale: float         # scale inside the warp (≥ 1 only when enlarging)
    angle: float              # degrees, counter-clockwise
    src_center: tuple[float, float]  # in pre-scaled coordinates
    dst_center: tuple[float, float]
    out_w: int
    out_h: int

    @property
    def total_scale(self) -> float:
        return self.pre_scale * self.warp_scale

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        return cls(d["pre_scale"], d["warp_scale"], d["angle"], tuple(d["src_center"]), tuple(d["dst_center"]),
                   d["out_w"], d["out_h"])

    def matrix(self) -> np.ndarray:
        m = cv2.getRotationMatrix2D(self.src_center, self.angle, self.warp_scale)
        m[0, 2] += self.dst_center[0] - self.src_center[0]
        m[1, 2] += self.dst_center[1] - self.src_center[1]
        return m


def subject_bbox(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    ys, xs = np.where(mask > 127)
    if xs.size == 0:
        return None
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def make_plan(mask: np.ndarray, canvas: Canvas, fill: float | None = None, angle: float = 0.0,
              max_upscale: float = 2.0) -> tuple[Plan, list[str]]:
    warnings: list[str] = []
    fill = fill or canvas.fill
    h, w = mask.shape
    bb = subject_bbox(mask)
    if bb is None:
        bb = (0.0, 0.0, float(w), float(h))
        warnings.append("No watch outline found; the whole photo was framed.")
    x0, y0, x1, y1 = bb
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bw, bh = x1 - x0, y1 - y0
    a = math.radians(angle)
    rw = abs(bw * math.cos(a)) + abs(bh * math.sin(a))
    rh = abs(bw * math.sin(a)) + abs(bh * math.cos(a))
    scale = min(fill * canvas.width / rw, fill * canvas.height / rh)
    if scale > max_upscale:
        warnings.append(f"The watch is small in this photo; it was enlarged only {max_upscale:.0f}× to keep detail sharp.")
        scale = max_upscale
    elif scale > 1.25:
        warnings.append(f"The watch was enlarged {scale:.1f}×; check fine detail when zoomed in.")
    pre = min(1.0, scale)
    warp = scale / pre
    plan = Plan(pre_scale=pre, warp_scale=warp, angle=angle, src_center=(cx * pre, cy * pre),
                dst_center=(canvas.width / 2, canvas.height * 0.49), out_w=canvas.width, out_h=canvas.height)
    return plan, warnings


def transform(img: np.ndarray, plan: Plan, *, is_mask: bool = False, replicate: bool = False) -> np.ndarray:
    src = img
    if plan.pre_scale < 0.9999:
        h, w = img.shape[:2]
        src = cv2.resize(img, (max(1, round(w * plan.pre_scale)), max(1, round(h * plan.pre_scale))),
                         interpolation=cv2.INTER_AREA)
    m = plan.matrix()
    interp = cv2.INTER_LINEAR if is_mask else cv2.INTER_CUBIC
    border = cv2.BORDER_REPLICATE if replicate else cv2.BORDER_CONSTANT
    out = cv2.warpAffine(src, m, (plan.out_w, plan.out_h), flags=interp, borderMode=border, borderValue=0)
    return out


def composite(fg: np.ndarray, mask: np.ndarray, background: np.ndarray, shadow: np.ndarray | None) -> np.ndarray:
    a = (mask.astype(np.float32) / 255.0)[..., None]
    bg = background.astype(np.float32)
    if shadow is not None:
        bg = bg * (1.0 - shadow[..., None])
    out = bg * (1.0 - a) + fg.astype(np.float32) * a
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def render_canvas(
    watch_rgb: np.ndarray,
    mask: np.ndarray,
    canvas: Canvas,
    *,
    background: str,
    fill: float | None = None,
    angle: float = 0.0,
    shadow: bool = True,
    plate: np.ndarray | None = None,
    plate_in_source_frame: bool = False,
    cleanup_bg: np.ndarray | None = None,
    seed: int = 7,
) -> tuple[np.ndarray, Plan, list[str]]:
    """Return (output RGB, plan, warnings). `watch_rgb` is the redacted, colour-corrected working image."""
    plan, warnings = make_plan(mask, canvas, fill, angle)
    fg = transform(watch_rgb, plan)
    mask_t = transform(mask, plan, is_mask=True)
    if background == "keep_original":
        bg = transform(watch_rgb, plan, replicate=True)
        shadow_map = None
    elif background == "cleanup":
        src = cleanup_bg if cleanup_bg is not None else watch_rgb
        bg = transform(src, plan, replicate=True)
        shadow_map = None
    elif background.startswith("ai_"):
        if plate is None:
            raise ValueError("AI background plate is missing.")
        bg = transform(plate, plan, replicate=True) if plate_in_source_frame else fit_plate(plate, canvas.width, canvas.height)
        shadow_map = contact_shadow(mask_t, background in DARK_STYLES) if shadow else None
    else:
        bg = make_background(background, canvas.width, canvas.height, seed=seed)
        shadow_map = contact_shadow(mask_t, background in DARK_STYLES) if shadow else None
    return composite(fg, mask_t, bg, shadow_map), plan, warnings


def platform_image(variant_rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = variant_rgb.shape[:2]
    if (w, h) == (width, height):
        return variant_rgb
    return cv2.resize(variant_rgb, (width, height), interpolation=cv2.INTER_AREA)
