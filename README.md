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
