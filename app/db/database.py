"""Persistence boundary for Audiobook Library.

All database access lives here and uses SQLAlchemy ORM sessions.  Keeping this
module as the only persistence boundary makes it possible to move beyond
SQLite later without leaking database details into the web or library code.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import ForeignKey, String, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config.settings import Settings


class Base(DeclarativeBase):
    pass


class StoredSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    destination_path: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, default="", nullable=False)
    narrator: Mapped[str] = mapped_column(String, default="", nullable=False)
    series: Mapped[str] = mapped_column(String, default="", nullable=False)
    series_number: Mapped[str] = mapped_column(String, default="", nullable=False)
    year: Mapped[str] = mapped_column(String, default="", nullable=False)
    description: Mapped[str] = mapped_column(String, default="", nullable=False)
    status: Mapped[str] = mapped_column(String, default="imported", nullable=False)
    files: Mapped[list["BookFile"]] = relationship(back_populates="book", cascade="all, delete-orphan")


class BookFile(Base):
    __tablename__ = "book_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    source_file: Mapped[str] = mapped_column(String, nullable=False)
    book: Mapped[Book] = relationship(back_populates="files")


def create_session_factory(database_path: Path) -> sessionmaker[Session]:
    """Create schema and return a session factory for a local SQLite database."""
    path = database_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def load_settings(session: Session) -> Settings:
    values = {item.key: item.value for item in session.scalars(select(StoredSetting)).all()}
    return Settings(
        library_path=Path(values["library_path"]).expanduser() if values.get("library_path") else None,
        import_paths=[Path(value).expanduser() for value in values.get("import_paths", "").splitlines() if value.strip()],
        organization_template=values.get("organization_template", "{author}/{title}"),
    )


def save_settings(session: Session, settings: Settings) -> None:
    values = {
        "library_path": str(settings.library_path.expanduser()) if settings.library_path else "",
        "import_paths": "\n".join(str(path.expanduser()) for path in settings.import_paths),
        "organization_template": settings.organization_template,
    }
    for key, value in values.items():
        stored = session.get(StoredSetting, key)
        if stored is None:
            session.add(StoredSetting(key=key, value=value))
        else:
            stored.value = value
    session.commit()


def remember_database_path(session: Session, database_path: Path) -> None:
    """Keep the chosen path visible in settings and reusable by future tooling."""
    stored = session.get(StoredSetting, "database_path")
    value = str(database_path.expanduser().resolve())
    if stored is None:
        session.add(StoredSetting(key="database_path", value=value))
    else:
        stored.value = value
    session.commit()


def list_books(session: Session) -> list[Book]:
    return list(session.scalars(select(Book).order_by(Book.author.collate("NOCASE"), Book.title.collate("NOCASE"))))


def get_book(session: Session, book_id: int) -> Book | None:
    return session.get(Book, book_id)


def update_book_metadata(session: Session, book_id: int, metadata: dict[str, str]) -> None:
    book = get_book(session, book_id)
    if book is None:
        raise ValueError(f"No book found with ID {book_id}.")
    for field, value in metadata.items():
        setattr(book, field, value.strip())
    session.commit()
