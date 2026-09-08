# polymerge

Merges multiple Battle of Polytopia screenshots of the *same* map -- taken by
different players, at different zoom levels, on different devices -- into one
composite showing the union of everyone's explored territory.

`polymerge.py` is the CLI that does the work; `polybot.py` is the Discord front
end that drives it. This file is for **running the bot**. The development notes
are in `CLAUDE.md`, and are deliberately not shipped in the image.

## Running it

The image is published to GHCR whenever a push to `main` touches something the
image actually contains (the two scripts, `requirements.txt`, `Dockerfile`,
`.dockerignore`, `Overlays/` or `Assets/`) -- a docs-only push publishes
nothing. So a host needs
`compose.yaml` and a `.env` -- **not this repo**. The screenshots under `tests/`
carry player handles in their HUDs and stay private, which is the whole reason
distribution goes through an image.

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

There is no database, no volume and no config file: marks live in Discord
reactions and every merge runs in its own temp dir, so the container is
disposable and a restart loses nothing.

**If the GHCR package is private**, the host has to authenticate before it can
pull -- a classic-PAT with `read:packages`, or make the package public under
Packages -> polymerge -> Package settings:

```bash
echo "$PAT" | docker login ghcr.io -u <github-user> --password-stdin
```

## Discord setup

- **Message Content Intent** must be checked under Bot -> Privileged Gateway
  Intents in the developer portal. Without it `message.content` arrives empty
  and `!merge` silently never fires.
- **Channel permissions**: `view_channel`, `send_messages`, `attach_files`,
  `read_message_history`, `add_reactions`. The console names whatever is
  missing per channel. `view_channel` is the one to suspect when *nothing at
  all* is logged as someone types `!merge` -- without it no message event ever
  reaches the bot, so it cannot know it was addressed, let alone reply.

On connect the bot prints every guild it is in and every channel it can post
in, which is enough to tell "not running" from "not invited" from "no
permission here" without guessing.

## Using it

```
!merge [size] [layers...]
!merge help
```

Attach the screenshots to the `!merge` message itself, or -- when players post
shots into a thread over time -- react 🗺️ on each screenshot and then run
`!merge` with nothing attached. The bot reacts ✅ on each shot it used, so a
later merge in the same thread will not re-merge them.

- **Size** is `11`, `14`, `16`, `18` or `20`, and is the first digit-only word
  wherever it sits. **Omit it and the board is measured** off the screenshots;
  the caption reports what was measured, so a wrong board is catchable. It
  refuses rather than guessing when the shots cannot answer -- a board with no
  fog left (a replay, a finished game) cannot be measured at all, so state the
  size for those.
- **Layers** are `grid`, `shade`, `spawns` and `push`, in any order, and none
  is on by default. A layer a board size does not have is skipped and named.

Getting the size wrong is the one input that ruins a merge without looking
wrong, which is why the bot reports what it used either way.

## Configuration

All optional except the token. Set them in `.env` beside `compose.yaml`.

| variable | default | |
|---|---|---|
| `POLYBOT_DISCORD_TOKEN` | *required* | the bot token, read from `.env`. Fails at `up` with a clear message if unset. Compose maps it to `DISCORD_TOKEN` inside the container, which is the name polybot reads |
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
