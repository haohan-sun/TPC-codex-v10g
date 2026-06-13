"""Shared types for local travel-planning skills.

Skills are small offline decision functions.  They return a local decision or
patch list; they must not rewrite an entire official plan payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class SkillContext:
    """Runtime context passed to skills without coupling them to one stage."""

    constraints: Any | None = None
    candidates: Any | None = None
    preferences: Any | None = None
    sandbox: Any | None = None
    policy: str = "safe"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """A local skill output.

    decision stores a structured local choice.  patches stores small edit
    operations that a caller may apply to its current slice of state.
    """

    name: str
    category: str
    decision: dict[str, Any] = field(default_factory=dict)
    patches: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillSpec:
    """Registry metadata for an offline local decision skill."""

    name: str
    category: str
    phase: str
    fn: Callable[[dict[str, Any], SkillContext | None], SkillResult]
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()
    description: str = ""
