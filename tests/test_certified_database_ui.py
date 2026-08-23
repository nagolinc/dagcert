from pathlib import Path

from examples.certified_database_ui.app import (
    delete_item,
    initialize_database,
    insert_item,
    list_items,
)


def test_database_ui_operations_preserve_sorting_and_pagination(tmp_path: Path):
    database = tmp_path / "items.sqlite3"
    initialize_database(database, reset=True)

    first = list_items(database, page=1, page_size=3, sort="title", direction="asc")
    second = list_items(database, page=2, page_size=3, sort="title", direction="asc")
    assert [item["title"] for item in first["items"]] == ["Atlas", "Beacon", "Cedar"]
    assert [item["title"] for item in second["items"]] == ["Delta", "Ember", "Fjord"]
    assert first["has_previous"] is False and first["has_next"] is True
    assert second["has_previous"] is True and second["has_next"] is True

    inserted = insert_item(database, title=" Zulu ", category=" browser ")
    descending = list_items(database, page=1, page_size=3, sort="title", direction="desc")
    assert descending["items"][0] == inserted

    assert delete_item(database, inserted["id"])
    after_delete = list_items(database, page=1, page_size=3, sort="title", direction="desc")
    assert all(item["id"] != inserted["id"] for item in after_delete["items"])
    assert not delete_item(database, inserted["id"])
