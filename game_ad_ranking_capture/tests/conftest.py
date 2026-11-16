import pytest

import config as C


@pytest.fixture(autouse=True)
def no_real_data_files(tmp_path, monkeypatch):
    """No test may read the repository's own corrections or member list: they point at files that do not exist."""
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "no_corrections.json")
    monkeypatch.setattr(C, "ROSTER_DIR", tmp_path / "no_members")
