import pytest

from kobolib.filenames import guess_from_stem


@pytest.mark.parametrize(
    "stem, title, authors",
    [
        (" Daniel C. Dennett - I've Been Thinking (2023, W. W. Norton & Company) - libgen.li",
         "I've Been Thinking", ["Daniel C. Dennett"]),
        ("Скиннер Беррес Фредерик - Оперантное поведение",
         "Оперантное поведение", ["Скиннер Беррес Фредерик"]),
        ("Newport, Cal - Deep Work (2016, Grand Central Publishing) - libgen.li",
         "Deep Work", ["Newport, Cal"]),
        ("01 Master and Commander - Patrick O'Brian",
         "Master and Commander", ["Patrick O'Brian"]),
        ("Service Model -- Adrian Tchaikovsky -- PS, 2024 -- Tor Publishing Group -- 9781250290281 -- fd5bcf0ac597eb8b449858f040ecc393 -- Anna’s Archive",
         "Service Model", ["Adrian Tchaikovsky"]),
        ("Hild{Nicola Griffith}(Farrar, Straus and Giroux){114720519} libgen.li",
         "Hild", ["Nicola Griffith"]),
        ("Wolfe Gene - Soldier of Arete (Latro 02) - 2012",
         "Soldier of Arete", ["Wolfe Gene"]),
        ("Darwin's Dangerous Idea_ Evolution and the Meaning of Life",
         "Darwin's Dangerous Idea: Evolution and the Meaning of Life", []),
        ("Make It Stick - Peter C. Brown", "Make It Stick", ["Peter C. Brown"]),
        ("04 Mauritius Command, The - Patrick O'Brian", "The Mauritius Command", ["Patrick O'Brian"]),
        ("02 Post Captain - Patrick O'Brian", "Post Captain", ["Patrick O'Brian"]),
        ("Various - Hugo Awards_ The Short Stories, Vol. 1 - 2020", "Hugo Awards: The Short Stories, Vol. 1", ["Various"]),
        ("01 Damon Knight (ed) - Orbit 1 - 1966", "Orbit 1", ["Damon Knight (ed)"]),
        ("01 Wolfe Gene - A Borrowed Man (A Borrowed Man) - 2015", "A Borrowed Man (A Borrowed Man)", ["Wolfe Gene"]),
        ("Swerve, The - Stephen Greenblatt", "The Swerve", ["Stephen Greenblatt"]),
        ("ajfelgajm", "ajfelgajm", []),
        ("Darwin, Charles_Dennett, Daniel Clement - Darwin's dangerous idea (2013_1996, Penguin) - libgen.li",
         "Darwin's dangerous idea", ["Darwin, Charles", "Dennett, Daniel Clement"]),
        ("[Gordian Protocol 1] The Gordian Protocol{Weber, David &amp_ Holo, Jacob}(2019, baen){113297064} libgen.li",
         "The Gordian Protocol", ["Weber, David", "Holo, Jacob"]),
        (" Ada Palmer, - Too Like the Lightning (2016, ePubLibre) - libgen.li",
         "Too Like the Lightning", ["Ada Palmer"]),
        (" Конан Дойль А., Пер. А. Шебец. - Кровавий Шлях. (1908) - libgen.li",
         "Кровавий Шлях.", ["Конан Дойль А., Пер. А. Шебец."]),
    ],
)
def test_title_and_authors(stem, title, authors):
    guess = guess_from_stem(stem)
    assert guess.title == title, f"{stem!r} should yield title {title!r}"
    assert guess.authors == authors, f"{stem!r} should yield authors {authors!r}"


@pytest.mark.parametrize(
    "stem, series, index",
    [
        ("[Imperial Radch №1] Leckie, Ann - Ancillary Justice (2013, Orbit _ Yen) - libgen.li", "Imperial Radch", "1"),
        ("[Honor Harrington 9 ] Weber, David - Ashes of Victory (2000, Baen) - libgen.li", "Honor Harrington", "9"),
        ("(Teixcalaan 2) Arkady Martine - A Desolation Called Peace", "Teixcalaan", "2"),
        ("(The Way 1-3) Greg Bear - The Eon Series", "The Way", "1-3"),
        ("Wolfe Gene - Shadow and Claw (Book of The New Sun 01-02) - 2011", "Book of The New Sun", "01-02"),
        ("[The Fifth Queen 1 - The Fifth Queen 1] The Fifth Queen{Ford, Ford Madox}(2023, Standard Ebooks){113907596} libgen.li", "The Fifth Queen", "1"),
        ("Make It Stick - Peter C. Brown", "", ""),
    ],
)
def test_series(stem, series, index):
    guess = guess_from_stem(stem)
    assert guess.series == series, f"{stem!r} should yield series {series!r}"
    assert guess.series_index == index, f"{stem!r} should yield index {index!r}"


@pytest.mark.parametrize(
    "stem, year",
    [
        ("Newport, Cal - Deep Work (2016, Grand Central Publishing) - libgen.li", "2016"),
        ("Darwin, Charles - Darwin's dangerous idea (2013_1996, Penguin Books Ltd) - libgen.li", "2013"),
        ("Wolfe Gene - Soldier of Arete (Latro 02) - 2012", "2012"),
        ("Make It Stick - Peter C. Brown", ""),
    ],
)
def test_year(stem, year):
    assert guess_from_stem(stem).year == year, f"{stem!r} should yield year {year!r}"


@pytest.mark.parametrize(
    "raw, authors",
    [
        ("Teague, Rowan &amp_ Marlowe, Petra", ["Teague, Rowan", "Marlowe, Petra"]),
        ("Rowan Teague, Petra Marlowe", ["Rowan Teague", "Petra Marlowe"]),
        ("Teague, Rowan", ["Teague, Rowan"]),
        ("Okonkwo, Harriet V.", ["Okonkwo, Harriet V."]),
        ("Rowan Teague_ Petra Marlowe", ["Rowan Teague", "Petra Marlowe"]),
        ("Teague, Rowan; Marlowe, Petra", ["Teague, Rowan", "Marlowe, Petra"]),
    ],
)
def test_split_authors_distinguishes_comma_lists_from_surname_first(raw, authors):
    from kobolib.filenames import split_authors

    assert split_authors(raw) == authors, f"{raw!r} should split into {authors}"


@pytest.mark.parametrize(
    "stem, title, authors, series, index, year",
    [
        ("Copper Hymn -- Teodor Vaskiv -- Tidewater 2, 2024 -- Lantern Press -- 9780000000001 -- 0123456789abcdef0123456789abcdef -- Anna’s Archive",
         "Copper Hymn", ["Teodor Vaskiv"], "Tidewater", "2", "2024"),
        ("Ashfall (Grey Tide, #2) -- Rowan Teague -- Lantern, London, 2023 -- Quill -- 9780000000002 -- 0123456789abcdef0123456789abcdef -- Anna’s Archive",
         "Ashfall", ["Rowan Teague"], "Grey Tide", "2", "2023"),
        ("Saltmarsh -- Penhale, Ivor -- 2010 -- Lantern -- 0123456789abcdef0123456789abcdef -- Anna’s Archive",
         "Saltmarsh", ["Penhale, Ivor"], "", "", "2010"),
        ("Ember -- Vaskiv, Teodor [Vaskiv, Teodor] -- Special edition, 2017;2002 -- Lantern -- 9780000000003 -- 0123456789abcdef0123456789abcdef -- Anna’s Archive",
         "Ember", ["Vaskiv, Teodor"], "", "", "2017"),
    ],
)
def test_annas_archive_names(stem, title, authors, series, index, year):
    guess = guess_from_stem(stem)
    assert (guess.title, guess.authors, guess.series, guess.series_index, guess.year) == (title, authors, series, index, year), f"{stem!r} should parse fully"
