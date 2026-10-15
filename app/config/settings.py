from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_ORGANIZATION_TEMPLATE = "{author}/{title}"


@dataclass
class Settings:
    library_path: Path | None = None
    import_paths: list[Path] = field(default_factory=list)
    organization_template: str = DEFAULT_ORGANIZATION_TEMPLATE


def parse_import_paths(value: str) -> list[Path]:
    return [Path(line.strip()).expanduser() for line in value.splitlines() if line.strip()]
