"""Error codes from 05-api-contract.md §1.2. `code` is the stable client contract."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


def invalid_request(msg: str = "Malformed request.") -> ApiError:
    return ApiError(400, "invalid_request", msg)


def not_found(msg: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", msg)


def forbidden(msg: str = "Not your resource.") -> ApiError:
    return ApiError(403, "forbidden", msg)


def market_ambiguous(candidates: list[dict[str, Any]], reason: str = "too_close") -> ApiError:
    """05 §5.2. `code` is the stable contract; the message explains which case it was."""
    message = (
        "That input matched more than one market."
        if reason == "too_close"
        else "That input did not match any market confidently enough to analyse."
    )
    return ApiError(409, "market_ambiguous", message, {"candidates": candidates, "reason": reason})


def run_in_progress(run_id: str) -> ApiError:
    return ApiError(
        409, "run_in_progress", "A run for this market is already active.", {"run_id": run_id}
    )


def report_not_ready(status: str) -> ApiError:
    return ApiError(409, "report_not_ready", "The report is not available yet.", {"status": status})


def service_unknown(raw: str) -> ApiError:
    return ApiError(422, "service_unknown", "That service is not in the taxonomy.", {"input": raw})


def location_unknown(raw: str) -> ApiError:
    return ApiError(422, "location_unknown", "That location could not be resolved.", {"input": raw})


def quota_exceeded() -> ApiError:
    return ApiError(429, "quota_exceeded", "Monthly run quota spent.")
