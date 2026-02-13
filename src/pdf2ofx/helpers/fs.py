from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


def open_path_in_default_app(path: Path) -> None:
    """Open a file with the system default application (e.g. PDF in viewer)."""
    path_str = str(path)
    if sys.platform == "win32":
        os.startfile(path_str)
    elif sys.platform == "darwin":
        subprocess.run(["open", path_str], check=False)
    else:
        subprocess.run(["xdg-open", path_str], check=False)


def ensure_dirs(base_dir: Path) -> dict[str, Path]:
    paths = {
        "base": base_dir,
        "input": base_dir / "input",
        "output": base_dir / "output",
        "tmp": base_dir / "tmp",
        "processed": base_dir / "processed",
        "failed": base_dir / "failed",
        "handlers": base_dir / "handlers",
        "normalizers": base_dir / "normalizers",
        "validators": base_dir / "validators",
        "converters": base_dir / "converters",
        "helpers": base_dir / "helpers",
        "tests": base_dir / "tests",
    }
    for path in (
        paths["input"],
        paths["output"],
        paths["tmp"],
        paths["processed"],
        paths["failed"],
    ):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def list_pdfs(input_dir: Path) -> list[Path]:
    return sorted([p for p in input_dir.iterdir() if p.suffix.lower() == ".pdf"])


def list_tmp_jsons(tmp_dir: Path) -> list[Path]:
    """List recovery candidates: tmp/*.json only.

    Excludes:
    - Any path under tmp/recovery/ (tmp/recovery/**)
    - Any file named *.raw.json, *.canonical.json, or *.meta.json

    Returns sorted list of Paths. Does not create tmp_dir.
    """
    if not tmp_dir.exists():
        return []
    recovery_dir = tmp_dir / "recovery"
    candidates: list[Path] = []
    for p in tmp_dir.iterdir():
        if not p.is_file() or p.suffix.lower() != ".json":
            continue
        if recovery_dir in p.parents or p.parent == recovery_dir:
            continue
        if p.name.endswith(".raw.json") or p.name.endswith(".canonical.json"):
            continue
        if p.name.endswith(".meta.json"):
            continue
        candidates.append(p)
    return sorted(candidates)


def ensure_recovery_dir(tmp_dir: Path) -> Path:
    """Create tmp/recovery/ if needed; return the path."""
    recovery_dir = tmp_dir / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    return recovery_dir


def selective_tmp_cleanup(
    path_keep_reasons: list[tuple[Path, str | None]],
) -> list[str]:
    """Delete tmp files that are 'clean'; return list of 'Kept: filename — reason'.

    For each (path, keep_reason): if path.exists(), then if keep_reason is None
    the file is deleted; else the file is kept and 'path.name — keep_reason'
    is appended to the returned list.
    """
    kept: list[str] = []
    for path, keep_reason in path_keep_reasons:
        if not path.exists():
            continue
        if keep_reason is None:
            try:
                path.unlink()
            except OSError:
                kept.append(f"{path.name} — could not delete")
        else:
            kept.append(f"{path.name} — {keep_reason}")
    return kept


def tmp_json_path(tmp_dir: Path, source_stem: str) -> Path:
    """Return a short, clickable tmp JSON path (no spaces, fixed length)."""
    slug = hashlib.sha256(source_stem.encode()).hexdigest()[:12]
    return tmp_dir / f"{slug}.json"


def _meta_path_for_tmp_json(tmp_json_path: Path) -> Path:
    """Sidecar meta path for a tmp JSON: same dir, same stem, .meta.json suffix."""
    return tmp_json_path.with_name(tmp_json_path.stem + ".meta.json")


def write_tmp_meta(tmp_json_path: Path, source_pdf_path: Path) -> None:
    """Write provenance sidecar tmp/<stem>.meta.json for recovery.

    Payload: source_pdf_path (resolved), source_name.
    Call after a successful raw extraction (no Mindee changes).
    """
    meta_path = _meta_path_for_tmp_json(tmp_json_path)
    payload = {
        "source_pdf_path": str(source_pdf_path.resolve()),
        "source_name": source_pdf_path.name,
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def read_tmp_meta(tmp_json_path: Path) -> dict | None:
    """Read provenance sidecar for a tmp JSON. Returns dict with source_pdf_path, source_name or None."""
    meta_path = _meta_path_for_tmp_json(tmp_json_path)
    if not meta_path.exists():
        return None
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or "source_pdf_path" not in data or "source_name" not in data:
        return None
    return data


def resolve_source_path_from_meta(
    meta: dict,
    processed_dir: Path,
    input_dir: Path,
) -> Path | None:
    """Resolve the source PDF path from meta, resilient to PDF move to processed/.

    Order: 1) meta['source_pdf_path'] if exists; 2) processed/<run_date>/source_name;
    3) input/source_name; 4) None.
    """
    source_name = meta.get("source_name")
    if not source_name:
        return None
    raw_path = meta.get("source_pdf_path")
    if raw_path:
        p = Path(raw_path)
        if p.exists():
            return p
    if processed_dir.exists():
        for sub in processed_dir.iterdir():
            if sub.is_dir():
                candidate = sub / source_name
                if candidate.exists():
                    return candidate
    candidate = input_dir / source_name
    if candidate.exists():
        return candidate
    return None


def write_json(path: Path, payload: Any, *, decimal_to_str: bool = False) -> None:
    """Write payload as JSON. When decimal_to_str=True, Decimal is serialized as string; other non-serializable types raise TypeError."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        raise TypeError(f"Object of type {o.__class__.__name__!r} is not JSON serializable")

    kwargs: dict[str, Any] = {"ensure_ascii": False, "indent": 2}
    if decimal_to_str:
        kwargs["default"] = default
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, **kwargs)


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
