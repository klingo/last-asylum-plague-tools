import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def root():
    """One Tk root for the whole run: starting and destroying several in one process makes the next one fail to find its
    Tcl library on Windows (the windows' tests skip themselves when Tk cannot start at all)."""
    try:
        tk_root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"cannot start Tk: {e}")
    tk_root.withdraw()
    yield tk_root
    tk_root.destroy()


@pytest.fixture(autouse=True)
def history_file(tmp_path_factory, monkeypatch):
    """No test writes the real history.json (the extract run records it)."""
    import history

    monkeypatch.setattr(history, "PATH", tmp_path_factory.mktemp("history") / "history.json")
