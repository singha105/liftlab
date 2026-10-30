from importlib.metadata import version

import liftlab


def test_version_matches_package_metadata():
    assert liftlab.__version__ == version("liftlab")
