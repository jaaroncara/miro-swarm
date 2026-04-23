"""Shared observability helpers for the simulation task pipeline."""

from __future__ import annotations

import json
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("mirofish.task_pipeline")


def _serialise_field_value(value: Any) -> str:
    if isinstance(value, set):
        value = sorted(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def log_task_pipeline_metric(
    metric_name: str,
    *,
    level: str = "info",
    **fields: Any,
) -> None:
    parts = [f"name={metric_name}"]
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={_serialise_field_value(value)}")

    message = "TASK_PIPELINE_METRIC " + " ".join(parts)
    log_method = getattr(logger, level, logger.info)
    log_method(message)
