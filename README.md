# kobo-alfred

Alfred workflow for searching an ebook library (the Kobo SD card) by metadata, with covers.

```
kb deep work                 every word must match, by prefix, ignoring case and diacritics
kb delany epub 1975          words match title, authors, series, folder, path, genre, format, language, year
kb inbox ukrainian           language matches by code or English name (uk, ukrainian)
kb                           empty query → books without a genre (↩ completes to kb inbox), then the most recently added
kb update                    rebuild the library index and, if sources are configured, the sources index (also kb:index)
kb:dups                      same title in several files or formats
kb:rnd epub                  five random books, drawn from those matching the words
kb:stats                     counts: books, incomplete downloads, duplicate titles
kb:lint                      problems: junk files, partial downloads, noisy/opaque names, duplicates, misfiled series, unclassified
kb:inbox                     books without a genre yet, oldest first
kb stats · kb plan · kb update…  every kb:x also works as `kb x [words]`: its rows come first, then books matching all words
kb:plan                      proposed moves/renames/trash, written to plan.tsv — ↩ on a row applies that line, ↩ on the head row applies all
kb:apply                     apply plan.tsv, then rebuild the index
kb:undo                      move the last batch back
kb:classify                  pick an inbox book, then a genre; the inbox shrinks as you go
kb:src cal newport           search the other sources (same filters) — ↩ copies the book into the library inbox
kb:src eur                   two or more results start with "Import all N books"; kb:classify likewise starts with
                             "Classify all N books" — ↩ on that row does it for every row below (also ⌥⇧↩ on any row)
```

Inside plain `kb`, a first word that names a command (`stats`, `dups`, `rnd`, `lint`, `inbox`, `classify`, `plan`,
`src`, `update`, `apply`, `undo`) runs it: `kb plan` lists the plan and ↩ on a row applies that row;
`kb src delany` searches the sources and ↩ imports; `kb update` shows one row that rebuilds the index on ↩. Books
matching the whole input are listed after, once each, so a command word never hides a book (`kb stats` also finds
"Stats for Dummies"). Only ↩ changes meaning per row; ⌥↩ (reveal), ⌘↩ (copy path) and ⌃↩ (browse folder) do the
same thing in every list. Typing the start of a command (`kb up`, `kb cl`) shows `kb update`, `kb classify`… rows
above the books; ↩ or ⇥ completes the word. Without an index, or with one from an older version, a single row
says so and ↩ on it rebuilds.

Each result shows: title · authors · series #n · year · FORMAT size · path relative to the library root.
Covers are used as icons (embedded epub/fb2 cover, otherwise a Quick Look thumbnail via `qlmanage`).

| Key          | Action                       |
|--------------|------------------------------|
| ↩            | open the book                |
| ⌥↩           | reveal in Finder             |
| ⌘↩           | copy library-relative path   |
| ⌃↩           | browse the book's folder     |
| ⇧ / ⌘Y       | Quick Look                   |
| ⇧↩           | set the genre                |
| ⌥⇧↩          | ↩ for every row shown (`kb:src`, `kb:inbox`, `kb:classify`, `kb:plan`) |
| fn↩          | move to its genre home now   |
| ⌘C           | copy relative path           |
| ⌘L           | large type: title/author/path|

`.part` files (unfinished downloads) are indexed but never listed by search; `kb:lint` reports them.

## Install

Download `Kobo Library.alfredworkflow` (or build it with `./build.sh`) and open it. The workflow is
self-contained: the `kobolib` package is bundled inside and runs on macOS's `/usr/bin/python3` (3.9, the
version the Command Line Tools ship), no dependencies, no virtualenv. The code stays 3.9-compatible on purpose:
`pyproject.toml` pins `requires-python = ">=3.9"` and CI runs the tests and ruff (target `py39`) on 3.9 and 3.13.

In the workflow's configuration set **Library root** (`/Volumes/Transcend/kobo`). Run `kb:index` once;
rerun after adding books, and after updating the workflow when it says "Index is from an older version" —
every command refuses to read or write an index built by an earlier version, so a rebuild is the only
upgrade step.

The index (`library.db`) and `covers/` live in Alfred's workflow data folder
(`~/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobolib`), which survives workflow
updates and cache clears. Override with the optional **Index folder** setting.

From a terminal: `KOBO_ROOT=… KOBO_DATA=… uv run kobolib index|search|dups|random|stats`.

## Organizing

The folder tree is the on-device browser, so it should encode exactly one thing: genre → author → series.
`kb:index` bootstraps a genre for every book from its first two folder levels
(`01_Fiction/01_Sci-Fi_Fantasy/…` → `fiction/sci-fi_fantasy`); books under `00_Inbox` or `99_Archives`
stay unclassified and show up in `kb:inbox`.

Genres live in a genre store (`genres.tsv` next to the index) keyed by a fingerprint of the book's
*text*, not its bytes: for an epub the set of its HTML files (whatever they are named or ordered), for an fb2
its `<body>`. A renamed, moved or repacked epub, a swapped cover or edited metadata is therefore still the
same book and keeps its genre; other formats, partial downloads and unreadable files are hashed whole.
`kb:index` computes the fingerprint while reading each book — it reads every byte, so a full reindex of a big
card takes a minute or two longer — and if a book's fingerprint has changed since the last run, its genre is
carried over by path. An older `tags.tsv` is read
once when `genres.tsv` does not exist yet; its tags are ignored.

Setting a genre (`kb:classify`, or ⇧↩ on any book) moves the book to its genre home right away —
`genre/author[/series]/` with a normalised filename — and updates that book's row in the index (no full
reindex); `kb:undo` reverses the move.
Books without a recognisable author stay put. `kb:plan` / `kb:apply`
remain for bulk work: junk, duplicates and anything classified before this behaviour existed.

`kb:lint` reports, never changes anything:

| rule | what it catches |
|---|---|
| `junk` | `FSCK0000.*`, `.textClipping`, `.zip`, empty folders |
| `partial` | `.part` downloads |
| `double_extension` | `Book.fb2.mobi` |
| `noisy_name` | leading spaces, `- libgen.li`, `-- Anna's Archive`, `&amp_`, `{Author}{id}` |
| `opaque` | `7_815203.epub`, `smp…epub`, `annas-arch-…fb2`, single-word titles without an author |
| `exact_duplicate` | identical files in several folders |
| `title_duplicate` | same title in several formats or editions |
| `misfiled_series` | a series book outside the folder that already holds its series (articles ignored) |
| `author_inversion` | an author folder that is the `First, Last` swap of a better-populated one |
| `unclassified` | no genre |

From a terminal: `kobolib lint --text` prints one finding per line (`rule<TAB>detail<TAB>paths`).
`kobolib tag <path|fingerprint> genre=fiction/sci-fi` sets the genre and moves the book.

`kb:plan` turns findings and genres into operations and writes them to `plan.tsv` next to the index
(`kobolib plan --text` prints it). Review it, delete lines you disagree with; nothing is applied yet.

| kind | meaning |
|---|---|
| `move` | relocate and/or rename a classified book to `<genre folder>/<Last, First>/[<Series>/]<Last, First> - <Title> (<Series> NN) (<Year>).<ext>` |
| `trash` | junk or a byte-identical copy → `_trash/<original path>` |
| `dups` | a less preferred edition of a title → `_dups/<original path>` (format order: epub, kepub, fb2, mobi, azw3, azw, pdf, djvu; then newer, then larger) |
| `skip` | two books want the same destination; resolved by hand |

`kb:apply` executes the plan with same-volume renames (`os.replace`), carries a KOReader `Book.sdr` sidecar
along with its book, rewrites the moved paths in KOReader's `collection.lua` / `history.lua` (keeping `.bak`
copies) and in path-mirrored `docsettings` sidecars, prunes folders left empty, journals every move to
`journal.jsonl`, and rebuilds the index. The card is case-insensitive, so a
destination that differs from the source only by letter case (or Unicode normalization) is the same file: such
a move is done as an in-place rename, folder by folder, never treated as a duplicate. When the destination
already exists as a different entry and the source is redundant (an
empty folder, or a byte-identical copy of the file already there) the source is removed instead, journaled as
a `delete`; a destination holding different content leaves the operation skipped, and the notification says so. A plan older than the index is refused. `kb:undo` reverses the last
batch (an undo is itself a batch, so undoing twice re-applies); a deleted copy comes back from the kept file. Nothing is ever deleted: `_trash/` and `_dups/`
are left for you, and both are ignored by the scanner.

`kb:classify` is the daily loop: type to find an inbox book, ↩, type a genre (existing ones are listed, an
unknown one is created), ↩. Narrow the inbox to a batch instead (`kb:classify newport`) and the list starts with
"Classify all N books": ↩ there (or ⌥⇧↩ on any row, also in `kb:inbox`) opens the same picker for every complete
book listed, and the genre you choose applies to all of them. From a terminal: `kobolib tag <path|fingerprint> genre=fiction/sci-fi_fantasy`.
Genres are searchable: every segment of the genre is a word (`kb fiction`, `kb sci`).

Any book you have just found — in `kb`, `kb:inbox`, or after `kb term` — can be fixed in place with ⇧↩: the
picker shows the current genre and lists known genres; typing any part of a genre's path filters them
(`spy` finds `fiction/spy`, case does not matter), ⇥ completes the genre, and the typed text is offered as a new
genre unless it already is one.

Author folders are `Last, First`. A plain `First Last` name is inverted, except Cyrillic names, which are
assumed `Фамилия Имя [Отчество]` as in libgen/flibusta filenames; an existing author folder (either form) wins
over the guess, so `Teague Rowan` joins `Teague, Rowan/` if that folder exists.

The genre folder is the existing one matching the genre; a series folder is only used when you own more than
one book of the series. Partial downloads and unclassified books are never moved. Names are made exFAT-safe.

## Other sources

Set **Other sources** (`KOBO_SOURCES`, paths separated by `:`) to the folders of ebooks that are not the
library yet — a Calibre library, a downloads folder, an old reader's card. `kb:index` (or `kb update`) then
also indexes them into a separate `sources.db`; an unmounted source is skipped and mentioned, never an error.
`kb:src` searches it with the same query syntax, and the source folder's name is part of the path, so
`kb:src calibre` narrows by source.

`kb:src` only ever shows what you could still import. Left out of the sources index:

- books whose fingerprint is already in the library, under any name or path;
- `.part` downloads;
- epubs and fb2s that cannot be read;
- pdf / mobi / azw / azw3 / djvu files without their signature bytes (`%PDF`, `BOOKMOBI`, `AT&TFORM`).

↩ copies the book into the library's inbox folder (the one whose name is `inbox` after the order prefix, or a
new `_inbox/`). When the list has more than one book it starts with "Import all N books" — ↩ there (or ⌥⇧↩ on
any row) copies every book listed (`kb:src calibre epub`, ↩). Each import adds the book to the library index
right away — no full reindex — so it shows up in `kb`,
`kb:inbox` and `kb:classify` immediately. The source is never touched: import only copies, and once a book is in
the library its source copy is simply no longer offered. Nothing is overwritten: an occupied destination refuses
the import, and so does an unreadable or unfinished file. From a terminal: `kobolib index` (both),
`kobolib index-sources` (sources only), `kobolib sources "query"`, `kobolib import <path>` (several paths,
one per line, import as a batch; the notification counts them and names what was skipped).

## Metadata sources

- **epub**: OPF (`dc:title`, `dc:creator`, `dc:language`, `dc:date`, `dc:publisher`, `calibre:series`), cover from `meta[name=cover]` / `properties=cover-image`.
- **fb2**: `title-info` (book-title, author, lang, sequence), `publish-info`, cover from `coverpage` binary.
- **mobi / azw / azw3 / pdf / djvu / partial / corrupt files**: parsed from the filename — libgen (`Author - Title (Year, Publisher) - libgen.li`), Anna's Archive (`Title -- Author -- …`), `[Series №N]`, `(Series N)`, `Title{Author}(Year, Publisher){id}`, `NN Title - Author`, `Title, The - Author`.

Filename parsing is a heuristic; `Author - Title` vs `Title - Author` is decided by which side looks more like a person
(`Last, First`, initials, no stopwords). Genuinely ambiguous two-word cases default to `Author - Title`.

## Development

```sh
uv run pytest
uv run ruff check && uv run ruff format --check
```

Modules, from the bottom up: `model` (the records), `paths`/`scan`/`identity`/`filenames`/`metadata` (reading the card),
`index` (SQLite FTS5), `tags` (the genre store), `lint`, `naming`, `plan`, `apply`/`koreader` (moving files), `alfred` (JSON items),
`config` (paths from the environment), `library` (operations), `commands` (the `kb` item lists) and `cli`.
