import io

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.validators import ValidationError
from PIL import Image

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_AVATAR_DIMENSION = 1200
AVATAR_OUTPUT_SIZE = 400


def validate_avatar_image(image: InMemoryUploadedFile) -> None:
    """Validate an uploaded avatar image."""
    if image.size > MAX_AVATAR_SIZE:
        raise ValidationError("حجم الصورة يجب ألا يتجاوز 2 ميجابايت.")

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("يُسمح فقط بصيغ JPEG و PNG و WebP.")

    try:
        img = Image.open(image)
        img.verify()
    except Exception as exc:
        raise ValidationError("الملف ليس صورة صالحة.") from exc
    finally:
        image.seek(0)

    try:
        img = Image.open(image)
        width, height = img.size
    except Exception as exc:
        raise ValidationError("الملف ليس صورة صالحة.") from exc
    finally:
        image.seek(0)

    if width > MAX_AVATAR_DIMENSION or height > MAX_AVATAR_DIMENSION:
        raise ValidationError(
            f"أبعاد الصورة يجب ألا تتجاوز {MAX_AVATAR_DIMENSION}×{MAX_AVATAR_DIMENSION} بكسل."
        )


def process_avatar_image(image: InMemoryUploadedFile, size: int = AVATAR_OUTPUT_SIZE) -> ContentFile:
    """Crop to a centered square and resize to ``size``×``size``."""
    img = Image.open(image)

    # Convert palette/RGBA to RGB for consistent output.
    if img.mode in ("RGBA", "P"):
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            rgb.paste(img, mask=img.split()[-1])
        else:
            rgb.paste(img)
        img = rgb

    width, height = img.size
    min_dim = min(width, height)
    left = (width - min_dim) // 2
    top = (height - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    img = img.resize((size, size), Image.LANCZOS)

    output = io.BytesIO()
    # Determine the canonical extension from the actually validated image
    # format, not the untrusted uploaded filename, preventing extension
    # injection attacks (e.g., a JPEG saved as .php or .svg).
    if img.format == "PNG":
        img.save(output, format="PNG")
        extension = "png"
    elif img.format == "WEBP":
        img.save(output, format="WEBP", quality=85)
        extension = "webp"
    else:
        # Default everything else (validated JPEG, etc.) to JPEG.
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(output, format="JPEG", quality=85)
        extension = "jpg"

    output.seek(0)
    return ContentFile(output.read(), name=f"avatar.{extension}")
