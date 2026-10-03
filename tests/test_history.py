import unicodedata
from pathlib import Path

from kobold.history import last_opened, latest_file
from kobold.koreader import KOREADER_DIR

HISTORY = """return {
    {
        ["file"] = "/mnt/onboard/00_Inbox/older.epub",
        ["time"] = 1700000000,
    },
    {
        ["file"] = "/mnt/onboard/01_Fiction/Teague, Rowan/Teague, Rowan - \\"Ash\\" (2011).epub",
        ["time"] = 1700009999,
    },
}
"""


def write_history(root: Path, text: str = HISTORY) -> Path:
    path = root / KOREADER_DIR / "settings" / "history.lua"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_latest_file_is_the_entry_with_the_newest_time():
    assert latest_file(HISTORY) == '/mnt/onboard/01_Fiction/Teague, Rowan/Teague, Rowan - "Ash" (2011).epub', (
        "the newest time wins, whatever the order in the file; escapes are undone"
    )


def test_latest_file_without_times_is_the_first_entry():
    text = 'return { { ["file"] = "/mnt/sd/a.epub" }, { ["file"] = "/mnt/sd/b.epub" } }'
    assert latest_file(text) == "/mnt/sd/a.epub", "KOReader keeps the newest entry first"


def test_last_opened_maps_the_device_path_onto_the_library(tmp_path: Path):
    write_history(tmp_path)
    book = tmp_path / "01_Fiction" / "Teague, Rowan" / 'Teague, Rowan - "Ash" (2011).epub'
    book.parent.mkdir(parents=True)
    book.write_bytes(b"")

    assert last_opened(tmp_path) == '01_Fiction/Teague, Rowan/Teague, Rowan - "Ash" (2011).epub', (
        "the device prefix differs from the library root; the longest tail that exists is the book"
    )


def test_last_opened_is_none_when_the_book_is_not_in_the_library(tmp_path: Path):
    write_history(tmp_path)

    assert last_opened(tmp_path) is None, "a path that exists nowhere under the root is no seed"


def test_last_opened_without_koreader_is_none(tmp_path: Path):
    assert last_opened(tmp_path) is None, "no history, no seed"


def test_last_opened_composes_decomposed_paths(tmp_path: Path):
    nfd = unicodedata.normalize("NFD", "Čapek.epub")
    write_history(tmp_path, f'return {{ {{ ["file"] = "/mnt/sd/{nfd}", ["time"] = 1 }} }}')
    (tmp_path / nfd).write_bytes(b"")

    assert last_opened(tmp_path) == "Čapek.epub", "the seed path is composed like every rel_path in the index"
