"""Asset dimensions, free of the parse group (pikepdf, pdfium, Docling) so Routes D and F can import it in
the media image."""

import io


def image_fields(data: bytes) -> dict[str, int]:
    """`width`, `height` (pixels) and `bytes` of a PNG or JPEG for its ProcessedAsset (viewer layout)."""
    from PIL import Image as PILImage

    with PILImage.open(io.BytesIO(data)) as image:
        width, height = image.size
    return {"width": width, "height": height, "bytes": len(data)}
