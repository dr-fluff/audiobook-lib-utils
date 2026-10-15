import os
import shutil
import tempfile
import re
from pathlib import Path

from app.config.settings import Settings
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import Book, BookFile, get_book


AUDIO_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".flac",
    ".m4a",
    ".m4b",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
METADATA_FIELDS = ("title", "author", "narrator", "series", "series_number", "year", "description")


def validate_settings(settings: Settings) -> None:
    if not settings.library_path:
        raise ValueError("Set a library path before scanning or organising books.")
    if not settings.import_paths:
        raise ValueError("Add at least one import path before scanning for books.")
    if not settings.organization_template.strip():
        raise ValueError("The organization template cannot be empty.")
    try:
        settings.organization_template.format(
            author="Author", title="Title", narrator="Narrator",
            series="Series", series_number="1", year="2000",
        )
    except (KeyError, ValueError, IndexError) as error:
        raise ValueError(f"Invalid organization template: {error}") from error
    for path in settings.import_paths:
        if not path.expanduser().is_dir():
            raise ValueError(f"Import path is not a directory: {path}")


def _audio_files(directory: Path) -> list[Path]:
    try:
        return sorted(
            (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS),
            key=lambda path: path.name.casefold(),
        )
    except OSError as error:
        raise OSError(f"Could not read import directory {directory}: {error}") from error


def _discover_books(import_path: Path, library_path: Path) -> list[tuple[Path, list[Path]]]:
    library_resolved = library_path.resolve()
    groups: dict[Path, list[Path]] = {}
    try:
        paths = import_path.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved == library_resolved or library_resolved in resolved.parents:
                continue
            groups.setdefault(path.parent, []).append(path)
    except OSError as error:
        raise OSError(f"Could not scan import path {import_path}: {error}") from error

    books = []
    for parent, files in groups.items():
        files.sort(key=lambda path: path.name.casefold())
        if parent == import_path:
            books.extend((path, [path]) for path in files)
        else:
            books.append((parent, files))
    return sorted(books, key=lambda book: str(book[0]).casefold())


def guess_metadata(source: Path) -> dict[str, str]:
    """Make an editable first-pass metadata guess from a file or folder name."""
    name = source.stem if source.is_file() or source.suffix.lower() in AUDIO_EXTENSIONS else source.name
    name = re.sub(r"^\s*(?:\d{1,3}[ ._-]+)?", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    author = ""
    if " - " in name:
        possible_author, possible_title = name.split(" - ", 1)
        if possible_author and possible_title:
            author, name = possible_author.strip(), possible_title.strip()
    if not author and not source.is_file() and source.parent.name not in ("", "."):
        author = source.parent.name
    return {"title": name or "Untitled", "author": author}


def scan_import_paths(session: Session, settings: Settings) -> int:
    validate_settings(settings)
    assert settings.library_path is not None
    new_books = 0
    for import_path in settings.import_paths:
        import_path = import_path.expanduser().resolve()
        for source, files in _discover_books(import_path, settings.library_path.expanduser()):
            guessed = guess_metadata(source)
            source_path = str(source.resolve())
            book = session.scalar(select(Book).where(Book.source_path == source_path))
            if book is None:
                book = Book(source_path=source_path, title=guessed["title"], author=guessed["author"])
                session.add(book)
                session.flush()
                new_books += 1
            existing_files = {file.source_file for file in book.files}
            for path in files:
                resolved_file = str(path.resolve())
                if resolved_file not in existing_files:
                    book.files.append(BookFile(source_file=resolved_file))
    session.commit()
    return new_books


def _safe_component(value: str, fallback: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in value)
    cleaned = cleaned.strip().strip(".")
    return cleaned or fallback


def _destination_for(settings: Settings, metadata: dict[str, str]) -> Path:
    assert settings.library_path is not None
    template_values = {
        field: _safe_component(metadata.get(field, ""), "Unknown " + field.replace("_", " ").title())
        for field in METADATA_FIELDS
    }
    relative = Path(settings.organization_template.format(**template_values))
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("The organization template must resolve to a safe relative path.")
    library = settings.library_path.expanduser().resolve()
    destination = (library / relative).resolve()
    if destination != library and library not in destination.parents:
        raise ValueError("The organization template resolves outside the library path.")
    return destination


def organize_book(session: Session, settings: Settings, book_id: int) -> Path:
    validate_settings(settings)
    book = get_book(session, book_id)
    if book is None:
        raise ValueError(f"No book found with ID {book_id}.")
    if book.status == "organized" and book.destination_path:
        return Path(book.destination_path)

    files = [
        Path(row.source_file)
        for row in sorted(book.files, key=lambda item: item.source_file.casefold())
    ]
    if not files or any(not path.is_file() for path in files):
        raise FileNotFoundError(f"Source audio files are missing for book {book_id}.")

    metadata = {field: getattr(book, field) for field in METADATA_FIELDS}
    destination = _destination_for(settings, metadata)
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".audiobook-import-", dir=destination.parent))
    try:
        for source in files:
            filename = f"{metadata['title']}{source.suffix}" if len(files) == 1 else source.name
            filename = _safe_component(filename, source.name)
            shutil.copy2(source, staging / filename)
        os.rename(staging, destination)
    except (OSError, shutil.Error):
        if staging.exists():
            shutil.rmtree(staging)
        raise

    book.destination_path = str(destination)
    book.status = "organized"
    session.commit()
    return destination


def organize_all(session: Session, settings: Settings) -> list[tuple[int, Path]]:
    book_ids = list(session.scalars(select(Book.id).where(Book.status != "organized").order_by(Book.id)))
    return [(book_id, organize_book(session, settings, book_id)) for book_id in book_ids]
