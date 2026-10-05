"""Suite-wide hermeticity pins for test/unit/."""

import os
import time
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _non_utc_localzone() -> Iterator[None]:
    """Pin localtime away from UTC for every unit test.

    A test that asserts a UTC rendering only proves the code is UTC-safe
    when the ambient zone differs — under TZ=UTC (every hosted CI runner)
    a local-time fallback produces the same bytes and the check is
    vacuous. ``_stamp``'s ``dt.UTC → None`` mutants survived exactly that
    way; pinning America/Sao_Paulo (UTC-3, no DST since 2019) makes the
    difference observable everywhere.
    """
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()
