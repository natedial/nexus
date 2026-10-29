from research_gleaner.lock import RunLock


def test_run_lock_creates_parent_and_releases(tmp_path):
    path = tmp_path / "state" / "sweep.lock"
    lock = RunLock(path)

    with lock:
        assert path.is_file()
        assert lock._handle is not None

    assert lock._handle is None
