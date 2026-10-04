"""The picker projection must not claim the canonical catalog entity name."""

from src.tui import model_catalog


def test_picker_rows_have_unambiguous_presentation_identity() -> None:
    """Require the specified row name and remove the ambiguous compatibility export."""
    assert not hasattr(model_catalog, "ModelCatalogEntryDAO")
    assert "ModelPickerRowDAO" in model_catalog.__all__
    rows = list(model_catalog.MODEL_CATALOG)
    assert rows
    assert all(type(row).__name__ == "ModelPickerRowDAO" for row in rows)
