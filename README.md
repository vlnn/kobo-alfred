# kobo-alfred

Alfred workflow for an ebook library on a Kobo SD card: search it by metadata, with covers, give books a genre,
keep the folders tidy and import from other sources.

Everything starts with one keyword, `kb`, and everything you type after it is a word.

```
kb                      books without a genre (a reminder), then the most recently added
kb <words>              search
kb <command> <words>    the command's rows for <words>, then books matching "<command> <words>"
```

## Searching

Words match by prefix, ignore case and diacritics, and every word must match. They are matched against:

| Field | Example word |
|---|---|
| title, authors, series, series number | `delany`, `dhalgren` |
| folder and path | `inbox`, `calibre` |
| genre (every path segment) | `fiction`, `sci` |
| format | `epub`, `fb2` |
| language (code and English name) | `uk`, `ukrainian` |
| year | `1975` |

So `kb delany epub 1975` finds Delany's epubs from 1975, and `kb fiction uk` Ukrainian fiction.

Each result shows: title · authors · series #n · year · FORMAT size · path relative to the library root. Covers
are used as icons (the embedded epub/fb2 cover, otherwise a Quick Look thumbnail via `qlmanage`). Unfinished
downloads (`.part`) are indexed but listed only by `kb trash`.

## Commands

A first word that names a command adds the command's rows on top. Below them come the books matching the whole
input, as if it were a plain search, each listed once: a command word never hides a book, so `kb stats` also finds
"Stats for Dummies". Typing two or more letters of a command (`kb cl`) shows `kb classify` above the books; ⇥ or ↩
completes the word.

| Command | Rows on top | ↩ on a row | Head row |
|---|---|---|---|
| *(none)* | the inbox reminder when the query is empty, then recent books | open | — |
| `rnd`, `random` | 5 random books, drawn from the books matching the remaining words | open | — |
| `inbox` | library books without a genre, oldest first, narrowed by the words | open | — |
| `classify` | with no words, the inbox; with words, every library book matching them, any genre | pick a genre for that book | **Set genre for all N** |
| `dups` | every copy of a title that exists in several files, side by side; the subtitle starts with `×N` | open | — |
| `stats` | books · inbox · duplicate titles · pending fixes · unfinished downloads · sources | complete the query to `kb inbox`, `kb dups`, `kb fix`, `kb trash` or `kb src` | — |
| `src` | importable books from other sources matching the words | import into the inbox | **Import all N** |
| `fix` | see [Fix](#fix) | apply that operation | **Fix all N** |
| `trash` | see [Trash](#trash) | move the book to `_trash/` | **Trash all N** |
| `update` | one row: rebuild the index (library, sources, PDF thumbnails) | rebuild in the background, notify | — |

Head rows appear when the list has two or more books (Fix all whenever there is something to fix) and do the
command for every row shown.

## Keys

| Key | Book row | Source row | Fix row | Genre picker row |
|---|---|---|---|---|
| ↩ | open (`classify`: pick a genre; `trash`: move to `_trash/`) | import | apply this operation | choose this genre |
| ⌥↩ | reveal in Finder | reveal in Finder | reveal in Finder | — |
| ⇧↩ | set the genre of this book | — | — | create the typed text as a new genre |
| ⇧ / ⌘Y | Quick Look | Quick Look | Quick Look | — |
| ⌘L | large type: title, author, path | same | same | — |

There are no bulk modifiers: bulk work is always a head row at the top of the list.

## Genres

The folder tree is the on-device browser, so it encodes exactly one thing: genre → author → series. `kb update`
bootstraps a genre for every book from its first two folder levels (`01_Fiction/01_Sci-Fi_Fantasy/…` →
`fiction/sci-fi_fantasy`); books under `00_Inbox` or `99_Archives` have none and wait in the inbox.

`kb classify` is the daily loop: it lists the inbox; ↩ on a book opens the genre picker. With words (`kb classify
newport`) it lists every library book matching them, whatever its genre. ⇧↩ on any book in any list opens the
same picker.

The genre picker:

- **Header:** the book's title and current genre, or "N books" in bulk mode.
- **Rows:** the current genre first ("Keep fiction/sci-fi · moves the book home if it isn't"), then the known
  genres whose path contains the typed text, ignoring case (`spy` finds `fiction/spy`). ⇥ completes a genre.
- **↩** applies the selected genre. **⇧↩ on any row** creates the typed text as a new genre. When nothing
  matches there is a single row, "No genre ‘xyz’ — ⇧↩ creates it", which does nothing on plain ↩.
- **Effect:** the book moves to `genre/author[/series]/` with a normalised filename, its index row is updated
  and the move is journaled. A book without a recognisable author keeps its place and its new genre.
- **Bulk:** "Set genre for all N" opens the same picker for every book listed; the notification counts the
  books that moved and those that stayed put.
- **Known genres** come from the genre store, from folders (the first two levels) and from the index.

Genres live in `genres.tsv` next to the index, keyed by a fingerprint of the book's *text*, not its bytes: for an
epub the set of its HTML files (whatever they are named or ordered), for an fb2 its `<body>`. A renamed, moved or
repacked epub, a swapped cover or edited metadata is still the same book and keeps its genre; other formats,
partial downloads and unreadable files are hashed whole. `kb update` computes the fingerprint while reading each
book, so a full update of a big card takes a minute or two longer; if a book's fingerprint has changed, its genre
is carried over by path. An older `tags.tsv` is read once when `genres.tsv` does not exist yet; its tags are
ignored.

Author folders are `Last, First`. A plain `First Last` name is inverted, except Cyrillic names, which are assumed
`Фамилия Имя [Отчество]` as in libgen/flibusta filenames; an existing author folder (either form) wins over the
guess, so `Teague Rowan` joins `Teague, Rowan/` if that folder exists. The genre folder is the existing one
matching the genre; a series folder is only used when you own more than one book of the series. Partial downloads
and unclassified books are never moved. Names are made exFAT-safe.

## Fix

`kb fix` works out what is wrong and offers to fix it straight away. There is no plan file and no review step:
the operations are computed when the list is shown and computed again when you press ↩.

1. **Fix all N** — the subtitle counts operations by kind (`12 moves · 3 to _trash · 2 to _dups`). ↩ applies
   everything, then rebuilds the index.
2. **Undo last batch (N moves)** — shown when the journal holds a batch, which can come from a fix, a genre move
   or a trash. An undo is itself a batch, so undoing twice re-applies.
3. **Reminders**, when non-zero: "N books without a genre" completes the query to `kb classify`, "N unfinished
   downloads" to `kb trash`.
4. **Operations**, one row each; ↩ applies it.
   - `move`: rename or relocate a classified book to `<genre folder>/<Last, First>/[<Series>/]<Last, First> - <Title> (<Series> NN) (<Year>).<ext>`
   - `trash`: junk or a byte-identical copy goes to `_trash/<original path>`
   - `dups`: a less preferred edition goes to `_dups/<original path>` (format order: epub, kepub, fb2, mobi,
     azw3, azw, pdf, djvu; then newer, then larger)
5. **Problems with no automatic remedy**, one row each; ↩ reveals the file so you can fix it by hand: conflicts
   (two books want one destination), an author folder that is the `First, Last` swap of a better-populated one,
   and names that stay noisy or opaque on unclassified books (they resolve once the book has a genre).

Words narrow every part: `kb fix newport` shows only what concerns matching books, so it doubles as "fix this one
book".

The findings behind it:

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

Every apply:

- moves the KOReader `.sdr` sidecar with its book;
- rewrites the paths in KOReader's `collection.lua` and `history.lua` (keeping `.bak` copies) and in
  path-mirrored `docsettings` sidecars;
- prunes folders left empty;
- renames in place when the destination differs only by letter case or Unicode normalisation (the card is
  case-insensitive);
- removes and journals a redundant source (an empty folder, or a byte-identical copy of a file already at the
  destination), while a destination holding different content leaves the operation skipped;
- deletes nothing else.

## Trash

`kb trash` is the manual way to set books aside.

- **No words:** unfinished downloads (`.part`), oldest first. This is the only list they appear in.
- **With words:** unfinished downloads matching the words first, then every library book matching them.
- **↩** moves the book to `_trash/<original path>`. The move is journaled (undo from `kb fix`), carries the
  KOReader sidecar, rewrites KOReader paths and removes the book from the index.
- **Trash all N** at the top does the same for every book listed.
- **Nothing is deleted.** Empty `_trash/` (and `_dups/`) by hand in Finder; the scanner ignores both.

## Other sources

Set **Other sources** (`KOBO_SOURCES`, paths separated by `:`) to folders of ebooks that are not in the library
yet: a Calibre library, a downloads folder, an old reader's card. `kb update` indexes them together with the
library into a separate `sources.db`; an unmounted source is skipped and named in the notification.

`kb src <words>` lists only what can be imported: not already in the library by fingerprint, not a partial
download, readable, and carrying its format's signature bytes (`%PDF`, `BOOKMOBI`, `AT&TFORM`). The source
folder's name is part of the path, so `kb src calibre` narrows by source.

↩ copies the book into the library's inbox folder (the one whose name is `inbox` after the order prefix, or a new
`_inbox/`) and adds it to the index at once; "Import all N" imports every book listed. The source is never
touched, nothing is overwritten, and refusals (destination taken, unreadable, already in the library) are named in
the notification. Source books never get a genre; they get one after import, through `kb classify` or ⇧↩.

## Reminders and feedback

The inbox is not empty when any complete library book has no genre. Its count appears at the top of an empty
`kb` (↩ completes to `kb inbox`), in `kb stats`, in `kb fix`, and at the end of the notifications after an import
or an update.

Every feedback row either acts on ↩ or says what to type:

| Situation | Row | ↩ |
|---|---|---|
| no index / index from an older version | "No index yet" / "Index is from an older version" | update |
| index empty | "Index is empty — is the card mounted? Alfred needs Removable Volumes access" | update |
| no matches | "No books match ‘…’" | — |
| no sources configured | a message naming `KOBO_SOURCES` | — |
| update running | "Update is running" | — |
| nothing to fix / inbox empty / no duplicates / nothing to trash | a message | — |

## Install

Download `Kobo Library.alfredworkflow` (or build it with `./build.sh`) and open it. The workflow is
self-contained: the `kobolib` package is bundled inside and runs on macOS's `/usr/bin/python3` (3.9, the version
the Command Line Tools ship), with no dependencies and no virtualenv. The code stays 3.9-compatible on purpose:
`pyproject.toml` pins `requires-python = ">=3.9"` and CI runs the tests and ruff (target `py39`) on 3.9 and 3.13.

In the workflow's configuration set **Library root** (`/Volumes/Transcend/kobo`), then run `kb update` once.
Rerun it after adding books, and after updating the workflow when it says "Index is from an older version": every
command refuses to read or write an index built by an earlier version, so an update is the only upgrade step.

The index (`library.db`), `genres.tsv`, `journal.jsonl` and `covers/` live in Alfred's workflow data folder
(`~/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobolib`), which survives workflow updates and
cache clears. Override it with the optional **Index folder** setting.

## Terminal

The terminal mirrors the words (`KOBO_ROOT=… KOBO_DATA=… uv run kobolib …`):

```
kobolib update [--no-thumbnails]
kobolib search "<words>"           Alfred JSON; the same input as kb
kobolib fix [--dry-run] [<words>]  --dry-run prints one operation per line (kind, src, dst, reason)
kobolib trash <path>…
kobolib undo
kobolib genre <path|fingerprint>… <genre>
kobolib import <path>…
```

Paths and fingerprints may also be given in one argument, one per line, which is how the head rows pass them.
The commands that change something also take `--notify`, which posts the summary as a macOS notification.

## Metadata sources

- **epub**: OPF (`dc:title`, `dc:creator`, `dc:language`, `dc:date`, `dc:publisher`, `calibre:series`), cover from `meta[name=cover]` / `properties=cover-image`.
- **fb2**: `title-info` (book-title, author, lang, sequence), `publish-info`, cover from `coverpage` binary.
- **mobi / azw / azw3 / pdf / djvu / partial / corrupt files**: parsed from the filename — libgen (`Author - Title (Year, Publisher) - libgen.li`), Anna's Archive (`Title -- Author -- …`), `[Series №N]`, `(Series N)`, `Title{Author}(Year, Publisher){id}`, `NN Title - Author`, `Title, The - Author`.

Filename parsing is a heuristic; `Author - Title` vs `Title - Author` is decided by which side looks more like a
person (`Last, First`, initials, no stopwords). Genuinely ambiguous two-word cases default to `Author - Title`.

## Development

```sh
uv run pytest
uv run ruff check && uv run ruff format --check
```

Modules, from the bottom up: `model` (the records), `paths`/`scan`/`identity`/`filenames`/`metadata` (reading the
card), `languages` (language names), `index` (SQLite FTS5), `query` (words to FTS), `tags` (the genre store),
`lint`, `naming`, `plan`, `apply`/`koreader` (moving files), `alfred` (JSON items), `config` (paths from the
environment), `library` (operations), `commands` (the `kb` lists and the genre picker) and `cli`.

Not built yet: `kb index` as a browsable view of the whole index (until then `index` is an ordinary search word),
and tags as KOReader collections.
