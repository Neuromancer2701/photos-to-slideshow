"""Image decoding (HEIC-aware) and frame compositing."""

from pathlib import Path

from PIL import Image, ImageOps

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
