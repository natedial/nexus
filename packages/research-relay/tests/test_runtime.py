from __future__ import annotations

import time

import pytest

from research_relay.runtime import clear_max_runtime, install_max_runtime


def test_max_runtime_raises_system_exit() -> None:
    install_max_runtime(1)
    try:
        with pytest.raises(SystemExit) as caught:
            time.sleep(3)
        assert caught.value.code == 1
    finally:
        clear_max_runtime()


def test_max_runtime_zero_is_a_no_op() -> None:
    install_max_runtime(0)
    try:
        time.sleep(0.05)
    finally:
        clear_max_runtime()
