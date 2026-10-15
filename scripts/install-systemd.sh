#!/usr/bin/env bash
# Install Audiobook Library as a local, systemd-managed Linux service.
# Run with sudo from a checked-out release of this repository.
set -euo pipefail

SERVICE_NAME="audiobook-lib"
SERVICE_USER="audiobook-lib"
INSTALL_DIR="/opt/audiobook-lib"
STATE_DIR="/var/lib/audiobook-lib"
DATABASE_PATH="${STATE_DIR}/library.sqlite3"
CONFIG_DIR="/etc/audiobook-lib"
HOST="127.0.0.1"
PORT="8686"
LIBRARY_PATH=""
IMPORT_PATHS=()
RECONFIGURE=false
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: sudo ./scripts/install-systemd.sh --library PATH --import PATH [options]

Required:
  --library PATH          Destination audiobook library directory.
  --import PATH           Source import directory. Repeat for multiple paths.

Options:
  --database PATH         SQLite database path (default: /var/lib/audiobook-lib/library.sqlite3)
  --host ADDRESS          Bind address (default: 127.0.0.1)
  --port PORT             Web port (default: 8686)
  --user USER             Service user (default: audiobook-lib)
  --install-dir PATH      Application installation directory (default: /opt/audiobook-lib)
  --reconfigure           Replace existing library/import settings in the database.
  --source PATH           Source checkout to install (default: this script's repository).
  -h, --help              Show this help.

The service is deliberately bound to localhost. Use an authenticated reverse
proxy if it must be reachable from another machine.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --library) LIBRARY_PATH="$2"; shift 2 ;;
    --import) IMPORT_PATHS+=("$2"); shift 2 ;;
    --database) DATABASE_PATH="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --user) SERVICE_USER="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --source) SOURCE_DIR="$2"; shift 2 ;;
    --reconfigure) RECONFIGURE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  printf 'Run this installer with sudo or as root.\n' >&2
  exit 1
fi
if [[ -z "$LIBRARY_PATH" || ${#IMPORT_PATHS[@]} -eq 0 ]]; then
  printf 'At least one --library and --import path are required.\n' >&2
  usage >&2
  exit 2
fi
for command in python3 rsync systemctl runuser; do
  command -v "$command" >/dev/null || { printf 'Missing required command: %s\n' "$command" >&2; exit 1; }
done
[[ -f "$SOURCE_DIR/pyproject.toml" ]] || { printf 'Not a project source directory: %s\n' "$SOURCE_DIR" >&2; exit 1; }
[[ -d "$LIBRARY_PATH" ]] || { printf 'Library directory does not exist: %s\n' "$LIBRARY_PATH" >&2; exit 1; }
for import_path in "${IMPORT_PATHS[@]}"; do
  [[ -d "$import_path" ]] || { printf 'Import directory does not exist: %s\n' "$import_path" >&2; exit 1; }
done

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -m 0755 "$INSTALL_DIR" "$CONFIG_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$STATE_DIR"
DATABASE_DIR="$(dirname "$DATABASE_PATH")"
if [[ ! -d "$DATABASE_DIR" ]]; then
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATABASE_DIR"
fi
runuser -u "$SERVICE_USER" -- test -w "$DATABASE_DIR" || {
  printf 'The service user %s cannot write the database directory: %s\n' "$SERVICE_USER" "$DATABASE_DIR" >&2
  exit 1
}
rsync -a --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'data/' --exclude '__pycache__/' \
  --exclude '.pytest_cache/' "$SOURCE_DIR/" "$INSTALL_DIR/"
chown -R root:root "$INSTALL_DIR"

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --disable-pip-version-check --no-cache-dir "$INSTALL_DIR"

cat >"$CONFIG_DIR/audiobook-lib.env" <<EOF
# This file survives application upgrades. Change it, then run:
# sudo systemctl restart audiobook-lib
AUDIOBOOK_LIB_DATABASE=${DATABASE_PATH}
AUDIOBOOK_LIB_HOST=${HOST}
AUDIOBOOK_LIB_PORT=${PORT}
EOF
chmod 0640 "$CONFIG_DIR/audiobook-lib.env"
chown root:"$SERVICE_USER" "$CONFIG_DIR/audiobook-lib.env"

cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Audiobook Library web service
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${CONFIG_DIR}/audiobook-lib.env
ExecStart=${INSTALL_DIR}/.venv/bin/audiobook-lib serve --host \${AUDIOBOOK_LIB_HOST} --port \${AUDIOBOOK_LIB_PORT}
Restart=on-failure
RestartSec=5
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=${STATE_DIR}

[Install]
WantedBy=multi-user.target
EOF

# Only initialize paths on the first install. Existing settings remain intact
# unless --reconfigure was supplied.
if [[ ! -f "$DATABASE_PATH" || "$RECONFIGURE" == true ]]; then
  imports_for_cli="$(printf '%s\n' "${IMPORT_PATHS[@]}")"
  runuser -u "$SERVICE_USER" -- "$INSTALL_DIR/.venv/bin/audiobook-lib" setup \
    --library "$LIBRARY_PATH" --imports "$imports_for_cli"
fi

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

printf '\nInstalled %s.\n' "$SERVICE_NAME"
printf 'Status:  sudo systemctl status %s\n' "$SERVICE_NAME"
printf 'Logs:    sudo journalctl -u %s -f\n' "$SERVICE_NAME"
printf 'Open:    http://%s:%s\n' "$HOST" "$PORT"
printf '\nEnsure %s can read every --import path and write the library path.\n' "$SERVICE_USER"
