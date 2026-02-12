from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def ensure_dirs(base_dir: Path) -> dict[str, Path]:
    paths = {
        "base": base_dir,
        "input": base_dir / "input",
        "output": base_dir / "output",
        "tmp": base_dir / "tmp",
        "handlers": base_dir / "handlers",
        "normalizers": base_dir / "normalizers",
        "validators": base_dir / "validators",
        "converters": base_dir / "converters",
        "helpers": base_dir / "helpers",
        "tests": base_dir / "tests",
    }
    for path in (paths["input"], paths["output"], paths["tmp"]):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def list_pdfs(input_dir: Path) -> list[Path]:
    return sorted([p for p in input_dir.iterdir() if p.suffix.lower() == ".pdf"])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def safe_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("wb") as handle:
        handle.write(payload)
    tmp_path.replace(path)


def safe_delete_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def load_local_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return {}


def save_local_settings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def timestamp_slug() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d-%H%M%S")
