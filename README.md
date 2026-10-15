# Audiobook Library

A small, self-hostable audiobook organizer for macOS and Linux. It scans one or more import folders, makes editable metadata guesses, and safely **copies** books into a structured library. It does not delete or move your imports.

## Quick start

Requires Python 3.12 or newer.

```sh
export AUDIOBOOK_LIB_DATABASE=./data/library.sqlite3
uv run audiobook-lib setup \
  --library /path/to/audiobooks \
  --imports $'/path/to/incoming\n/path/to/another-inbox'
uv run audiobook-lib scan
uv run audiobook-lib serve
```

Open <http://127.0.0.1:8686> to edit settings and metadata, scan imports, or organize selected books. The default layout is `{author}/{title}` and can be changed in Settings.

## Commands

```text
AUDIOBOOK_LIB_DATABASE=/path/to/library.sqlite3 audiobook-lib setup --library PATH --imports PATHS [--template TEMPLATE]
AUDIOBOOK_LIB_DATABASE=/path/to/library.sqlite3 audiobook-lib scan
AUDIOBOOK_LIB_DATABASE=/path/to/library.sqlite3 audiobook-lib organize
AUDIOBOOK_LIB_DATABASE=/path/to/library.sqlite3 audiobook-lib list
AUDIOBOOK_LIB_DATABASE=/path/to/library.sqlite3 audiobook-lib serve [--host HOST] [--port PORT]
```

## Docker

Adjust the host volume paths in `compose.yaml`, then run:

```sh
docker compose up --build -d
```

Inside the UI, use the container-visible paths: `/library` for the library and `/imports` for imports. The database is persisted in `./data`. Docker binds the interface to localhost by default; put it behind an authenticated reverse proxy before making it available beyond the server.

## Local development and Linux service

For local use, `make help` lists the available commands. A typical first run is:

```sh
make setup LIBRARY=/path/to/audiobooks IMPORTS=/path/to/incoming
make run
```

On macOS, enable a Finder folder picker in the local settings page with:

```sh
make run PICKER=--enable-native-path-picker
```

The picker opens on the computer hosting the service, not on a remote web browser. It is disabled by default and is unsuitable for a headless systemd server; enter server paths manually there.

To deploy directly on a systemd Linux server (without Docker), run this from a checked-out release:

```sh
sudo ./scripts/install-systemd.sh \
  --library /srv/audiobooks \
  --import /srv/audiobook-imports
```

Repeat `--import` for every source folder. The installer creates a dedicated `audiobook-lib` account, stores app state in `/var/lib/audiobook-lib`, writes `/etc/audiobook-lib/audiobook-lib.env`, and enables `audiobook-lib.service`. It binds to `127.0.0.1:8686`; use a reverse proxy with authentication for network access. The service account must be able to read each import folder and write the library folder.

## Current scope

The first release supports common audio extensions, a SQLite database through SQLAlchemy, metadata inferred from `Author - Title` file names, editable fields (title, author, narrator, series, year, and description), and copy-based organization. Online metadata providers and embedded audio-tag reading can be added as opt-in providers in a later release.

## Database location and restarts

Set `AUDIOBOOK_LIB_DATABASE` (recommended for a service/container) or pass `--database /path/to/library.sqlite3` before every command. This is intentionally an explicit deployment setting: a process cannot discover a database before it knows where to open it. Once opened, the database records the chosen location plus all library, import-path, organization, and metadata settings. Docker sets the variable to `/data/audiobook-library.sqlite3` automatically.
