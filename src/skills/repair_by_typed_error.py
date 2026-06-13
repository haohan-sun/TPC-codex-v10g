"""Map typed verifier errors to small local repair patches."""

from __future__ import annotations

from typing import Any

from src.data_layer.schema import ErrorType, TypedError
from src.skills.skill_types import SkillContext, SkillResult


def repair_by_typed_error(
    payload: dict[str, Any],
    context: SkillContext | None = None,
) -> SkillResult:
    """Return local patches for a typed verifier error."""
    error = payload.get("error")
    etype = _error_type(error)
    patches: list[dict[str, Any]] = []

    if etype == ErrorType.FORMAT:
        patches.append({"op": "ensure_schema_fields"})
    elif etype == ErrorType.TICKET:
        patches.append({"op": "normalize_tickets"})
    elif etype == ErrorType.TRANSPORT:
        patches.append({"op": "fill_missing_transport"})
        patches.append({"op": "normalize_transport_units"})
    elif etype == ErrorType.BUDGET:
        patches.append({"op": "replace_with_lower_cost_candidates"})
        patches.append({"op": "trim_optional_attractions"})
    elif etype == ErrorType.TIME:
        patches.append({"op": "push_forward_conflicts"})
    elif etype == ErrorType.MEAL:
        patches.append({"op": "insert_or_shift_meals"})
    elif etype == ErrorType.MUST_VISIT:
        patches.append({"op": "insert_missing_must_visit"})
    elif etype == ErrorType.OPENING_HOURS:
        patches.append({"op": "shift_to_opening_window"})
    else:
        patches.append({"op": "ensure_schema_fields"})
        patches.append({"op": "push_forward_conflicts"})

    return SkillResult(
        name="repair_by_typed_error",
        category="repair",
        decision={"error_type": etype.value, "patch_count": len(patches)},
        patches=patches,
        score=float(len(patches)),
        evidence=[p["op"] for p in patches],
    )


def _error_type(error: Any) -> ErrorType:
    if isinstance(error, TypedError):
        return error.error_type
    value = getattr(error, "error_type", None)
    if isinstance(value, ErrorType):
        return value
    if isinstance(error, dict):
        value = error.get("error_type") or error.get("type")
    try:
        return ErrorType(value)
    except Exception:
        return ErrorType.UNKNOWN
