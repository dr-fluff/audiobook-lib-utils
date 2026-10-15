import tempfile
import unittest
from pathlib import Path

from app.config.settings import Settings
from app.db.database import create_session_factory, get_book, list_books, load_settings, remember_database_path, save_settings
from app.lib.library import guess_metadata, organize_book, scan_import_paths


class LibraryTests(unittest.TestCase):
    def test_guesses_author_and_title(self):
        guessed = guess_metadata(Path("Ursula Le Guin - A Wizard of Earthsea.m4b"))
        self.assertEqual(guessed, {"author": "Ursula Le Guin", "title": "A Wizard of Earthsea"})

    def test_scan_and_organize_copies_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imports, library = root / "imports", root / "library"
            imports.mkdir()
            source = imports / "Author - Story.mp3"
            source.write_bytes(b"audio")
            session_factory = create_session_factory(root / "library.sqlite3")
            with session_factory() as session:
                settings = Settings(library, [imports])
                self.assertEqual(scan_import_paths(session, settings), 1)
                book = list_books(session)[0]
                destination = organize_book(session, settings, book.id)
                self.assertTrue((destination / "Story.mp3").is_file())
                self.assertTrue(source.is_file())
                self.assertEqual(get_book(session, book.id).status, "organized")

    def test_settings_and_database_location_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "state" / "library.sqlite3"
            session_factory = create_session_factory(database_path)
            with session_factory() as session:
                remember_database_path(session, database_path)
                save_settings(session, Settings(root / "library", [root / "inbox-a", root / "inbox-b"], "{author}/{series}/{title}"))
            with session_factory() as session:
                settings = load_settings(session)
                self.assertEqual(settings.library_path, root / "library")
                self.assertEqual(settings.import_paths, [root / "inbox-a", root / "inbox-b"])
                self.assertEqual(settings.organization_template, "{author}/{series}/{title}")
