"""Tests for helpers/fs."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from pdf2ofx.converters.ofx_emitter import emit_ofx
from pdf2ofx.helpers.fs import (
    ensure_recovery_dir,
    list_tmp_jsons,
    read_tmp_meta,
    resolve_source_path_from_meta,
    selective_tmp_cleanup,
    transaction_line_numbers,
    write_json,
    write_tmp_meta,
)
from pdf2ofx.validators.contract_validator import validate_statement


def test_transaction_line_numbers_v2(tmp_path: Path) -> None:
    """V2 structure: inference.result.fields.transactions.items."""
    json_path = tmp_path / "v2.json"
    json_path.write_text(
        """{
  "inference": {
    "result": {
      "fields": {
        "transactions": {
          "items": [
            {
              "fields": {}
            },
            {
              "fields": {}
            }
          ]
        }
      }
    }
  }
}
""",
        encoding="utf-8",
    )
    lines = transaction_line_numbers(json_path)
    assert len(lines) == 2
    assert lines[0] < lines[1]


def test_transaction_line_numbers_missing_file(tmp_path: Path) -> None:
    assert transaction_line_numbers(tmp_path / "nonexistent.json") == []


def test_transaction_line_numbers_empty_items(tmp_path: Path) -> None:
    json_path = tmp_path / "empty.json"
    json_path.write_text(
        '{"inference":{"result":{"fields":{"transactions":{"items":[]}}}}}',
        encoding="utf-8",
    )
    assert transaction_line_numbers(json_path) == []


# ---------------------------------------------------------------------------
# list_tmp_jsons: recovery candidates (hard rule)
# ---------------------------------------------------------------------------


def test_list_tmp_jsons_includes_only_top_level_json(tmp_path: Path) -> None:
    """Recovery candidates = tmp/*.json; exclude tmp/recovery/** and *.raw.json / *.canonical.json."""
    (tmp_path / "a1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b2.json").write_text("{}", encoding="utf-8")
    got = list_tmp_jsons(tmp_path)
    assert len(got) == 2
    assert {p.name for p in got} == {"a1.json", "b2.json"}


def test_list_tmp_jsons_excludes_recovery_subdir(tmp_path: Path) -> None:
    """Exclude any path under tmp/recovery/."""
    (tmp_path / "top.json").write_text("{}", encoding="utf-8")
    recovery = tmp_path / "recovery"
    recovery.mkdir(parents=True)
    (recovery / "recover_abc.json").write_text("{}", encoding="utf-8")
    (recovery / "recover_abc.raw.json").write_text("{}", encoding="utf-8")
    (recovery / "recover_abc.canonical.json").write_text("{}", encoding="utf-8")
    got = list_tmp_jsons(tmp_path)
    assert len(got) == 1
    assert got[0].name == "top.json"


def test_list_tmp_jsons_excludes_raw_and_canonical_suffix(tmp_path: Path) -> None:
    """Exclude *.raw.json and *.canonical.json even in top-level tmp."""
    (tmp_path / "plain.json").write_text("{}", encoding="utf-8")
    (tmp_path / "x.raw.json").write_text("{}", encoding="utf-8")
    (tmp_path / "x.canonical.json").write_text("{}", encoding="utf-8")
    got = list_tmp_jsons(tmp_path)
    assert len(got) == 1
    assert got[0].name == "plain.json"


def test_list_tmp_jsons_excludes_meta_json(tmp_path: Path) -> None:
    """Exclude *.meta.json so sidecar files are not recovery candidates."""
    (tmp_path / "a1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a1.meta.json").write_text('{"source_pdf_path":"/x.pdf","source_name":"x.pdf"}', encoding="utf-8")
    (tmp_path / "b2.meta.json").write_text("{}", encoding="utf-8")
    got = list_tmp_jsons(tmp_path)
    assert len(got) == 1
    assert got[0].name == "a1.json"


def test_list_tmp_jsons_empty_when_dir_missing(tmp_path: Path) -> None:
    assert list_tmp_jsons(tmp_path / "nonexistent") == []


def test_ensure_recovery_dir_creates_and_returns_path(tmp_path: Path) -> None:
    recovery = ensure_recovery_dir(tmp_path)
    assert recovery == tmp_path / "recovery"
    assert recovery.exists() and recovery.is_dir()
    ensure_recovery_dir(tmp_path)
    assert recovery.exists()


def test_selective_tmp_cleanup_deletes_clean_keeps_rest(tmp_path: Path) -> None:
    clean = tmp_path / "clean.json"
    dirty = tmp_path / "dirty.json"
    clean.write_text("{}", encoding="utf-8")
    dirty.write_text("{}", encoding="utf-8")
    kept = selective_tmp_cleanup([
        (clean, None),
        (dirty, "reconciliation ERROR"),
    ])
    assert not clean.exists()
    assert dirty.exists()
    assert kept == ["dirty.json — reconciliation ERROR"]


# ---------------------------------------------------------------------------
# write_json with decimal_to_str: canonical statement persistence
# ---------------------------------------------------------------------------


def _minimal_canonical_statement_with_decimal() -> dict:
    """Canonical statement with Decimal in transactions (as in recovery path)."""
    return {
        "schema_version": "1.0",
        "account": {"account_id": "ACC-123", "bank_id": "B", "account_type": "CHECKING", "currency": "EUR"},
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        "transactions": [
            {
                "fitid": "FIT1",
                "posted_at": "2024-01-05",
                "amount": Decimal("-3.50"),
                "debit": Decimal("3.50"),
                "credit": None,
                "name": "Coffee",
                "memo": "x",
                "trntype": "DEBIT",
            },
        ],
    }


def test_write_json_decimal_to_str_roundtrip_and_reparse(tmp_path: Path) -> None:
    """With decimal_to_str=True, Decimal is serialized as string; load back and reparse to same value."""
    stmt = _minimal_canonical_statement_with_decimal()
    path = tmp_path / "canon.json"
    write_json(path, stmt, decimal_to_str=True)
    raw = path.read_text(encoding="utf-8")
    loaded = json.loads(raw)
    assert loaded["transactions"][0]["amount"] == "-3.50"
    assert loaded["transactions"][0]["debit"] == "3.50"
    assert loaded["transactions"][0]["credit"] is None
    assert Decimal(loaded["transactions"][0]["amount"]) == Decimal("-3.50")
    assert Decimal(loaded["transactions"][0]["debit"]) == Decimal("3.50")


def test_write_json_decimal_to_str_downstream_compatibility(tmp_path: Path) -> None:
    """Loaded canonical JSON (string amounts) is accepted by validate_statement and emit_ofx."""
    stmt = _minimal_canonical_statement_with_decimal()
    path = tmp_path / "canon.json"
    write_json(path, stmt, decimal_to_str=True)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    result = validate_statement(loaded)
    assert result.statement is not None
    payload = emit_ofx(result.statement, "OFX2")
    assert isinstance(payload, bytes)
    assert b"FIT1" in payload or b"STMTTRN" in payload


# ---------------------------------------------------------------------------
# write_tmp_meta / read_tmp_meta: provenance sidecar (v0.1.2)
# ---------------------------------------------------------------------------


def test_write_tmp_meta_read_tmp_meta_roundtrip(tmp_path: Path) -> None:
    """write_tmp_meta creates .meta.json; read_tmp_meta returns dict with source_pdf_path, source_name."""
    tmp_json = tmp_path / "abc123.json"
    tmp_json.write_text("{}", encoding="utf-8")
    source_pdf = tmp_path / "input" / "statement_01-2025.pdf"
    source_pdf.parent.mkdir(parents=True)
    source_pdf.write_bytes(b"")
    write_tmp_meta(tmp_json, source_pdf)
    meta = read_tmp_meta(tmp_json)
    assert meta is not None
    assert meta["source_name"] == "statement_01-2025.pdf"
    assert "statement_01-2025.pdf" in meta["source_pdf_path"]
    assert (tmp_path / "abc123.meta.json").exists()


def test_read_tmp_meta_returns_none_when_missing(tmp_path: Path) -> None:
    """read_tmp_meta returns None when sidecar does not exist."""
    tmp_json = tmp_path / "nonexistent.json"
    tmp_json.write_text("{}", encoding="utf-8")
    assert read_tmp_meta(tmp_json) is None


def test_read_tmp_meta_returns_none_when_invalid(tmp_path: Path) -> None:
    """read_tmp_meta returns None for invalid JSON or missing required keys."""
    tmp_json = tmp_path / "bad.json"
    tmp_json.write_text("{}", encoding="utf-8")
    (tmp_path / "bad.meta.json").write_text("not json", encoding="utf-8")
    assert read_tmp_meta(tmp_json) is None
    (tmp_path / "bad.meta.json").write_text('{"only":"key"}', encoding="utf-8")
    assert read_tmp_meta(tmp_json) is None


def test_resolve_source_path_from_meta_order(tmp_path: Path) -> None:
    """Resolution order: meta path if exists, then processed/<name>, then input/<name>."""
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    input_dir.mkdir()
    processed_dir.mkdir()
    (processed_dir / "2025-02").mkdir()
    pdf_in_processed = processed_dir / "2025-02" / "stmt.pdf"
    pdf_in_processed.write_bytes(b"")
    pdf_in_input = input_dir / "stmt.pdf"
    pdf_in_input.write_bytes(b"")

    meta_existing = {"source_pdf_path": str(pdf_in_processed.resolve()), "source_name": "stmt.pdf"}
    got = resolve_source_path_from_meta(meta_existing, processed_dir, input_dir)
    assert got == pdf_in_processed

    meta_moved = {"source_pdf_path": str((tmp_path / "gone.pdf").resolve()), "source_name": "stmt.pdf"}
    got = resolve_source_path_from_meta(meta_moved, processed_dir, input_dir)
    assert got == pdf_in_processed  # found in processed/2025-02/stmt.pdf

    (processed_dir / "2025-02" / "stmt.pdf").unlink()
    got = resolve_source_path_from_meta(meta_moved, processed_dir, input_dir)
    assert got == pdf_in_input

    pdf_in_input.unlink()
    got = resolve_source_path_from_meta(meta_moved, processed_dir, input_dir)
    assert got is None


def test_write_json_decimal_to_str_raises_on_other_non_serializable(tmp_path: Path) -> None:
    """When decimal_to_str=True, non-Decimal non-serializable types raise TypeError (no silent coercion)."""
    from datetime import date
    path = tmp_path / "bad.json"
    payload = {"x": date(2024, 1, 15)}
    with pytest.raises(TypeError, match="not JSON serializable"):
        write_json(path, payload, decimal_to_str=True)
