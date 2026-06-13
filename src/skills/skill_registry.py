"""Compatibility facade for the local skill registry.

New code should import from ``src.skills.registry``.  This module remains so
older imports do not recreate the previous Plan-wide apply_all behavior.
"""

from __future__ import annotations

from src.skills.registry import call_skill, get_skill, list_skills, register_builtin_skills, register_skill
from src.skills.skill_types import SkillContext, SkillResult, SkillSpec

__all__ = [
    "SkillContext",
    "SkillResult",
    "SkillSpec",
    "call_skill",
    "get_skill",
    "list_skills",
    "register_builtin_skills",
    "register_skill",
]
