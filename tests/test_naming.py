import pytest

from kobolib.naming import author_folder, canonical_name, destination, fat_safe, genre_root, shelves
from tests.test_alfred import row


@pytest.mark.parametrize(
    "authors, folder",
    [
        ("Rowan Teague", "Teague, Rowan"),
        ("Teague, Rowan", "Teague, Rowan"),
        ("Rowan Teague; Petra Marlowe", "Teague, Rowan"),
        ("Morwenna O'Hare", "O'Hare, Morwenna"),
        ("Harriet V. Okonkwo", "Okonkwo, Harriet V."),
        ("Тіґ Ровен", "Тіґ, Ровен"),
        ("Plato", "Plato"),
        ("Petra Marlowe (ed)", "Marlowe, Petra"),
        ("Marlowe, Petra (eds.)", "Marlowe, Petra"),
        ("", ""),
    ],
)
def test_author_folder(authors, folder):
    assert author_folder(authors) == folder, f"{authors!r} should file under {folder!r}"


@pytest.mark.parametrize(
    "overrides, name",
    [
        ({}, "Newport, Cal - Deep Work (Focus 02) (2016).epub"),
        ({"series": "", "series_index": ""}, "Newport, Cal - Deep Work (2016).epub"),
        ({"year": ""}, "Newport, Cal - Deep Work (Focus 02).epub"),
        ({"authors": ""}, "Deep Work (Focus 02) (2016).epub"),
        ({"series_index": "1-3"}, "Newport, Cal - Deep Work (Focus 01-03) (2016).epub"),
        ({"series_index": "12"}, "Newport, Cal - Deep Work (Focus 12) (2016).epub"),
        ({"partial": True}, "Newport, Cal - Deep Work (Focus 02) (2016).epub.part"),
        ({"format": "fb2"}, "Newport, Cal - Deep Work (Focus 02) (2016).fb2"),
        ({"title": "Salt: A Signal?"}, "Newport, Cal - Salt_ A Signal_ (Focus 02) (2016).epub"),
    ],
)
def test_canonical_name(overrides, name):
    assert canonical_name(row(**overrides)) == name, f"{overrides} should name the file {name!r}"


@pytest.mark.parametrize(
    "raw, safe",
    [
        ('a:b?c*d|e"f<g>h/i\\j', "a_b_c_d_e_f_g_h_i_j"),
        ("  double   space  ", "double space"),
        ("trailing. ", "trailing"),
        ("x" * 300 + ".epub", "x" * 250 + ".epub"),
    ],
)
def test_fat_safe(raw, safe):
    assert fat_safe(raw) == safe, f"{raw!r} should become {safe!r}"


def test_fat_safe_truncates_on_utf8_bytes_not_chars():
    name = "ї" * 200 + ".fb2"
    safe = fat_safe(name)
    assert len(safe.encode()) <= 255 and safe.endswith(".fb2"), "long names should be cut at 255 bytes keeping the extension"


def test_genre_root_prefers_existing_folder():
    folders = {"01_Fiction", "01_Fiction/01_Sci-Fi_Fantasy", "01_Fiction/01_Sci-Fi_Fantasy/Series", "02_NonFiction"}
    layout = shelves(folders)
    assert genre_root("fiction/sci-fi_fantasy", layout) == "01_Fiction/01_Sci-Fi_Fantasy", (
        "an existing folder for the genre should be reused"
    )
    assert genre_root("fiction/mystery", layout) == "01_Fiction/mystery", "a new genre nests under the existing parent"
    assert genre_root("games/go", layout) == "games/go", "an unknown genre becomes its own path"


@pytest.mark.parametrize(
    "overrides, series_count, rel_path",
    [
        ({}, 2, "01_Fiction/01_Sci-Fi_Fantasy/Newport, Cal/Focus/Newport, Cal - Deep Work (Focus 02) (2016).epub"),
        ({}, 1, "01_Fiction/01_Sci-Fi_Fantasy/Newport, Cal/Newport, Cal - Deep Work (Focus 02) (2016).epub"),
        ({"series": "", "series_index": ""}, 0, "01_Fiction/01_Sci-Fi_Fantasy/Newport, Cal/Newport, Cal - Deep Work (2016).epub"),
        ({"authors": ""}, 0, "01_Fiction/01_Sci-Fi_Fantasy/Deep Work (Focus 02) (2016).epub"),
    ],
)
def test_destination(overrides, series_count, rel_path):
    folders = {"01_Fiction", "01_Fiction/01_Sci-Fi_Fantasy"}
    got = destination(row(**overrides), "fiction/sci-fi_fantasy", shelves(folders), series_count)
    assert got == rel_path, f"{overrides} with {series_count} in series should land at {rel_path!r}"


def test_author_folder_prefers_existing_inverse_folder():
    known = {"Teague, Rowan"}
    assert author_folder("Rowan Teague", known) == "Teague, Rowan", "a normal name keeps its own folder"
    assert author_folder("Teague Rowan", known) == "Teague, Rowan", (
        "a surname-first name should join the existing folder instead of making 'Rowan, Teague'"
    )
    assert author_folder("Teague Rowan", set()) == "Rowan, Teague", "without a hint the last word is the surname"


def test_destination_uses_known_author_folders():
    folders = {"01_Fiction", "01_Fiction/Teague, Rowan"}
    got = destination(row(authors="Teague Rowan", series="", year=""), "fiction", shelves(folders), 0)
    assert got.startswith("01_Fiction/Teague, Rowan/Teague, Rowan - "), "destination and file name should both use the resolved author"


@pytest.mark.parametrize(
    "authors, folder",
    [
        ("Дольд-Михайлик Юрий Петрович", "Дольд-Михайлик, Юрий Петрович"),
        ("Бердник Олесь Павлович", "Бердник, Олесь Павлович"),
        ("Стросс Чарлз", "Стросс, Чарлз"),
        ("Артур Конан Дойл", "Дойл, Артур Конан"),
    ],
)
def test_cyrillic_names_follow_surname_first_convention(authors, folder):
    assert author_folder(authors) == folder, f"{authors!r} should file under {folder!r}"


def test_known_authors_includes_plain_folders():
    from kobolib.naming import known_authors

    assert known_authors({"01_Fiction/Rowan Teague", "01_Fiction/Marlowe, Petra", "01_Fiction/Standalone"}) == {
        "Teague, Rowan",
        "Marlowe, Petra",
    }, "a 'First Last' folder counts as that author's home"


def test_shelves_prefers_the_shallowest_genre_folder_deterministically():
    layout = shelves(
        {"01_Fiction/01_Sci-Fi_Fantasy/Deep", "01_Fiction/01_Sci-Fi_Fantasy", "01_Fiction/01_Sci-Fi_Fantasy/Alt", "01_Fiction"}
    )
    assert genre_root("fiction/sci-fi_fantasy", layout) == "01_Fiction/01_Sci-Fi_Fantasy", "the shallowest folder of the genre is its home"
    assert genre_root("fiction", layout) == "01_Fiction", "a top-level genre maps to its top-level folder"
