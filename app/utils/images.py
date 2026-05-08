"""Image upload validation and sanitisation.

The uploads endpoint can't trust the client's ``Content-Type`` header
or the file extension — both are attacker-controlled. We re-decode the
bytes through Pillow, verify they're a real JPEG/PNG/WEBP, drop EXIF
metadata, and re-encode to a normalised buffer that's safe to write
to disk.
"""

import io

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

# PIL format ID -> (canonical content_type, file extension).
_PIL_FORMAT_TO_META: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


def validate_and_normalise_image(data: bytes) -> tuple[bytes, str, str]:
    """Verify *data* decodes as one of the allowed image formats and
    return ``(sanitised_bytes, content_type, extension)``.

    ``Image.verify()`` parses the file enough to confirm it isn't a
    payload disguised behind a valid magic-byte prefix; the second
    open + save strips EXIF / ICC / arbitrary metadata chunks so an
    attacker can't smuggle data through them.
    """
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="File is not a valid image") from None

    # ``verify()`` consumes the stream — re-open for the actual encode.
    img = Image.open(io.BytesIO(data))
    fmt = img.format
    if fmt not in _PIL_FORMAT_TO_META:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    content_type, ext = _PIL_FORMAT_TO_META[fmt]

    save_kwargs: dict = {}
    if fmt == "JPEG":
        # JPEG can't store P / RGBA / CMYK as-is; coerce to RGB.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        save_kwargs = {"quality": 90, "optimize": True}
    elif fmt == "PNG":
        save_kwargs = {"optimize": True}

    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue(), content_type, ext
