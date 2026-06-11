# =============================================================================
# @project    ELY — Exactly Like You
# @file       app/agent/tools/graduated/fibonacci_tool.py
# @brief      Tool gradué — généré par Ely, éprouvé à l'usage, converti
#             en code core par le pipeline de graduation (Sprint 4d V4).
#
# @author     Ely (auto-developing agent) — revue humaine via PR
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#
# PROVENANCE (gates au moment de la graduation) :
# {
#   "learned_skill_id": "dff03273-74cb-44ff-814d-85383702acad",
#   "origin_user": "4be29159",
#   "graduated_at": "2026-06-11T12:50:06+00:00",
#   "stats": {
#     "invocations": 2,
#     "use_count": 2,
#     "io_dispatches": 0,
#     "errors_recent": 0,
#     "refusals_recent": 0,
#     "age_days": 5,
#     "last_error_at": null,
#     "last_used_at": "2026-06-11T12:30:11.611776"
#   }
# }
# =============================================================================
from __future__ import annotations

from langchain_core.tools import tool

from app.skills.base import Domain
from app.skills.decorator import register


@register(
    domain=Domain.WORKSPACE,
    skill_name="fibonacci",
    skill_display_name="Fibonacci Number",
    skill_description=(
        "Compute the n-th Fibonacci number (F(0)=0, F(1)=1) "
        "using a pure iterative method."
    ),
    skill_icon="🧩",
    enabled_by_default=False,
)
@tool
def fibonacci(n: int) -> int:
    """Compute the n-th Fibonacci number (0-indexed, F(0)=0, F(1)=1).

    Use this tool when you need the exact Fibonacci number for a
    non-negative integer n (e.g., n=10 returns 55).  It uses an
    iterative O(n) algorithm and requires no external I/O.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
