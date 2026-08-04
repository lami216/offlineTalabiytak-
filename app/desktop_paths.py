import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True)
class DesktopPaths:
    root: Path
    database: Path
    images: Path
    logs: Path
    temp: Path
    secret: Path

    @classmethod
    def create(cls, root: Path | None = None):
        base = Path(root or user_data_path("Talabiytak", appauthor=False)) / "data"
        result = cls(
            base,
            base / "talabiytak.db",
            base / "images",
            base / "logs",
            base / "temp",
            base / "settings.key",
        )
        for directory in (result.root, result.images, result.logs, result.temp):
            directory.mkdir(parents=True, exist_ok=True)
        return result


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)
