import config as C
import main
import text_browser as TB
import text_mapping as TM

TABLE = [
    {"location": "pack_data:items.a.name", "status": "suggested", "source": "tables/Item:a.name", "en": "A"},
    {"location": "pack_data:items.b.name", "status": "official", "source": "tables/Item:b.name", "en": "B"},
]


def test_text_status_summarizes_and_lists_what_needs_attention(monkeypatch, capsys):
    monkeypatch.setattr(main, "text_table", lambda: TABLE)
    assert main.main(["text-status"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Official 1 of 2 webapp texts") and "suggested (1): pack_data:items.a.name" in out and "official (" not in out


def test_text_map_accept_maps_the_suggested_texts_then_reports(monkeypatch, capsys):
    monkeypatch.setattr(main, "text_table", lambda: TABLE)
    monkeypatch.setattr(TM, "accept_suggestions", lambda table: sum(r["status"] == "suggested" for r in table))
    assert main.main(["text-map", "--accept"]) == 0
    assert capsys.readouterr().out.startswith("mapped 1 webapp texts")
    assert main.main(["text-map"]) == 0 and not capsys.readouterr().out.startswith("mapped")  # without --accept: only the status


def test_text_sync_lists_the_changes_and_says_whether_it_wrote_them(monkeypatch, capsys):
    done = [{"location": "pack_data:items.a.name", "lang": "de", "action": "write", "old": "", "new": "Axt", "note": "x"},
            {"location": "pack_data:items.b.name", "lang": "", "action": "skipped", "old": "", "new": "", "note": "gone"}]
    applied = []
    monkeypatch.setattr(TM, "sync", lambda apply: applied.append(apply) or done)
    assert main.main(["text-sync"]) == 0
    out = capsys.readouterr().out
    assert "write   pack_data:items.a.name [de]: '' -> 'Axt'" in out and "skipped pack_data:items.b.name: gone" in out
    assert "1 texts would be written, 1 skipped  (preview: add --apply to write them)" in out
    assert main.main(["text-sync", "--apply"]) == 0 and applied == [False, True]
    assert "1 texts written" in capsys.readouterr().out


def test_texts_writes_the_browser_and_the_webapp_commands_stop_without_the_webapp(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(TB, "write", lambda: tmp_path / "index.html")
    assert main.main(["texts"]) == 0 and "index.html" in capsys.readouterr().out
    monkeypatch.setattr(C, "WEBAPP_ASSETS", tmp_path / "missing")
    assert main.main(["text-sync"]) == 1 and "LAST_ASYLUM_WEBAPP" in capsys.readouterr().err
