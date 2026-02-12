from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.errors import Stage, StageError


def infer_pdf(api_key: str, model_id: str, pdf_path: Path) -> dict[str, Any]:
    try:
        from mindee import ClientV2
    except Exception as exc:  # pragma: no cover - dependency issues
        raise StageError(
            stage=Stage.MINDEE,
            message="Mindee client library unavailable.",
            hint="Install the mindee package.",
        ) from exc

    try:
        client = ClientV2(api_key)
        with pdf_path.open("rb") as handle:
            response = client.enqueue_and_get_inference(file=handle, model_id=model_id)
    except Exception as exc:
        raise StageError(
            stage=Stage.MINDEE,
            message="Mindee inference failed.",
            hint=str(exc),
        ) from exc

    if hasattr(response, "raw_data"):
        return response.raw_data
    if hasattr(response, "raw_response"):
        return response.raw_response
    if isinstance(response, dict):
        return response
    raise StageError(
        stage=Stage.MINDEE,
        message="Mindee response could not be serialized.",
        hint="Unexpected response format.",
    )
