"""Small real SQLite-backed HTTP application used by the reference certificate."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import argparse
import json
import sqlite3

from dagcert import UnhandledException

from .operations import (
    ItemDeleteInput,
    ItemDeleted,
    ItemInsertInput,
    ItemInsertInvalid,
    ItemStored,
    ItemsListInput,
    ItemsListInvalid,
    ItemsListed,
    delete_item_task,
    insert_item_task,
    list_items_task,
)


STATIC_DIRECTORY = Path(__file__).with_name("static")
SEED_ITEMS = (
    ("Atlas", "reference"),
    ("Beacon", "active"),
    ("Cedar", "archive"),
    ("Delta", "active"),
    ("Ember", "reference"),
    ("Fjord", "archive"),
    ("Grove", "active"),
)


def initialize_database(path: str | Path, *, reset: bool = False) -> None:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        database.unlink(missing_ok=True)
    with sqlite3.connect(database) as connection:
        # WAL avoids a rollback-journal create/delete cycle on every HTTP write
        # and permits readers to continue while a request commits.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL
            )
            """
        )
        count = int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
        if count == 0:
            connection.executemany(
                "INSERT INTO items (title, category) VALUES (?, ?)",
                SEED_ITEMS,
            )


def list_items(
    path: str | Path, *, page: int, page_size: int, sort: str, direction: str,
) -> dict[str, Any]:
    result = list_items_task(ItemsListInput(Path(path), page, page_size, sort, direction))
    if isinstance(result, ItemsListInvalid):
        raise ValueError(result.reason)
    if isinstance(result, UnhandledException):
        raise RuntimeError(f"list operation failed: {result.exception_type}: {result.message}")
    return {
        "items": [
            {"id": item.id, "title": item.title, "category": item.category}
            for item in result.items
        ],
        "page": result.page, "page_size": result.page_size, "total": result.total,
        "has_previous": result.has_previous, "has_next": result.has_next,
        "sort": result.sort, "direction": result.direction,
    }


def insert_item(path: str | Path, *, title: str, category: str) -> dict[str, Any]:
    result = insert_item_task(ItemInsertInput(Path(path), title, category))
    if isinstance(result, ItemInsertInvalid):
        raise ValueError(result.reason)
    if isinstance(result, UnhandledException):
        raise RuntimeError(f"insert operation failed: {result.exception_type}: {result.message}")
    return {"id": result.id, "title": result.title, "category": result.category}


def delete_item(path: str | Path, identifier: int) -> bool:
    result = delete_item_task(ItemDeleteInput(Path(path), identifier))
    if isinstance(result, UnhandledException):
        raise RuntimeError(f"delete operation failed: {result.exception_type}: {result.message}")
    return result.found


class ApplicationServer(ThreadingHTTPServer):
    database_path: Path


class ApplicationHandler(BaseHTTPRequestHandler):
    server: ApplicationServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/items":
            self._list(parse_qs(parsed.query))
            return
        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if parsed.path in static_files:
            filename, content_type = static_files[parsed.path]
            self._bytes(HTTPStatus.OK, (STATIC_DIRECTORY / filename).read_bytes(), content_type)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/items":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            payload = self._request_json()
            item = insert_item(
                self.server.database_path,
                title=str(payload.get("title", "")),
                category=str(payload.get("category", "")),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.CREATED, item)

    def do_DELETE(self) -> None:
        segments = urlparse(self.path).path.strip("/").split("/")
        if len(segments) != 3 or segments[:2] != ["api", "items"]:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            identifier = int(segments[2])
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "item ID must be an integer"})
            return
        if not delete_item(self.server.database_path, identifier):
            self._json(HTTPStatus.NOT_FOUND, {"error": "item not found"})
            return
        self._json(HTTPStatus.OK, {"deleted": identifier})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _list(self, query: dict[str, list[str]]) -> None:
        try:
            result = list_items(
                self.server.database_path,
                page=int(query.get("page", ["1"])[0]),
                page_size=int(query.get("page_size", ["3"])[0]),
                sort=query.get("sort", ["title"])[0],
                direction=query.get("direction", ["asc"])[0],
            )
        except (ValueError, IndexError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, result)

    def _request_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        self._bytes(
            status,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _bytes(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def create_server(database_path: str | Path, *, port: int = 0) -> ApplicationServer:
    initialize_database(database_path)
    server = ApplicationServer(("127.0.0.1", port), ApplicationHandler)
    server.database_path = Path(database_path)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the certified database/UI example")
    parser.add_argument("--database", default=str(Path(__file__).with_name("app.sqlite3")))
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    initialize_database(args.database, reset=args.reset)
    server = create_server(args.database, port=args.port)
    print(f"serving http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
