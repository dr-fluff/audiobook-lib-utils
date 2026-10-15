from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.config.settings import Settings, parse_import_paths
from app.db.database import create_session_factory, list_books, load_settings, remember_database_path, save_settings
from app.lib.library import organize_all, scan_import_paths
from app.web.server import serve


def _database(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audiobook-lib", description="Organize an audiobook library.")
    configured_database = os.environ.get("AUDIOBOOK_LIB_DATABASE")
    parser.add_argument(
        "--database", type=_database, default=_database(configured_database) if configured_database else None,
        required=not bool(configured_database),
        help="SQLite database path (or set AUDIOBOOK_LIB_DATABASE)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Save library and import paths")
    setup.add_argument("--library", required=True, type=Path)
    setup.add_argument("--imports", required=True, help="Import paths, separated by newlines")
    setup.add_argument("--template", default="{author}/{title}")
    commands.add_parser("scan", help="Find audiobooks in the configured import paths")
    commands.add_parser("organize", help="Copy all scanned books into the library")
    commands.add_parser("list", help="List known books")
    web = commands.add_parser("serve", help="Run the web interface")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8686)
    web.add_argument(
        "--enable-native-path-picker", action="store_true",
        default=os.environ.get("AUDIOBOOK_LIB_NATIVE_PATH_PICKER") == "1",
        help="Allow the GUI to open Finder/Zenity on the computer hosting the service",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        serve(args.database, args.host, args.port, args.enable_native_path_picker)
        return
    session_factory = create_session_factory(args.database)
    with session_factory() as session:
        remember_database_path(session, args.database)
        if args.command == "setup":
            settings = Settings(args.library.expanduser(), parse_import_paths(args.imports), args.template)
            save_settings(session, settings)
            print("Settings saved.")
        elif args.command == "scan":
            print(f"Found {scan_import_paths(session, load_settings(session))} new book(s).")
        elif args.command == "organize":
            print(f"Organized {len(organize_all(session, load_settings(session)))} book(s).")
        elif args.command == "list":
            for book in list_books(session):
                print(f"{book.id:>4}  {book.status:<10}  {book.author} — {book.title}")


if __name__ == "__main__":
    main()
