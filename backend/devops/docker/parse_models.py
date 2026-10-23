"""Bake and check the OCR models of the parse image (target `parse` in backend.Dockerfile).

`prefetch` runs as root before the code is copied: it downloads the RapidOCR checkpoints that docling resolves
for each CJK language into RapidOCR's own model directory, where the library looks first. The worker runs as
`app` and cannot write there, so a checkpoint that is not baked fails the page with Permission denied.

`verify` runs as `app` after the code is copied: for every RapidOCR language and Tesseract script model that
Route A1 can ask for (backend/routes/a1_office/convert.py), it opens the file the engine will open. A new
language in Route A1 without a baked model fails the build here instead of a document at run time.
"""

import sys
from pathlib import Path

BACKEND = "onnxruntime"
RAPIDOCR_LANGUAGES = ("japan", "ch", "korean")  # docling codes; "chinese" is docling's alias for "ch"
TESSDATA = Path("/usr/share/tesseract-ocr/5/tessdata")
TESSERACT_ALWAYS = ("osd", "eng")


def rapidocr_dir() -> Path:
    import rapidocr

    return Path(rapidocr.__file__).resolve().parent / "models"


def prefetch() -> None:
    from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

    for lang in RAPIDOCR_LANGUAGES:
        RapidOcrModel.download_models(BACKEND, local_dir=rapidocr_dir(), lang=lang)
    for path in rapidocr_dir().iterdir():
        path.chmod(0o644)


def rapidocr_files(lang: str) -> list[Path]:
    """The files RapidOCR opens for `lang`, resolved with the parameters docling passes it."""
    from docling.models.stages.ocr.rapid_ocr_model import (
        _RAPIDOCR_CLS_MODEL_LANG,
        _RAPIDOCR_DET_MODEL_LANG,
        _RAPIDOCR_MODEL_TYPE,
        _RAPIDOCR_V4V5_MODEL_TYPE,
        _backend_to_engine_type,
        _resolve_rapidocr,
    )
    from rapidocr import ModelType, OCRVersion
    from rapidocr.inference_engine.base import FileInfo, InferSession
    from rapidocr.utils.typings import TaskType

    spec = _resolve_rapidocr(lang, BACKEND)
    engine = _backend_to_engine_type(BACKEND)
    size = ModelType(
        _RAPIDOCR_MODEL_TYPE if spec.ppocr_version == OCRVersion.PPOCRV6 else _RAPIDOCR_V4V5_MODEL_TYPE
    )
    infos = (
        FileInfo(engine, spec.ppocr_version, TaskType.DET, _RAPIDOCR_DET_MODEL_LANG, size),
        FileInfo(engine, OCRVersion.PPOCRV4, TaskType.CLS, _RAPIDOCR_CLS_MODEL_LANG, ModelType.MOBILE),
        FileInfo(engine, spec.ppocr_version, TaskType.REC, spec.rapidocr_code, size),
    )
    files = []
    for info in infos:
        url = InferSession.get_model_url(info)
        files.append(rapidocr_dir() / Path(url["model_dir"]).name)
        if info.task_type == TaskType.REC and url.get("dict_url"):
            files.append(rapidocr_dir() / Path(url["dict_url"]).name)
    return files


def verify() -> None:
    from backend.routes.a1_office.convert import DOCLING_LANGUAGE_CODES, TESSERACT_SCRIPT_MODELS

    wanted: dict[Path, str] = {}
    for lang in sorted(set(DOCLING_LANGUAGE_CODES["rapidocr"].values())):
        for path in rapidocr_files(lang):
            wanted.setdefault(path, f"rapidocr {lang}")
    for name in sorted(set(TESSERACT_SCRIPT_MODELS.values()) | set(TESSERACT_ALWAYS)):
        wanted.setdefault(TESSDATA / f"{name}.traineddata", f"tesseract {name}")
    failures = []
    for path, need in sorted(wanted.items()):
        try:
            with path.open("rb") as handle:
                handle.read(1)
        except OSError as error:
            failures.append(f"{need}: {error}")
    if failures:
        sys.exit("OCR models the worker cannot open:\n  " + "\n  ".join(failures))
    print(f"{len(wanted)} OCR model files readable")


if __name__ == "__main__":
    {"prefetch": prefetch, "verify": verify}[sys.argv[1]]()
