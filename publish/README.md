# polymerge — source mirror

polymerge is a Discord bot that merges several players' Battle of Polytopia
screenshots of one map into a single composite showing everyone's explored
territory combined.

This repository is a **read-only mirror of the source that handles your
screenshots**, published so that what the bot does with them is something you
can check rather than take on trust. It is updated automatically on every
change; each commit message names the commit it came from.

## What's here

| file | what it is |
|---|---|
| `polybot.py` | the Discord side: receives commands, downloads the screenshots, posts the result |
| `polymerge.py` | the image processing, run as a separate process by `polybot.py` |
| `requirements.txt` | the pinned dependencies |

## What's not here, and why

This is not a buildable checkout. Three things are left out:

- **The test corpus.** It is 75 real screenshots from real games, and many carry
  a player's handle in the game's own HUD. Publishing them to demonstrate that
  screenshots aren't kept would be a poor joke.
- **The board renders and sprites**, which are the game's art rather than mine.
- **Everything else in the working repo** — scratch tooling, notes, and the
  development history.

None of it is needed to read what happens to an image.

## The part people ask about

**What the bot receives.** Discord bots don't work by being handed only the
messages addressed to them. polymerge holds the *message content* intent, which
it needs in order to see attachments on other people's messages when you mark
them with 🗺️ — and with that intent, Discord delivers every message and
attachment in every channel the bot can see, asked for or not. So I'm not going
to tell you the bot *can't* see your screenshots. It receives what the channel
shows it, the same as every other member of that channel.

**What it does with them.** This is the part the code settles:

- A screenshot is only ever written to disk during a merge you ran. In
  `polybot.py`, `attachment.save()` appears exactly once, inside `do_merge`.
- It is written to a scratch directory from `tempfile.mkdtemp`, which is removed
  by `shutil.rmtree` in a `finally` block — so it goes away when the merge ends,
  whether the merge worked, failed, or timed out.
- **No message text or screenshot leaves the bot, except the finished map going
  back to the channel you ran the merge in.** `polybot.py` imports one
  non-standard library, `discord`. `polymerge.py` imports two, `cv2` and
  `numpy`. There is no HTTP client, no socket, no telemetry, no analytics, and
  no third-party service anywhere in either file. Check the import lines at the
  top of each; they are short.
- There is no database and no storage of any kind. The container it runs in
  mounts no volumes, so a restart leaves nothing behind.

**What is recorded.** The machine's console log gets a line per merge: which
channel it ran in, who asked, how many screenshots, and the merge's own
diagnostics — which include the upload filenames of any screenshot the merge
couldn't place. That is how the bot gets debugged when someone reports it
misbehaving. It stays on the host, it goes to nobody, and it doesn't include
your screenshots — but it isn't nothing, so I'd rather say it here than have you
find it out.

**What you're still trusting me for.** I run the machine. Nothing in a source
mirror can prove that the code here is the code running, or that I haven't
changed it since — so if it matters to you, the honest summary is that you're
trusting the operator, and this mirror only narrows what you have to take on
faith. The commit trail is the part you can audit.

Worth saying plainly: a screenshot you post in a game channel is already visible
to everyone in that channel, and to Discord. The bot isn't what exposes it.

## Questions

Open an issue here, or ask in the server where you use the bot.
