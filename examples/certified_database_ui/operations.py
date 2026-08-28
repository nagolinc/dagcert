"""Strongly typed SQLite task boundaries used by the production HTTP adapter."""

from dataclasses import dataclass
from pathlib import Path
from typing import Union
import sqlite3

from dagcert.runtime import operation


SORT_COLUMNS = {"title": "title", "category": "category", "created": "id"}


@dataclass(frozen=True)
class ItemsListInput:
    path: Path
    page: int
    page_size: int
    sort: str
    direction: str


@dataclass(frozen=True)
class ItemRecord:
    id: int
    title: str
    category: str


@dataclass(frozen=True)
class ItemsListed:
    items: tuple[ItemRecord, ...]
    page: int
    page_size: int
    total: int
    has_previous: bool
    has_next: bool
    sort: str
    direction: str


@dataclass(frozen=True)
class ItemsListInvalid:
    reason: str


@dataclass(frozen=True)
class ItemsListFailed:
    reason: str


@dataclass(frozen=True)
class ItemInsertInput:
    path: Path
    title: str
    category: str


@dataclass(frozen=True)
class ItemStored:
    id: int
    title: str
    category: str


@dataclass(frozen=True)
class ItemInsertInvalid:
    reason: str


@dataclass(frozen=True)
class ItemInsertFailed:
    reason: str


@dataclass(frozen=True)
class ItemDeleteInput:
    path: Path
    identifier: int


@dataclass(frozen=True)
class ItemDeleted:
    found: bool


@dataclass(frozen=True)
class ItemDeleteFailed:
    reason: str


@operation
def list_items_task(
    request: ItemsListInput,
) -> Union[ItemsListed, ItemsListInvalid, ItemsListFailed]:
    if request.page < 1 or request.page_size < 1:
        return ItemsListInvalid("page and page_size must be positive")
    if request.sort not in SORT_COLUMNS or request.direction not in {"asc", "desc"}:
        return ItemsListInvalid("unsupported sort or direction")
    order_column = SORT_COLUMNS[request.sort]
    order_direction = request.direction.upper()
    offset = (request.page - 1) * request.page_size
    try:
        with sqlite3.connect(request.path) as connection:
            connection.row_factory = sqlite3.Row
            total = int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            rows = connection.execute(
                f"""
                SELECT id, title, category
                FROM items
                ORDER BY {order_column} {order_direction}, id {order_direction}
                LIMIT ? OFFSET ?
                """,
                (request.page_size, offset),
            ).fetchall()
    except sqlite3.Error as error:
        return ItemsListFailed(str(error))
    return ItemsListed(
        tuple(ItemRecord(int(row["id"]), str(row["title"]), str(row["category"])) for row in rows),
        request.page, request.page_size, total, request.page > 1,
        offset + len(rows) < total, request.sort, request.direction,
    )


@operation
def insert_item_task(
    request: ItemInsertInput,
) -> Union[ItemStored, ItemInsertInvalid, ItemInsertFailed]:
    normalized_title = request.title.strip()
    normalized_category = request.category.strip()
    if not normalized_title or not normalized_category:
        return ItemInsertInvalid("title and category are required")
    try:
        with sqlite3.connect(request.path) as connection:
            cursor = connection.execute(
                "INSERT INTO items (title, category) VALUES (?, ?)",
                (normalized_title, normalized_category),
            )
            if cursor.lastrowid is None:
                return ItemInsertFailed("SQLite did not return an inserted row ID")
            identifier = int(cursor.lastrowid)
    except sqlite3.Error as error:
        return ItemInsertFailed(str(error))
    return ItemStored(identifier, normalized_title, normalized_category)


@operation
def delete_item_task(request: ItemDeleteInput) -> Union[ItemDeleted, ItemDeleteFailed]:
    try:
        with sqlite3.connect(request.path) as connection:
            cursor = connection.execute("DELETE FROM items WHERE id = ?", (request.identifier,))
    except sqlite3.Error as error:
        return ItemDeleteFailed(str(error))
    return ItemDeleted(cursor.rowcount == 1)
