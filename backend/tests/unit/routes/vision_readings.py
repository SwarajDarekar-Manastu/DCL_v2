"""Canned vision replies as the model returns them since ``image_context.v2``: every capability that describes
an image carries ``image_metadata`` (a required field)."""

IMAGE_METADATA = {"subject": "test image", "setting": "unknown", "hardware": []}


def with_image_metadata(schema, reading):
    if isinstance(reading, dict) and "image_metadata" in schema.model_fields:
        return {"image_metadata": IMAGE_METADATA, **reading}
    return reading
