"""Re-run after the metadata changes (dispatcher/reindex.py): the stored folder context is rebuilt with
today's patterns and fills only empty labels."""

from datetime import date

from backend.dispatcher.folder_context import build_folder_context
from backend.dispatcher.reindex import relabel
from backend.postgres.models import Document


def _stored(folders, name):
    return build_folder_context(folders[0], folders, name).model_dump(mode="json") | {
        "test_run_id": None,  # as built by the old patterns
        "doc_date": None,
    }


def test_relabel_fills_empty_labels_from_the_path_and_keeps_what_the_file_said():
    folders = [
        "APU Injector",
        "Injector 14",
        "13012026 - Flow Test (No Mesh) Injector 14",
        "Pressure_Data_Files",
    ]
    plot = Document(title="Injector 14 - Test03", folder_context=_stored(folders, "Injector 14 - Test03.png"))
    assert sorted(relabel(plot)) == ["doc_date", "hardware_item", "test_run_id"]
    assert (plot.test_run_id, plot.hardware_item, plot.doc_date, plot.date_source) == (
        "T03",
        "INJ14",
        date(2026, 1, 13),
        "path",
    )
    photo = Document(
        title="Injector 14 - Test03",
        folder_context=_stored(folders, "Injector 14 - Test03.png"),
        doc_date=date(2026, 1, 14),
        date_source="exif",
    )
    relabel(photo)
    assert (photo.doc_date, photo.date_source) == (date(2026, 1, 14), "exif")


def test_a_document_without_a_stored_path_is_left_alone():
    assert relabel(Document(title="x", folder_context={})) == []
