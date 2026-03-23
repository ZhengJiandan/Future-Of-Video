from PIL import Image

from app.core.config import settings
from app.utils.image_variants import (
    asset_url_to_path,
    build_upload_url,
    ensure_thumbnail_for_path,
    thumbnail_path_for_source_path,
    thumbnail_url_for_asset,
)


def test_thumbnail_url_for_asset_creates_local_thumbnail(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    source_dir = tmp_path / "generated" / "pipeline" / "character_library" / "references"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "sample.png"

    Image.new("RGB", (2400, 1600), color=(12, 45, 78)).save(source_path, format="PNG")

    asset_url = build_upload_url(source_path)
    thumbnail_url = thumbnail_url_for_asset(asset_url)

    thumbnail_path = thumbnail_path_for_source_path(source_path)
    assert thumbnail_url == build_upload_url(thumbnail_path)
    assert thumbnail_path.exists()

    with Image.open(thumbnail_path) as image:
        assert max(image.size) <= 640


def test_thumbnail_url_for_asset_ignores_non_upload_url() -> None:
    assert thumbnail_url_for_asset("https://example.com/demo.png") == ""
    assert asset_url_to_path("https://example.com/demo.png") is None


def test_ensure_thumbnail_for_path_returns_none_for_non_image(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    source_path = tmp_path / "generated" / "notes.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("not an image", encoding="utf-8")

    assert ensure_thumbnail_for_path(source_path) is None
