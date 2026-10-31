"""Simulation proofs: the stats library on thousands of experiments where the truth is known.

Every experiment is simulated by the Day 3 simulator, loaded into an in-memory warehouse,
built into `experiment_users`, and analyzed the way the readout would. All results are
SYNTHETIC.

1. A/A: no effect, read once at EXP-001's N. About 5% false positives, uniform p-values.
2. Peeking: no effect, checked every day for 28 days. A fixed-horizon z-test that stops at
   the first p < 0.05 is wrong far more than 5% of the time; the mSPRT isn't.
3. CUPED: no effect, returning and new users, with and without the pre-period covariate.
4. SRM: a 52/48 split against a planned 50/50, and a fair 50/50, at several sizes.
5. Power: a true effect of the MDE, read at the planned N. About 80% detected.

`run_all` spreads the experiments over processes; `liftlab proofs` calls it.
"""

import math
import multiprocessing
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats

from liftlab import dryrun, readout, warehouse
from liftlab.simulate import WINDOW_START, Experiment, simulate
from liftlab.stats import power as pw
from liftlab.stats.cuped import cuped
from liftlab.stats.sequential import mixing_sd, msprt, proportion_looks
from liftlab.stats.srm import srm_check
from liftlab.stats.tests import ztest_proportions

BASELINE, MDE, ALPHA = 0.30, 0.05, 0.05
N_PER_ARM = pw.sample_size_proportions(BASELINE, MDE)  # 1,377, EXP-001's plan
# mSPRT tuned to EXP-001: effects about the size of the MDE, by the planned N (eq. 12).
MIXING_SD = mixing_sd(MDE, math.sqrt(2 * BASELINE * (1 - BASELINE)), N_PER_ARM, alpha=ALPHA)

PEEK_DAYS = 28
PEEK_USERS, PEEK_WEEKS = 3600, 5  # about EXP-001's N arrives within the 28 days
CUPED_USERS, CUPED_WEEKS, CUPED_START = 8000, 6, 28
SRM_SIZES = (2754, 10_000, 20_000)  # users simulated; EXP-001's total first
SRM_SPLITS = (0.50, 0.52)
FIRST_SEED = {"aa": 10_001, "peeking": 20_001, "cuped": 30_001, "srm": 40_001, "power": 50_001}


@dataclass(frozen=True)
class FixedHorizon:
    """A/A or power: one read at N per arm."""

    runs: int
    true_effect: float
    detected: int
    rate: float
    rate_ci: tuple[float, float]
    expected: float
    mean_diff: float
    p_values: list[float]
    diffs: list[float]


@dataclass(frozen=True)
class Peeking:
    runs: int
    looks: int
    naive_rate: float
    naive_ci: tuple[float, float]
    msprt_rate: float
    msprt_ci: tuple[float, float]
    single_look_rate: float  # the fixed-horizon test read once, on the last day
    mixing_sd: float
    naive_by_day: list[float]  # share of runs that had rejected by each day
    msprt_by_day: list[float]
    mean_users_per_arm: float


@dataclass(frozen=True)
class CupedProof:
    runs: int
    mean_users: float
    variance_reduction: float  # mean of what each readout reported
    empirical_variance_reduction: float  # 1 - var(adjusted estimates) / var(raw), across runs
    ci_width_reduction: float
    coverage_raw: float
    coverage_cuped: float
    returning_variance_reduction: float
    returning_mean_users: float
    raw_estimates: list[float]
    cuped_estimates: list[float]


@dataclass(frozen=True)
class SRMProof:
    runs: int  # per size and split
    sizes: list[int]  # mean exposed users, per size
    flagged: dict[str, list[float]]  # split -> share flagged at p < 0.001, per size
    expected_52: list[float]  # noncentral chi-square power at each size


# Workers: one simulated experiment each, top-level so processes can run them.


def _users(seed: int, n_users: int, weeks: int, experiment: Experiment) -> pd.DataFrame:
    sim = simulate(n_users, seed=seed, weeks=weeks, experiment=experiment)
    con = warehouse.connect(":memory:")
    con.execute("set enable_progress_bar = false")  # thousands of runs, each in its own warehouse
    try:
        warehouse.load_events(con, sim.events, source="synthetic", data_end=sim.truth.data_end)
        warehouse.build(con)
        return readout.experiment_users(con, experiment.key, "synthetic")
    finally:
        con.close()


def fixed_horizon_run(seed: int, effect: float) -> tuple[float, float]:
    run = dryrun.run_once(seed, N_PER_ARM, effect, alpha=ALPHA)
    return run.result.diff, run.result.p_value


def peeking_run(seed: int) -> tuple[list[float], list[float], float]:
    """p-values at each daily look: fixed-horizon z-test, and always-valid mSPRT."""
    experiment = Experiment(start_day=0, audience="new")
    users = _users(seed, PEEK_USERS, PEEK_WEEKS, experiment)
    closes = users["first_opened_at"] + pd.Timedelta(hours=24)
    test = (users["variant"] == "test").to_numpy()
    activated = users["activated"].to_numpy()
    counts = []
    for day in range(2, PEEK_DAYS + 2):  # day 1 has no closed 24-hour windows yet
        seen = (closes <= pd.Timestamp(WINDOW_START + timedelta(days=day))).to_numpy()
        counts.append(
            (
                int((activated & seen & ~test).sum()), int((seen & ~test).sum()),
                int((activated & seen & test).sum()), int((seen & test).sum()),
            )
        )  # fmt: skip
    x_c, n_c, x_t, n_t = (list(column) for column in zip(*counts, strict=True))
    naive = [
        ztest_proportions(*look).p_value if min(look[1], look[3]) > 0 else 1.0 for look in counts
    ]
    sequential = msprt(*proportion_looks(x_c, n_c, x_t, n_t), mixing_sd=MIXING_SD, alpha=ALPHA)
    return naive, list(sequential.p_values), (n_c[-1] + n_t[-1]) / 2


def cuped_run(seed: int) -> tuple[float, ...]:
    experiment = Experiment(start_day=CUPED_START, audience="all")
    users = _users(seed, CUPED_USERS, CUPED_WEEKS, experiment)
    users = users[users["window_7d_closed"]]
    results = []
    for group in (users, users[~users["new_at_exposure"]]):
        r = cuped(
            group["completed_sessions_7d"].to_numpy(float),
            (group["variant"] == "test").to_numpy(),
            group["pre_sessions_28d"].to_numpy(float),
            alpha=ALPHA,
        )
        results += [r.unadjusted_estimate, r.unadjusted_se, r.estimate, r.se, len(group)]
    return tuple(results)


def srm_run(seed: int, n_users: int, test_share: float) -> tuple[int, float]:
    experiment = Experiment(start_day=0, audience="new", test_share=test_share)
    users = _users(seed, n_users, 2, experiment)
    counts = users["variant"].value_counts()
    result = srm_check(
        {"control": int(counts.get("control", 0)), "test": int(counts.get("test", 0))},
        {"control": 0.5, "test": 0.5},
    )
    return len(users), result.p_value


# The proofs


def aa_test(runs: int, map_: Callable = map) -> FixedHorizon:
    return _fixed_horizon(runs, 0.0, FIRST_SEED["aa"], map_)


def power_check(runs: int, map_: Callable = map) -> FixedHorizon:
    return _fixed_horizon(runs, MDE, FIRST_SEED["power"], map_)


def _fixed_horizon(runs: int, effect: float, first: int, map_: Callable) -> FixedHorizon:
    seeds = range(first, first + runs)
    results = list(map_(fixed_horizon_run, seeds, [effect] * runs))
    diffs = [d for d, _ in results]
    p_values = [p for _, p in results]
    detected = sum(p < ALPHA for p in p_values)
    if effect:
        # Power at the simulator's true control rate, which is 30.7% rather than the
        # planned 30.0%.
        control = dryrun.run_once(first, 50, effect).true_control
        expected = pw.power_proportions(control, effect, N_PER_ARM, alpha=ALPHA)
    else:
        expected = ALPHA
    return FixedHorizon(
        runs=runs,
        true_effect=effect,
        detected=detected,
        rate=detected / runs,
        rate_ci=wilson(detected, runs),
        expected=expected,
        mean_diff=float(np.mean(diffs)),
        p_values=p_values,
        diffs=diffs,
    )


def peeking(runs: int, map_: Callable = map) -> Peeking:
    seeds = range(FIRST_SEED["peeking"], FIRST_SEED["peeking"] + runs)
    results = list(map_(peeking_run, seeds))
    naive = np.array([r[0] for r in results]) < ALPHA
    sequential = np.array([r[1] for r in results]) <= ALPHA
    naive_any, msprt_any = int(naive.any(axis=1).sum()), int(sequential.any(axis=1).sum())
    return Peeking(
        runs=runs,
        looks=PEEK_DAYS,
        naive_rate=naive_any / runs,
        naive_ci=wilson(naive_any, runs),
        msprt_rate=msprt_any / runs,
        msprt_ci=wilson(msprt_any, runs),
        single_look_rate=float(naive[:, -1].mean()),
        mixing_sd=MIXING_SD,
        naive_by_day=np.logical_or.accumulate(naive, axis=1).mean(axis=0).tolist(),
        msprt_by_day=np.logical_or.accumulate(sequential, axis=1).mean(axis=0).tolist(),
        mean_users_per_arm=float(np.mean([r[2] for r in results])),
    )


def cuped_proof(runs: int, map_: Callable = map) -> CupedProof:
    seeds = range(FIRST_SEED["cuped"], FIRST_SEED["cuped"] + runs)
    r = np.array(list(map_(cuped_run, seeds)))
    raw, raw_se, adj, adj_se, n = r[:, 0], r[:, 1], r[:, 2], r[:, 3], r[:, 4]
    ret_raw_se, ret_adj_se, ret_n = r[:, 6], r[:, 8], r[:, 9]
    z = stats.norm.ppf(1 - ALPHA / 2)
    return CupedProof(
        runs=runs,
        mean_users=float(n.mean()),
        variance_reduction=float(np.mean(1 - (adj_se / raw_se) ** 2)),
        empirical_variance_reduction=float(1 - adj.var(ddof=1) / raw.var(ddof=1)),
        ci_width_reduction=float(1 - adj_se.mean() / raw_se.mean()),
        coverage_raw=float(np.mean(np.abs(raw) <= z * raw_se)),
        coverage_cuped=float(np.mean(np.abs(adj) <= z * adj_se)),
        returning_variance_reduction=float(np.mean(1 - (ret_adj_se / ret_raw_se) ** 2)),
        returning_mean_users=float(ret_n.mean()),
        raw_estimates=raw.tolist(),
        cuped_estimates=adj.tolist(),
    )


def srm_proof(runs: int, map_: Callable = map) -> SRMProof:
    first = FIRST_SEED["srm"]
    jobs = [
        (first + i, size, split) for size in SRM_SIZES for split in SRM_SPLITS for i in range(runs)
    ]
    results = list(map_(srm_run, *zip(*jobs, strict=True)))
    by_job: dict[tuple[int, float], list[tuple[int, float]]] = {}
    for (_, size, split), (exposed, p) in zip(jobs, results, strict=True):
        by_job.setdefault((size, split), []).append((exposed, p))
    flagged = {
        f"{split:.0%}": [
            float(np.mean([p < 0.001 for _, p in by_job[size, split]])) for size in SRM_SIZES
        ]
        for split in SRM_SPLITS
    }
    # Exposed users per experiment, averaged over every run at that size.
    sizes = [
        round(np.mean([n for split in SRM_SPLITS for n, _ in by_job[size, split]]))
        for size in SRM_SIZES
    ]
    return SRMProof(
        runs=runs, sizes=sizes, flagged=flagged, expected_52=[srm_power(n, 0.52) for n in sizes]
    )


def srm_power(total: float, share: float, threshold: float = 0.001) -> float:
    """Chance a chi-square SRM check flags `share` vs a planned 50/50, at `total` users."""
    noncentrality = total * 4 * (share - 0.5) ** 2
    critical = stats.chi2.isf(threshold, 1)
    return float(stats.ncx2.sf(critical, 1, noncentrality))


def wilson(k: int, n: int, level: float = 0.95) -> tuple[float, float]:
    z = stats.norm.ppf(0.5 + level / 2)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return float(centre - half), float(centre + half)


def run_all(
    runs: int, srm_runs: int, workers: int = 1, only: Iterable[str] | None = None
) -> dict[str, object]:
    """Run the proofs, `runs` experiments each (SRM: `srm_runs` per size and split)."""
    chosen = set(only or ("aa", "peeking", "cuped", "srm", "power"))

    def run(map_: Callable) -> dict[str, object]:
        proofs = {
            "aa": lambda: aa_test(runs, map_),
            "peeking": lambda: peeking(runs, map_),
            "cuped": lambda: cuped_proof(runs, map_),
            "srm": lambda: srm_proof(srm_runs, map_),
            "power": lambda: power_check(runs, map_),
        }
        return {name: proof() for name, proof in proofs.items() if name in chosen}

    if workers <= 1:
        return run(map)
    # spawn, not fork: the parent may hold DuckDB's threads
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(workers, mp_context=context) as pool:
        return run(lambda fn, *iterables: pool.map(fn, *iterables, chunksize=4))


def as_dict(results: dict[str, object]) -> dict[str, dict]:
    return {name: asdict(result) for name, result in results.items()}
