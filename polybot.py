"""Discord front end for polymerge.py.

Screenshots can reach a merge two ways:

    !merge 20      <- with the screenshots attached to that same message

or, when players just post their shots individually into a thread as they
take them (likely interleaved with unrelated chatter/images), react to each
one with MARK_EMOJI to opt it in, then run `!merge 20` (or `/merge`) with no
attachments. The bot scans the channel/thread history for MARK_EMOJI'd images
and, after a successful merge, reacts DONE_EMOJI on each source message so a
later merge in the same thread doesn't pick them up again. The reactions *are*
the state -- the bot itself remembers nothing between commands, matching the
same-message path below.

There are two front ends, and they differ only in how the options arrive:
`!merge [size] [layers...]` parses free text, while `/merge` takes the same
two as typed options that Discord validates and describes at the point of
typing. Both call do_merge, so there is one queue, one estimate and one set of
channel copy however a merge was asked for.

`/merge` deliberately takes **no attachments**. A slash command has no
variadic attachment option, so offering that path would mean MAX_SHOTS
separate slots in the picker and one file dialog each; `!merge` keeps the job,
where dropping four files onto one message already works well. Since the
reaction workflow is the one most players use, this costs the common case
nothing.

Two things slash commands do not change, recorded because both look like they
should. Guild operators still grant the same REQUIRED_PERMS in the same
channels -- the composite is an ordinary channel message either way; what
changes is that a missing permission becomes *sayable*, since an interaction
reaches the bot whatever the channel overwrites say. And the message_content
privileged intent is still required, because the MARK_EMOJI scan reads
attachments off other people's messages.

The bot downloads the resolved images to a scratch directory, shells out to
polymerge.py, and posts merged.png back.

Three things about this design are deliberate.

--map-size is optional, and leaving it off measures the board rather than
guessing at it: polymerge counts the tiles across a shot that spans the board,
and refuses when no shot can answer. It never falls back to a default and never
snaps a measurement to the nearest supported size, because getting the size
wrong does not look like a failure -- the board silhouette still fits the
template, so anchoring "succeeds", but every tile lands out of phase, the fog
test matches nothing and calls the whole board explored, and the merge quietly
degenerates. polymerge's --min-fog-lock guard catches it, and its message is
passed straight through to the channel. A measured size is reported back in the
caption, since it is the one input the player would otherwise have supplied, and
the one whose being wrong ruins a merge invisibly.

polymerge runs as a *subprocess*, not an import. It is a CLI: it reads
sys.argv, and it reports every failure by raising SystemExit with a message.
Importing it would mean catching SystemExit all over and sharing a process with
OpenCV for a ~20s CPU-bound job that would block the event loop. A subprocess
gets isolation, a timeout that actually works, and stdout/stderr for free.

Reactions, not a remembered session, are what let screenshots posted as
separate messages be collected. An earlier design considered having the bot
accumulate a session across multiple messages (a `!merge start` / `!merge
done` window) and rejected it in favor of one-message-in/one-composite-out;
tracking marks via reactions keeps that property -- there is still no bot-side
session state, no window to leave open by accident, and no risk of an
unrelated image in the thread getting swept in, since only images someone
explicitly marked ever qualify.
"""

import asyncio, collections, os, pathlib, re, shutil, statistics, sys, tempfile, time
import typing

import discord
from discord import app_commands
from discord.ext import commands

HERE = pathlib.Path(__file__).resolve().parent
POLYMERGE = HERE / "polymerge.py"

# Board sizes the bot offers, and the name Polytopia gives each. Kept in step
# with polymerge's MAP_SIZE_CHOICES -- 30x30 ("massive") is deliberately not
# here yet; see the note on MAP_SIZE_DEFERRED there.
MAP_SIZES = (11, 14, 16, 18, 20)
MAP_SIZE_NAMES = {11: "tiny", 14: "small", 16: "normal", 18: "large",
                  20: "huge"}

# The optional layers a player can ask for, and what the bot passes through as
# --overlays. Every one of them is opt-in: a merge nobody asked a question of
# should hand back the map as the game draws it, and a layer is only wanted by
# someone who knows what they are reading it for. `shade` was on by default
# once, which also meant every player had to be told about `noshade` -- a
# second thing to learn in order to get back to plain output. An empty default
# costs the player who wants shading one word and costs everyone else nothing.
OVERLAY_NAMES = ("shade", "grid", "spawns", "push")
OVERLAY_DEFAULT = frozenset()
# One line each, for `!merge help`. Keyed by layer so the help cannot list a
# layer the parser does not accept, or miss one it does.
OVERLAY_HELP = {
    "shade": "checkerboard shading on fog tiles",
    "grid": "tile grid lines on the full map",
    "spawns": "the default spawn zones on fog tiles (for most map types)",
    "push": "default push direction arrows on every tile",
}
# Typed by players, so accept the obvious synonyms rather than making them
# guess the one word that works.
OVERLAY_ALIASES = {"shading": "shade", "shaded": "shade", "checker": "shade",
                   "checkerboard": "shade", "gridded": "grid", "lines": "grid",
                   "spawn": "spawns", "spawnzones": "spawns",
                   "zones": "spawns", "arrows": "push", "pushes": "push",
                   "pushdirections": "push"}
# cv2.imread's formats, restricted to what phones and tablets actually produce.
# The test sets alone cover all three (jpg/png/webp), deliberately.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

MAX_SHOTS = 8               # a merge should be no more than 6 shots (2 per player in 3v3)
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
# Discord's free-tier attachment limit: 20 MB as of August 2026, up from 8.
#
# Deliberately one fixed number and not the guild's real limit, which is higher
# on a boosted server and which discord.py would hand over as
# Guild.filesize_limit. One bot serves several servers, and this figure is
# channel-facing copy -- reading it per guild would have the bot quote a
# different limit in each one. Being conservative on a boosted server costs a
# re-encode nobody notices.
#
# MB, not MiB, on two counts. The player-facing message below divides by 1e6,
# so MiB would report this back as "21 MB"; and erring low costs at most that
# same needless re-encode, where erring high costs a failed upload after the
# merge has already run. The FAQ's caveat about the limit now being checked
# before compression rather than after does not apply to a bot, which uploads
# exactly the bytes it has.
MAX_UPLOAD_BYTES = 20 * 1000 * 1000
MERGE_TIMEOUT_S = 300       # a 4-shot merge is ~15-20s; this is a hang guard
# Longest wait a merge will be allowed to join, in seconds. Merges serialize
# behind one semaphore across every guild and nothing caps the queue, so
# without this a player can be committed to a wait far longer than the merge
# is worth, having been shown a number only after they were already in it.
#
# 10 minutes is about sixteen 4-shot merges, or two hung ones running to
# MERGE_TIMEOUT_S. It is a bound on the absurd rather than a scheduling
# policy -- the estimate behind it is rough by construction (board content
# matters nearly as much as shot count) and should not be tuned as if it were
# not.
MAX_QUEUE_WAIT_S = 600
MAX_MSG_CHARS = 1900        # Discord's limit is 2000; leave room for framing

# React on a screenshot to opt it into the next merge. Overridable by whoever
# runs the bot (POLYMERGE_MARK_EMOJI=...) rather than per-channel: a per-channel
# setting would need somewhere to persist channel_id -> emoji, and the whole
# point of tracking marks in reactions is that the bot stores nothing.
MARK_EMOJI = os.environ.get("POLYMERGE_MARK_EMOJI") or "🗺️"
# Bot reacts with this once a shot has been merged. A custom emoji is written
# "<:name:id>" and works here unchanged, but only if the bot can reach it: one
# uploaded to this server, or an app-owned emoji. A guild emoji from *another*
# server additionally needs the bot in that server and USE_EXTERNAL_EMOJIS.
DONE_EMOJI = os.environ.get("POLYMERGE_DONE_EMOJI") or "✅"
# Flavour. Unlike MARK_EMOJI/DONE_EMOJI above, nothing keys on these -- they
# decorate messages and the bot never reads them back, so a deployment that
# cannot reach them can blank any of them out (POLYMERGE_HAPPY_EMOJI=) without
# breaking anything.
#
# These are *application* emoji, not guild ones, so the reachability caveat on
# DONE_EMOJI does not apply to them: they render in every server the bot is in
# and in DMs, with no USE_EXTERNAL_EMOJIS needed anywhere.
#
# Placement is per *sentence*, not per message: these strings mostly read
# "[what happened]. [what to do about it].", and a glyph parked at the very end
# would attach itself to the advice rather than to the news. So the emoji
# trails the sentence it is about, after that sentence's full stop.
HAPPY_EMOJI = os.environ.get("POLYMERGE_HAPPY_EMOJI") or "<:wolfyay:1541488102114328586>"
SAD_EMOJI = os.environ.get("POLYMERGE_SAD_EMOJI") or "<:wolfconfused:1541488101241782354>"
CREDIT_EMOJI = os.environ.get("POLYMERGE_CREDIT_EMOJI") or "<:arcticwolves:1541488099010281492>"
# Carried by both of the pre-merge messages, and deliberately the same one
# for both: the queue notice is *edited* into the ack when the slot frees
# (see starting_text), so a player watching that message sees the text
# change under a wolf that stays put, then HAPPY_EMOJI when the composite
# lands. Different emoji either side of the edit would read as two events.
WAIT_EMOJI = os.environ.get("POLYMERGE_WAIT_EMOJI") or "<:wolfwait:1541528693430681660>"
HISTORY_LIMIT = 500         # how far back into the channel/thread to look for marks

# One merge at a time. Each is CPU-bound and pegs a core for ~20s, so running
# several concurrently makes all of them slower rather than any of them faster.
MERGE_LOCK = asyncio.Semaphore(1)

# Queue bookkeeping, so someone waiting behind another guild's merge can be told
# where they are rather than merely that they are waiting. asyncio.Semaphore
# exposes no waiter count (._waiters is private and not safe to read), so the
# queue is tracked here instead. The event loop is single-threaded and none of
# these is read across an await from its own write, so plain module state is
# sufficient and needs no lock of its own.
#
# _waiting holds one _Queued per merge waiting, carrying the *shot count* rather
# than just a placeholder, so each can be charged its own size.
#
# It used to hold bare shot counts, on the reasoning that only the sum is ever
# read and so entries with equal counts are interchangeable. That stopped being
# true when the queue notice started updating live: a waiting merge now has to
# find its own position in this list, which a bare int cannot supply -- two
# 3-shot merges are the same int and different places in the queue. Identity is
# the whole point of the record, so remove by identity, never by value.
_waiting = []               # _Queued, in queue order, not yet started
_running_shots = None       # shot count of the in-flight merge, None when idle
_running_since = None       # time.monotonic() when the in-flight merge began


class _Queued:
    """One merge waiting for the slot, and the notice telling its player so.

    `notice` is the channel message to keep up to date as merges ahead of this
    one finish, or None when nobody was told to wait (the queue was empty, so
    the merge went straight to an ack). `shown` is the text last written to it,
    so an unchanged render costs no API call -- see refresh_queue_notices."""

    __slots__ = ("shots", "notice", "shown")

    def __init__(self, shots):
        self.shots = shots
        self.notice = None
        self.shown = None


# Slot seconds for a merge of n screenshots: t = MERGE_FIXED_S + MERGE_PER_SHOT_S * n.
# The intercept is real but small -- template load, process start and output
# encode do not scale with the shot count -- and it is what the old
# purely-proportional model had no way to express.
#
# Measured by merging the *same* board's first 1..k shots, which is the only way
# to separate shot count from board content: archers_test2 fits 1.83 + 4.38n,
# test_screenshots 1.47 + 4.61n, goon_test 1.22 + 3.65n (that last is 18x18 and
# cheaper per shot, which is why the seed sits nearer the 20x20 pair -- reading
# a little high is the safe direction for a wait).
#
# Do *not* re-derive these by regressing `tools/baseline.py --jobs 1` across the
# corpus. It looks like the obvious fit and it is confounded: the 2-shot sets are
# also the cheaper boards, so board content masquerades as shot count and the
# intercept comes out at -2.3s. It fits n = 2..5 well (R^2 0.92) and is nonsense
# outside it, predicting 42.5s at MAX_SHOTS against this seed's 36.7s.
#
# Two things this seed is not. It is the polymerge subprocess alone, where the
# bot's own slot hold also covers the attachment downloads, so it reads slightly
# low. And it was measured on a development machine, not on the deploy host --
# the container carries no assumption about what it lands on. Both are absorbed
# by the speed factor below.
MERGE_FIXED_S = 1.5
MERGE_PER_SHOT_S = 4.4
_speed = collections.deque(maxlen=10)   # observed / predicted, one per merge


def template_for(map_size):
    """The blank render for a board size, matching polymerge's template_path_for.

    Overlays/<name>-blank.png is the only source there is, and deliberately:
    a fallback render would engage silently and merge against different fog art
    rather than say anything. The callers' .exists() checks report a missing
    render instead.

    An unsupported size falls through to a name that cannot exist, so the
    preflight check refuses it rather than raising here."""
    name = MAP_SIZE_NAMES.get(map_size, str(map_size))
    return HERE / "Overlays" / f"{name}-blank.png"


def parse_overlays(words):
    """Turn the words after `!merge [size]` into (layers, unrecognised).

    Bare words add a layer. Order does not matter and case does not either,
    because this is typed into a chat box rather than a shell.

    Nothing is on by default, so `no`-prefixed words and `plain` have nothing
    left to remove. They are still parsed, and deliberately no longer
    advertised: they were needed only while `shade` was on by default, and a
    player who learnt `noshade` then should get a merge rather than an error
    now. Removing them would turn a once-correct command into an unrecognised
    word."""
    layers = set(OVERLAY_DEFAULT)
    unknown = []
    for raw in words:
        w = re.sub(r"[^a-z]", "", raw.lower())
        if w in ("plain", "bare", "clean", "nothing"):
            layers.clear()
            continue
        off = w.startswith("no") and w[2:] not in ("", "ne")
        stem = w[2:] if off else w
        stem = OVERLAY_ALIASES.get(stem, stem)
        if stem not in OVERLAY_NAMES:
            unknown.append(raw)
            continue
        layers.discard(stem) if off else layers.add(stem)
    return layers, unknown


def safe_name(index, filename):
    """A collision-free, traversal-free name that still reads like the original.

    Attachment filenames come from the user, so they cannot be joined onto a
    path as-is. Two attachments can also legitimately share a basename, and
    polymerge keys its per-image dicts on basename -- identical names would
    silently collapse two shots into one. The index prefix prevents both.
    """
    stem = pathlib.Path(filename).stem
    ext = pathlib.Path(filename).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem)[:40] or "shot"
    return f"{index:02d}_{stem}{ext}"


def tail(text, limit=MAX_MSG_CHARS):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "...\n" + text[-limit:]


def merge_speed():
    """How much slower this host runs than the one the seed was measured on.

    One scalar rather than a re-fitted MERGE_FIXED_S and MERGE_PER_SHOT_S,
    because those two describe the *algorithm* and the algorithm is the same
    wherever the container lands -- what is genuinely unknown is the host's
    speed. That matters practically: a single factor is learnable from the very
    first completed merge at any shot count, where fitting both terms needs
    merges at two or more distinct counts before it means anything, and fits
    them badly from ten noisy samples even then.

    The median rather than the mean, because the samples have a long tail on one
    side only: a merge can be arbitrarily slow (a fog-heavy board, a host under
    load, a hang that runs to MERGE_TIMEOUT_S) and cannot be faster than the
    work. Averaged, one clamped timeout sample nearly doubles every estimate for
    the next ten merges; a median outvotes it from the third sample on. The
    clamp at the sampling site still earns its place, since with one sample the
    median *is* that sample.

    1.0 until the first real merge has been timed, i.e. trust the seed."""
    return statistics.median(_speed) if _speed else 1.0


def merge_estimate(n_shots):
    """Rough seconds of slot time for a merge of n screenshots."""
    return merge_speed() * (MERGE_FIXED_S + MERGE_PER_SHOT_S * n_shots)


def wait_estimate(ahead):
    """Rough seconds before a merge queued right now could start.

    `ahead` is the shot counts of the merges already waiting, so each is
    charged its own size. Charging them all at the asking merge's size was
    wrong in both directions the moment two differently-sized merges queued up.

    The in-flight merge is charged only its *remaining* time, which is the part
    worth getting right: counting a nearly-finished merge as a whole one
    overestimates by up to a full merge, and that is exactly the case a player
    sees most often."""
    seconds = sum(merge_estimate(n) for n in ahead)
    if _running_since is not None:
        seconds += max(0.0, merge_estimate(_running_shots)
                       - (time.monotonic() - _running_since))
    return seconds


def queue_notice_text(rec):
    """What to tell the player waiting at `rec`, or None once it is their turn.

    The position is read live out of _waiting, so this is re-rendered rather
    than stored: the whole point is that "queued behind 3" becomes "behind 1"
    without the player having to ask."""
    try:
        ahead_recs = _waiting[:_waiting.index(rec)]
    except ValueError:
        return None                     # already left the queue
    ahead = len(ahead_recs) + (1 if MERGE_LOCK.locked() else 0)
    if not ahead:
        return None
    seconds = wait_estimate(r.shots for r in ahead_recs)
    return (f"Queued behind {ahead} merge{'' if ahead == 1 else 's'} -- "
            f"starting in {human_wait(seconds)}. {WAIT_EMOJI}")


async def refresh_queue_notices():
    """Re-render every waiting merge's notice, after the queue has moved.

    Driven by the queue changing rather than by a timer: the only moments the
    numbers move are a merge finishing or joining, so there is nothing for a
    poll to catch in between.

    Best-effort throughout, the same posture as the DONE_EMOJI reactions -- a
    notice that cannot be edited (deleted message, permission withdrawn
    mid-merge) must never sink the merge that is about to run.

    Editing only on a *changed* render is what keeps this clear of Discord's
    per-channel edit rate limit without needing a throttle of its own:
    human_wait rounds to 5-second buckets under a minute and to whole minutes
    above, so a queue that has not visibly moved costs no API calls at all."""
    for rec in list(_waiting):
        text = queue_notice_text(rec)
        # None means this merge has reached the front, and its own acquire
        # writes starting_text() over the notice a moment later -- so leaving
        # it alone here is right, not an omission. Editing it to "your turn"
        # first would put two messages where the player needs one.
        if rec.notice is None or text is None or text == rec.shown:
            continue
        try:
            await rec.notice.edit(content=text)
            rec.shown = text
        except discord.HTTPException:
            pass


def human_wait(seconds):
    """A duration a player can read, without overpromising precision.

    The estimate is an average over past merges, so reporting it to a tenth of
    a second would claim an accuracy it does not have. The cut is at 55s rather
    than 60 so the seconds form never rounds up to a bare "60s"."""
    if seconds < 55:
        return f"about {max(5, int(round(seconds / 5)) * 5)}s"
    return f"about {seconds / 60:.0f} min"


def emoji_key(e):
    """A comparison key for a reaction emoji, ignoring presentation selectors.

    Many emoji have both a bare and a U+FE0F ("render as emoji") form, and
    which one arrives depends on the client that sent the reaction -- 0x1F5FA
    vs 0x1F5FA,0xFE0F for the map. An exact == against one spelling silently
    misses the other, and the symptom is the worst kind: the user sees their
    reaction sitting there and the bot reports finding no screenshots.
    """
    return str(e).replace("\uFE0F", "")


def emoji_debug(e):
    """Console-safe rendering of an emoji: codepoints, not the glyph.

    A Windows console is often cp1252, where printing an emoji raises
    UnicodeEncodeError -- inside a command that surfaces as the command
    failing, which is a spectacularly misleading way to learn about a
    logging bug. Custom emoji ("<:name:id>") are ASCII and print as-is.
    """
    s = str(e)
    if s.isascii():
        return s
    return "+".join(f"U{ord(c):04X}" for c in s)


async def collect_marked_shots(channel, limit=HISTORY_LIMIT):
    """(message, attachment) pairs for images someone reacted MARK_EMOJI on,
    oldest first, skipping any the bot has already reacted DONE_EMOJI to (a
    prior merge already consumed them). Reaction state, not the bot process,
    is what makes this idempotent across repeated merges in one thread.
    """
    pairs = []
    scanned = img_msgs = 0
    barren = 0          # marked, but nothing usable on it
    seen = {}
    # Deliberately NOT oldest_first=True. With no `after`, discord.py turns
    # that into "start at the beginning of the channel and walk forward", so
    # limit=500 returns the *first* 500 messages the channel ever had, which
    # is no good for long game threads. Take the
    # most recent `limit` instead, then reverse so shots still merge in
    # posting order.
    recent = [m async for m in channel.history(limit=limit)]
    for message in reversed(recent):
        scanned += 1
        images = [a for a in message.attachments
                  if pathlib.Path(a.filename).suffix.lower() in IMAGE_EXTS]
        if not images:
            # Someone marking a text message or a PDF should hear about it --
            # silently ignoring it looks identical to the bot being broken.
            if any(emoji_key(r.emoji) == emoji_key(MARK_EMOJI)
                   for r in message.reactions):
                barren += 1
            continue
        img_msgs += 1
        for r in message.reactions:
            seen[emoji_debug(r.emoji)] = seen.get(emoji_debug(r.emoji), 0) + 1
        marked = any(emoji_key(r.emoji) == emoji_key(MARK_EMOJI)
                     for r in message.reactions)
        consumed = any(emoji_key(r.emoji) == emoji_key(DONE_EMOJI) and r.me
                       for r in message.reactions)
        if marked and not consumed:
            pairs.extend((message, a) for a in images)

    # "It didn't find my reactions" has several very different causes -- wrong
    # channel, out of history range, or an emoji that merely looks right. This
    # line separates them without guessing.
    print(f"scan #{channel}: {scanned} msgs, {img_msgs} with images, "
          f"reactions on those: {seen or '(none)'}, "
          f"want {emoji_debug(MARK_EMOJI)}, matched {len(pairs)}, "
          f"marked-but-empty {barren}")
    return pairs, barren


JPEG_FALLBACK_QUALITY = (95, 90, 85, 80)


def shrink_for_upload(png_path, limit):
    """A path to the composite that fits `limit` bytes, or None.

    The composite is a PNG a little under the template's own size (2880x1800 at
    20x20), and a densely-explored board makes a big one: the largest in the
    test corpus is 4.6 MB. Blowing the limit is a maddening way to fail, since
    the merge has already succeeded and taken ~20s and the player gets nothing.
    Re-encoding as JPEG rather than refusing turns that into a non-event.

    Against the current 20 MB limit nothing in the corpus comes close, so this
    should now never run. It is kept rather than deleted because every input to
    that comfort sits outside this program: the limit has moved twice, a merge
    can be posted somewhere with a lower one, and 30x30 renders at 4500x3000,
    about 2.6x the pixels of 20x20.

    Quality is chosen for fidelity first: on the largest composite in the
    corpus, quality 95 gives 1.40 MB (a 4x reduction) at a mean absolute error
    under 1/255, which is invisible on the game's flat colour art. That is so
    far inside the limit that the lower rungs should never be reached -- they
    exist only so a pathological board degrades gradually instead of failing.

    OpenCV is imported here rather than at module scope on purpose. Keeping it
    out of the bot's startup is the same instinct that makes polymerge a
    subprocess: the event loop should not be carrying it around for a path
    that almost never runs. The encode itself is CPU-bound, so callers should
    run this off the event loop."""
    import cv2
    img = cv2.imread(str(png_path))
    if img is None:
        return None
    for q in JPEG_FALLBACK_QUALITY:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        if ok and len(buf) <= limit:
            jpg = png_path.with_suffix(".jpg")
            jpg.write_bytes(buf.tobytes())
            return jpg
    return None


def dropped_shots(stdout):
    """Screenshots polymerge could not place on the board, as (count, names).

    This is the one diagnostic that has to reach the *channel* rather than the
    console. Every other failure is loud — the merge stops and says why — but
    a dropped shot still produces a perfectly good-looking composite that is
    quietly missing one player's territory. A real user hit exactly this and
    reported it as "failed to attach the oum ss"; they only noticed by eye.
    Saying "Merged 2 screenshots" when one was discarded is the bot lying."""
    for line in (stdout or "").splitlines():
        if line.startswith("DROPPED "):
            head, _, names = line.partition(":")
            n = head.split()[1].split("/")[0]
            return int(n), [s.strip() for s in names.split(",") if s.strip()]
    return 0, []


def ruins_marked(stdout):
    """How many fogged ruin tiles the composite ended up outlining.

    Unlike the fog-lock line this *is* worth telling the channel: the merge
    draws purple outlines on tiles nobody has explored, and without a word of
    explanation a player has no way to know what they mean. The per-tile
    breakdown stays on the console; only the count goes out."""
    for line in (stdout or "").splitlines():
        m = re.search(r"(\d+) marked on the composite", line)
        if m:
            return int(m.group(1))
    return 0


def ruin_sprite_missing(stdout):
    """True when the host has no ruin sprite, so no marker could be found.

    Worth a sentence for the same reason skipped_overlays is, only more so: a
    silent zero here reads as "this board has no ruins under fog", which is a
    claim about the *map* rather than about the bot, and a much stronger one
    than the truth. It means the deployment is missing Assets/ -- see the
    Dockerfile."""
    return any(line.startswith("NO-RUIN-SPRITE")
               for line in (stdout or "").splitlines())


def skipped_overlays(stdout):
    """Layers the player asked for that this board size does not have.

    Worth a sentence in the channel for the same reason the detected size is:
    a player who asked for the grid and got a composite without one would
    reasonably conclude the bot ignored them, or that the merge went wrong."""
    for line in (stdout or "").splitlines():
        m = re.match(r"NO-OVERLAY \d+: ([a-z ]+?) --", line)
        if m:
            return m.group(1).split()
    return []


def detected_size(stdout):
    """The board size polymerge measured, when it was not told one.

    Worth putting in the channel rather than only the console, unlike most
    diagnostics: the size is the one input a player would otherwise have
    supplied themselves, and it is the input whose being wrong ruins a merge
    invisibly. Stating it lets them catch a wrong board before they trust the
    composite. Returns None when the size was supplied."""
    for line in (stdout or "").splitlines():
        m = re.match(r"detected map size: (\d+)x\d+", line.strip())
        if m:
            return int(m.group(1))
    return None


def size_unconfirmed(stdout):
    """True when polymerge merged at a stated size that nothing could confirm.

    Only reachable with an explicit size: a *detected* one that then locks no
    fog is a contradiction and polymerge refuses outright, so this cannot fire
    on a bare `!merge`. It is the replay case -- the player asserted a size, and
    the fog the check compares against is not there to compare.

    Worth a sentence in the channel for the same reason dropped_shots is, and
    more urgently: the merge succeeded and looks entirely normal, and the one
    thing that could have caught a mistyped size is the thing that just came
    back empty. help_text already promises the bot says so."""
    return any(line.strip().startswith("WARNING: no shot locked onto the fog")
               for line in (stdout or "").splitlines())


def size_suspect(stdout):
    """Percent of tiles disagreeing across sources when that looked too high to
    be a right-sized merge, or None.

    polymerge's backstop for a stated size nothing else could check, and it only
    runs when size_unconfirmed is already true -- so this is the stronger half of
    the same story, not a separate one. Prefer it in the caption when both fire:
    it measures the *harm* an out-of-phase lattice does, where the other reports
    only that the usual check could not run."""
    for line in (stdout or "").splitlines():
        m = re.match(r"WARNING: (\d+)% of tiles disagree", line.strip())
        if m:
            return int(m.group(1))
    return None


def fog_lock_line(stdout):
    """polymerge prints one 'fog lock (...)' line per run: how many tiles matched
    the template's fog art, which is what says the tile lattice really lined up.

    It is no longer the first line of defence against a wrong size. polymerge's
    board-size check owes nothing to --map-size and refuses before a composite is
    ever written, wherever some shot spans the board. What is left for this
    number is the case that check abstains on -- a stated size on a board no shot
    spans -- and confirming that an ordinary merge landed."""
    for line in (stdout or "").splitlines():
        if line.startswith("fog lock"):
            return line.strip()
    return None


async def run_polymerge(workdir, image_paths, map_size, out_path, overlays=None):
    """Returns (returncode, stdout, stderr). Never raises on merge failure.

    `map_size` of None omits the flag, which asks polymerge to measure the
    board off the screenshots instead. The template goes with it: without a
    size there is no template to name, and polymerge picks its own once it has
    measured. It refuses rather than guessing when the shots cannot answer, so
    None can never become a silently wrong size.

    `overlays` is a set and is always passed explicitly by the command path --
    an empty one becomes `--overlays none`. The None default here omits the flag
    and so takes polymerge's own default, which is *not* the bot's: polymerge's
    CLI defaults to `shade` and the bot defaults to nothing (see
    OVERLAY_DEFAULT). Callers that mean "no layers" must pass the empty set.

    Nothing here special-cases a board with no fog. polymerge merges one as long
    as the size was stated rather than detected, warning on stdout that nothing
    present can confirm it -- so `!merge 16` works on a replay.

    That warning does reach the player, via size_unconfirmed and the caption --
    as does its stronger follow-on, size_suspect. They are the only evidence a
    stated size was wrong that survives to a *successful* run, so letting them
    sit unread in stdout meant the merge looked entirely normal in the one case
    the player most needed telling about."""
    layers = (None if overlays is None
              else (",".join(sorted(overlays)) if overlays else "none"))
    cmd = [
        sys.executable, str(POLYMERGE),
        *[str(p) for p in image_paths],
        *([] if map_size is None else
          ["--map-size", str(map_size), "--template", str(template_for(map_size))]),
        *([] if layers is None else ["--overlays", layers]),
        "-o", str(out_path),
        # Always on: with no Elyrion shot in the batch it detects nothing
        # (verified across every non-Elyrion test set), and with one it copies
        # the fogged-ruin markers onto the composite, which is exactly what a
        # team merging an Elyrion player's shots wants. The per-tile report
        # stays on the console with the other diagnostics.
        "--ruin-vision",
        # Same reasoning as --ruin-vision: it detects nothing when no shot
        # shows a population bar, so there is no wrong answer to guess at, and
        # a player should not have to know that the bar is owner-only to get
        # their own city's population into the merge.
        "--city-bars",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=MERGE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None, "", f"merge timed out after {MERGE_TIMEOUT_S}s"
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


intents = discord.Intents.default()
# Privileged: also has to be ticked under Bot -> Privileged Gateway Intents in
# the Discord developer portal. Without it message.content arrives empty and
# the command silently never fires.
#
# Slash commands do *not* relieve this. An interaction carries its own options,
# but collect_marked_shots reads message.attachments off arbitrary history
# messages, and this intent gates attachments exactly as it gates content -- so
# the 🗺️ scan needs it however the merge was invoked.
intents.message_content = True

# Overridable so a second instance can run in a guild that already has one
# without both answering the same message. The beta bot takes a different
# prefix (and different MARK/DONE emoji); its /merge does not collide, since
# Discord disambiguates slash commands by application in the picker.
COMMAND_PREFIX = os.environ.get("POLYMERGE_PREFIX") or "!"
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# The help command's name, kept in one place because it is interpolated into
# channel copy and into /merge's own description.
#
# It is deliberately *not* `merge-help`, which was the first name and was a
# trap: `merge` is a strict prefix of it, so typing `/merge` matched both
# commands and Enter took whichever Discord had highlighted -- which is ranked
# by a rule Discord does not document and evidently personalizes per user. That
# converges on the right answer for someone who merges often and is wrong for
# someone who has never run either, i.e. exactly the person least able to tell
# the picker mis-fired.
#
# Whether *this* name escapes the collision depends on whether the picker
# matches a substring of the command name or only a prefix: "merge" is inside
# "polymerge-help" but does not start it. That is worth testing in a real guild
# rather than assuming -- if it still collides, the fix is a name with no
# "merge" in it at all (`polyhelp`), and nothing but this constant changes.
HELP_COMMAND = "polymerge-help"

# Guild id to sync slash commands to instantly, for development. Global sync is
# what production wants -- one instance serving several guilds -- but it is not
# instant, which makes iterating on a command signature slow. Unset in
# production.
DEV_GUILD_ID = os.environ.get("POLYMERGE_DEV_GUILD")


@bot.event
async def setup_hook():
    """Register the slash commands with Discord.

    In setup_hook rather than on_ready because on_ready can fire more than once
    (any gateway RESUME after a disconnect), and syncing is a rate-limited write
    rather than something to repeat per reconnect.

    This is the one piece of *deploy-time state* the bot has: the command
    signature lives on Discord's side once synced, so a container running old
    code can leave a command shape published that it no longer implements. That
    is the same failure the Dockerfile's missing Overlays/ produced -- a
    deployment quietly disagreeing with the source -- which is why on_ready
    prints what actually synced rather than assuming it worked."""
    try:
        if DEV_GUILD_ID:
            where = discord.Object(id=int(DEV_GUILD_ID))
            bot.tree.copy_global_to(guild=where)
            synced = await bot.tree.sync(guild=where)
            print(f"synced {len(synced)} slash commands to guild {DEV_GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"synced {len(synced)} slash commands globally")
    except discord.HTTPException as e:
        # Not fatal: !merge does not need the tree, so a failed sync should cost
        # the slash commands and nothing else.
        print(f"slash command sync FAILED: {e!r}", file=sys.stderr)


@bot.event
async def on_ready():
    print(f"connected as {bot.user}")
    # Which servers/channels the bot can actually see. "Nothing happens when I
    # type !merge" is usually one of: process not running, bot not in the
    # guild, or no permission in that specific channel -- this prints enough to
    # tell those apart without guessing.
    for g in bot.guilds:
        visible = [c.name for c in g.text_channels
                   if c.permissions_for(g.me).send_messages]
        print(f"  guild {g.name!r}: can post in {visible or '(nothing!)'}")
    if not bot.guilds:
        print("  in no guilds -- the invite URL was never completed")
    # Not printed per guild, because it cannot be: whether a guild authorized
    # the `applications.commands` scope is not exposed to the bot, so "/merge
    # is missing from the picker here" is indistinguishable from a failed sync
    # from inside. A guild invited with the `bot` scope alone sees no slash
    # commands however cleanly they synced, and the fix is re-authorizing that
    # guild -- which adds the scope without kicking the bot or resetting its
    # permissions. `{COMMAND_PREFIX}merge` works either way.
    print(f"  prefix commands: {COMMAND_PREFIX}merge (always available)")


# Everything the bot actually needs in a channel, and what breaks without it.
# view_channel is first because its absence is invisible from inside the bot:
# without it no message event ever arrives, so there is nothing to log and no
# way to reply. That is the one case the console cannot distinguish from the
# process being down, which is why on_guild_channel_create below reports it.
REQUIRED_PERMS = {
    "view_channel": "see messages at all",
    "send_messages": "reply",
    "attach_files": "upload the merged image",
    "read_message_history": "find reacted screenshots",
    "add_reactions": "mark shots as merged",
}


def perm_report(channel, me):
    """Which required permissions are missing here, as a console-ready string."""
    p = channel.permissions_for(me)
    missing = [k for k in REQUIRED_PERMS if not getattr(p, k, False)]
    if not missing:
        return "all required permissions present"
    return "MISSING " + ", ".join(f"{k} (cannot {REQUIRED_PERMS[k]})"
                                  for k in missing)


class Caller:
    """Whoever asked for a merge, over either entry point.

    do_merge is shared by `!merge` and `/merge`, and the two hand it different
    objects -- a commands.Context carrying the invoking message, or an
    Interaction carrying none. This is the whole of the difference between
    them: five attributes and a send.

    On the interaction side every visible message is an ordinary channel
    message, not an interaction followup, and that is deliberate. An
    interaction token expires 15 minutes after the initial response, while a
    merge's wall clock is queue wait + downloads + merge against one semaphore
    shared by every guild -- so a busy queue can outlive the token and the
    composite would be posted nowhere, after the work was already done. Using
    the token once (to defer, inside the 3-second deadline) and never again
    makes that impossible rather than merely handled, and it is also what lets
    the queue notice below be edited for as long as the queue takes."""

    __slots__ = ("channel", "guild", "author", "attachments",
                 "_ctx", "_interaction")

    def __init__(self, channel, guild, author, attachments,
                 ctx=None, interaction=None):
        self.channel = channel
        self.guild = guild
        self.author = author
        self.attachments = attachments
        self._ctx = ctx
        self._interaction = interaction

    @classmethod
    def from_ctx(cls, ctx):
        return cls(ctx.channel, ctx.guild, ctx.author, ctx.message.attachments,
                   ctx=ctx)

    @classmethod
    def from_interaction(cls, interaction):
        # No attachments, ever: /merge is reactions-only. A slash command has
        # no variadic attachment option, so parity with !merge's drag-and-drop
        # would mean MAX_SHOTS separate option slots and one file picker each.
        return cls(interaction.channel, interaction.guild, interaction.user,
                   [], interaction=interaction)

    @property
    def can_attach(self):
        """Whether this entry point can carry screenshots on the command itself.

        True for a prefix command, false for a slash one. Player-facing copy
        keys on this rather than assuming: telling a /merge user to attach
        their shots to the command sends them somewhere they cannot go."""
        return self._ctx is not None

    def typing(self):
        return self.channel.typing()

    async def send(self, content=None, *, reply=True, **kw):
        """Post to the channel, surviving having no permission to.

        Every channel-facing message goes through this. Without it a missing
        send_messages turns into an unhandled Forbidden -- and when that
        happens inside on_command_error, the error handler itself raises, so
        the operator sees a confusing traceback instead of the actual problem.
        Only Forbidden is swallowed, and only after logging the diagnosis to
        the console; anything else propagates to the error handlers as normal.

        `reply` is honoured for a prefix command and ignored for a slash one,
        which has no invoking message to reply to."""
        try:
            send = (self._ctx.reply if reply and self._ctx is not None
                    else self.channel.send)
            return await send(content, **kw) if content is not None else await send(**kw)
        except discord.Forbidden:
            where = getattr(self.channel, "name", self.channel)
            me = self.guild.me if self.guild else None
            detail = perm_report(self.channel, me) if me else "DM"
            print(f"cannot post in #{where}: {detail}", file=sys.stderr)
            # A slash command still has one channel left when the public one is
            # shut: the interaction's own ephemeral response, which is exempt
            # from the channel's permission overwrites. This is the one thing
            # !merge can never do -- without view_channel it never even
            # receives the command -- so it is worth the extra call to tell the
            # player exactly which permission is missing rather than to say
            # nothing at all.
            await self.tell_privately(
                f"I can't post in this channel. {SAD_EMOJI} {detail}.")
            return None

    async def tell_privately(self, content):
        """Say something only the invoker sees, or nothing on the prefix path.

        Best-effort: this runs on paths that are already failing, and an
        expired or already-consumed interaction must not raise on top of the
        problem it is reporting."""
        if self._interaction is None:
            return
        try:
            await self._interaction.edit_original_response(content=content)
        except discord.HTTPException:
            pass

    async def clear_placeholder(self):
        """Drop the ephemeral "thinking" placeholder left by the deferral.

        Only the slash path has one -- `!merge` posts its ack directly and has
        nothing to clear. Best-effort for the same reason as above."""
        if self._interaction is None:
            return
        try:
            await self._interaction.delete_original_response()
        except discord.HTTPException:
            pass


@bot.event
async def on_guild_channel_update(before, after):
    """Log the moment the bot's own permissions in a channel change.

    This is the *only* thing that can be done about someone editing a
    channel's overwrites so the bot can no longer see it. Once view_channel is
    gone Discord stops delivering messages there, so the bot never receives
    the `!merge`, has no context to reply in, and cannot know anyone tried --
    the failure is unobservable from inside. Catching the permission change
    itself at least puts a timestamped line in the console naming the channel,
    which turns "the bot is ignoring us in #x" from an investigation into a
    lookup.

    Only logged when the permissions the bot actually needs changed, so
    ordinary topic and name edits stay silent."""
    if not isinstance(after, discord.TextChannel):
        return
    me = after.guild.me
    was, now = perm_report(before, me), perm_report(after, me)
    if was != now:
        print(f"permissions changed in #{after.name} "
              f"({after.guild.name!r}): {now}", file=sys.stderr)


@bot.event
async def on_guild_channel_delete(channel):
    """Also fires when the bot merely *loses sight* of a channel rather than
    the channel being deleted -- from the gateway's point of view those look
    the same. Worth a line either way, for the same reason as above."""
    if isinstance(channel, discord.TextChannel):
        print(f"no longer see #{channel.name} in {channel.guild.name!r} "
              f"(deleted, or permissions now hide it)", file=sys.stderr)


@bot.event
async def on_guild_channel_create(channel):
    """New channels are picked up live -- discord.py updates its cache from the
    gateway, so no restart is needed. What *is* worth surfacing is whether the
    bot can actually use the new channel, since a category's permission
    overwrites are inherited silently and "the bot ignores me in #new-channel"
    is otherwise indistinguishable from the bot being down."""
    me = channel.guild.me
    if isinstance(channel, discord.TextChannel):
        print(f"new channel #{channel.name} in {channel.guild.name!r}: "
              f"{perm_report(channel, me)}")


@bot.event
async def on_command_error(ctx, error):
    """discord.py swallows command errors by default, which reads exactly like
    the bot ignoring you. Log everything; only reply for real faults."""
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"command error in #{ctx.channel}: {error!r}", file=sys.stderr)
    await Caller.from_ctx(ctx).send(
        f"Command failed: `{type(error).__name__}`. {SAD_EMOJI} "
        f"See bot console.")


async def on_tree_error(interaction, error):
    """The same for slash commands, which have their own error path.

    app_commands swallows errors exactly as the prefix commands do, and for the
    same reason it is worth handling: an unreported failure is indistinguishable
    from the bot ignoring you. The reply goes out ephemerally rather than into
    the channel -- a traceback's worth of noise helps nobody but the person who
    ran it, and unlike the prefix path there is somewhere private to put it."""
    where = getattr(interaction.channel, "name", interaction.channel)
    print(f"app command error in #{where}: {error!r}", file=sys.stderr)
    text = (f"Command failed: `{type(error).__name__}`. {SAD_EMOJI} "
            f"See bot console.")
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(content=text)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


bot.tree.on_error = on_tree_error


def help_text():
    """What the bot says to someone who typed `!merge help`.

    Everything variable is interpolated rather than written out, so the text
    cannot drift from the code: the board sizes, the shot limit, the accepted
    formats, and both emoji -- which matter most, since MARK_EMOJI and
    DONE_EMOJI are overridable per deployment and hardcoding them here would
    tell users of a re-skinned server to react with the wrong thing.

    It is deliberately the *whole* help rather than a pointer to a further
    command: someone who has gone looking for help should not have to ask
    twice. That costs length -- ~1340 characters against Discord's 2000, so
    there is room for a few more bullets and no more. Check len() before
    adding one; the failure is the whole message vanishing, not a truncation.

    The layer list is built from OVERLAY_HELP rather than written out, for the
    same anti-drift reason as everything else here: a layer the parser accepts
    but the help does not name is a feature nobody can find, and a layer named
    here but not accepted is an error message the player did not earn.

    `!merge` on its own does *not* print this -- it attempts a merge, since
    that is what someone who has already attached their shots wants, and the
    size is measurable without them saying it. The two replies a lost player
    actually reaches -- an unrecognised size, and no screenshots found -- both
    name `!merge help`, so it stays one message away from anywhere someone
    gets stuck.

    Symbols the composite can contain are explained here *and*, where they are
    conditional, at the point of use -- the success caption names the ruin
    count only when there are ruins. A symbol is best explained next to the
    picture containing it."""
    sizes = ", ".join(str(n) for n in MAP_SIZES)
    fmts = ", ".join(sorted(e.lstrip(".") for e in IMAGE_EXTS if e != ".jpeg"))
    # The board size is an optional trailing word exactly like the layers are,
    # and the parser takes it in any position, so it heads the same list rather
    # than being described apart from them. Both halves are built from the
    # constants for the same anti-drift reason: a size or a layer the parser
    # accepts but the help does not name is a feature nobody can find.
    opts = (f"- `{MAP_SIZES[-1]}` sets the board size (or use {sizes}), which is "
            f"otherwise measured from the screenshots.\n"
            + "".join(f"- `{n}` shows {OVERLAY_HELP[n]}.\n" for n in OVERLAY_NAMES))
    return (
        f"Usage: `/merge`, or `{COMMAND_PREFIX}merge`. React {MARK_EMOJI} on "
        f"screenshots posted above, then run either one. `{COMMAND_PREFIX}merge` "
        f"also takes screenshots attached to its own message, which `/merge` "
        f"cannot.\n"
        f"`/merge` offers the options below as fields. With "
        f"`{COMMAND_PREFIX}merge` they are words after the command, in any "
        f"order, e.g. `{COMMAND_PREFIX}merge grid 20`:\n"
        + opts +
        f"\n"
        f"Other information:\n"
        f"- Works on up to {MAX_SHOTS} shots. Supported formats: {fmts}.\n"
        f"- After the merge runs, the bot reacts {DONE_EMOJI} on the screenshots "
        f"merged, so they won't be merged again.\n"
        f"- Screenshots should include at least two adjoining board edges.\n"
        f"- Assumes the top and bottom 15% of screenshots contain UI elements "
        f"and crops them.\n"
        f"- Fog tiles may carry purple outlines for ruins seen in Elyrion "
        f"screenshots.\n"
        f"- Shots without fog may require a board size input.\n"
        f"- The merge takes the highest-resolution shot, except it "
        f"deprioritizes tiles with village/ruin capture badges and "
        f"prioritizes tiles with city population bars.\n"
        f"\n"
        f"Credits: Made by palanq, with support from our robot overlords and "
        f"the ArcticWolves team. {CREDIT_EMOJI}"
    )


def log_invocation(caller, what):
    """One line per merge asked for, before anything that needs a permission.

    So the console can tell "the bot never received it" (nothing printed --
    almost always a missing view_channel) apart from "received it but cannot
    answer" (this line, then a MISSING report). Without it the two look
    identical from the channel.

    Slash commands narrow the first case rather than removing it: an
    interaction is delivered to the application directly, so /merge arrives
    whatever the channel overwrites say. A silent console still means a missing
    view_channel, but now only for the prefix command."""
    me = caller.guild.me if caller.guild else None
    print(f"{what} from {caller.author} in #{caller.channel}: "
          + (perm_report(caller.channel, me) if me else "DM"))


@bot.command(name="merge")
async def merge(ctx, size: str = None, *extras):
    """!merge [size] [layers...] in any order, either with screenshots attached
    to that same message, or with no attachments to merge every screenshot in
    this channel/thread that's been reacted MARK_EMOJI and not yet merged.

    This is the free-text front end. /merge below does the same job with typed
    options, and both hand off to do_merge -- so there is one queue, one
    estimate and one set of channel copy, whichever way a merge was asked for."""
    caller = Caller.from_ctx(ctx)
    log_invocation(caller, f"{COMMAND_PREFIX}merge {size} {' '.join(extras)}")
    if size is not None and size.lower() in ("help", "?"):
        await caller.send(help_text())
        return

    # The size is optional, so are the layers, and neither has to come first.
    # This is typed into a chat box rather than a shell, so `!merge grid 20`
    # has to work as well as `!merge 20 grid` -- the help says the layer words
    # go in any order, and a player will reasonably assume the number does too.
    # So the size is the first digit-only word wherever it sits, and every
    # other word is a layer. A stray *second* number is deliberately left in
    # `words`, so it falls through to parse_overlays and is reported as
    # unrecognised: `!merge 20 16` is ambiguous, and picking one silently is
    # the one failure this program cannot afford.
    #
    # None of this parsing is dead now that /merge exists, and it is not
    # duplicated there: Discord validates typed options itself, so the slash
    # path cannot reach either of the replies below.
    words = ([] if size is None else [size]) + list(extras)
    at = next((i for i, w in enumerate(words) if w.isdigit()), None)
    size = words.pop(at) if at is not None else None
    overlays, bad_layers = parse_overlays(words)
    if bad_layers:
        await caller.send(
            f"Don't know what to do with {', '.join(f'`{w}`' for w in bad_layers)}. "
            f"{SAD_EMOJI} You can add "
            + ", ".join(f"`{n}`" for n in OVERLAY_NAMES)
            + f", in any order. `{COMMAND_PREFIX}merge help` says what each "
            f"one draws."
        )
        return

    # No size given means measure it, not show help. A bare `!merge` is what
    # someone types when they have already attached their shots and expect
    # something to happen, so spending it on help made the common case cost two
    # messages. Help is still one word away, and the no-screenshots reply below
    # names it -- which is the moment a confused player actually needs it.
    map_size = None
    if size is not None:
        if not size.isdigit() or int(size) not in MAP_SIZES:
            listed = [f"`{n}`" for n in MAP_SIZES]
            await caller.send(
                f"`{size}` is not a supported board size. {SAD_EMOJI} Use "
                + ", ".join(listed[:-1]) + f" or {listed[-1]}"
                + f", or just `{COMMAND_PREFIX}merge` to work it out from the "
                f"screenshots. `{COMMAND_PREFIX}merge help` explains the rest."
            )
            return
        map_size = int(size)

    await do_merge(caller, map_size, overlays)


@bot.tree.command(
    name="merge",
    # Names the help command, because the picker shows this line while someone
    # is typing `/merge` -- which is where a player who needs the instructions
    # actually is. That is most of the discoverability the help command gives
    # up by not being called `merge-something`, bought back for nothing.
    description="Merge screenshots reacted " + MARK_EMOJI
                + f" into one map -- /{HELP_COMMAND} explains",
)
@app_commands.choices(size=[
    app_commands.Choice(name=f"{n}x{n} ({MAP_SIZE_NAMES[n]})", value=n)
    for n in MAP_SIZES
])
@app_commands.describe(
    size="Board size. Leave blank to measure it from the screenshots.",
    **{n: OVERLAY_HELP[n].capitalize() for n in OVERLAY_NAMES},
)
async def merge_slash(interaction: discord.Interaction,
                      size: typing.Optional[app_commands.Choice[int]] = None,
                      shade: bool = False, grid: bool = False,
                      spawns: bool = False, push: bool = False):
    """/merge -- the reaction workflow, with the options typed rather than parsed.

    Deliberately takes no attachments. A slash command has no variadic
    attachment option, so offering the drag-and-drop path here would mean
    MAX_SHOTS separate slots cluttering the picker and one file dialog each;
    `!merge` keeps that job, where dropping four files on one message just
    works.

    The choices and descriptions above are built from MAP_SIZES,
    MAP_SIZE_NAMES and OVERLAY_HELP for the same anti-drift reason help_text
    is: a layer the parser accepts but the UI does not name is a feature nobody
    can find, and one the UI names but the parser rejects is an error the
    player did not earn."""
    # First statement, before the history scan below: an interaction has three
    # seconds to be answered at all, and collect_marked_shots walks up to
    # HISTORY_LIMIT messages at 100 per API call before anything is sent.
    # Ephemeral because it is a placeholder rather than a message -- the real
    # ack goes to the channel, where everyone waiting on the merge can see it.
    await interaction.response.defer(ephemeral=True)
    caller = Caller.from_interaction(interaction)
    layers = {n for n, on in (("shade", shade), ("grid", grid),
                              ("spawns", spawns), ("push", push)) if on}
    log_invocation(caller, f"/merge {size.value if size else None} "
                           f"{' '.join(sorted(layers))}")
    await do_merge(caller, size.value if size else None, layers)


@bot.tree.command(name=HELP_COMMAND,
                  description="How to use the merge bot")
async def merge_help_slash(interaction: discord.Interaction):
    """The half of help_text that the option descriptions cannot carry.

    Discord renders the command and option descriptions inline as you type, so
    the board size and the layers document themselves under /merge. Everything
    else in help_text has nowhere to appear: the MARK/DONE reaction workflow,
    the shot limit, the accepted formats, the two-adjoining-edges rule, the
    crop, the ruin outlines and the credits. Hence a command of its own.

    Ephemeral: someone reading the instructions does not need to post them to
    the channel, and a game thread does not need a wall of help in it."""
    await interaction.response.send_message(help_text(), ephemeral=True)


async def do_merge(caller, map_size, overlays):
    """Run one merge and report it, however the merge was asked for.

    Shared by both front ends, which is what puts them on one queue: MERGE_LOCK,
    _waiting, _running_* and merge_speed are module state reached only through
    here, so a /merge queues behind a !merge and wait_estimate covers both. Do
    not give either front end its own path to the semaphore."""
    global _running_shots, _running_since

    if map_size is not None and not template_for(map_size).exists():
        await caller.send(f"Missing `{template_for(map_size).name}` on the bot "
                          f"host. {SAD_EMOJI}")
        return
    if map_size is None and not any(template_for(n).exists() for n in MAP_SIZES):
        await caller.send(f"No board templates on the bot host. {SAD_EMOJI}")
        return

    shots = [a for a in caller.attachments
             if pathlib.Path(a.filename).suffix.lower() in IMAGE_EXTS]
    skipped = len(caller.attachments) - len(shots)

    # Attachments on the command message itself win outright, so a quick
    # attach-and-merge never has to think about reactions. Only when there
    # are none do we fall back to scanning for MARK_EMOJI'd screenshots --
    # this is what lets a thread accumulate shots across many messages.
    source_messages = []
    barren = 0
    from_history = False
    if not shots:
        from_history = True
        try:
            pairs, barren = await collect_marked_shots(caller.channel)
        except discord.Forbidden:
            # Scanning needs Read Message History, which is easy to omit when
            # granting per-channel permissions. Name it rather than reporting
            # the generic "no screenshots found", which sends you hunting the
            # reactions instead of the permission.
            await caller.send(
                "Can't read this channel's history, so can't find reacted "
                f"screenshots. {SAD_EMOJI} Needs the Read Message History "
                "permission here."
            )
            return
        shots = [a for _, a in pairs]
        source_messages = list({m.id: m for m, _ in pairs}.values())

    if not shots:
        # The one reply a lost player is most likely to see, so it is where the
        # help gets named -- a bare `!merge` no longer prints it, and someone
        # who ran a merge with nothing marked is exactly who was looking for it.
        #
        # Both routes to the help are named, because which one is reachable
        # depends on how they got here: the slash help needs the guild to have
        # authorized slash commands at all, and `!merge help` always works.
        # Attaching is named only when it is possible -- /merge takes no
        # attachments, so telling a slash user to attach them sends them to a
        # dead end.
        attach = ("Attach them to this message, or react" if caller.can_attach
                  else "React")
        msg = (f"No usable screenshots found. {SAD_EMOJI} {attach} "
               f"{MARK_EMOJI} on screenshots posted above, then merge again. "
               f"`/{HELP_COMMAND}` or `{COMMAND_PREFIX}merge help` explains "
               f"how.")
        if barren:
            message, it = ("message", "it") if barren == 1 else ("messages", "them")
            msg += f" ({barren} marked {message} had no image on {it}.)"
        await caller.send(msg)
        return
    if len(shots) > MAX_SHOTS:
        # Easy to hit from history, since one post can carry several images.
        hint = (" Un-react some and try again." if from_history
                else " Send fewer at a time.")
        await caller.send(f"Found {len(shots)} screenshots, limit is "
                          f"{MAX_SHOTS}. {SAD_EMOJI}{hint}")
        return
    oversized = [a.filename for a in shots if a.size > MAX_ATTACHMENT_BYTES]
    if oversized:
        await caller.send(f"Too large: {', '.join(oversized)} {SAD_EMOJI}")
        return

    # Refuse a wait nobody would sit through, rather than accepting it and
    # going quiet. The queue is unbounded and merges are serialized across
    # every guild, so a busy evening can stack a wait longer than the merge is
    # worth -- and the player has no way to see the queue they are joining.
    #
    # A refusal here costs a retry; the alternative costs the same wait and
    # then delivers. Deliberately generous, and read against a rough estimate:
    # CLAUDE.md is explicit that board content matters nearly as much as shot
    # count, so this is a bound on the absurd, not a scheduling policy.
    queued_wait = wait_estimate(r.shots for r in _waiting)
    if queued_wait > MAX_QUEUE_WAIT_S:
        await caller.send(
            f"Too many merges queued right now -- yours would wait "
            f"{human_wait(queued_wait)}. {SAD_EMOJI} Try again in a few minutes."
        )
        return

    note = (f" ({skipped} non-image attachment{'' if skipped == 1 else 's'} ignored)"
             if skipped else "")
    at = f" at {map_size}x{map_size}" if map_size else ""

    # Recomputed at each use rather than built once, because the estimate can
    # move between the ack and the edit below -- most sharply over the bot's
    # first few merges, while the learned speed factor is still replacing the
    # seed, which is exactly when a queued player is watching this message.
    def starting_text():
        plural = "" if len(shots) == 1 else "s"
        return (f"Merging {len(shots)} screenshot{plural}{at}{note} -- "
                f"{human_wait(merge_estimate(len(shots)))}. {WAIT_EMOJI}")

    rec = _Queued(len(shots))
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="polymerge_"))
    # safe name -> "image 2 of 3". Deliberately a *position*, not the
    # filename the user uploaded: anything echoed into the channel is
    # attacker-controlled text, and a filename is the easiest place to hide
    # something abusive. Positions also read better when the shots came from
    # reactions scattered up a thread and nobody remembers the filenames.
    position_of = {}
    try:
        # Acquired explicitly rather than with `async with`, so this merge can
        # leave the queue the moment it stops waiting -- whether that is because
        # the slot was granted or because the wait was cancelled. An
        # `async with` gives no hook between those two.
        #
        # Joined to the queue *before* the ack is sent, so the position the ack
        # reports is read from the same list that refresh_queue_notices will
        # later re-read. Removed by identity, not by value -- see _Queued.
        _waiting.append(rec)
        try:
            # Only claim to be merging when we are. Leading with "Merging ..."
            # while the job still sits behind another guild's merge leaves a
            # queued player watching a static message that claims work is
            # happening, which reads from the channel as the bot having hung.
            # Waiting on a job in a guild you cannot see is precisely when you
            # need telling.
            queued = queue_notice_text(rec)
            rec.notice = await caller.send(queued or starting_text())
            rec.shown = queued
            # The public ack is up, so the slash command's ephemeral "thinking"
            # placeholder has nothing left to say. No-op for a prefix command,
            # which never had one.
            await caller.clear_placeholder()
            await MERGE_LOCK.acquire()
        finally:
            _waiting.remove(rec)
        held0 = time.monotonic()
        _running_since, _running_shots = held0, len(shots)
        try:
            if rec.shown is not None and rec.notice is not None:
                # The edit *is* the signal that the wait ended, so it replaces
                # the queue notice rather than adding a message. Best-effort:
                # a failed edit must never sink a merge that is about to run,
                # the same posture as the DONE_EMOJI reactions below.
                try:
                    await rec.notice.edit(content=starting_text())
                except discord.HTTPException:
                    pass
            async with caller.typing():
                paths = []
                for i, a in enumerate(shots):
                    p = workdir / safe_name(i, a.filename)
                    await a.save(p)
                    paths.append(p)
                    position_of[p.name] = i + 1

                out_path = workdir / "merged.png"
                t0 = time.monotonic()
                rc, stdout, stderr = await run_polymerge(
                    workdir, paths, map_size, out_path, overlays)
                elapsed = time.monotonic() - t0
        finally:
            # Slot-hold time, not `elapsed`: the estimate is answering "when
            # does the slot free up", and the downloads above hold it too.
            # Sub-second holds are refusals that never did any work (missing
            # template, unreadable file) -- they say nothing about how long the
            # next merge takes, and a run of them would drag every estimate
            # far too optimistic.
            #
            # Clamped, because one absurd sample poisons the next ten estimates:
            # a merge that hung until MERGE_TIMEOUT_S says nothing about how long
            # merges take, and at 300s it would land near 30x the prediction.
            held = time.monotonic() - held0
            if held > 1.0:
                predicted = MERGE_FIXED_S + MERGE_PER_SHOT_S * len(shots)
                _speed.append(min(4.0, max(0.25, held / predicted)))
            _running_since = _running_shots = None
            MERGE_LOCK.release()
            # Everyone behind this merge just moved up one. Fired rather than
            # awaited: the composite still has to be encoded and posted below,
            # and the people waiting should not be told after the person who
            # is already finished. The queue changing is the only moment these
            # numbers move, so there is nothing a poll would catch in between.
            asyncio.create_task(refresh_queue_notices())

        if rc != 0 or not out_path.exists():
            # polymerge reports every refusal by raising SystemExit with an
            # explanation (wrong map size, nothing anchorable, unreadable
            # file). Those messages are written for a human, so pass them
            # through rather than replacing them with a generic failure.
            detail = tail(stderr) or tail(stdout) or "no output"
            # polymerge only knows the index-prefixed safe names. Swap them
            # for positions before this reaches the channel, so the bot never
            # repeats a user-supplied filename. Longest first, so "10_a.jpg"
            # cannot be shadowed by a partial match on "1_a.jpg".
            for safe in sorted(position_of, key=len, reverse=True):
                detail = detail.replace(
                    safe, f"image {position_of[safe]} of {len(shots)}")
            head, _, rest = detail.partition("\n")
            # The console too, not only the channel. A refusal is the one
            # outcome that otherwise leaves no trace in the log: this path
            # returns before the fog-lock and ruin lines below, so the log shows
            # the command arriving and then nothing at all, which reads exactly
            # like the bot having silently dropped it. Whoever is reading the
            # log is usually not the player who got the message.
            print(f"#{caller.channel} merge FAILED: {head}", file=sys.stderr)
            await caller.send(
                      reply=False,
                      content=f"**Error:** {head} {SAD_EMOJI}"
                           + (f"\n```\n{rest.strip()}\n```" if rest.strip() else ""))
            return

        size_bytes = out_path.stat().st_size
        if size_bytes > MAX_UPLOAD_BYTES:
            # Re-encode rather than refuse: the merge already succeeded, so
            # don't throw it away over a few MB.
            # Off the event loop because the encode is CPU-bound.
            print(f"#{caller.channel}: composite is {size_bytes / 1e6:.1f} MB, "
                  f"re-encoding to JPEG for upload")
            smaller = await asyncio.to_thread(
                shrink_for_upload, out_path, MAX_UPLOAD_BYTES)
            if smaller is None:
                await caller.send(reply=False, content=
                    f"The merge worked but the result is {size_bytes / 1e6:.1f} MB "
                    f"and I couldn't get it under this server's "
                    f"{MAX_UPLOAD_BYTES / 1e6:.0f} MB upload limit. {SAD_EMOJI}"
                )
                return
            out_path = smaller

        # Fog lock stays on the console rather than in the channel: it is the
        # one number that distinguishes a correct merge from a silently wrong
        # one, so it is worth keeping, but it means nothing to a player.
        found_size = detected_size(stdout)
        used_size = map_size or found_size
        lock = fog_lock_line(stdout)
        if lock:
            print(f"#{caller.channel} merged {len(shots)} at {used_size}"
                  + (" (detected)" if map_size is None else "") + f": {lock}")
        for line in (stdout or "").splitlines():
            # Same console-not-channel reasoning as fog lock: which shots got
            # dropped as misanchored and what ruin markers were found matter
            # for diagnosing a merge, but are noise to a player reading the
            # channel -- the composite itself already shows the markers.
            if line.strip().startswith(("dropping ", "Elyrion ruin vision",
                                        "WARNING:")):
                print(f"#{caller.channel}: {line.strip()}")

        n_dropped, dropped = dropped_shots(stdout)
        used = len(shots) - n_dropped
        if n_dropped:
            # Positions, not filenames -- see position_of. Stated as a
            # Warning because the merge did succeed; it is just incomplete,
            # and that is the one outcome a player cannot see for themselves.
            #
            # Deliberately says what happened rather than why. Do not sharpen
            # this into a claim about the image ("does not look like a
            # Polytopia screenshot"): the commonest cause is a perfectly
            # ordinary screenshot showing only one side of the board. polymerge
            # drops a shot for several reasons and the DROPPED line does not say
            # which, so the only honest wording covers all of them. The hint is
            # the actionable half -- see the edge rule in anchor_to_template.
            nums = sorted(position_of[d] for d in dropped if d in position_of)
            if len(nums) == 1:
                which, was = f"Image {nums[0]}", "was"
            else:
                which = ("Images " + ", ".join(str(x) for x in nums[:-1])
                         + f" and {nums[-1]}")
                was = "were"
            caption = (f"**Warning:** {which} of {len(shots)} couldn't be "
                       f"placed on the board and {was} skipped. {SAD_EMOJI} "
                       f"Merged the other {used} in {elapsed:.0f}s. A "
                       f"screenshot needs two adjoining sides of the board "
                       f"in frame.")
        else:
            plural = "" if len(shots) == 1 else "s"
            caption = (f"Merged {len(shots)} screenshot{plural} in "
                       f"{elapsed:.0f}s. {HAPPY_EMOJI}")
        if map_size is None and found_size:
            # Named rather than left implicit: the size is the one input the
            # player would otherwise have supplied, and the one whose being
            # wrong ruins a merge invisibly. No alternative size is suggested --
            # listing all five buries the actual result, and naming one implies
            # the bot has a second guess when it does not.
            caption += (f" Board measured as {found_size}x{found_size}."
                        f" Remerge including map size if that's wrong.")

        # Mutually exclusive with the clause above, by construction: both of
        # polymerge's size warnings need a size the *player* stated, since a
        # detected one that then locks no fog is a contradiction it refuses on.
        pct = size_suspect(stdout)
        if pct is not None:
            # The stronger of the two, so it replaces the other rather than
            # joining it: this measured what an out-of-phase lattice actually
            # did, where the one below reports only that the usual check had
            # nothing to run on. Bold because the merge is probably wrong --
            # every other clause appended here is merely informative.
            caption += (f" **Warning:** {pct}% of tiles disagree between the "
                        f"screenshots, which usually means "
                        f"{used_size}x{used_size} is the wrong size. Check the "
                        f"map before trusting it. {SAD_EMOJI}")
        elif size_unconfirmed(stdout):
            # Says what could not be done rather than why, the same discipline
            # as the dropped-shot caption and ruin_sprite_missing. Nothing here
            # separates "no fog left on this board" from "wrong size", and
            # asserting the first would tell a player who mistyped the size
            # that everything was as expected.
            #
            # Takes no SAD_EMOJI, unlike the clause above. This is the honest
            # replay/finished-game outcome -- `!merge 16` on a board with no
            # fog left reaches here every time and nothing is wrong -- so the
            # caption keeps the HAPPY_EMOJI its base sentence already carries.
            # Same for the ruin and skipped-overlay clauses below: informative,
            # not warnings.
            caption += (f" Couldn't double-check {used_size}x{used_size}: "
                        f"nothing in these shots matched the fog art.")

        n_ruins = ruins_marked(stdout)
        if n_ruins:
            caption += (f" {n_ruins} ruin{'' if n_ruins == 1 else 's'} under fog "
                        f"(seen by Elyrion), outlined in purple.")
        elif ruin_sprite_missing(stdout):
            # Deliberately says what the bot could not do, not what the board
            # contains -- the two are easy to conflate and only one is true.
            caption += " (Ruins under fog weren't checked for on this run.)"
        gone = skipped_overlays(stdout)
        if gone:
            # Plural "boards" rather than "a {n}x{n} board" so the article
            # doesn't have to agree -- "a 11x11" and "an 18x18" both come up.
            # `gone` itself needs the same treatment: an 11x11 board is missing
            # three of the four layers, so asking for two of them at once
            # (`!merge 11 push spawns`) is a real, not hypothetical, case.
            size_txt = f"{found_size or map_size}x{found_size or map_size}"
            layer, exist, it = (("layer", "exists", "it was") if len(gone) == 1
                                else ("layers", "exist", "they were"))
            caption += (f" No {' or '.join(gone)} {layer} {exist} for {size_txt} "
                        f"boards, so {it} left off.")
        # out_path.name, not a hardcoded "merged.png": the upload-size
        # fallback above may have swapped in a JPEG, and labelling that .png
        # would hand clients a file whose extension lies about its contents.
        await caller.send(reply=False, content=caption,
                          file=discord.File(out_path, filename=out_path.name))

        # Mark history-sourced shots consumed so the next !merge in this
        # thread doesn't pick them up again. Best-effort: a missing "Add
        # Reactions" permission shouldn't fail a merge that already succeeded.
        for m in source_messages:
            try:
                await m.add_reaction(DONE_EMOJI)
            except discord.HTTPException:
                pass
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("set DISCORD_TOKEN in the environment")
    if not POLYMERGE.exists():
        raise SystemExit(f"cannot find {POLYMERGE}")
    if not any(template_for(n).exists() for n in MAP_SIZES):
        raise SystemExit(f"no board renders found in {HERE / 'Overlays'}")
    bot.run(token)


if __name__ == "__main__":
    main()
