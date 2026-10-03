# kobold

*kobo + alfred.* A small creature that hoards books on an SD card.

Type `kb` in Alfred, see your library with covers, press ↩ to read. Then let it tidy the library for you: file every book under `genre / Author, Name / Series / Author - Title (Year).epub`, set duplicates and junk aside, and undo if you don't like the result. Nothing is deleted except a file that is byte-for-byte already at its destination.

The library is a folder on your Mac. Everything the workflow writes stays inside that folder (plus its own index next to Alfred's data); it doesn't talk to the Kobo. Keep the folder in sync with the device however you like (Syncthing, a mounted SD card, rsync) and point the workflow at the Mac side.

```
kb delany epub            →  Delany, Samuel R. - Dhalgren (1975) · EPUB 1.2 MB · 01_Fiction/02_Sci-Fi/…
kb fix                    →  Fix all 14 · 9 moves · 4 to _trash · 1 to _dups
kb classify               →  pick a genre, the book moves home
kb src heinlein           →  import from Calibre / Downloads into the inbox
```

## Install (three minutes)

1. Grab `Kobold.alfredworkflow` from [Releases](https://github.com/vlnn/kobold/releases) (every push to `main` publishes a `latest` build) or build it yourself with `./build.sh`. Double-click it.
2. In the workflow's configuration set **Library root** to the folder that holds your books, e.g. `~/Books/kobo` (a Syncthing folder) or `/Volumes/Transcend/kobo` (the card itself).
3. Type `kb update` ↩. A notification arrives when the index is built.

Nothing to install: the workflow bundles `kobold` and runs on macOS's own `/usr/bin/python3` (3.9+), no dependencies.

If your library root is on a removable volume and `kb` shows *Index is empty — is the card mounted?* while it is mounted, give Alfred access to **Removable Volumes** (System Settings → Privacy & Security → Files and Folders), then `kb update` again.

## Search

Every word you type must match, by prefix, one of: title, authors, series, series number, folder, path, genre, subjects (`dc:subject` in an epub, `genre` in an fb2), format, language (code or English name: `uk` and `ukrainian` both work), year. Case and diacritics are ignored.

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
kb like        books like one: the top match for the words, or the one KOReader opened last
kb model       the local model server: which models it serves, which one answers, which one embeds
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

Dry run from a terminal: `kobold fix --dry-run` prints `kind	src	dst	reason`, one per line.

## Walkthrough 3: pull books in from Calibre or Downloads

Set **Other sources** in the workflow configuration to `~/Calibre Library:~/Downloads` (paths separated by `:`), run `kb update`, then:

```
kb src heinlein             books in the sources that are NOT already in the library
   ↩ on a row               copied into the library inbox, indexed, ready for kb classify
   ↩ on Import all          every row shown
```

Books already in the library (by content fingerprint, not by name) are hidden, so `kb src` is always "what am I missing"; when every match is a library copy the row says so instead of "no books match", and `kb stats` shows one row per source with how many of its books are new. Import *copies*; the source keeps its file. The destination is your existing inbox folder (any top-level folder whose name is `inbox` after the `NN_` prefix, e.g. `00_Inbox`), or `_inbox/` if there is none. Unreadable and `.part` files are refused.

## Walkthrough 4: let a local model do the reading

Everything above works with no model. If you run [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server` on the Mac, the workflow can propose answers to the three chores that still need a human per book — a genre for a new book, a real title and author for a file named `7_815203.epub`, and which author folders are one person spelled differently — plus one new view, *what else do I have like this*. The model never moves a file: every proposal is a row, and only ↩ acts, through the same journaled batch as everything else.

Set **Model server** in the workflow configuration to the server's URL (`http://127.0.0.1:8080`), then:

```
kb model                                      what the server serves · ✓ marks the current choices
   ↩ on a model → Use … for the oracle        writes the choice into the workflow configuration
kb classify                                   Ask the model about 12 inbox books and 4 unnamed files · ↩ asks in the background
   …notification: Asked about 12 books: 9 genres suggested, 2 without an answer, 1 skipped
kb classify                                   Dhalgren   author ? · fiction/sci-fi? · …   ← the ? is a suggestion
   Accept 9 suggested genres                  ↩ files every listed book under its suggestion, one undoable batch
   ↩ on Dhalgren                              the picker lists the suggestion first
kb fix                                        Penhale, Ivor - Table Napkin Folding.pdf   move · suggested title and author · …
                                              Merge 3 author folders into Delany, Samuel R.   ↩ moves 7 books · ⌥↩ reveals
kb fix 7_815203                               Dismiss suggestions for this book
```

What the model sees is the book's metadata, its `dc:subject`/`dc:description` (fb2: `genre`/`annotation`), the first two thousand characters of its text and, for a genre question, the list of known genres; `kobold ask --dry-run` prints exactly that. Every answer is constrained by a JSON schema (a genre is one of the known genres or `none`), stored in `oracle.tsv` keyed by content fingerprint and the hash of the evidence, and kept until the evidence changes, so re-indexing, renaming or moving a book costs nothing. Setting a genre, applying a suggested rename, or dismissing a book forgets its answers. `oracle.log` keeps the last 500 exchanges for *why did it say that*.

Suggested operations in `kb fix` apply only when you ↩ on their row (or name the file on the command line): **Fix all**, a bare `kobold fix` and `--dry-run` stay certain-only. A merge moves books from the alias folders into the canonical one and renames them to the canonical spelling, and the alias is written down in `authors.tsv`, so a book whose embedded author still reads the alias spelling stays home from then on; undoing the merge forgets the alias again. Folders that are plainly one person — the same surname with and without a middle name or initial (`Delany, Samuel` / `Delany, Samuel R`), a lifespan suffix (`Illich, Ivan, 1926-2002`), or an inverted twin that holds fewer books (`Ann, Leckie` / `Leckie, Ann`) — are offered as merges even with no model; the model adds the cases a rule can't see, such as `Азімов` and `Азимов`.

Embeddings need a model made for them, served with `--embeddings`; the chat model that answers the questions cannot do it (the server answers 501 if asked), and a chat server started with `--embeddings` would pool its hidden states into poor vectors. The usual setup is a second server on its own port, pointed at by **Embedding server**:

```sh
llama-server --hf-repo Geofront/BGE-M3-GGUF --hf-file BGE-M3-Q8_0.gguf \
  --embeddings --alias bge-m3 -c 2048 -b 2048 -ub 2048 -ngl 99 --port 8081
```

Any multilingual embedding model with a GGUF does; the batch sizes matter because an embedding model takes each input in one micro-batch, and the workflow sends up to 1 500 characters. If the server wants a key — `--api-key`, or `LLAMA_API_KEY` exported in the shell that started it — put it in **Model server API key**.

With an embedding model chosen too (**Use … for embeddings** in `kb model`), `↩` on *Embed N new books* in `kb model`, `kb stats` or `kb like` embeds the library in the background, and then:

```
kb like dhalgren              Like Dhalgren                 Delany, Samuel R. · 01_Fiction/02_Sci-Fi/…
                              Nova                          91% · Delany, Samuel R. · 1968 · EPUB 400 KB · …   ↩ opens
                              Babel-17                      88% · …
kb like                       seed = the book KOReader opened last (history.lua), else the newest book
```

Vectors live in `vectors.db` keyed by model, so switching the embedding model keeps the old set until the new one is complete. Similarity is cosine over stored vectors, computed when a vector is stored, never while you type.

Turn on **Ask and embed on update** in the configuration and `kb update` does all of this by itself after indexing: the name and genre questions for books without an answer, the author question when the folders changed, and embedding for books without a vector — a notification per step, none when there is nothing new. Off by default, so indexing stays as fast as it is.

Nothing in the UI mentions the model until **Model server** is set; a server that does not answer shows as *Model not reachable at …* in `kb classify`, `kb fix` and `kb model`.

### Running llama-server

The workflow only needs an OpenAI-compatible `/v1/chat/completions` that honours `response_format` with a JSON schema; any recent `llama-server` does. Two ways to run it:

```sh
llama-server --hf-repo <org>/<model>-GGUF:Q4_K_M --alias oracle --jinja -c 8192 -ngl 99 --port 8080
```

serves one model; **Model** in `kb model` is then its alias. Or start the server with no model and a preset file, and it runs in *router mode*: every `[section]` is a model it can serve, loaded the first time a request names it:

```ini
[oracle]
hf-repo = <org>/<model>-GGUF:Q4_K_M
jinja = true
ctx-size = 8192
n-gpu-layers = 99
```

```sh
llama-server --port 8080 --models-preset ~/.config/llama.cpp/models.ini --models-max 2
```

Router mode is the comfortable one — swap models in `kb model` without restarting anything — with one thing to know: nothing is loaded until it is asked for. The first question after a start pays for loading the weights, and the very first time for downloading them into `~/.cache/llama.cpp`, which for a 20–30 B model is minutes to tens of minutes during which every request in the pass times out at 60 s and is counted as *skipped*. Wait for the download (the blob grows under `…/blobs/*.downloadInProgress`), or ask once from a terminal with `curl` before the pass, and ask again. `sleep-idle-seconds` in a preset unloads the model after that many idle seconds and brings the loading pause back on the next question; leave it out on a machine with the RAM, or expect one skipped book after each break.

Choices that matter for this workflow:

- **An instruct model, not a thinking one.** Answers are capped at 64 tokens for a genre and 256 for a title; a thinking model spends them inside `<think>` and the answer comes back empty. The workflow asks the template not to think, which the hybrid Qwen3 family respects, but a `-Thinking-` build ignores it.
- **`--jinja`.** Without it the chat template is approximated and the JSON-schema grammar fights the model more than it should.
- **Context of 8 k or so.** A question carries the book's metadata, two thousand characters of text and the genre list: 3–4 k tokens with Cyrillic text. The author question sends every author folder in the library; 8 k covers a few thousand folders.
- **Keep the embedding server separate**, as above: **Model server** on one port, **Embedding server** on the other. Pointing **Model server** at the embedding server makes every question time out, because that server never produces a chat completion.
- **Start it as a service** (`brew services start llama.cpp` with the preset in its arguments, or a launchd agent) rather than from a shell, so it is there when Alfred asks and survives a logout. A manually started copy loses the port to a service that is already listening and exits at once — check `lsof -nP -iTCP:8080 -sTCP:LISTEN` when a restart seems to change nothing.

`kb model` reads `/v1/models` of both servers, so it knows what each one *can* serve; whether a model is loaded right now is `curl localhost:8080/health` (router mode: the per-model entry in `/models`), and `oracle.log` says how long each answer took.

## KOReader users

Moves and renames also carry each book's `.sdr` sidecar along and rewrite the paths in `.adds/koreader/settings/{collection,history,bookmarks}.lua` (a `.bak` is written first) and under `.adds/koreader/docsettings/`, so highlights, progress and collections survive `kb fix`. This only works if `.adds/koreader` lives under your library root: either the root is the device itself, or your sync includes that folder.

## How it reads your folders

The folder tree is what the Kobo shows, so the tool keeps it meaning exactly one thing: **genre → author → series**.

- Genre is the first two folder levels with their order prefixes stripped: `01_Fiction/02_Sci-Fi_Fantasy/…` → `fiction/sci-fi_fantasy`. A folder that looks like an author (`Surname, Given` or `Given Surname`) ends the genre early, so `programming/Dietrich, Erik/…` is genre `programming` with the author straight under it. Books under `inbox`, `archives`, `_inbox`, `_dups`, `_trash` or `_broken` have no genre and show up in `kb inbox`.
- Author folders are `Surname, Given`. Existing folders win: if you already have `Le Guin, Ursula K.`, that spelling is reused. Aliases you have accepted through a merge (`authors.tsv`) win over the metadata: once `Delany, Samuel` is an alias of `Delany, Samuel R`, every book that names the shorter form files under the longer one.
- A series gets its own folder only when the library holds more than one book of it.
- Canonical file name: `Surname, Given - Title (Series 03) (Year).epub`, FAT-safe, ≤ 255 bytes.
- Genres live in `genres.tsv` keyed by a content fingerprint, so they survive renames and moves. `kb update` bootstraps a genre for every book from its folder, never overwriting one you set.

## Where things are

Index (`library.db`, `sources.db`), `covers/`, `genres.tsv`, `authors.tsv`, the model's answers (`oracle.tsv`, `oracle.log`), `vectors.db` and the undo journal (`journal.jsonl`) live in Alfred's workflow data folder, `~/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobold`, which survives workflow updates and cache clears. Override with **Index folder**.

**Upgrading from kobo-alfred:** the workflow was called Kobo Library and its data lived under `com.anokhin.kobolib`. The first run of Kobold renames that folder to `com.anokhin.kobold`, so the index, covers and genres carry over. Workflow settings don't: Alfred keys them by bundle id, so set **Library root** (and any model settings) again. Terminal variables moved from `KOBO_*` to `KOBOLD_*`.

The index stores paths relative to the library root, so if the same tree exists in two places (the card and a synced folder, say) you can switch **Library root** between them without rebuilding.

Format support: epub and fb2 are read for metadata and cover; mobi, azw, azw3, pdf and djvu are described from their filename (libgen, Anna's Archive, `[Series №N]`, `Title - Author` and friends). `.part` files are indexed, flagged as unfinished downloads, and only ever offered to `kb trash`.

## From a terminal

The same commands, same data:

```
export KOBOLD_ROOT=/Volumes/Transcend/kobo
export KOBOLD_DATA="$HOME/Library/Application Support/Alfred/Workflow Data/com.anokhin.kobold"
uv run kobold update
uv run kobold search delany | jq '.items[].title'
uv run kobold fix --dry-run
uv run kobold fix delany
uv run kobold trash "$KOBOLD_ROOT/00_Inbox/broken.epub.part"
uv run kobold genre "$KOBOLD_ROOT/00_Inbox/nova.epub" fiction/sci-fi
uv run kobold import ~/Downloads/babel-17.epub
uv run kobold undo
uv run kobold ask [genre|name|authors] [<words>]   # --force re-asks, --dry-run prints the evidence
uv run kobold dismiss <fingerprint-or-path>
uv run kobold embed [<words>]                      # --force re-embeds
uv run kobold models
uv run kobold choose oracle|embed <model>
```

`KOBOLD_ORACLE_URL`, `KOBOLD_ORACLE_MODEL`, `KOBOLD_EMBED_URL` and `KOBOLD_EMBED_MODEL` configure the model from the terminal the way the workflow panel does; `KOBOLD_ORACLE_KEY` (and `KOBOLD_EMBED_KEY` when the embedding server has its own) is sent as a bearer token to a server started with `--api-key`.

`KOBOLD_SOURCES` takes the other sources. `search` and `genres` print Alfred's JSON; everything else prints one line and, with `--notify`, posts it as a macOS notification.

Set `KOBOLD_DATA` as above if you want the terminal and Alfred to share one index: without it the CLI defaults to `~/Library/Application Support/kobold`, a separate copy.

## When something looks off

| You see | Do |
| --- | --- |
| *No index yet* | ↩ on that row, or `kb update` |
| *Index is from an older version* | ↩ on that row: the workflow was updated and the index format changed |
| *Index is empty — is the card mounted?* | the library root is missing or empty: check the path, mount the volume, or grant Alfred Removable Volumes access |
| *Library root not mounted: …* (after `kb update`) | the **Library root** path doesn't exist right now |
| *No books found: …* (after `kb update`) | the root exists but holds no epub/fb2/mobi/azw/azw3/pdf/djvu; the message says why if it's a permissions problem |
| *Indexing is running, try again later* | wait for the notification; a stale lock expires after an hour |
| *Set KOBOLD_SOURCES, then kb update* | **Other sources** is empty |
| *No source is mounted* | plug in the drive named in **Other sources** |
| *No book selected* in the genre picker | it was opened directly; use ⇧↩ on a book or ↩ in `kb classify` |
| *Nothing to fix* | the library is clean |
| *Asking the model… a notification follows* / *The model is already being asked* | one pass runs at a time; wait for its notification. A pass that died leaves `oracle.lock` behind for an hour; delete it to go on |
| *Model not reachable at …* | start `llama-server`, or fix **Model server**; `kb model` shows whether it answers |
| every request skipped, `oracle.log` says *401* | the server wants a key: set **Model server API key** (`--api-key` or `LLAMA_API_KEY` on the server side) |
| `oracle.log` full of *timed out*, `seconds` = 60 | the model is not answering within a minute: it is still downloading or loading (router mode loads on the first request, `sleep-idle-seconds` unloads it again — see *Running llama-server*), **Model server** points at the embedding server, or the oracle is a thinking model spending the minute on reasoning; choose a plain instruct model in `kb model` |
| `oracle.log` full of *400 Bad Request* | the request names a model the server does not know (router mode: no `model` at all); pick one in `kb model`, or set `KOBOLD_ORACLE_MODEL` in the terminal |
| the terminal and Alfred disagree about what was asked | they use different data folders unless `KOBOLD_DATA` is set; each has its own `oracle.log` and `oracle.tsv` |
| `kobold embed` skips every book | the embedding server answers 501: it was started without `--embeddings`, or with a chat model; see the walkthrough |
| *No embedding model* in `kb like` | ↩ on a model in `kb model`, then **Use … for embeddings** |
| *No embeddings yet* | ↩ on that row embeds the library in the background |

## Development

```
uv run pytest
uv run ruff check && uv run ruff format --check
./build.sh                      → dist/Kobold.alfredworkflow
```

CI runs the tests on Python 3.9 and 3.13, builds the workflow and publishes it as the `latest` pre-release; a `v*` tag makes a proper release.
