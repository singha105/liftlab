import json
import time
from datetime import datetime

import pandas as pd
import pytest

from liftlab import warehouse
from liftlab.simulate import simulate


@pytest.fixture(scope="session")
def synthetic():
    """The default run: 20,000 synthetic users, seed 7, loaded and built in memory."""
    started = time.perf_counter()
    sim = simulate(20_000, seed=7)
    elapsed = time.perf_counter() - started
    con = warehouse.connect(":memory:")
    warehouse.load_events(con, sim.events, source="synthetic", data_end=sim.truth.data_end)
    warehouse.build(con)
    return sim, con, elapsed


def event(user: str, name: str, at: str, uuid: str | None = None, **properties) -> dict:
    return {
        "uuid": uuid,
        "event": name,
        "distinct_id": user,
        "timestamp": datetime.fromisoformat(at),
        "properties": json.dumps({"is_demo": False, **properties}),
    }


def build_warehouse(events: list[dict], data_end: str):
    """A warehouse built from hand-written events, for edge cases."""
    con = warehouse.connect(":memory:")
    frame = pd.DataFrame(events)
    warehouse.load_events(con, frame, source="synthetic", data_end=datetime.fromisoformat(data_end))
    warehouse.build(con)
    return con
