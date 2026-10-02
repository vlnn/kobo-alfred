# kobo-alfred

Alfred workflow for searching an ebook library (the Kobo SD card) by metadata, with covers.

```
kb deep work                 full-text over title / authors / series / folder / filename
kb author:delany fmt:epub    filters: fmt: in: author: series: lang: year: genre: tag: is:partial is:complete
kb in:inbox                  folder match is substring, case-insensitive
kb                           empty query → most recently added books
kb:index                     rebuild the library index and, if sources are configured, the sources index (also `kb update`)
kb:dups                      same title in several files or formats
kb:rnd fmt:epub              five random complete books, filters allowed
kb:stats                     counts: books, incomplete downloads, duplicate titles
kb:lint                      problems: junk files, partial downloads, noisy/opaque names, duplicates, misfiled series, unclassified
kb:inbox                     books without a genre yet, oldest first
kb stats · kb plan · kb index…   every kb:x also works as `kb x [query]`: its rows come first, then books matching the word
kb:plan                      proposed moves/renames/trash, written to plan.tsv — ↩ on a row applies that line, ↩ on the head row applies all
kb:apply                     apply plan.tsv, then rebuild the index
kb:undo                      move the last batch back
kb:classify                  pick an inbox book, then a genre; the inbox shrinks as you go
kb:src cal newport           search the other sources (same filters) — ↩ copies the book into the library inbox
```

Inside plain `kb`, a first word that names a command (`stats`, `dups`, `rnd`, `lint`, `inbox`, `classify`, `plan`,
`src`, `index`/`update`, `apply`, `undo`) runs it: `kb plan` lists the plan and ↩ on a row applies that row;
`kb src delany` searches the sources and ↩ imports; `kb index` shows one row that rebuilds the index on ↩. Books whose
title, author or path contain the word are listed after. Only ↩ is rerouted: ⌥↩ / ⌘↩ keep their `kb` meaning
(reveal / copy path), so "move into the inbox" stays a `kb:src` feature. Typing the start of a command (`kb ind`,
`kb cl`) shows `kb index`, `kb classify`… rows above the books; ↩ or ⇥ completes the word.

Each result shows: title · authors · series #n · year · FORMAT size · path relative to the library root.
Covers are used as icons (embedded epub/fb2 cover, otherwise a Quick Look thumbnail via `qlmanage`).

| Key          | Action                       |
|--------------|------------------------------|
| ↩            | open the book                |
| ⌥↩           | reveal in Finder             |
| ⌘↩           | copy library-relative path   |
| ⌃↩           | browse the book's folder     |
| ⇧ / ⌘Y       | Quick Look                   |
| ⇧↩           | fix genre / tags             |
| fn↩          | move to its genre home now   |
| ⌘C           | copy relative path           |
| ⌘L           | large type: title/author/path|

`.part` files (unfinished downloads) are indexed, flagged with ⚠︎ and not actionable.

## Install

Download `Kobo Library.alfredworkflow` (or build it with `./build.sh`) and open it. The workflow is
self-contained: the `kobolib` package is bundled inside and runs on macOS's `/usr/bin/python3` (3.9, the
version the Command Line Tools ship), no dependencies, no virtualenv. The code stays 3.9-compatible on purpose:
`pyproject.toml` pins `requires-python = ">=3.9"` and CI runs the tests and ruff (target `py39`) on 3.9 and 3.13.

In the workflow's configuration set **Library root** (`/Volumes/Transcend/kobo`). Run `kb:index` once;
rerun after adding books.

The index (`library.db`) and `covers/` live in Alfred's workflow data folder
(`~/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobolib`), which survives workflow
updates and cache clears. Override with the optional **Index folder** setting.

From a terminal: `KOBO_ROOT=… KOBO_DATA=… uv run kobolib index|search|dups|random|stats`.

## Organizing

The folder tree is the on-device browser, so it should encode exactly one thing: genre → author → series.
`kobolib` keeps a tag store (`tags.tsv` next to the index) keyed by a content fingerprint, so tags survive
renames and moves. The fingerprint is a hash of the book's text — an epub's HTML files regardless of their
names or order, an fb2's `<body>` — so a repacked epub, a swapped cover or edited metadata is still the same
book; other formats, partial downloads and unreadable files are hashed whole. `kb:index` computes it while
reading each book (it reads every byte, so a full reindex of a large card takes a minute or two longer), and
carries tags over by path when a book's fingerprint changes. `kb:index` bootstraps a genre for every book from its first two folder levels
(`01_Fiction/01_Sci-Fi_Fantasy/…` → `fiction/sci-fi_fantasy`); books under `00_Inbox` or `99_Archives`
stay unclassified and show up in `kb:inbox`.

Setting a genre (`kb:classify`, or ⇧↩ "Fix" on any book) moves the book to its genre home right away —
`genre/author[/series]/` with a normalised filename — and updates that book's row in the index (no full
reindex); `kb:undo` reverses the move.
Books without a recognisable author stay put, as do tag-only edits (`+tag`, `-tag`). `kb:plan` / `kb:apply`
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
`kobolib tag <path|fingerprint> genre=fiction/sci-fi +tag -tag` sets the genre (and moves the book), adds or removes tags.

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
unknown one is created), ↩. From a terminal: `kobolib tag <path|fingerprint> genre=fiction/sci-fi_fantasy +now -bought`.
Genres and tags are searchable (`kb genre:fiction tag:now`); `genre:` matches by prefix.

Any book you have just found — in `kb`, `kb:inbox`, or after `kb term` — can be fixed in place with ⇧↩: the
picker shows the current genre and tags and lists known genres; typing any part of a genre's path filters them
(`spy` finds `fiction/spy`, case does not matter), ⇥ completes the genre, and the typed text is offered as a new
genre unless it already is one. `+tag` offers the tags used on other books, then the typed tag itself; `-tag`
narrows the book's own tags. Current tags are listed for removal when the query is empty.

Author folders are `Last, First`. A plain `First Last` name is inverted, except Cyrillic names, which are
assumed `Фамилия Имя [Отчество]` as in libgen/flibusta filenames; an existing author folder (either form) wins
over the guess, so `Teague Rowan` joins `Teague, Rowan/` if that folder exists.

The genre folder is the existing one matching the genre; a series folder is only used when you own more than
one book of the series. Partial downloads and unclassified books are never moved. Names are made exFAT-safe.

## Other sources

Set **Other sources** (`KOBO_SOURCES`, paths separated by `:`) to the folders of ebooks that are not the
library yet — a Calibre library, a downloads folder, an old reader's card. `kb:index` (or `kb update`) then also indexes them into a
separate `sources.db`; an unmounted source is skipped and mentioned, never an error. `kb:src` searches it with the same query syntax, and
the source folder's name is part of the path, so `kb:src in:calibre` narrows by source. Books whose
fingerprint is already in the library are not listed — `kb:src` only ever shows what you could still import —
and neither are `.part` downloads, epubs and fb2s that cannot be read, or pdf/mobi/azw/djvu files without
their signature bytes.

↩ copies the book into the library's inbox folder (the one whose name is `inbox` after the order prefix, or a
new `_inbox/`) and adds it to the library index right away — no full reindex — so it shows up in `kb`,
`kb:inbox` and `kb:classify` immediately. ⌥↩ moves instead of copying. Nothing is overwritten: an occupied
destination refuses the import, and so does an unreadable or unfinished file. From a terminal: `kobolib index` (both), `kobolib index-sources` (sources only), `kobolib sources "query"`,
`kobolib import [--move] <path>`.

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
`index` (SQLite FTS5), `tags`, `lint`, `naming`, `plan`, `apply`/`koreader` (moving files), `alfred` (JSON items),
`config` (paths from the environment), `library` (operations), `commands` (the `kb` item lists) and `cli`.
