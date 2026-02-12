from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pdf2ofx.helpers.errors import Stage, StageError


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
        input_source = client.source_from_path(str(pdf_path))

        from mindee.input.inference_parameters import InferenceParameters
        params = InferenceParameters(model_id=model_id)

        response = client.enqueue_and_get_inference(input_source, params)
    except Exception as exc:
        raise StageError(
            stage=Stage.MINDEE,
            message="Mindee inference failed.",
            hint=str(exc),
        ) from exc

    if hasattr(response, "raw_http"):
        raw = response.raw_http
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw
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
