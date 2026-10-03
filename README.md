# kobo-alfred

Type `kb` in Alfred, see your Kobo library with covers, press ↩ to read. Then let it tidy the library for you: file every book under `genre / Author, Name / Series / Author - Title (Year).epub`, set duplicates and junk aside, and undo if you don't like the result. Nothing is deleted except a file that is byte-for-byte already at its destination.

The library is a folder on your Mac. Everything the workflow writes stays inside that folder (plus its own index next to Alfred's data); it doesn't talk to the Kobo. Keep the folder in sync with the device however you like (Syncthing, a mounted SD card, rsync) and point the workflow at the Mac side.

```
kb delany epub            →  Delany, Samuel R. - Dhalgren (1975) · EPUB 1.2 MB · 01_Fiction/02_Sci-Fi/…
kb fix                    →  Fix all 14 · 9 moves · 4 to _trash · 1 to _dups
kb classify               →  pick a genre, the book moves home
kb src heinlein           →  import from Calibre / Downloads into the inbox
```

## Install (three minutes)

1. Grab `Kobo Library.alfredworkflow` from [Releases](https://github.com/vlnn/kobo-alfred/releases) (every push to `main` publishes a `latest` build) or build it yourself with `./build.sh`. Double-click it.
2. In the workflow's configuration set **Library root** to the folder that holds your books, e.g. `~/Books/kobo` (a Syncthing folder) or `/Volumes/Transcend/kobo` (the card itself).
3. Type `kb update` ↩. A notification arrives when the index is built.

Nothing to install: the workflow bundles `kobolib` and runs on macOS's own `/usr/bin/python3` (3.9+), no dependencies.

If your library root is on a removable volume and `kb` shows *Index is empty — is the card mounted?* while it is mounted, give Alfred access to **Removable Volumes** (System Settings → Privacy & Security → Files and Folders), then `kb update` again.

## Search

Every word you type must match, by prefix, one of: title, authors, series, series number, folder, path, genre, format, language (code or English name: `uk` and `ukrainian` both work), year. Case and diacritics are ignored.

```
kb dhalgren              one book
kb delany                everything by Delany
kb delany epub           …only the epubs
kb sci-fi 1975           genre + year
kb inbox                 whatever is still in the inbox folder
kb                       newest books first (with a reminder if some have no genre)
```

Each row is `title` over `authors · series #n · year · FORMAT size · path`. The icon is the embedded cover for epub and fb2, a Quick Look thumbnail for pdf, and the plain file icon for everything else. Lists show the first 40 matches, so add a word if what you want isn't there.

| Key | Does |
| --- | --- |
| ↩ | open the book |
| ⌥↩ | reveal in Finder |
| ⇧↩ | set the genre (opens the genre picker) |
| ⇧ or ⌘Y | Quick Look |
| ⌘C | copy the library-relative path |
| ⌘L | large type: title, author, path |

## Commands

A first word that names a command puts its rows above the normal search results. Type two letters and ↩ to complete it.

```
kb stats       counts: books, no-genre, duplicates, pending fixes, unfinished downloads, sources
kb dups        every copy of a title that exists in several files
kb rnd         five random books (kb rnd epub → five random epubs)
kb inbox       books without a genre, oldest first
kb classify    give those books a genre, one by one or all at once
kb fix         what is wrong and how to fix it · ↩ applies
kb trash       unfinished downloads, or any book you name · ↩ moves it to _trash/
kb src         search other sources · ↩ imports into the inbox
kb update      rebuild the index (library, sources, PDF thumbnails) in the background
```

Every command accepts search words after it: `kb fix delany` shows only fixes touching Delany, `kb trash lovecraft` lets you set aside a specific book.

## Walkthrough 1: file a book you just downloaded

You copied `Dhalgren.epub` to `00_Inbox/` in your library.

```
kb update                                     index it
kb classify                                   the inbox, each row ending in "↩ pick a genre"
   ↩ on Dhalgren                              genre picker opens
   type sci  ↩  on fiction/sci-fi             done
```

Notification: `Dhalgren → fiction/sci-fi · moved → 01_Fiction/02_Sci-Fi/Delany, Samuel R./`

What happened: the genre was stored, and because the book has an author it was moved straight to its home and renamed to the canonical form `Delany, Samuel R. - Dhalgren (1975).epub`. Books without an author get a genre but stay where they are.

Variations:

- Many books? The list starts with **Set genre for all N books** — one genre for every row shown. `kb classify delany` lists every library book matching the words, whatever genre it has now, so you can re-file an author in one go.
- New genre? Type it in the picker and press ⇧↩ to create it.
- Changed your mind? ⇧↩ on a book in the search, `kb dups`, `kb rnd`, `kb inbox` or `kb trash` lists reopens the picker (not on `kb src` rows or unfinished downloads). **Keep …** at the top moves the book home without changing the genre.

## Walkthrough 2: tidy the whole library

```
kb fix
```

The first rows are the plan:

```
Fix all 14                 9 moves · 4 to _trash · 1 to _dups
Undo last batch (6 moves)  (only after you've applied something)
3 books without a genre    ↩ lists them
2 unfinished downloads     ↩ lists them
Delany, Samuel R. - Nova (1968).epub       move · relocate + rename · 00_Inbox/nova.epub → 01_Fiction/02_Sci-Fi/Delany, Samuel R./
FSCK0001.REC                               trash · FSCK0001.REC: not a book · FSCK0001.REC → _trash/
Dhalgren.mobi                              dups · Dhalgren: epub, mobi · 01_Fiction/…/Dhalgren.mobi → _dups/01_Fiction/…/
⚠︎ Babel-17.epub                            skip · destination taken by 01_Fiction/02_Sci-Fi/Delany, Samuel R./Delany, Samuel R. - Babel-17 (1966).epub · …
Nova: filename carries download noise      noisy name · 1 file · 99_Archives/Nova_(1968)_--_Delany.epub
```

- ↩ on a row applies that one operation; ↩ on **Fix all** applies them all. ⌥↩ reveals the file instead.
- `move` puts a book in its genre/author/series home with a canonical name. A noisy or opaque filename disappears here for free: the move renames it.
- `trash` moves junk (`FSCK*`, `.zip`, `.txt`, any non-book file, empty folders, identical copies) to `_trash/`, mirroring its path. Dot-files and KOReader `.sdr` folders are never junk.
- `dups` keeps the best copy of a title (complete, in a genre folder, epub > fb2 > mobi > azw3 > azw > pdf > djvu, newest, largest) and moves the rest to `_dups/`.
- `⚠︎ skip` rows need you: the destination is already taken by another file.
- Rows with no verb (`noisy name`, `opaque`, `double extension`, `author inversion`) are books that are *not* moving, usually because they have no genre or no author, so the name can't be fixed by filing them. ↩ reveals the file. Give the book a genre with ⇧↩ and the row usually turns into a `move`.

"Identical" and "already in the library" mean the same text: for epubs the fingerprint is a hash of the book's text files only, so two copies with different covers or metadata still count as one book. Other formats are hashed whole.

Every batch is journaled, whether it came from `kb fix`, from setting a genre or from `kb trash`; **Undo last batch** reverses the most recent one (and undo is itself a batch, so undoing twice re-applies). `_trash/` and `_dups/` are never scanned, so an `rm -r` there is your decision alone.

The one deletion: when a move finds a byte-identical file already at the destination, the redundant source is removed instead of moved. That is journaled too, and undo restores it from the kept copy. Folders left empty are pruned; case-only and accent-only renames happen in place.

Dry run from a terminal: `kobolib fix --dry-run` prints `kind	src	dst	reason`, one per line.

## Walkthrough 3: pull books in from Calibre or Downloads

Set **Other sources** in the workflow configuration to `~/Calibre Library:~/Downloads` (paths separated by `:`), run `kb update`, then:

```
kb src heinlein             books in the sources that are NOT already in the library
   ↩ on a row               copied into the library inbox, indexed, ready for kb classify
   ↩ on Import all          every row shown
```

Books already in the library (by content fingerprint, not by name) are hidden, so `kb src` is always "what am I missing". Import *copies*; the source keeps its file. The destination is your existing inbox folder (any top-level folder whose name is `inbox` after the `NN_` prefix, e.g. `00_Inbox`), or `_inbox/` if there is none. Unreadable and `.part` files are refused.

## KOReader users

Moves and renames also carry each book's `.sdr` sidecar along and rewrite the paths in `.adds/koreader/settings/{collection,history,bookmarks}.lua` (a `.bak` is written first) and under `.adds/koreader/docsettings/`, so highlights, progress and collections survive `kb fix`. This only works if `.adds/koreader` lives under your library root: either the root is the device itself, or your sync includes that folder.

## How it reads your folders

The folder tree is what the Kobo shows, so the tool keeps it meaning exactly one thing: **genre → author → series**.

- Genre is the first two folder levels with their order prefixes stripped: `01_Fiction/02_Sci-Fi_Fantasy/…` → `fiction/sci-fi_fantasy`. Books under `inbox`, `archives`, `_inbox`, `_dups`, `_trash` or `_broken` have no genre and show up in `kb inbox`.
- Author folders are `Surname, Given`. Existing folders win: if you already have `Le Guin, Ursula K.`, that spelling is reused.
- A series gets its own folder only when the library holds more than one book of it.
- Canonical file name: `Surname, Given - Title (Series 03) (Year).epub`, FAT-safe, ≤ 255 bytes.
- Genres live in `genres.tsv` keyed by a content fingerprint, so they survive renames and moves. `kb update` bootstraps a genre for every book from its folder, never overwriting one you set.

## Where things are

Index (`library.db`, `sources.db`), `covers/`, `genres.tsv` and the undo journal (`journal.jsonl`) live in Alfred's workflow data folder, `~/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobolib`, which survives workflow updates and cache clears. Override with **Index folder**.

Format support: epub and fb2 are read for metadata and cover; mobi, azw, azw3, pdf and djvu are described from their filename (libgen, Anna's Archive, `[Series №N]`, `Title - Author` and friends). `.part` files are indexed, flagged as unfinished downloads, and only ever offered to `kb trash`.

## From a terminal

The same commands, same data:

```
export KOBO_ROOT=/Volumes/Transcend/kobo
export KOBO_DATA="$HOME/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobolib"
uv run kobolib update
uv run kobolib search delany | jq '.items[].title'
uv run kobolib fix --dry-run
uv run kobolib fix delany
uv run kobolib trash "$KOBO_ROOT/00_Inbox/broken.epub.part"
uv run kobolib genre "$KOBO_ROOT/00_Inbox/nova.epub" fiction/sci-fi
uv run kobolib import ~/Downloads/babel-17.epub
uv run kobolib undo
```

`KOBO_SOURCES` takes the other sources. `search` and `genres` print Alfred's JSON; everything else prints one line and, with `--notify`, posts it as a macOS notification.

Set `KOBO_DATA` as above if you want the terminal and Alfred to share one index: without it the CLI defaults to `~/Library/Application Support/kobolib`, a separate copy.

## When something looks off

| You see | Do |
| --- | --- |
| *No index yet* | ↩ on that row, or `kb update` |
| *Index is from an older version* | ↩ on that row: the workflow was updated and the index format changed |
| *Index is empty — is the card mounted?* | the library root is missing or empty: check the path, mount the volume, or grant Alfred Removable Volumes access |
| *Library root not mounted: …* (after `kb update`) | the **Library root** path doesn't exist right now |
| *No books found: …* (after `kb update`) | the root exists but holds no epub/fb2/mobi/azw/azw3/pdf/djvu; the message says why if it's a permissions problem |
| *Indexing is running, try again later* | wait for the notification; a stale lock expires after an hour |
| *Set KOBO_SOURCES, then kb update* | **Other sources** is empty |
| *No source is mounted* | plug in the drive named in **Other sources** |
| *No book selected* in the genre picker | it was opened directly; use ⇧↩ on a book or ↩ in `kb classify` |
| *Nothing to fix* | the library is clean |

## Development

```
uv run pytest
uv run ruff check && uv run ruff format --check
./build.sh                      → dist/Kobo Library.alfredworkflow
```

CI runs the tests on Python 3.9 and 3.13, builds the workflow and publishes it as the `latest` pre-release; a `v*` tag makes a proper release.
