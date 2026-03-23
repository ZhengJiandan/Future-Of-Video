from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

THUMBNAIL_DIRNAME = "thumbnails"
THUMBNAIL_SUFFIX = "__thumb.jpg"
DEFAULT_THUMBNAIL_MAX_SIZE = (640, 640)
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def build_upload_url(path: Path) -> str:
    relative_path = path.relative_to(Path(settings.UPLOAD_DIR))
    return f"/uploads/{relative_path.as_posix()}"


def asset_url_to_path(asset_url: str) -> Optional[Path]:
    normalized = str(asset_url or "").strip()
    if not normalized or not normalized.startswith("/uploads/"):
        return None
    return Path(settings.UPLOAD_DIR) / normalized.replace("/uploads/", "", 1)


def thumbnail_url_for_asset(asset_url: str, *, max_size: tuple[int, int] = DEFAULT_THUMBNAIL_MAX_SIZE) -> str:
    asset_path = asset_url_to_path(asset_url)
    if not asset_path:
        return ""

    thumbnail_path = ensure_thumbnail_for_path(asset_path, max_size=max_size)
    if not thumbnail_path:
        return ""
    return build_upload_url(thumbnail_path)


def ensure_thumbnail_for_path(
    source_path: Path,
    *,
    max_size: tuple[int, int] = DEFAULT_THUMBNAIL_MAX_SIZE,
) -> Optional[Path]:
    if not source_path.exists() or not source_path.is_file():
        return None

    if source_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return None

    thumbnail_path = thumbnail_path_for_source_path(source_path)
    if thumbnail_path.exists() and thumbnail_path.stat().st_mtime >= source_path.stat().st_mtime:
        return thumbnail_path

    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(source_path) as image:
            prepared = ImageOps.exif_transpose(image)
            if prepared.mode in {"RGBA", "LA"} or (
                prepared.mode == "P" and "transparency" in prepared.info
            ):
                background = Image.new("RGB", prepared.size, (245, 247, 250))
                alpha_image = prepared.convert("RGBA")
                background.paste(alpha_image, mask=alpha_image.getchannel("A"))
                prepared = background
            else:
                prepared = prepared.convert("RGB")

            prepared.thumbnail(max_size, Image.Resampling.LANCZOS)
            prepared.save(thumbnail_path, format="JPEG", quality=82, optimize=True)
        return thumbnail_path
    except (OSError, UnidentifiedImageError):
        return None


def thumbnail_path_for_source_path(source_path: Path) -> Path:
    return source_path.parent / THUMBNAIL_DIRNAME / f"{source_path.stem}{THUMBNAIL_SUFFIX}"
