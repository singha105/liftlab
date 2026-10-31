"""Percentile bootstrap intervals for statistics without a handy variance formula.

Resample the units with replacement, recompute the statistic, repeat, and take the middle
95% of the results. It's for things like a p75 load time, where there's no textbook standard
error. The unit is the first axis of each sample: to resample users rather than page loads,
pass one row per user (padded with NaN) and have the statistic ignore the padding.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

# Resampled values held in memory at once; batches keep a large bootstrap from needing GBs.
_BATCH_VALUES = 20_000_000


@dataclass(frozen=True)
class BootstrapResult:
    estimate: float  # the statistic on the original samples
    ci: tuple[float, float]
    se: float  # standard deviation of the bootstrap distribution
    n_resamples: int
    level: float


def bootstrap_ci(
    statistic: Callable[..., ArrayLike],
    *samples: ArrayLike,
    n_resamples: int = 2000,
    level: float = 0.95,
    seed: int | np.random.Generator | None = None,
) -> BootstrapResult:
    """Percentile bootstrap interval for `statistic(*samples)`.

    Each sample is resampled independently along its first axis, the way each arm of an
    experiment is. `statistic` must be vectorized: it gets one array per sample with an extra
    leading axis of resamples, shape (B, n, ...), and returns B values. For example
    `lambda c, t: t.mean(axis=1) - c.mean(axis=1)`. The same seed gives the same interval.
    """
    if not 0 < level < 1:
        raise ValueError("level must be between 0 and 1")
    if n_resamples < 100:
        raise ValueError("use at least 100 resamples")
    arrays = [np.asarray(sample, dtype=float) for sample in samples]
    if not arrays or any(len(a) < 2 for a in arrays):
        raise ValueError("each sample needs at least two units")

    estimate = _call(statistic, [a[None] for a in arrays], 1)[0]
    rng = np.random.default_rng(seed)
    batch = max(1, _BATCH_VALUES // sum(a.size for a in arrays))
    draws = np.empty(n_resamples)
    for start in range(0, n_resamples, batch):
        b = min(batch, n_resamples - start)
        resampled = [a[rng.integers(0, len(a), size=(b, len(a)))] for a in arrays]
        draws[start : start + b] = _call(statistic, resampled, b)

    tail = (1 - level) / 2
    low, high = np.quantile(draws, [tail, 1 - tail])
    return BootstrapResult(
        estimate=float(estimate),
        ci=(float(low), float(high)),
        se=float(draws.std(ddof=1)),
        n_resamples=n_resamples,
        level=level,
    )


def _call(statistic: Callable[..., ArrayLike], arrays: list[np.ndarray], b: int) -> np.ndarray:
    values = np.asarray(statistic(*arrays), dtype=float).reshape(-1)
    if values.shape != (b,):
        raise ValueError("statistic must return one value per resample")
    return values
