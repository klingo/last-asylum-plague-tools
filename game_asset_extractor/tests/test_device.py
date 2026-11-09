import device as D


def test_parse_stat_maps_file_names_to_device_paths_last_folder_wins():
    text = (
        "393130 /sdcard/Android/data/com.phs.global/files/ABAsset/31/ui_atlas_x.assetbundles\n"
        "12 /sdcard/Android/data/com.phs.global/files/ABAsset/40/uitexture_y.assetbundles\n"
        "7 /sdcard/Android/data/com.phs.global/files/ABAsset/50/ui_atlas_x.assetbundles\n"
        "5 /sdcard/Android/data/com.phs.global/files/ABAsset/50/readme.txt\n"
        "\n"
    )
    found = D.parse_stat(text)
    assert found == {
        "ui_atlas_x.assetbundles": "/sdcard/Android/data/com.phs.global/files/ABAsset/50/ui_atlas_x.assetbundles",
        "uitexture_y.assetbundles": "/sdcard/Android/data/com.phs.global/files/ABAsset/40/uitexture_y.assetbundles",
    }


def test_parse_manifest_text_survives_the_utf8_bom_the_game_writes():
    raw = b"\xef\xbb\xbf" + b'{"abList": [{"fileName": "a"}]}'
    assert D.parse_manifest_text(raw) == {"abList": [{"fileName": "a"}]}


def test_find_adb_prefers_the_explicit_path(tmp_path):
    exe = tmp_path / "adb.exe"
    exe.write_text("")
    assert D.find_adb(str(exe)) == str(exe)
