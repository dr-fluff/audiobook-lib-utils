from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, parse_import_paths
from app.db.database import create_session_factory, get_book, list_books, load_settings, remember_database_path, save_settings, update_book_metadata
from app.lib.library import METADATA_FIELDS, organize_all, organize_book, scan_import_paths


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _notice(message: str, kind: str = "ok") -> str:
    return f'<p class="notice {kind}">{_escape(message)}</p>' if message else ""


def _layout(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(title)} · Audiobook Library</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1e293b;background:#f8fafc}}
header{{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #cbd5e1;margin-bottom:1.5rem}}a{{color:#075985}}
form{{margin:0}}label{{display:block;font-weight:600;margin:.8rem 0 .25rem}}input,textarea{{box-sizing:border-box;width:100%;padding:.55rem;border:1px solid #94a3b8;border-radius:.3rem;font:inherit}}textarea{{min-height:6rem}}
button{{margin:.8rem .4rem .8rem 0;padding:.55rem .9rem;background:#0369a1;color:#fff;border:0;border-radius:.3rem;font:inherit;cursor:pointer}}button.secondary{{background:#475569}}
table{{width:100%;border-collapse:collapse;background:#fff}}td,th{{padding:.65rem;text-align:left;border-bottom:1px solid #e2e8f0}}.notice{{padding:.7rem;border-radius:.3rem;background:#dcfce7}}.notice.error{{background:#fee2e2}}.muted{{color:#64748b}}.actions{{display:flex;gap:.4rem;flex-wrap:wrap}}section{{background:#fff;padding:1rem;border-radius:.5rem;box-shadow:0 1px 2px #0001}}
</style></head><body><header><h1>Audiobook Library</h1><nav><a href="/">Books</a> · <a href="/settings">Settings</a></nav></header>{body}</body></html>""".encode()


class LibraryHandler(BaseHTTPRequestHandler):
    session_factory: sessionmaker[Session]
    native_path_picker_enabled = False

    def log_message(self, format: str, *args: object) -> None:
        return

    def _connection(self) -> Session:
        return self.session_factory()

    def _respond(self, content: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _json(self, value: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        parsed = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        connection = self._connection()
        try:
            if route == "/":
                self._books(connection)
            elif route == "/settings":
                self._settings(connection)
            elif route.startswith("/books/"):
                self._book_edit(connection, route)
            else:
                self._respond(_layout("Not found", "<h2>Not found</h2>"), HTTPStatus.NOT_FOUND)
        finally:
            connection.close()

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        values = self._form()
        if route == "/choose-folder":
            if not self.native_path_picker_enabled:
                self._json({"error": "Native folder selection is disabled."}, HTTPStatus.FORBIDDEN)
                return
            try:
                selected = choose_folder()
            except RuntimeError as error:
                self._json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._json({"path": selected, "cancelled": not bool(selected)})
            return
        connection = self._connection()
        try:
            try:
                if route == "/settings":
                    settings = Settings(Path(values["library_path"]).expanduser() if values.get("library_path") else None,
                                        parse_import_paths(values.get("import_paths", "")),
                                        values.get("organization_template", "{author}/{title}"))
                    save_settings(connection, settings)
                    self._redirect("/settings?message=Saved")
                elif route == "/scan":
                    count = scan_import_paths(connection, load_settings(connection))
                    self._redirect(f"/?message=Found+{count}+new+book(s)")
                elif route == "/organize":
                    result = organize_all(connection, load_settings(connection))
                    self._redirect(f"/?message=Organized+{len(result)}+book(s)")
                elif route.startswith("/books/") and route.endswith("/organize"):
                    book_id = int(route.split("/")[2])
                    destination = organize_book(connection, load_settings(connection), book_id)
                    self._redirect(f"/books/{book_id}?message=Organized+to+{destination}")
                elif route.startswith("/books/"):
                    book_id = int(route.split("/")[2])
                    metadata = {field: values.get(field, "") for field in METADATA_FIELDS}
                    if not metadata["title"].strip():
                        raise ValueError("A title is required.")
                    update_book_metadata(connection, book_id, metadata)
                    self._redirect(f"/books/{book_id}?message=Saved")
                else:
                    self._respond(_layout("Not found", "<h2>Not found</h2>"), HTTPStatus.NOT_FOUND)
            except (OSError, ValueError, FileExistsError) as error:
                self._respond(_layout("Action failed", _notice(str(error), "error") + "<p><a href='/'>Back to library</a></p>"), HTTPStatus.BAD_REQUEST)
        finally:
            connection.close()

    def _books(self, connection: Session) -> None:
        query = parse_qs(urlparse(self.path).query).get("message", [""])[0]
        rows = "".join(
            f"<tr><td><a href='/books/{book.id}'>{_escape(book.title)}</a></td><td>{_escape(book.author)}</td><td>{_escape(book.series)}</td><td>{_escape(book.status)}</td></tr>"
            for book in list_books(connection)
        ) or "<tr><td colspan='4' class='muted'>No books yet. Configure import paths, then scan.</td></tr>"
        body = _notice(query) + """<div class="actions"><form action="/scan" method="post"><button>Scan import paths</button></form><form action="/organize" method="post"><button class="secondary">Organize all pending</button></form></div>
<p class="muted">Scanning adds records and guesses metadata; organizing copies files into the library. Imports are never deleted.</p>
<table><thead><tr><th>Title</th><th>Author</th><th>Series</th><th>Status</th></tr></thead><tbody>""" + rows + "</tbody></table>"
        self._respond(_layout("Books", body))

    def _settings(self, connection: Session) -> None:
        settings = load_settings(connection)
        picker = ""
        if self.native_path_picker_enabled:
            picker = """<p class="muted">Choose a folder on the computer hosting this service.</p><script>
async function chooseFolder(target) {
  const response = await fetch('/choose-folder', {method: 'POST'});
  const result = await response.json();
  if (result.error) { alert(result.error); return; }
  if (!result.cancelled) {
    const field = document.querySelector(`[name="${target}"]`);
    field.value = target === 'import_paths' && field.value.trim() ? `${field.value.trim()}\\n${result.path}` : result.path;
  }
}
</script>"""
        library_choose_button = '<button type="button" onclick="chooseFolder(\'library_path\')">Choose folder…</button>' if self.native_path_picker_enabled else ""
        import_choose_button = '<button type="button" onclick="chooseFolder(\'import_paths\')">Add import folder…</button>' if self.native_path_picker_enabled else ""
        body = f"""<section><h2>Library settings</h2><p class="muted">Paths are local paths as seen by this server or container.</p><form method="post" action="/settings">
<label>Library path</label><input name="library_path" value="{_escape(settings.library_path)}" placeholder="/data/library">{library_choose_button}
<label>Import paths (one per line)</label><textarea name="import_paths" placeholder="/data/incoming">{_escape(chr(10).join(map(str, settings.import_paths)))}</textarea>{import_choose_button}
<label>Folder template</label><input name="organization_template" value="{_escape(settings.organization_template)}"><p class="muted">Available: {{author}}, {{title}}, {{narrator}}, {{series}}, {{series_number}}, {{year}}. Example: <code>{{author}}/{{series}}/{{title}}</code></p><button>Save settings</button></form></section>"""
        body += picker
        self._respond(_layout("Settings", body))

    def _book_edit(self, connection: Session, route: str) -> None:
        book_id = int(route.split("/")[2])
        book = get_book(connection, book_id)
        if book is None:
            self._respond(_layout("Not found", "<h2>Book not found</h2>"), HTTPStatus.NOT_FOUND)
            return
        message = parse_qs(urlparse(self.path).query).get("message", [""])[0]
        inputs = "".join(f"<label>{field.replace('_', ' ').title()}</label><input name='{field}' value='{_escape(getattr(book, field))}'>" for field in METADATA_FIELDS if field != "description")
        body = _notice(message) + f"""<section><h2>Edit book</h2><form method="post" action="/books/{book_id}">{inputs}<label>Description</label><textarea name="description">{_escape(book.description)}</textarea><button>Save metadata</button></form>
<form method="post" action="/books/{book_id}/organize"><button class="secondary">Organize this book</button></form><p class="muted">Source: {_escape(book.source_path)}<br>Destination: {_escape(book.destination_path) or 'Not organized'}</p></section>"""
        self._respond(_layout(book.title, body))


def choose_folder() -> str:
    """Open the host OS picker and return a directory path, or blank on cancel."""
    if sys.platform == "darwin":
        command = ["osascript", "-e", "POSIX path of (choose folder with prompt \"Select audiobook folder\")"]
    elif shutil.which("zenity"):
        command = ["zenity", "--file-selection", "--directory", "--title=Select audiobook folder"]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory"]
    else:
        raise RuntimeError("No native folder picker is available. Install Zenity or KDialog, or enter the path manually.")
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    return result.stdout.strip() if result.returncode == 0 else ""


def serve(
    database_path: Path,
    host: str = "127.0.0.1",
    port: int = 8686,
    native_path_picker_enabled: bool = False,
) -> None:
    class ConfiguredHandler(LibraryHandler):
        pass
    ConfiguredHandler.session_factory = create_session_factory(database_path)
    ConfiguredHandler.native_path_picker_enabled = native_path_picker_enabled
    with ConfiguredHandler.session_factory() as session:
        remember_database_path(session, database_path)
    server = ThreadingHTTPServer((host, port), ConfiguredHandler)
    print(f"Audiobook Library is running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
