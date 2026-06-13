"""Verifier error classification."""

from __future__ import annotations

from src.data_layer.schema import ErrorType, TypedError, VerifierError


def parse_errors(errors: list[VerifierError]) -> list[TypedError]:
    return [
        TypedError(
            error_type=_infer_error_type(e),
            message=e.message,
            location=e.location,
            repair_hint=f"repair_{_infer_error_type(e).value}",
        )
        for e in errors
    ]


def _infer_error_type(error: VerifierError) -> ErrorType:
    if error.error_type != ErrorType.UNKNOWN:
        return error.error_type
    text = f"{error.error_code} {error.message}".lower()
    if "ticket" in text:
        return ErrorType.TICKET
    if "budget" in text or "cost" in text:
        return ErrorType.BUDGET
    if "time" in text or "overlap" in text or "conflict" in text:
        return ErrorType.TIME
    if "transport" in text or "taxi" in text or "metro" in text:
        return ErrorType.TRANSPORT
    if "meal" in text or "lunch" in text or "dinner" in text or "breakfast" in text:
        return ErrorType.MEAL
    if "must" in text or "visit" in text:
        return ErrorType.MUST_VISIT
    if "schema" in text or "format" in text or "missing" in text:
        return ErrorType.FORMAT
    if "open" in text or "opening" in text:
        return ErrorType.OPENING_HOURS
    return ErrorType.UNKNOWN
