# kobo-alfred — local model (oracle) design

Status: implemented, 2026-10-03. Builds on the interface described in the README; nothing there changes.

Deviations from the proposal as implemented are listed at the end.

## Why

Three things in the library still need a human for every book:

1. Giving a new book a genre (`kb classify`, one picker per book).
2. Naming books whose filename carries no usable metadata (`opaque`, `noisy_name`, and every mobi/azw/pdf/djvu, which are described from the filename by heuristics).
3. Merging author folders that are the same person spelled differently (`Delany, Samuel R.` / `Delany, Samuel` / `Дилэни, Сэмюэл`).

These are judgement calls on short text, which is what a small local language model is good at. A model running in llama.cpp on the Mac can propose answers; the workflow shows them as rows and the person presses ↩. The model never moves a file.

A fourth thing is not a chore but a missing view: *what else do I have like this?* Search finds words; it cannot find the book that is about the same thing under a different title. An embedding model on the same server answers that as `kb like`.

## Principles

1. **Optional.** With no model running, the workflow behaves exactly as today. Nothing in the UI mentions the oracle until a suggestion exists.
2. **Suggestions, not actions.** The oracle writes to its own store. Only ↩ in Alfred turns a suggestion into a genre, a rename or a move, through the same journaled `apply` as everything else.
3. **Never on the hot path.** Script filters answer in under 100 ms and only *read* the stores. The oracle and the embedder run in the background runner, where `update` and `fix` already run, and end with a notification. The one exception is `kb model`, which asks the local server for its model list with a half-second timeout, because that list *is* the thing being shown.
4. **Closed answers.** Every question has a schema. Genre is chosen from the known genres or `none`; names are strings the row shows verbatim before anything happens. The model cannot invent a genre or a command.
5. **Metadata wins.** The oracle fills blanks. A book with `dc:title` is never re-titled; a book with a genre is never re-classified unless asked.
6. **Compute once.** Answers are keyed by fingerprint and kept until the evidence changes, so re-indexing, renaming or moving a book costs nothing.
7. **No new dependencies.** The server speaks HTTP; `urllib` from the stdlib is enough. The workflow keeps running on `/usr/bin/python3`.

## Server

The oracle talks to a running `llama-server` through its OpenAI-compatible endpoint.

```
POST {KOBO_ORACLE_URL}/v1/chat/completions
{
  "messages": [{"role": "system", "content": …}, {"role": "user", "content": …}],
  "temperature": 0,
  "response_format": {"type": "json_schema", "json_schema": {"name": "genre", "schema": {…}}}
}
```

[llama-server converts the schema to a grammar for that request](https://docs.liquid.ai/deployment/on-device/llama-cpp/structured-output), so the reply is always valid JSON of the shape asked for, and an `enum` of genres is honoured token by token. The workflow sends the configured model name in the `model` field. In llama-server's [router mode](https://glukhov.org/llm-hosting/llama-cpp/llama-server-router-mode/) the server starts empty, lists what it knows at `/v1/models`, and loads the model a request names, swapping as needed; a single-model server ignores the field. Embeddings come from `/v1/embeddings` on the same server (router mode with an embedding model in its preset) or from a second server on another port.

Configuration (workflow variables, like the existing ones):

| Variable | Meaning | Default |
|---|---|---|
| `KOBO_ORACLE_URL` | base URL of llama-server; empty turns the oracle and the embedder off | empty |
| `KOBO_ORACLE_MODEL` | model for the questions | empty: whatever the server loads by default |
| `KOBO_EMBED_URL` | base URL for embeddings, when they run on another server | empty: same as the oracle |
| `KOBO_EMBED_MODEL` | embedding model; empty turns `kb like` off | empty |

These are ordinary workflow configuration fields. `kb model` (below) writes the two model fields for you; the URLs are typed once.

Model requirements: an instruct model that handles the library's languages (Cyrillic included) and follows a schema. A 3–8B model at Q4 on Apple Silicon answers a genre question in a second or two, which is fine for a background pass over a few hundred inbox books. The model is not named in the code or the docs; it is whatever the server runs.

## Evidence

What the oracle is shown about a book, in this order, as much as exists:

1. Title, authors, series, series index, language, year, format, library-relative path.
2. `dc:subject` (all of them) and `dc:description` from the OPF; `genre` and `annotation` from fb2 `title-info`. **These are not indexed today and are the strongest evidence, so indexing them is step 1 below, and useful on its own.**
3. The first ~2 000 characters of body text: the first text member of an epub (the same members the fingerprint hashes), the `body` of an fb2, the first text record of a mobi. PDF and djvu give only metadata and filename; there is no stdlib text extractor and the oracle is not worth a dependency.
4. The list of known genres (`library.known_genres`), for questions that choose among them.

Evidence is assembled by `evidence.py` from the index row and the file; it is the only place that opens a book on the oracle's behalf.

## Questions

Each question is a function in `oracle.py` with a fixed schema. Three to start.

### Genre

For a book without a genre. Answer: one of the known genres, or `none` when the model is not confident.

```json
{"genre": {"enum": ["fiction/sci-fi", "nonfiction/history", "…", "none"]}}
```

`none` is stored too, so the book is not asked about again until the genre list grows or the person asks.

### Name

For a book whose title or authors came from the filename (`Book.guessed` — a flag `from_filename` sets) and that `lint` reports as `opaque` or `noisy_name`, or whose format has no embedded metadata. Answer:

```json
{"title": "string", "authors": ["string"], "confident": true}
```

Only title and authors. Series and year are where small models make things up; they stay whatever the filename said. `confident: false` answers are stored and not shown.

### Author alias

For the set of author folders. Answer: groups of folder names that denote one person and the canonical form for each group, `Surname, Given` as `naming.surname_first` would write it.

```json
{"groups": [{"canonical": "Delany, Samuel R.", "aliases": ["Delany, Samuel", "Дилэни, Сэмюэл"]}]}
```

This question is asked about the whole library at once, not per book, and only on request.

## Store

`oracle.tsv` next to `genres.tsv`, one row per fingerprint and question:

```
fingerprint	question	answer	evidence_hash	asked_at
```

`answer` is the JSON reply. `evidence_hash` is a hash of the evidence string; a row is stale when the hash changes (new metadata, a grown genre list) and is then re-asked on the next pass. Author aliases use the fingerprint `*` and the hash of the sorted folder list.

Rows are deleted when the suggestion is acted on, when the person dismisses it, or when the book leaves the index.

## Vectors

`vectors.db` next to the index, SQLite:

```
vectors(model, fingerprint, dim, vec BLOB)         float32, packed with struct; one row per model and book
neighbours(model, fingerprint, rank, other, score)  the twenty nearest, computed when the vector is stored
```

The text embedded is the same evidence as the oracle's, without the genre list, cut to about 1 500 characters so it fits a typical embedding model's window. The model must be multilingual for a library that mixes scripts; as with the oracle, it is not named in code.

Similarity is cosine over the stored vectors, computed in pure Python with `array('f')` and `sum(map(mul, a, b))`. Per new book that is one pass over the library, a fraction of a second at a few thousand books, and it happens in the background right after the vector arrives, so `kb like` is a lookup. The first pass over a whole library is one N² sweep, minutes, once. A book's neighbour list is recomputed only when its own vector changes; other books' lists pick it up lazily, when they are next recomputed, or on `embed --force`.

`kb like` with no words needs the last book KOReader opened: `koreader.py` already finds `history.lua` to rewrite paths; reading its latest entry is a small regex over the same file.

## Interface

No new keyword, no new grammar. Suggestions appear inside the lists that already exist.

### `kb classify` and the genre picker

```
kb classify
  Set genre for all 12 books                     ↩ picks one genre for every book listed below
  Accept 9 suggested genres                      ↩ files each book under its suggested genre     ← new, only when ≥ 1 suggestion
  Dhalgren            author ? · fiction/sci-fi? · EPUB 1.2 MB · 00_Inbox/…   ↩ pick a genre
  Nova                author ? · genre ? · …
```

A suggested genre shows in the subtitle with a trailing `?` where `genre ?` is today. In the picker for that book the suggestion is the first row:

```
  fiction/sci-fi      suggested · ↩ sets it and moves the book home
  Keep …              (only when the book already has a genre)
  …known genres…
```

**Accept N suggested genres** sets the genre of every listed book that has one, through the existing `genre` command with its fingerprints and genres, so every move is journaled and undoable as one batch. It is a head row, like the others; there is no modifier.

### `kb fix`

Two kinds of new rows, both below the automatic operations:

```
  Delany, Samuel R. - Nova (1968).epub     rename · suggested title and author · 00_Inbox/7_815203.epub → 00_Inbox/
  Merge 3 author folders into Delany, Samuel R.   ↩ moves 7 books · ⌥↩ reveals
```

↩ on a `suggested` rename applies that one move. The rename is computed by `naming.canonical_name` from the suggested title and authors, so a book that then gets a genre moves home with the right name. Author merges are one row per group; ↩ applies the group's moves as one batch. Both are plain `Operation`s with `reason` starting with `suggested`, so `Fix all` can include or exclude them; it excludes them, because `Fix all` today only does what is certain.

Dismissing is implicit: choosing a different genre in the picker, or renaming or moving the file by hand, changes the evidence and the suggestion goes with it. For a suggestion that keeps coming back, `kb fix <words>` narrowed to that book shows a head row **Dismiss suggestions for this book**; ↩ marks the row dismissed in the store and it is not asked again until `--force`. ⌥↩ keeps its one meaning, reveal, everywhere.

### Asking

```
kb fix
  Ask the model about 12 inbox books and 4 unnamed files     ↩ runs in the background, then notifies   ← only when the oracle is configured and there is something unasked
```

The same row appears in `kb classify` when inbox books are unasked. ↩ runs `kobolib ask` in the background runner. `kb update` does not ask on its own: indexing should stay as fast as it is, and the person decides when to spend the minutes.

### `kb like`

```
kb like dhalgren
  Like Dhalgren                 Delany, Samuel R. · 01_Fiction/02_Sci-Fi/…           ← header, the seed, not actionable
  Nova                          91% · Delany, Samuel R. · 1968 · EPUB 400 KB · …     ↩ opens
  Babel-17                      88% · …
  Embed 240 new books           ↩ runs in the background, then notifies             ← only when some books have no vector
kb like                        seed = the book KOReader opened last (history.lua), else the newest book
```

The seed is the top search match for the words; add words to pick another. Rows are the seed's nearest neighbours by cosine similarity, twenty at most, other editions of the same title left out (same `norm_title`). They are ordinary book rows: every key works. Below them come the plain search results for `like <words>`, as for every command.

Nothing is computed while you type. `kb like` reads the seed's precomputed neighbour list from the vector store; with no vectors at all it shows one row, *No embeddings yet · ↩ embeds in the background*.

### `kb model`

```
kb model
  Oracle: qwen2.5-7b-instruct          http://127.0.0.1:8080 · reachable            ← header
  Embeddings: bge-m3                   1 240 of 1 300 books embedded · ↩ embeds the rest
  qwen2.5-7b-instruct                  ✓ oracle · ↩ choose what it is for
  gemma-3-4b-it                        ↩ choose what it is for
  bge-m3                               ✓ embeddings · ↩ choose what it is for
  Model not reachable at …             (instead of the list, when the server is down)
```

Rows are what `/v1/models` returns, from both URLs when they differ. ↩ on a model opens a two-row chooser, a second script filter like the genre picker:

```
  Use gemma-3-4b-it for the oracle
  Use gemma-3-4b-it for embeddings      (re-embeds everything; the old vectors are kept until the new ones exist)
```

↩ writes the choice into the workflow configuration through Alfred's AppleScript `set configuration`, so the configuration panel stays the single source of truth and the terminal keeps reading the same variables. Switching the embedding model does not delete anything: vectors are keyed by model, and `kb like` uses the current model's set while *Embed N new books* fills it.

### Feedback rows

| Situation | Row | ↩ |
|---|---|---|
| oracle configured, server not reachable | "Model not reachable at {url}" in `kb fix` and `kb classify` | — |
| asked, nothing suggested | "The model had no suggestions" (notification only) | — |
| `kb like` with `KOBO_EMBED_MODEL` empty | "No embedding model · ↩ opens kb model" | completes to `kb model` |
| `kb like` with no vectors for the current model | "No embeddings yet" | embed |
| `kb model`, server down | "Model not reachable at {url}" | — |

### Terminal

```
kobolib ask [genre|name|authors] [<words>]     ask the unasked, or everything matching the words; --force re-asks
kobolib ask --dry-run                           print the evidence that would be sent, one book per block
```

`--dry-run` is the debugging tool: it shows exactly what the model sees.

```
kobolib embed [<words>]                        embed books without a vector for the current model; --force re-embeds
kobolib like <words>                           Alfred JSON, the same rows as kb like
kobolib models                                 what the server(s) list, with the current choices marked
kobolib choose oracle|embed <model>            write the choice to the workflow configuration
```

## Effect on the existing interface and code

The grammar, keys, commands, journal format and `apply` path do not change. Every new row appears only when a suggestion exists or `KOBO_ORACLE_URL` is set. Three things are visible to everyone, model or not:

1. **Search widens.** Once `dc:subject` is indexed as searchable, `kb history` also matches books a publisher tagged *History*, not only ones with the word in the title or path. The "No books match" subtitle lists *subjects* among the fields. (Alternative, if this is unwanted: store subjects `UNINDEXED` and use them only as picker evidence.)
2. **One forced re-index.** The schema version bumps for the new columns; everyone sees *Index is from an older version* once and presses ↩.
3. **Picker order.** Known genres whose path shares a word with the book's subjects sort above the rest. Today: current genre, then alphabetical. After: current genre, subject-likely genres, the rest.

With the oracle on, `genre ?` in `kb classify` subtitles becomes `fiction/sci-fi?` when a suggestion exists, the picker gains a first row, and the head rows and `kb fix` rows above appear. Two commands are added, `like` and `model`; with nothing configured each shows its one feedback row and then the plain search results, as every command does. `kb stats` gains one row. No existing row is removed or changes meaning.

### Existing code that changes shape

| Where | Today | After |
|---|---|---|
| `commands.headed` | one head row | `headed(heads: list[dict], items, batch_size)`; `classify` needs *Set genre for all* and *Accept N* together. `src` and `trash` call sites follow. |
| `library.fix_operations` | the plan filtered by targets | the plan filtered by targets, **plus suggested operations only when targeted**. ↩ on a suggested row applies it; *Fix all* and bare `kobolib fix` stay certain-only. This is the one place the model's output and the planner meet; the rule lives there and nowhere else. |
| `model.Book` / `model.Row` | — | `subjects`, `description`, `guessed`; `to_row`, `row_reader` and the tests' `BASE_ROW` follow. |
| `metadata.from_filename` | fills blanks | also sets `Book.guessed`. |
| `library.run_index`, `library.refresh_index` | rekey `genres.tsv` | also prune `oracle.tsv` for fingerprints that left the index. |
| `info.plist`, `test_workflow.ROUTES` | — | four variables; `ask`, `embed`, `choose` routes; a second chained script filter. |
| `commands.COMMAND_LIST`, `stats` | nine commands | `like` and `model` added; a stats row *N books embedded · ↩ kb model*. |

### What it simplifies

- `GenreStore` and `SuggestionStore` have the same shape (TSV, keyed by fingerprint, load/save/get/set/prune). A small `TsvStore` with the mechanics and two thin subclasses replaces the hand-rolled CSV code in `genres.py`.
- `lint.looks_opaque` guesses "the title came from the filename" with *no author and a title of at most two words*. With `guessed` stored, that is a lookup and the heuristic goes.
- `known_genres` gains a second caller (the genre schema) and stays where it is.

### What it must not touch

`query`, `apply`, `naming`, `plan`, `koreader`, `identity`, `scan`, `covers`, the `trash`, `src`, `update` and `undo` commands, the journal format, the key table. Needing to edit any of these during implementation means the design drifted; stop and revisit this document.

## Behaviour details

- **Order of asking:** names first, then genres, so a book that gets a title is classified under it.
- **Batching:** one request per book per question. Simpler than batching several books into one prompt, and the schema stays small. Author aliases are one request per library.
- **Timeouts:** 60 s per request; a timeout is a skip, not a failure. The pass continues and the notification counts skips.
- **Logging:** `oracle.log` in the data folder records each prompt, reply, and duration, truncated to the last 500 entries. It is the answer to "why did it say that".
- **Idempotence:** `ask` twice without `--force` does nothing the second time.
- **Undo:** accepting suggestions goes through `genre` and `apply`, so `Undo last batch` in `kb fix` covers it.
- **Dc:subject without a model:** once subjects are indexed, the genre picker sorts known genres whose path shares a word with a subject to the top, with no oracle at all. This is step 1 and ships first.

## Modules

| Module | Role |
|---|---|
| `evidence.py` | `evidence_for(row, question) -> str` and `evidence_hash`. Opens the file for the text sample. |
| `oracle.py` | `ask(question, evidence, schema) -> dict \| None` over `urllib`; `genre_of`, `name_of`, `author_groups` wrap it with their schemas and prompts. Off when `KOBO_ORACLE_URL` is empty. |
| `store.py` | `TsvStore`: the fingerprint-keyed TSV mechanics shared by `GenreStore` and `SuggestionStore`. |
| `suggestions.py` | `SuggestionStore` on `oracle.tsv`: `get`, `set`, `stale`, `dismiss`, `prune(rows)`. |
| `genres.py` | `GenreStore` becomes a thin `TsvStore` subclass. |
| `commands.py` | subtitle marker, picker row, `Accept N`, `Ask the model` rows, suggested rename and merge rows in `fix`; the `like` and `model` commands and the *Use model* chooser. |
| `vectors.py` | `VectorStore` on `vectors.db`: `put`, `get`, `neighbours`, `missing(rows)`; cosine and the neighbour pass. |
| `embedder.py` | `embed(text) -> list[float] \| None` over `/v1/embeddings`; `models(url) -> list[str]` over `/v1/models`. |
| `history.py` | `last_opened(root) -> rel_path \| None` from KOReader's `history.lua`. |
| `cli.py` | `ask`, `embed`, `like`, `models`, `choose` subcommands; `genre` and `fix` unchanged. |
| `metadata.py` | reads `dc:subject`, `dc:description`, fb2 `genre` and `annotation` into `Book.subjects` and `Book.description`; sets `Book.guessed`. |
| `index.py` | stores `subjects` (searchable) and `description` (unindexed); `SCHEMA_VERSION` bump. |
| `info.plist` | the four variables; `ask` and `embed` in the background runner's `case`; `choose` run in the foreground; a *Use model* script filter chained from `kb model`, like the genre picker. |

## Tests

Nothing in the suite needs a model. `oracle.ask` is patched with `pytest-mock`; a fixture holds recorded replies for a dozen books, including a `none`, a `confident: false`, a Cyrillic alias group and a malformed reply that must be treated as `None`.

- `test_evidence.py`: what is sent, per format; the hash changes when subjects change and not when the file is renamed.
- `test_oracle.py`: request body shape (schema, temperature 0, no `model` unless configured), timeout and connection errors become `None`, log entries.
- `test_store.py`: `TsvStore` round trip and prune; `test_genres.py` keeps passing unchanged.
- `test_suggestions.py`: staleness, dismiss, prune on removed fingerprints.
- `test_lint.py`: `opaque` driven by `guessed`; the two-word cases move to `test_filenames.py`.
- `test_commands.py`: the rows above appear only when they should; `Accept N` passes the right fingerprint→genre pairs; `Fix all` leaves `suggested` operations alone.
- `test_cli.py`: `ask` is idempotent, `--force` re-asks, `--dry-run` writes nothing; `embed` skips embedded books; `choose` runs the expected AppleScript (mocked `subprocess.run`).
- `test_vectors.py`: cosine on known vectors, neighbour ranks, other editions excluded, vectors keyed by model.
- `test_commands.py` (more): `kb like` seed selection with and without words, the *Embed N* row only when something is missing, `kb model` rows from a mocked `/v1/models`, the chooser's two rows.
- `test_history.py`: latest entry from a sample `history.lua`, missing file.

## Implementation order

TDD, each step a green commit, each step useful without the next.

1. **Subjects and descriptions.** Read them in `metadata.py`, store them, make subjects searchable, sort the picker by subject overlap. Bump the schema.
2. **`Book.guessed`.** `from_filename` marks what it filled; `lint.looks_opaque` uses it instead of its two-word heuristic.
3. **`TsvStore`** extracted from `GenreStore`; `SuggestionStore` on top of it. Pruning wired into `run_index` and `refresh_index`.
4. **`evidence.py` and `oracle.py`** with the genre question. `kobolib ask genre` works from the terminal.
5. **`headed` takes a list**; picker and `kb classify` rows: the `?` marker, the suggested first row, `Accept N`, `Ask the model`.
6. **Name question**; `fix_operations` learns the targeted-only rule; suggested renames in `kb fix`.
7. **Author alias question**, merge rows.
8. **`kb model`**: `embedder.models`, the rows, the *Use model* chooser, `choose` through AppleScript. Useful before any embedding exists: it is also where you see whether the server is up.
9. **`vectors.py` and `embed`**: store, cosine, neighbour pass, the background command, the stats row.
10. **`kb like`**: seed by words, then `history.py` for the no-words case.
11. **plist variables, README section, this document marked implemented.**

## Later

- `kb next`: rank unread books against the last ten entries of KOReader's `history.lua`, using the vectors `kb like` already has. Mostly a question of what "unread" means on the Kobo side.
- ~~Embedding during `kb update` for new books, behind a setting, once the per-book cost is known on real libraries.~~ Done: `KOBO_MODEL_ON_UPDATE`.
- A text sample for PDFs if a dependency-free extractor turns out to be good enough; until then PDFs get metadata and filename only.
- ~~Asking during `kb update` behind a setting, once the pass is known to be fast enough on real libraries.~~ Done: the same setting.

## Not doing

- Query rewriting or natural-language search. The word grammar is instant; a model in front of it would make `kb` feel broken.
- Free-text blurbs or summaries. Nothing in the UI has room for them, and they cannot be checked.
- Series and year from the model. Too often invented; the filename parser's guess is at least traceable.
- Any automatic move on the model's say-so, however confident.

## As implemented

- The passes that decide which books to ask about, and the embedding pass, live in `asking.py` rather than in `cli.py`; `cli.py` only parses arguments and reports.
- `evidence_for(row, genres)` takes the genre list instead of a question name; the hash leaves out the `Path:` line, so a rename or move is not new evidence.
- Which books are "unasked" is decided from the store alone (no stored answer), not from evidence hashes, so the script filters never open a book. "Model not reachable" in `kb fix` and `kb classify` comes from a note the last `ask` or `embed` pass left (`oracle.status`), cleared by the next answer; only `kb model` probes the server.
- `kobolib dismiss <book>` backs the *Dismiss suggestions for this book* row; a dismissed book keeps empty answers with evidence hash `*`, so it is not asked again until `--force`.
- The `genre` command takes `fingerprint<TAB>genre` lines so *Accept N suggested genres* reuses it; every genre set by one call is now one journaled batch, so *Undo last batch* covers all of them.
- A suggested rename or merge is hidden for a file that already has a certain operation: the planner wins. After a merge, the planner derives author folders from embedded metadata, so a book whose metadata still carries the alias spelling may be offered a move back.
- A new vector is scored against every stored one and slotted into the lists of the books it is near, so every neighbour list stays exact at one pass per new book; there is no lazy pickup.
- `KOBO_MODEL_ON_UPDATE` (a checkbox, off by default) makes `kb update` run the name, genre and author questions and the embedding pass after indexing, reporting only steps that did something.
- `kb model`'s *Embeddings* header counts embedded books and, while some are missing, is itself the ↩-embeds row; the embedding server's reachability shows as a *Model not reachable* row in the list when it differs from the oracle's.
