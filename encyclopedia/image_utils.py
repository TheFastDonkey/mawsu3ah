"""Image validation and processing utilities for edition covers."""

import io
import uuid
from pathlib import PurePath

from django.core.files.base import ContentFile
from django.core.validators import ValidationError
from PIL import Image, ImageOps

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_PIL_FORMATS = {"JPEG", "PNG", "WEBP"}

MAX_COVER_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_COVER_INPUT_DIMENSION = 2048  # px
MAX_COVER_PIXELS = MAX_COVER_INPUT_DIMENSION * MAX_COVER_INPUT_DIMENSION

MAX_COVER_WIDTH = 800  # px
MAX_COVER_HEIGHT = 1200  # px
COVER_QUALITY = 85

_CONTENT_TYPE_TO_PIL = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

_PIL_TO_EXTENSION = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


def _pil_format_for(image) -> str:
    """Return the Pillow save format for an uploaded image."""
    content_type = getattr(image, "content_type", "")
    if content_type:
        pil_format = _CONTENT_TYPE_TO_PIL.get(content_type.lower())
        if pil_format:
            return pil_format

    # Fallback: reopen briefly to inspect the real format.
    with Image.open(image) as img:
        fmt = img.format
    image.seek(0)
    if fmt in ALLOWED_PIL_FORMATS:
        return fmt
    raise ValidationError("تعذر تحديد صيغة الصورة.")


def validate_cover_image(image) -> None:
    """Validate a cover upload against strict size/dimension/format limits."""
    if getattr(image, "size", 0) > MAX_COVER_FILE_SIZE:
        raise ValidationError("حجم الصورة يجب ألا يتجاوز 2 ميجابايت.")

    content_type = getattr(image, "content_type", "")
    if content_type and content_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("يُسمح فقط بصيغ JPEG و PNG و WebP.")

    try:
        with Image.open(image) as img:
            img.verify()
    except Exception as exc:
        raise ValidationError("الملف ليس صورة مقبولة.") from exc
    finally:
        image.seek(0)

    try:
        with Image.open(image) as img:
            fmt = img.format
            width, height = img.size
    except Exception as exc:
        raise ValidationError("الملف ليس صورة مقبولة.") from exc
    finally:
        image.seek(0)

    if fmt not in ALLOWED_PIL_FORMATS:
        raise ValidationError("لا يسمح إلا بصيغة JPEG و PNG و WebP.")

    if width > MAX_COVER_INPUT_DIMENSION or height > MAX_COVER_INPUT_DIMENSION:
        raise ValidationError(
            f"أبعاد الصورة يجب ألا تتجاوز {MAX_COVER_INPUT_DIMENSION}×{MAX_COVER_INPUT_DIMENSION} بكسل."
        )

    if width * height > MAX_COVER_PIXELS:
        raise ValidationError("عدد بكسلات الصورة يتجاوز الحد المسموح به.")


def process_cover_image(image) -> ContentFile:
    """Resize a cover to fit inside the output box, strip metadata, and return a ContentFile.

    The image is never cropped or upscaled.
    """
    pil_format = _pil_format_for(image)
    extension = _PIL_TO_EXTENSION[pil_format]

    with Image.open(image) as img:
        # Normalize EXIF orientation and strip the orientation tag.
        img = ImageOps.exif_transpose(img)

        # Resize to fit, preserving aspect ratio; thumbnail never upscales.
        img.thumbnail((MAX_COVER_WIDTH, MAX_COVER_HEIGHT), Image.Resampling.LANCZOS)

        output = io.BytesIO()

        if pil_format == "PNG":
            img.save(output, format="PNG", optimize=True)
        elif pil_format == "WEBP":
            # Convert palette/RGBA to RGB for consistent output; WebP supports alpha,
            # but we keep it simple and strip transparency to avoid surprises.
            if img.mode in ("RGBA", "P"):
                rgb = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    rgb.paste(img, mask=img.split()[-1])
                else:
                    rgb.paste(img)
                img = rgb
            img.save(output, format="WEBP", quality=COVER_QUALITY, exif=b"")
        else:
            # JPEG
            if img.mode != "RGB":
                rgb = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    rgb.paste(img, mask=img.split()[-1])
                else:
                    rgb.paste(img)
                img = rgb
            img.save(output, format="JPEG", quality=COVER_QUALITY, optimize=True, exif=b"")

    output.seek(0)
    safe_name = f"cover_{uuid.uuid4().hex[:12]}.{extension}"
    return ContentFile(output.read(), name=safe_name)


def is_safe_temp_cover_path(path: str) -> bool:
    """Return True if the temporary cover path looks safe to open/delete."""
    if not path:
        return False
    if PurePath(path).is_absolute():
        return False
    if ".." in PurePath(path).parts:
        return False
    return path.startswith("tmp/covers/")
