import pytest

import config as C
import scan as Sc

MANIFEST = {
    "abList": [
        {"pathName": "UI/Atlas/Module/Zombie_ItemIcon144/Zombie_ItemIcon144Atlas.prefab", "fileName": "a.assetbundles", "md5": "1", "size": 100},
        {"pathName": "UITexture/DynamicTexture/BigBg/bg1.png", "fileName": "b.assetbundles", "md5": "2", "size": 50},
        {"pathName": "Assets/ArtResources/Role/Prop_F/icon_ani", "fileName": "c.assetbundles", "md5": "3", "size": 9},
    ]
}


def test_group_of_takes_the_folder_of_an_asset_and_the_name_of_a_folder_bundle():
    assert Sc.group_of("UI/Atlas/Module/Zombie_ItemIcon144/Zombie_ItemIcon144Atlas.prefab") == "Zombie_ItemIcon144"
    assert Sc.group_of("UITexture/DynamicTexture/BigBg/bg1.png") == "BigBg"
    assert Sc.group_of("Assets/ArtResources/Role/Prop_F/icon_ani") == "icon_ani"
    assert Sc.group_of("single.png") == "single.png"


def test_entries_of_reads_the_manifest():
    e = Sc.entries_of(MANIFEST)
    assert e["a.assetbundles"] == {"path": "UI/Atlas/Module/Zombie_ItemIcon144/Zombie_ItemIcon144Atlas.prefab",
                                   "group": "Zombie_ItemIcon144", "type": "pictures", "md5": "1", "kb": 100}
    assert set(e) == {"a.assetbundles", "b.assetbundles", "c.assetbundles"}


@pytest.mark.parametrize("path,kind", [
    ("UI/Atlas/Module/X/XAtlas.prefab", "pictures"),
    ("UITexture/DynamicTexture/BigBg/bg.png", "pictures"),
    ("Assets/EffectClassify/UI/Main/e.prefab", "effects"),
    ("Spines/ui/s", "effects"),
    ("UI/Models/SpineAssets_F/hero", "effects"),
    ("Assets/ArtResources/Role/Prop_F/icon_ani", "models"),
    ("Role/NPC/n", "models"),
    ("Scenes/WorldScene/prefabs/p.prefab", "scenes"),
    ("UI/UIModules/Mall/MallPanel.prefab", "layouts"),
    ("GameData/language_F/de", "data"),
    ("LuaScript/Eyu/Logic/Datas", "data"),
    ("LuaScript", "data"),
    ("Font_F/f", "other"),
    ("Assets/Wwise/w", "other"),
])
def test_type_of_follows_the_path_prefix(path, kind):
    assert Sc.type_of(path) == kind


def test_parse_types():
    assert Sc.parse_types("pictures") == ("pictures",)
    assert Sc.parse_types(" pictures, data ") == ("pictures", "data")
    assert Sc.parse_types("all") == tuple(C.TYPES)
    for bad in ("", "pictures,nope", ","):
        with pytest.raises(ValueError):
            Sc.parse_types(bad)


def test_select_keeps_the_chosen_types_and_applies_the_filter():
    e = Sc.entries_of(MANIFEST)
    assert set(Sc.select(e)) == {"a.assetbundles", "b.assetbundles"}  # pictures by default
    assert set(Sc.select(e, types=tuple(C.TYPES))) == set(e)
    assert set(Sc.select(e, types=("models",))) == {"c.assetbundles"}
    assert set(Sc.select(e, pattern="itemicon")) == {"a.assetbundles"}  # case-insensitive
    assert set(Sc.select(e, types=("pictures", "models"), pattern="prop_f")) == {"c.assetbundles"}


def test_diff_classifies_new_changed_removed_unchanged():
    wanted = Sc.select(Sc.entries_of(MANIFEST))
    pulled = {"a.assetbundles": {"md5": "OLD", "path": "x"}, "gone.assetbundles": {"md5": "9", "path": "y"}}
    result = Sc.diff(wanted, pulled)
    assert set(result["new"]) == {"b.assetbundles"}
    assert set(result["changed"]) == {"a.assetbundles"}
    assert result["removed"] == ["gone.assetbundles"]
    assert result["unchanged"] == {}
    same = Sc.diff(wanted, {n: {"md5": e["md5"], "path": e["path"]} for n, e in wanted.items()})
    assert set(same["unchanged"]) == {"a.assetbundles", "b.assetbundles"} and not same["new"] and not same["changed"]


def test_a_pulled_bundle_of_an_unscanned_type_is_not_removed_only_one_the_game_dropped():
    entries = Sc.entries_of(MANIFEST)
    pulled = {"c.assetbundles": {"md5": "3", "path": "x"}, "gone.assetbundles": {"md5": "9", "path": "y"}}
    result = Sc.diff(Sc.select(entries), pulled, known=entries)  # scanning pictures only; c is a model
    assert result["removed"] == ["gone.assetbundles"]


def test_by_type_counts_per_type_and_folder_with_news_first():
    entries = Sc.entries_of(MANIFEST)
    entries["d.assetbundles"] = {"path": "UITexture/DynamicTexture/BigBg/bg2.png", "group": "BigBg", "type": "pictures", "md5": "4", "kb": 10}
    entries["e.assetbundles"] = {"path": "UI/Atlas/Module/Old/OldAtlas.prefab", "group": "Old", "type": "pictures", "md5": "5", "kb": 7}
    pulled = {"b.assetbundles": {"md5": "2", "path": "x"}, "e.assetbundles": {"md5": "5", "path": "y"}}
    result = Sc.diff(Sc.select(entries, types=("pictures", "models")), pulled, known=entries)
    rows = Sc.by_type(result)
    assert [r["type"] for r in rows] == ["pictures", "models"]
    pictures = rows[0]
    assert (pictures["new"], pictures["changed"], pictures["unchanged"], pictures["kb"]) == (2, 0, 2, 110)
    assert [g["group"] for g in pictures["groups"]] == ["BigBg", "Zombie_ItemIcon144", "Old"]  # news first (a tie: by name)
    assert pictures["groups"][0] == {"group": "BigBg", "new": 1, "changed": 0, "unchanged": 1, "kb": 10}
    assert pictures["groups"][2]["unchanged"] == 1 and pictures["groups"][2]["kb"] == 0  # nothing to download
    assert rows[1]["label"] == C.TYPES["models"][0] and rows[1]["new"] == 1


def test_summary_lines_tell_counts_and_megabytes():
    result = Sc.diff(Sc.select(Sc.entries_of(MANIFEST)), {})
    result["version"] = "1.0.805"
    lines = Sc.summary_lines(result)
    assert lines[0].startswith("resource version 1.0.805: 2 new, 0 changed, 0 unchanged, 0 removed")
    assert lines[1] == f"{C.TYPES['pictures'][0]}: 2 new, 0 changed, 0 unchanged"
    assert "    BigBg: 1 new, 0 changed" in lines


def test_commands_that_touch_the_webapp_stop_when_its_folder_is_missing(monkeypatch, tmp_path, capsys):
    import config as C
    import main

    monkeypatch.setattr(C, "WEBAPP_ASSETS", tmp_path / "missing")
    assert main.main(["sync"]) == 1
    assert "LAST_ASYLUM_WEBAPP" in capsys.readouterr().err
