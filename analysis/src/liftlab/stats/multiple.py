"""Holm's correction for testing several secondary metrics at once.

Each extra metric is another chance for a false positive. Holm keeps the chance of any false
positive across the family at alpha, and it rejects everything Bonferroni does and sometimes
more: the smallest p-value is compared with alpha / m, the next with alpha / (m - 1), and so
on, stopping at the first that fails.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class HolmResult:
    p_values: tuple[float, ...]
    adjusted: tuple[float, ...]  # compare each with alpha
    reject: tuple[bool, ...]
    alpha: float


def holm(p_values: Sequence[float], *, alpha: float = 0.05) -> HolmResult:
    """Holm-adjusted p-values, in the order given."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if any(not 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be between 0 and 1")
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        # Adjusted p-values can't decrease down the sorted list, or a larger p would be
        # rejected while a smaller one isn't.
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return HolmResult(
        p_values=tuple(float(p) for p in p_values),
        adjusted=tuple(adjusted),
        reject=tuple(p <= alpha for p in adjusted),
        alpha=alpha,
    )
