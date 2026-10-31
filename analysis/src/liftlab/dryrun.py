"""EXP-001's pre-registered test, run on simulated experiments where the true effect is known.

Each run simulates new users arriving into a 50/50 test, loads their events into an in-memory
warehouse, builds the SQL models, and reads activation the way the real analysis will: from
`dim_users`, for exposed users, stopping once both arms have the planned number. Then the
stats library's two-proportion z-test. Repeated, the share of runs that detect the effect is
the empirical power; with no effect, it's the false-positive rate.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from statistics import NormalDist

from liftlab import warehouse
from liftlab.simulate import QUICK_START_KEY, Experiment, simulate
from liftlab.stats.tests import Comparison, ztest_proportions

_Z = NormalDist()
# Users arrive over two simulated weeks and the last day's don't get a full 24 hours, so each
# run simulates this many users per user the test needs.
WEEKS = 2
USERS_PER_NEEDED = 1.3


@dataclass(frozen=True)
class Run:
    seed: int
    true_control: float
    true_effect: float
    result: Comparison
    detected: bool


def run_once(seed: int, n_per_arm: int, effect: float, *, alpha: float = 0.05) -> Run:
    sim = simulate(
        math.ceil(2 * n_per_arm * USERS_PER_NEEDED),
        seed=seed,
        weeks=WEEKS,
        experiment=Experiment(start_day=0, audience="new", activation_effect=effect),
    )
    con = warehouse.connect(":memory:")
    try:
        warehouse.load_events(con, sim.events, source="synthetic", data_end=sim.truth.data_end)
        warehouse.build(con)
        exposed = con.execute(
            """
            select variant, activated_at is not null, activation_window_closed
            from dim_users
            where source = 'synthetic' and experiment_key = ?
            order by exposed_at, user_id
            """,
            [QUICK_START_KEY],
        ).fetchall()
    finally:
        con.close()

    counts = {"control": [0, 0], "test": [0, 0]}  # users, activated
    for variant, activated, window_closed in exposed:
        if not window_closed:
            raise RuntimeError(f"seed {seed}: the simulation ended before both arms were full")
        counts[variant][0] += 1
        counts[variant][1] += activated
        if min(counts["control"][0], counts["test"][0]) >= n_per_arm:
            break
    else:
        raise RuntimeError(f"seed {seed}: too few users to fill both arms")

    (n_c, x_c), (n_t, x_t) = counts["control"], counts["test"]
    result = ztest_proportions(x_c, n_c, x_t, n_t, alpha=alpha)
    truth = sim.truth.experiment
    return Run(
        seed, truth.activation_control, truth.activation_effect, result, result.p_value < alpha
    )


@dataclass(frozen=True)
class PowerCheck:
    runs: list[Run]

    @property
    def reps(self) -> int:
        return len(self.runs)

    @property
    def detected(self) -> int:
        return sum(run.detected for run in self.runs)

    @property
    def power(self) -> float:
        return self.detected / self.reps

    def power_ci(self, level: float = 0.95) -> tuple[float, float]:
        """Wilson interval for the detection rate: 200 runs only pin it down to a few points."""
        z = _Z.inv_cdf(0.5 + level / 2)
        n, p = self.reps, self.power
        centre = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return centre - half, centre + half

    @property
    def wrong_direction(self) -> int:
        """Detections with the opposite sign to the true effect."""
        return sum(run.detected and run.result.diff * run.true_effect < 0 for run in self.runs)


def empirical_power(
    reps: int,
    n_per_arm: int,
    effect: float,
    *,
    alpha: float = 0.05,
    first_seed: int = 1,
    progress: Callable[[int], None] | None = None,
) -> PowerCheck:
    runs = []
    for seed in range(first_seed, first_seed + reps):
        runs.append(run_once(seed, n_per_arm, effect, alpha=alpha))
        if progress:
            progress(len(runs))
    return PowerCheck(runs)
