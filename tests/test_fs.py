"""Tests for helpers/fs."""
from __future__ import annotations

from pathlib import Path

import pytest

from pdf2ofx.helpers.fs import transaction_line_numbers


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
