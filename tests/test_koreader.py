from pathlib import Path

from kobolib.koreader import KOREADER_DIR, fix_paths, rewrite_lua, settings_files

COLLECTION = '''return {
    ["favorites"] = {
        ["/mnt/sd/00_Inbox/a.epub"] = { ["order"] = 1 },
        ["/mnt/sd/00_Inbox/a.epub.sdr"] = { ["order"] = 2 },
        ["/mnt/sd/other/a.epub"] = { ["order"] = 3 },
    },
}
'''


def test_rewrite_lua_replaces_exact_paths_only():
    out = rewrite_lua(COLLECTION, {"00_Inbox/a.epub": "01_Fiction/a.epub"})

    assert '["/mnt/sd/01_Fiction/a.epub"]' in out, "the moved book's path should be rewritten"
    assert '["/mnt/sd/other/a.epub"]' in out, "a different book sharing the name must stay"
    assert '["/mnt/sd/00_Inbox/a.epub.sdr"]' in out, "a longer path starting with the moved one must stay"


def test_fix_paths_rewrites_files_with_backup(tmp_path: Path):
    settings = tmp_path / KOREADER_DIR / "settings"
    settings.mkdir(parents=True)
    (settings / "collection.lua").write_text(COLLECTION)
    (settings / "history.lua").write_text('return { { ["file"] = "/mnt/sd/00_Inbox/a.epub" } }')

    changed = fix_paths(tmp_path, {"00_Inbox/a.epub": "01_Fiction/a.epub"})

    assert sorted(p.name for p in changed) == ["collection.lua", "history.lua"], "both files should be rewritten"
    assert (settings / "collection.lua.bak").read_text() == COLLECTION, "a backup should be kept"
    assert "/mnt/sd/01_Fiction/a.epub" in (settings / "history.lua").read_text(), "history should follow the move"


def test_fix_paths_without_koreader_is_a_noop(tmp_path: Path):
    assert fix_paths(tmp_path, {"a": "b"}) == [], "no KOReader install means nothing to fix"


def test_fix_paths_moves_mirrored_docsettings_sidecar(tmp_path: Path):
    mirrored = tmp_path / KOREADER_DIR / "docsettings" / "mnt" / "sd" / "00_Inbox" / "a.sdr"
    mirrored.mkdir(parents=True)
    (mirrored / "metadata.epub.lua").write_text("return {}")

    fix_paths(tmp_path, {"00_Inbox/a.epub": "01_Fiction/Teague, Rowan/a.epub"})

    moved = tmp_path / KOREADER_DIR / "docsettings" / "mnt" / "sd" / "01_Fiction" / "Teague, Rowan" / "a.sdr"
    assert (moved / "metadata.epub.lua").exists() and not mirrored.exists(), "a docsettings sidecar mirrored by path should follow the book"


def test_settings_files_lists_only_existing(tmp_path: Path):
    (tmp_path / KOREADER_DIR / "settings").mkdir(parents=True)
    (tmp_path / KOREADER_DIR / "settings" / "history.lua").write_text("")
    assert [p.name for p in settings_files(tmp_path)] == ["history.lua"], "only present settings files are returned"
