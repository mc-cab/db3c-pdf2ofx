from __future__ import annotations

import hashlib
import json
import re
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


def tmp_json_path(tmp_dir: Path, source_stem: str) -> Path:
    """Return a short, clickable tmp JSON path (no spaces, fixed length)."""
    slug = hashlib.sha256(source_stem.encode()).hexdigest()[:12]
    return tmp_dir / f"{slug}.json"


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


def normalize_ofx_filename(
    account_id: str,
    period_end: str,
    source_name: str,
    *,
    max_len: int = 80,
) -> str:
    """Build a short, filesystem-safe OFX filename.

    Format: ``{account_id}_{period_end}_{uid4}.ofx``
    Example: ``00020866101_2025-02-28_a3f7.ofx``

    *source_name* is hashed to produce a deterministic 4-char UID that
    avoids collisions when the same account/period is processed twice
    from different source PDFs.
    """
    uid = hashlib.sha256(source_name.encode()).hexdigest()[:4]
    clean_id = re.sub(r"[^a-zA-Z0-9]", "", account_id)
    clean_period = re.sub(r"[^0-9\-]", "", period_end)
    stem = f"{clean_id}_{clean_period}_{uid}"
    max_stem = max_len - 4  # leave room for ".ofx"
    if len(stem) > max_stem:
        stem = stem[:max_stem]
    return f"{stem}.ofx"


def transaction_line_numbers(json_path: Path) -> list[int]:
    """Return 1-based line numbers for each transaction in a Mindee tmp JSON file.

    Supports V2 (inference.result.fields.transactions.items) and V1
    (prediction.Transactions). Returns [] if structure is missing or invalid.
    """
    if not json_path.exists():
        return []
    try:
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    items: list[Any] = []
    # V2: inference.result.fields.transactions.items
    tr = (raw.get("inference") or {}).get("result") or {}
    tr = (tr.get("fields") or {}).get("transactions") or {}
    if isinstance(tr, dict):
        items = tr.get("items") or []
    # V1: document.inference.prediction.Transactions or inference.prediction
    if not isinstance(items, list) or len(items) == 0:
        inf = (raw.get("document") or {}).get("inference") or raw.get("inference") or {}
        pred = inf.get("prediction") or {}
        items = pred.get("Transactions") or pred.get("transactions") or []
    if not isinstance(items, list) or len(items) == 0:
        return []

    count = len(items)
    with json_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the array start line: "items": [ (V2) or "Transactions": [ (V1)
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if '"items": [' in line and i > 0 and "transactions" in lines[i - 1]:
            start_idx = i
            break
    if start_idx is None:
        for i, line in enumerate(lines):
            if '"Transactions": [' in line:
                start_idx = i
                break
    if start_idx is None:
        return []

    # From the line after the "[", find lines that are only whitespace + "{"
    indent_len: int | None = None
    result: list[int] = []
    for k in range(start_idx + 1, len(lines)):
        if len(result) >= count:
            break
        s = lines[k]
        stripped = s.strip()
        if stripped == "{":
            if indent_len is None:
                indent_len = len(s) - len(s.lstrip())
            if indent_len is not None and (len(s) - len(s.lstrip())) == indent_len:
                result.append(k + 1)
    return result
