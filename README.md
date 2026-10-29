# polymerge

Merges multiple Battle of Polytopia screenshots of the *same* map -- taken by
different players, at different zoom levels, on different devices -- into one
composite showing the union of everyone's explored territory.

| file | what it is |
|---|---|
| `polymerge.py` | the merge itself, a single-file Python/OpenCV CLI |
| `polybot.py` | the Discord front end; runs `polymerge.py` as a subprocess |
| `Overlays/` | blank all-fog board renders, one per board size, plus the optional decorative layers |
| `Assets/` | the Elyrion ruin sprite and the tribe head icons the merge matches against |
| `tests/` | the regression corpus: real screenshots, grouped one board per folder |
| `tools/` | development tooling -- `baseline.py` runs every test set and diffs the results |
| `shoreline/` | infers whether fogged tiles are land or water from shoreline art; kept out of the merge and the bot until it is proven reliable |
| `CLAUDE.md` | the development notes: how the pipeline works, why, and what was measured |

The board renders and sprites under `Overlays/` and `Assets/` are the game's own
art, extracted for registration; Battle of Polytopia is © Midjiwan AB.

## Running the merge locally

Python 3.12 with the pinned `requirements.txt`:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on Linux/macOS
.venv/Scripts/python polymerge.py shot1.jpg shot2.jpg --map-size 20 -o merged.png
```

- `--map-size` is `11`, `14`, `16`, `18` or `20`. Omit it and the size is
  measured off the screenshots; it refuses rather than guessing when they cannot
  answer (a board with no fog left cannot be measured, so state the size for
  replays and finished games).
- `--debug-dir debug/` writes per-tile provenance, conflicts and per-shot
  diagnostics. `--help` lists everything else.

## Running the bot

The image is published to GHCR (`ghcr.io/palanq/polymerge`) whenever a push to
`main` touches something the image contains -- the two scripts,
`requirements.txt`, `Dockerfile`, `.dockerignore`, `Overlays/` or `Assets/`. A
host needs only `compose.yaml` and a `.env`, not a checkout:

```bash
mkdir polybot && cd polybot
# copy compose.yaml from this repo next to a .env holding:
#   POLYBOT_DISCORD_TOKEN=...
docker compose up -d
```

| | |
|---|---|
| update | `docker compose pull && docker compose up -d` |
| logs | `docker compose logs -f` |
| stop | `docker compose down` |

To build it yourself instead: `docker build -t polybot .`

There is no database, no volume and no config file: marks live in Discord
reactions and every merge runs in its own temp dir, so the container is
disposable and a restart loses nothing.

## Discord setup

- **Message Content Intent** must be checked under Bot -> Privileged Gateway
  Intents in the developer portal for `!merge`. Without it `message.content`
  arrives empty and `!merge` silently never fires. `/merge` does not need it.
- **`applications.commands` scope** in the invite URL, or the slash commands
  never appear in that server. Re-authorizing an existing server with the extra
  scope does not kick the bot or reset its roles.
- **Channel permissions**: `view_channel`, `send_messages`, `attach_files`,
  `read_message_history`, `add_reactions` (and `send_messages_in_threads` for
  merges in threads). The console names whatever is missing per channel.
  `view_channel` is the one to suspect when *nothing at all* is logged as
  someone types `!merge` -- without it no message event ever reaches the bot.

On connect the bot prints every guild it is in and every channel it can post
in, which is enough to tell "not running" from "not invited" from "no
permission here" without guessing.

## Using it

```
!merge [size] [layers...]
!merge help
/merge
/polymerge-help
```

**`!merge`**: attach the screenshots to the message itself, or -- when players
post shots into a channel or thread over time -- react 🗺️ on each screenshot
and then run `!merge` with nothing attached. The bot reacts ✅ on each shot it
used, so a later merge in the same place will not re-merge them.

**`/merge`**: attach up to three screenshots directly, with size and layers as
typed options. It can also take a previous composite as `base` and update it
with the new shots. It works even in channels where the bot has no permissions
of its own.

- **Size** is `11`, `14`, `16`, `18` or `20`. **Omit it and the board is
  measured**; the caption reports what was measured, so a wrong board is
  catchable.
- **Layers** are `grid`, `shade`, `spawns` and `push`, in any order, and none
  is on by default. A layer a board size does not have is skipped and named.

Getting the size wrong is the one input that ruins a merge without looking
wrong, which is why the bot reports what it used either way.

## Configuration

All optional except the token. Set them in `.env` beside `compose.yaml`.

| variable | default | |
|---|---|---|
| `POLYBOT_DISCORD_TOKEN` | *required* | the bot token, read from `.env`. Fails at `up` with a clear message if unset. Compose maps it to `DISCORD_TOKEN` inside the container, which is the name polybot reads |
| `POLYMERGE_PREFIX` | `!` | the prefix-command prefix; give a second instance in the same server a different one |
| `POLYMERGE_DEV_GUILD` | unset | sync slash commands to this one guild id (instant) instead of globally |
| `POLYMERGE_MARK_EMOJI` | 🗺️ | react with this to opt a shot into the next merge |
| `POLYMERGE_DONE_EMOJI` | ✅ | the bot marks merged shots with it. **State, not decoration** -- it is how a later merge knows what it already used |
| `POLYMERGE_HAPPY_EMOJI` | wolf | flavor only |
| `POLYMERGE_SAD_EMOJI` | wolf | flavor only |
| `POLYMERGE_WAIT_EMOJI` | wolf | flavor only |
| `POLYMERGE_CREDIT_EMOJI` | wolf | flavor only |

The four flavor defaults are *application* emoji owned by the ArcticWolves bot
app, so they render in every server that app is in. **A different bot
application will not resolve those IDs** and will post the raw `<:name:id>`
text -- set them to your own, or to empty (`POLYMERGE_HAPPY_EMOJI=`) to drop
the decoration. Nothing reads them back, so blanking them breaks nothing.

## Development

There is no test runner with assertions; `tools/baseline.py` is the stand-in.
Capture a run, make the change, compare:

```bash
.venv/Scripts/python tools/baseline.py -o before.json
.venv/Scripts/python tools/baseline.py --compare before.json
```

`CLAUDE.md` explains what each tracked number means, which code paths the
corpus does *not* reach, and the measurements behind most of the constants in
`polymerge.py`.
