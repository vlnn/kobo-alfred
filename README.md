# kobo-alfred

Alfred workflow for searching an ebook library (the Kobo SD card) by metadata, with covers.

```
kb deep work                 full-text over title / authors / series / folder / filename
kb author:delany fmt:epub    filters: fmt: in: author: series: lang: year: is:partial is:complete
kb in:inbox                  folder match is substring, case-insensitive
kb                           empty query → most recently added books
kb:index                     rebuild the index (reads epub/fb2 metadata, extracts covers)
kb:dups                      same title in several files or formats
kb:rnd fmt:epub              five random complete books, filters allowed
kb:stats                     counts: books, incomplete downloads, duplicate titles
kb:lint                      problems: junk files, partial downloads, noisy/opaque names, duplicates, misfiled series, unclassified
kb:inbox                     books without a genre yet, oldest first
```

Each result shows: title · authors · series #n · year · FORMAT size · path relative to the library root.
Covers are used as icons (embedded epub/fb2 cover, otherwise a Quick Look thumbnail via `qlmanage`).

| Key          | Action                       |
|--------------|------------------------------|
| ↩            | open the book                |
| ⌥↩           | reveal in Finder             |
| ⌘↩           | copy library-relative path   |
| ⌃↩           | browse the book's folder     |
| ⇧ / ⌘Y       | Quick Look                   |
| ⌘C           | copy relative path           |
| ⌘L           | large type: title/author/path|

`.part` files (unfinished downloads) are indexed, flagged with ⚠︎ and not actionable.

## Install

Download `Kobo Library.alfredworkflow` (or build it with `./build.sh`) and open it. The workflow is
self-contained: the `kobolib` package is bundled inside and runs on macOS's `/usr/bin/python3` (3.9+),
no dependencies, no virtualenv.

In the workflow's configuration set **Library root** (`/Volumes/Transcend/kobo`). Run `kb:index` once;
rerun after adding books.

The index (`library.db`) and `covers/` live in Alfred's workflow data folder
(`~/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobolib`), which survives workflow
updates and cache clears. Override with the optional **Index folder** setting.

From a terminal: `KOBO_ROOT=… KOBO_DATA=… uv run kobolib index|search|dups|random|stats`.

## Organizing

The folder tree is the on-device browser, so it should encode exactly one thing: genre → author → series.
`kobolib` keeps a tag store (`tags.tsv` next to the index) keyed by a content fingerprint, so tags survive
renames and moves. `kb:index` bootstraps a genre for every book from its first two folder levels
(`01_Fiction/01_Sci-Fi_Fantasy/…` → `fiction/sci-fi_fantasy`); books under `00_Inbox` or `99_Archives`
stay unclassified and show up in `kb:inbox`.

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
| `misfiled_series` | a series book outside the folder that already holds its series |
| `unclassified` | no genre |

From a terminal: `kobolib lint --text` prints one finding per line (`rule<TAB>detail<TAB>paths`).

## Metadata sources

- **epub**: OPF (`dc:title`, `dc:creator`, `dc:language`, `dc:date`, `dc:publisher`, `calibre:series`), cover from `meta[name=cover]` / `properties=cover-image`.
- **fb2**: `title-info` (book-title, author, lang, sequence), `publish-info`, cover from `coverpage` binary.
- **mobi / azw / azw3 / pdf / djvu / partial / corrupt files**: parsed from the filename — libgen (`Author - Title (Year, Publisher) - libgen.li`), Anna's Archive (`Title -- Author -- …`), `[Series №N]`, `(Series N)`, `Title{Author}(Year, Publisher){id}`, `NN Title - Author`, `Title, The - Author`.

Filename parsing is a heuristic; `Author - Title` vs `Title - Author` is decided by which side looks more like a person
(`Last, First`, initials, no stopwords). Genuinely ambiguous two-word cases default to `Author - Title`.

## Development

```sh
uv run pytest
```
