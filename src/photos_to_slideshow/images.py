"""Image decoding (HEIC-aware) and frame compositing."""

from pathlib import Path

from PIL import Image, ImageOps, ImageFilter

import pillow_heif

# Register HEIC/HEIF decoders with Pillow
pillow_heif.register_heif_opener()


def decode_image(path: Path) -> Image.Image:
    """Open an image, apply EXIF orientation, return an RGB Pillow image."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # honor camera rotation
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def render_frame(path: Path, canvas_size: tuple[int, int]) -> Image.Image:
    """Compose a single slide: photo fit-letterboxed onto a blurred copy of itself.

    The blurred background fills the canvas; the photo is centered at max
    aspect-preserved size. Photo content is never cropped.
    """
    canvas_w, canvas_h = canvas_size
    src = decode_image(path)

    # Background: scale to *cover* the canvas, then blur heavily
    bg = ImageOps.fit(src, (canvas_w, canvas_h), method=Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=40))

    # Foreground: scale to *fit* inside the canvas (no crop)
    fg = src.copy()
    fg.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)

    # Composite centered
    canvas = bg.copy()
    fx = (canvas_w - fg.width) // 2
    fy = (canvas_h - fg.height) // 2
    canvas.paste(fg, (fx, fy))
    return canvas
