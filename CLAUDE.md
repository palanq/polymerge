# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python/OpenCV CLI (`polymerge.py`) that merges multiple Battle of
Polytopia screenshots of the *same* map — taken by different players, at
different zoom levels, different devices — into one composite showing the
union of everyone's explored (non-fog) territory. There is no package
structure and no build step: it's one script plus the blank "all-fog" board
renders it registers screenshots against, one per board size.

Layout:

```
polymerge.py            the whole program
polybot.py              Discord front end; runs polymerge.py as a subprocess
Overlays/               board renders, one set per board size (see below)
    <name>-blank.png      blank all-fog render -- this is the template
    <name>-gridded.png    optional layers, in the blank's exact pixel frame
    <name>-shaded.png
    <name>-push.png
    <name>-Nspawns.png
Assets/Rainbowflame.png the game's own Elyrion ruin-vision sprite
tools/baseline.py       runs every test set and prints/diffs the baselines
tools/ruinsprite.py     measures the ruin sprite against the corpus; sets the
                          ruin detector's constants, ships with nothing
tests/<set>/            screenshots for one board, plus that set's outputs:
    *.jpg|png|webp        the input screenshots
    merged.png            the composite (regenerate freely)
    debug/                --debug-dir output for that set
shoreline/              shoreline inference -- a separate program, and
                          deliberately no part of the merge or the bot.
                          See shoreline/SHORELINES.md; nothing here
                          imports it, and nothing here may.
```

**There is still no automated test runner in the sense of assertions, but
`tools/baseline.py` is the stand-in and should be used.** It runs polymerge
over all 24 sets and prints one table of worst `--cross-check`, explored union,
conflicts, city bars, ruins and per-shot fog lock, and
`--compare` diffs that against a stored JSON run and prints only what moved. Capture a "before" table, make
the change, compare. It is what caught an "obviously inert" refactor silently
costing 5 sets a city bar each, and what proved the same refactor inert once
fixed. It is not shipped code — polymerge and polybot never import it.

```bash
.venv/Scripts/python.exe tools/baseline.py -o before.json
.venv/Scripts/python.exe tools/baseline.py --compare before.json
```

`tests/<set>/merged.png` and `tests/<set>/debug/` are regenerable program
output — safe to delete at any time. There is no `ui.json` any more: the
`--ui-mask` option still exists for a mid-screen dialog the band crops can't
cover, but the checked-in rect file was left over from before
`--top-crop`/`--bottom-crop` and was measured to be inert — passing it changed
no union, no winner, no conflict and no `--cross-check` number on any set. It
was also a hazard, because it keys on *basename* and `cym1.jpg`/`cym2.jpg`
exist in both `test_ss_2` and `test_ss_3` as different images, so one set's
rects would silently apply to the other's shots. If you ever reintroduce
per-file rects, key them on something unambiguous.

## Running it

```bash
.venv/Scripts/python.exe polymerge.py shot1.jpg shot2.jpg shot3.jpg --map-size 20 -o merged.png --debug-dir debug/
```

- The venv at `.venv/` already has the right interpreter (3.12) and packages
  (`opencv-python`, `numpy`) installed — activate it or call
  `.venv/Scripts/python.exe` directly rather than assuming a global `python`.
- `--map-size` is one of **11, 14, 16, 18, 20** (30 exists as a render but is
  deferred — see the `Overlays/` section), resolving to
  `Overlays/<name>-blank.png`; `--template` still overrides. **Omitting it measures
  it off the screenshots** (`detect_map_size`, below) — which is not the same
  as guessing: it counts the tiles across a shot that spans the board, and
  refuses to run when no shot can answer. Getting it wrong is the
  single most destructive mistake available here, because it does not look
  like a geometry failure: the board silhouette still fits the template
  silhouette, so anchoring "succeeds", but the tile lattice period is off by
  N_real/N_given, every tile's fog art lands out of phase, the fog test
  therefore matches nothing and calls the *entire board* explored, and the
  merge degenerates into whichever source the winner rule happens to favor
  pasting its own fog over everyone else's terrain. `--min-fog-lock` (below)
  exists solely to make this loud. **`test_ss_3` is a 20x20 board** — it was
  being run at `--map-size 18`, which is what produced the "yad's vision is
  missing" merge.
- `--min-fog-lock` (default 8) fails the run unless at least one shot matches
  that many tiles against the template's fog art at NCC >= 0.7. Fog is a fixed
  render, so a correct anchor puts genuine fog tiles at 0.95+ and explored
  ones near 0.0 with almost nothing between; measured across all four test
  sets the best-locking shot scores 105-211 when `--map-size` is right and 2-4
  when it is wrong. The check is deliberately per-*run*, not per-image: a
  single zoomed-in shot sitting inside explored territory can honestly have
  only ~15 fog tiles in frame and still be anchored perfectly
  (`test_ss_2/cym1.jpg`, `test_screenshots/Screenshot_20260728-170349217.jpg`
  are both like this).
  **When it does trip, whether that refuses the run depends on who claimed the
  board size** — because nothing available at that point separates the two
  causes of a zero lock (a wrong size, or a board with no fog left), but *that*
  question can be answered:
  - **Detected.** The claim is this program's own, and `detect_map_size` gets it
    from span over fog repeat period — so a detected size means fog was found
    and measured, and a run that then locks none of it is wrong about something.
    Refuse.
  - **Stated with `--map-size`.** It is the person's assertion, and a wrong one
    is their error to make. Warn loudly and merge. This is a deliberate product
    call: a replay is rare, and refusing every one of them to guard against a
    mistyped size served nobody. `!merge 16` therefore works on `tests/fogless`,
    and `--min-fog-lock 0` is no longer needed for it.

  A wrong *stated* size is still guarded twice over. The board-size check is
  independent and stronger and refuses wherever it can measure at all (it stops
  `test_ss_3` at 18 and `goon_test2` at 20 long before this point). What gets
  through is a wrong stated size on a board where that check abstains — the
  `pol_archi_test` shape, where neither shot spans the board — and
  `CONFLICT_FRAC_SUSPECT` below is the backstop for exactly that.
- `--debug-dir` is the main diagnostic tool during development: it writes
  `provenance.png` (winner per tile), `conflicts.png` (tiles where sources
  disagree), `grid_overlay.png`, `badges_<name>.png` (capture-badge pixels
  excluded, always written even when empty — see below), `ruins_<name>.png`
  (ruin-vision pixels accepted, when `--ruin-vision` is on), `bars_<name>.png`
  (population bars found and the 3x3 blocks promoted, when `--city-bars` is
  on) and `explored_<name>.png` per source. Always pass it when iterating.
- `--ruin-vision` detects Elyrion's through-fog ruin markers, reports their
  tiles, and outlines them in violet on the composite's fog. Off by default in
  the CLI; the Discord bot passes it always, since it finds nothing when no
  Elyrion player contributed (~0.4s on a normal board, ~0.7s on a fog-heavy
  one). See the ruin-vision section below.
- `--city-bars` detects the owner-only city population bar and promotes the
  shot showing it on that city's 3x3 block, so the bar survives into the
  composite. Off by default in the CLI; the Discord bot passes it always, for
  the same no-wrong-answer reason. See the city-bar section below.
- `--overlays` draws the board's decorative layers on the finished composite:
  `shade`, `grid`, `spawns`, `push`, comma-separated, or `none`. Default
  `shade`. They come from the same `Overlays/` renders as the board itself and
  share its pixel frame exactly, so they alpha-blend on with **no registration
  or warping** — see the `Overlays/` section. Drawn after the tile paste (so
  they read over real terrain, not just fog) and before the ruin markers (so a
  marker is never dimmed). `shade` and `spawns` are clipped to tiles nobody
  explored; `grid` and `push` cover the whole board. A layer
  that does not exist for the board size is skipped and named on stdout as
  `NO-OVERLAY`, never an error — the bot lifts that line into its caption.
  **Overlays cannot change the merge**: they are painted after every decision,
  so union, conflicts and bar counts are identical whatever is requested
  (verified across the corpus).
- `--cross-check` is the correctness regression test alongside
  `tools/baseline.py`: it anchors every input independently, hops shot A → shot B via SIFT
  (trustworthy to ~0.2px, verified — see below), and reports how far that
  disagrees with anchoring B directly. Run this after touching anything in
  the registration path; a `worst disagreement` under ~0.05 tiles is healthy,
  anything over ~0.1 tiles means something regressed. It independently catches
  a wrong `--map-size`: `test_ss_3` reports 0.015 tiles at 20 and 0.634 at 18.
  **Caveat: it is only meaningful for shots whose *explored* regions
  overlap.** SIFT matches local texture, and fog is a fixed repeating render
  full of small crystalline shapes that look locally distinctive, so fog
  matches fog — and because the fog art is periodic, it happily matches the
  *wrong repeat* of itself. Two failure shapes, both false alarms:
  - Shots sharing no territory at all. On `test_ss_fruit` that yields an
    11.1-tile "disagreement" between `oum` and `zeb`; the two pairs that do
    overlap agree to 0.012 and 0.034 tiles, and all three anchors are mutually
    consistent by transitivity.
  - Shots that overlap heavily but are *mostly fog*, which is worse and was
    found on `test_ss_elyruins`: `ely1` vs `ely2` reports **17.4 tiles on 115
    inliers** — a confident, high-inlier match onto a lattice repeat several
    tiles off. Both shots are in fact anchored correctly, and the evidence
    that settles it does not come from cross-check at all: both anchor from
    two edge pairs agreeing to 0.00%/0.01%, both lock 245 and 202 fog tiles,
    and — independently — both detect an Elyrion ruin marker on *the same*
    tile (8,7), which two anchors 17 tiles apart could not do.
  Inlier *fraction* does not separate the cases either (2.8% spurious vs 3.4%
  genuine on `test_ss_fruit`), and neither does inlier count. So read the
  per-pair table rather than just the worst number, discount pairs whose
  regions don't touch in `provenance.png`, and on a fog-dominated board treat
  the fog-lock count and edge-pair spread as the primary signals instead.
- `--single` anchors exactly one image with no cross-image registration, for
  isolating whether a problem is in one shot's own anchor.
- Every run prints a **timing** block (`PHASES`). A 4-shot merge is ~12s
  without `--debug-dir`, ~16s with, dominated by the three `joint_register`
  pyramid levels (1.7s / 2.3s / 4.3s for div=4 / 2 / 1). That taper is the
  fix for a former inefficiency worth remembering: `_tile_sample_grid`'s
  `max_px` used to be a flat constant, so the cap never bound at the coarse
  levels (a tile holds only ~276 px at div=4), every level gathered ~300
  samples per tile, and because the coarse levels evaluate *more* candidates
  (343 vs 175) they cost *more* in total than the full-resolution level
  (37.9M and 36.9M gathers vs 22.1M) — a pyramid that shrank the images but
  not the work. `max_px` is now `max(320 // div, 160)`, cutting the phase from
  12.6s to 8.3s. **Don't lower that 160 floor**: dropping it to 24 saves
  another 1.3s but pushes `test_ss_2` from 0.021 to 0.059 cross-check tiles,
  past the 0.05 healthy bar, because its `cym1.jpg` locks only 15 fog tiles
  and so has little to constrain the fit. At 160 no set exceeds 0.056, which
  is where the worst set already sat beforehand. Either way the *merge* is
  unchanged — identical explored union on every set checked, with `test_ss_3`
  and `test_ss_2` each reporting one conflict fewer — so the cross-check
  movement here is a leading indicator, not damage.
  Everything else is minor: fog pixel masks ~2.1s, debug overlays ~1.9s,
  ruin-vision detection ~0.4-1.3s when `--ruin-vision` is on (it matches the
  game's flame sprite over the fog region -- see that section for what the cost
  buys and where the remaining cost is) and city-bar
  detection ~0.45s when `--city-bars` is, image loading ~0.5s,
  and the whole per-tile half of the pipeline (sampling, winner selection,
  conflict check, paste) under 0.8s combined.
- **Test sets live under `tests/<set>/`**, each holding its own screenshots
  plus that set's `merged.png` and `debug/`, so a set is entirely
  self-contained. One PyCharm run configuration per set writes back into its
  own folder. Validate changes with `tools/baseline.py` (which runs all 24 and
  diffs the tracked numbers), then read the console output and debug overlays
  for anything it flags. **Every set is 18x18 or 20x20** — sizes 11, 14 and 16
  have no real screenshots at all and are covered only by a synthetic
  round-trip, so a real set at one of those sizes is the most valuable thing
  anyone could add to this corpus.

  | set | size | shots | notes |
  |---|---|---|---|
  | `test_screenshots` | 20x20 | 4 | same board as `test_ss_2` |
  | `test_ss_2` | 20x20 | 4 | same board as `test_screenshots` |
  | `test_ss_3` | 20x20 | 4 | two players, zoom differs ~1.4x |
  | `goon_test2` | **18x18** | 2 | |
  | `test_ss_5` | 20x20 | 3 | |
  | `test_ss_fruit` | 20x20 | 3 | `.webp`; three non-overlapping views |
  | `archers_test2` | 20x20 | 5 | |
  | `beautiful_test3` | 20x20 | 4 | same board as `test_screenshots`/`test_ss_2` |
  | `goon_test` | **18x18** | 2 | |
  | `test_ss_elyruins` | 20x20 | 4 | Elyrion ruin vision; a near-empty board |
  | `badland_test` | 20x20 | 2 | landscape shot; desert board; from a real bot failure |
  | `badland_test3` | 20x20 | 3 | same board, other captures; `cym.png` has one edge |
  | `pol_archi_test` | **18x18** | 2 | Polaris/archipelago; sunrise-lit sky |
  | `star_change` | **18x18** | 3 | capture badge on the rim; one shot has ~7 fog tiles |
  | `badland_test2` | 20x20 | 2 | landscape; desert; whole board in frame, turn 13 |
  | `perilous_test` | **18x18** | 2 | landscape; ice/blossom board; two lighthouses in frame |
  | `missized_test` | **18x18** | 3 | turn 0, ~fully fogged; one shot at s_it=2.23 |
  | `basin_treaties` | **18x18** | 2 | one shot at s_it=0.40, the most zoomed-*in* in the corpus; two disjoint islands |
  | `xizauh` | 20x20 | 4 | Polaris player; ice terrain reads as fog to every color test |
  | `u_forest` | **18x18** | 4 | Elyrion, three shots from one player; ~85% fog; vivid ruin markers |
  | `u_forest2` | **18x18** | 2 | turn 1, two disjoint starts; Elyrion; drawer-tab chrome |
  | `fogless` | **16x16** | 2 | replay; no fog anywhere; turn-timeline chrome |
  | `replay_ss2` | **16x16** | 2 | replay; no fog; play-button chrome; lone-pair and terrain-inlier regression test |
  | `vengir_cultist` | **18x18** | 2 | Vengir/Cultist; one shot at each zoom extreme; city-name-text false-bar regression test |
  | `scorched_earth` | **18x18** | 2 | the corpus's only **majority-red** population bar (Icalus, (15,6)); city-bar ground truth |

  `star_change` is the regression test for two separate defects, one per shot,
  and both were invisible in a composite that looked fine:
  - `oum.png` is a zoomed-in view of a nearly-fully-developed board with only
    about seven fog tiles in frame. It has no edge pair, takes its zoom from
    `fog_period_scale`, locks **zero** fog tiles, and the per-image misanchor
    guard used to drop it outright — costing 81 tiles of union. It now borrows
    a whole anchor by SIFT instead (see the misanchor guard section).
  - `oum2.png` carries a **capture badge sitting on the NW rim**, and its glow
    was leaking into the board silhouette and putting the shot a full tile out.
    It is the reason `badge_halo` exists. Note the badge also defeated the
    *sunrise-sky* path into being used at all: with the halo gone, that shot
    anchors from ordinary brightness masks and never reaches the fallback.

  Keep all three. The set is also unusually good at showing anchor errors
  without any tooling, because `oum.png` and `oum2.png` are the same player's
  shots: whenever both are anchored right they report the same three cities at
  the same tiles, and a one-tile error shows up as `(1,8) (8,16) (11,16)`
  against `(2,8) (9,16) (12,16)` in the `--city-bars` report.

  `badland_test` earns its place twice over: it is the only **landscape**
  screenshot in the corpus and the only **desert** board, and it came from a
  Discord user reporting that one of their two shots silently vanished from
  the merge. It is the regression test for `PERIOD_MIN_PROMINENCE` — a board
  whose pale sand and white city roofs defeat the color test that picks the
  region `fog_period_scale` autocorrelates. Keep it.

  `missized_test` is the regression test for `fog_period_scale`'s **sweep
  floor**. Its `z2.png` is a whole 18x18 board photographed at s_it=2.23 — the
  most zoomed-out shot in the corpus by a wide margin, past the 1.70 the
  game-facts section records — so its true fog period is 40.4px against the old
  sweep's 40.5px floor. The fundamental fell just outside the window, the first
  peak found was the 2x harmonic at ~80px, and the board measured **8.60 tiles
  instead of 17.9**. That refused the merge outright: as a size disagreement
  with `z1.jpg` under a bare `!merge`, and as "this looks like a 13x13 board"
  under `--map-size 18`. Note the anchor itself was never in trouble — `z2.png`
  has all four edges and anchors from them to +0.04% — so this was purely the
  guard against a wrong size blocking a run at the right one. Keep the set; it
  is the only shot anywhere near that end of the zoom range.

  `basin_treaties` is the regression test for `fog_period_scale`'s **sweep
  ceiling**, the exact mirror of `missized_test`'s floor. Its `q.png` is the
  most zoomed-*in* shot in the corpus at s_it=0.398 — zoomed enough that only
  two of the four board edges are in frame (`a-max` and `b-min`, no opposite
  pair), so it cannot take its zoom from the edges and depends on the fog
  period entirely. That period is 202.3px against the old `hi=2.30` sweep's
  185px ceiling: a clean peak at ncc 0.72, simply outside the window. The shot
  measured nothing, could not self-anchor, found 0 SIFT inliers against the
  only other shot (the two views share no territory — see below) and was
  **dropped**, halving the merge. `hi` is now 3.75. Note the failure was loud
  rather than silent, unlike the wrong-`--map-size` class: the shot raised
  "no periodic fog found to read the zoom off" and the merge went on without
  it.

  Its second property is independent and worth keeping too: **the two shots
  show disjoint islands**, so no SIFT pair exists and `--cross-check` reports
  `n/a` rather than a number. That is not a failure — it is the honest answer
  when nothing overlaps, and it makes this the only set that exercises that
  path (`test_ss_fruit` has three views of which two do overlap). Judge the set
  on its union (69) and per-shot fog lock (208/55) instead.

  `xizauh` is the set where **terrain most resembles fog**. Its `pol.jpg` is a
  Polaris player's view, and Polaris renders its territory as pale blue-white
  ice — the same brightness and the same low saturation as the fog cube. The
  color prefilter that picks the region `fog_period_scale` autocorrelates
  admits **83.5% of that shot's valid pixels** as fog-ish, the highest in the
  corpus and well above the 49.2% on `badland_test/oum.jpg` that motivated
  `PERIOD_MIN_PROMINENCE` in the first place. So this is the harder version of
  the same test: the prominence rule has to find a real periodic peak inside a
  frame that is five-sixths "fog" by color. It does — 64.3px at ncc 0.68, and
  the shot then anchors to within 0.013 tiles of `imp1.png` by SIFT.

  It matters beyond `fog_period_scale`, because the standing decision against
  identifying fog by color/saturation has always been justified by "mountains,
  snow and ice are exactly as desaturated as fog", and until now the corpus had
  no set where a *whole player's territory* was that color. `perilous_test`
  has ice terrain but not an ice-tribe player; `pol_archi_test` is Polaris but
  nearly fully explored, so little fog remains to confuse. Any future change to
  fog classification should be run against this set specifically. It is also
  the corpus's richest set for city bars — 28 found across 4 shots, of which
  **19 were the name-text and fruit false positives** the south-vertex floor now
  discards; it reports 9 today, and that is the honest figure.

  **`vengir_cultist` is the regression test for the city-name-text false bar.**
  Two shots of an 18x18 board, one from a Vengir player and one from a Cultist,
  and they bracket the zoom range within a single set: `v1.png` anchors at
  s_it=0.749 (the shot is 1.33x the template's own resolution) and `v2.png` at
  1.843, the most zoomed-*out* shot in the corpus. That spread is what makes it
  a good bar test rather than a coincidence — sharpness ranking hands almost
  every contested tile to `v1`, so any city `v2` owns keeps its bar only if
  something outranks sharpness.

  Its city **Xasna at (5,4)** is that case, and it failed in the way that is
  hardest to see. `v2` owns Xasna and shows its complete bar; `v1` sees
  the same city as a foreign one, with a faded label, no star and no bar. `v1`
  nevertheless produced a *detected* bar at (5,4) — the letters **`a` and `n` of
  "Xasna"**, two closed round letterforms 10px and 9px wide at an even 18px
  pitch, which clear every per-segment test and the group's span and pitch tests
  alike. That is a detected-bar strong claim for the shot that does **not** own
  the city, and it outranks `v2`'s (correct) vision claim, so `v1` took the whole
  block and the composite spliced Xasna's label and dropped its bar entirely.
  Suppressing that one detection restores the bar intact, with nothing else
  changed.

  Keep the set for a second reason: **the shot that owns the contested bar is
  the blurrier one**, and that is not a coincidence but the shape of the whole
  problem — a bar is only ever *lost* to a sharper shot, so the shot that needs
  defending is always the one with the least detail to defend itself with. It is
  why the star-icon idea cannot help here (see the city-bar section). It is also
  why `v2` defeated the old bottom-up detector: at s_it=1.843 the whole
  ~120-template-px bar is 66 px in `v2`'s own pixels, so each segment is ~13 px
  with a dark dot in the middle of it, and the segments shredded into slivers
  that failed that detector's aspect test. The anchor-first detector never asks:
  it tests the bar as one oblong at a legal width, so a shredded subdivision
  costs it nothing. Keep the set as the regression test for that distinction.

  `badland_test2` and `perilous_test` were in `tests/` but had never been
  entered here; the numbers below are measured, but **their provenance is not
  recorded** — if either came from a specific bot failure, that is worth adding.

  **`goon_test2` and `goon_test` are also the same board** — different
  screenshots (different bytes, different turn) by the same two players, which
  is why both hold an `imp.jpg` and a `q.jpg` and why their unions sit at
  238/324 and 237/324. That makes them an independent cross-check on anything
  per-tile, in the same way the three sets above are: two turns of one board,
  so any per-tile claim can be made twice and compared.

  Twenty-four sets but fewer distinct boards — `test_screenshots`, `test_ss_2` and
  `beautiful_test3` are all the same map, which is worth remembering when
  judging whether a change generalizes (it also gives ruin-vision detection
  three independent looks at the same ruins; see below). Mixed aspect ratios,
  devices and file formats (jpg/png/webp), deliberately not uniform, since the
  pipeline has to be robust to arbitrary phone/tablet captures. `test_ss_3`
  exercises winner selection hardest. `goon_test2` is the only independent
  check that the `--min-fog-lock` guard works on a board size it was not
  calibrated on (it locks 54/105 tiles at 18 and 3/4 at 20). `test_ss_fruit`
  is the only set whose shots barely overlap. `test_ss_fruit` and
  `test_ss_elyruins` are the two that exercise the `fog_period_scale` zoom
  fallback (`oum.webp`, `cym.jpg` and `hood.png` have no opposite edge pair).
  **`test_ss_elyruins` is the most demanding set on the registration path**:
  its board is ~78% fog, two of its four shots have no edge pair, and
  `hood.png` is rendered at 1.66x the template's resolution — more zoomed-in
  than any other shot in any set, and the case that broke the old fog-patch
  zoom fallback. `pol_archi_test` is the only set that exercises the
  sunrise-sky fallback (`sky_mask`) and the SIFT zoom fallback — both its
  shots need the first; `kick.png` needed the second until `_board_component`
  let it self-anchor, and `badland_test3/cym.png` is now the only shot that
  does. `missized_test` and
  `basin_treaties` bracket the zoom range, at s_it=2.23 and s_it=0.40 (see
  above), and `badland_test2` and `perilous_test` add two more landscape
  captures to `badland_test`'s one. `xizauh` is the one set where a player's
  own terrain is the same color as fog. **`u_forest` is the set where ruin
  markers are rendered most vividly**, and with `basin_treaties` it is the
  historical regression test for the retired `RUIN_VIVID_*` band — both were
  finding a fraction of their ruins through a saturation cap calibrated on
  blurrier captures, which is the mistake the sprite-matching rewrite removed
  outright (see the ruin-vision section). Its `e3.png` is the case for the
  retired `_fog_borne_pieces`: its ruin at (2,1) sits directly against explored
  terrain and was absorbed into it by the candidate close. Keep both as
  regression tests — the close is gone, but "a marker on the fog frontier" and
  "a vividly-captured marker" are the two shapes any future ruin detector will
  get wrong first. It has **9 ruins**, and
  it is the corpus's best cross-shot corroboration of ruin detection: three of
  them are found independently by two different screenshots.

  **`u_forest2` is the regression test for `_board_component`** — the only set
  whose merge is impossible without it. Its `ely.png` carries the game's
  collapsed side-drawer tab in the top-right corner, which entered the
  silhouette and captured `b-min` 577px past the real NE rim; the shot then had
  no `b`-direction edge, could not pan-anchor, and was dropped, halving the
  merge. It is a good regression test for a second reason: nothing else in the
  run flagged it. The composite of the surviving shot looked entirely healthy,
  which is the failure shape this file warns about throughout.

  Two further properties worth keeping. It is **turn 1** — the earliest board
  in the corpus, ~76% fog with two disjoint starting islands and no city
  bars at all (the only set scoring 0 alongside `u_forest`), so it exercises
  the sparse end of everything. And its 48-inlier SIFT pair is the corpus's
  clearest example of *why* `SIFT_ZOOM_MIN_INLIERS` sits at 150: two shots that
  genuinely share no territory still match fog to fog well enough to produce a
  confident-looking 6.3-tile cross-check number.

  **`replay_ss2` is the second replay set, and it exists because `fogless`
  merging did not mean replays worked.** It is the same game mode, the same
  board size and the same chrome family, and it failed for three further reasons
  in a row — each of which is now a mechanism in its own right:
  1. The replay's **play button** is a triangle whose upper edge runs 1.1° off
     `dir_a`, so it passed the chrome filter's angle test and captured `b-min`.
     (Fixed by the smoothing window; see `_board_component`.)
  2. `s1`'s only opposite pair had a **weak side** (69 points), and the
     lone-pair rule rejected it. Its span was right all along — 1330.3px against
     the 1331.9 the other shot independently implies. (Fixed by
     `LONE_PAIR_EXTENT_LO`.)
  3. `s2` had no pair at all and its SIFT borrow was **113 inliers against the
     150 floor**. (Fixed by `SIFT_TERRAIN_MIN_INLIERS`.)

  Keep both replay sets: `fogless` covers the fog-lock and un-refinement paths,
  `replay_ss2` covers the three above, and nothing else in the corpus reaches any
  of them.

  ### City-bar ground truth (confirmed with the project owner)

  **Six sets are now labeled, and this is the only thing any bar detector
  should be judged on.** Everything else in this section is a measurement of
  behavior; this is a measurement of truth. Tiles are given per *board*, since
  a bar belongs to a city rather than to a screenshot.

  | set | real bars | flagged but **not** bars |
  |---|---|---|
  | `fogless` | 1 — Tetesum (12,4) | — |
  | `replay_ss2` | 1 — Bergo (4,3) | — |
  | `test_ss_3` | 10 — (8,6) (10,9) (11,2) (11,18) (12,13) (13,6) (15,15) (16,1) (17,12) (18,16) | (9,7) (13,5) |
  | `archers_test2` | 12 — (3,15) (5,12) (6,6) (6,16) (7,2) (8,13) (9,9) (9,16) (10,4) (11,13) (12,9) (12,16) | (3,13) |
  | `badland_test3` | 16 — (4,16) (6,13) (9,9) (9,15) (9,18) (11,12) (12,8) (12,16) (15,6) (15,9) (15,13) (15,16) (18,7) (18,10) (18,13) (18,16) | (3,3) |
  | `scorched_earth` | 10 — (2,3) (2,9) (3,6) (6,3) (6,6) (6,9) (9,4) (12,4) (13,9) (15,6) | (4,8) (8,9) (11,13) |

  The four larger sets were labeled by eye over the union of everything the
  shipped detector and the anchor-first probe each proposed, so the "not bars"
  column is *flagged* false positives rather than an exhaustive sweep of the
  board — a bar neither detector proposed would not appear in either column.
  Read recall against these numbers as an upper bound.

  Two further labeled facts, both worth keeping because they cost time to
  establish:
  - **`test_ss_2` (15,18) has no bar for anyone.** The city Szugusha is there
    with a plainly visible name plate, and no bar under it in any shot. It was
    briefly mislabeled as real from a thumbnail, which is the trap: **a plate
    means "city", not "bar"**, and the two look alike at a glance. Any future
    plate-based test has to survive this case.
  - **The 25 candidates in the 0.34-0.55 score band split 12 real / 13 false**
    (`tools/barprobe.py --raw`, near-miss sheet). That band is the only view
    anyone has onto *false negatives*, since a miss otherwise leaves no
    artifact, and it is worth regenerating whenever the accept rule changes.

  **`scorched_earth` carries the corpus's only majority-red bar** — Icalus at
  (15,6), six red segments and no white. Keep it for that alone: red is the one
  bar color that breaks a luminance-based silhouette test, because pure red
  converts to a gray of about 76 against grass at about 130, so a red bar is
  *darker* than its background where white and blue bars are brighter.

  **Both replay sets have a *known* city-bar answer, which nothing else in the
  corpus does, and that makes them the only ground truth the bar detector has.**
  (They were the only one; four more sets are labeled above.)
  Each is a single player on an early turn, so each board carries exactly **one**
  population bar — `fogless` Tetesum at (12,4), `replay_ss2` Bergo at (4,3),
  both confirmed with the project owner. Two separate bar bugs were found by
  comparing against those two numbers and nothing else (see the city-bar
  section); the detector had been reporting 17 and 18. Do not read either set's
  bar count as "more is better" — the target is 1 and 1, and it currently reads
  **1 and 2**. `replay_ss2`'s two survivors are pairs of red fruit crops at
  (4,13) and (6,14); its real bar, Bergo at (4,3), is still missed because its
  two segments fuse into one component and the current detector needs two.

  **`fogless` is the only board with no fog whose merge needs nothing unusual to
  anchor**, which makes it the regression test for two things nothing else covers.
  It is where the chrome filter is load-bearing (the replay turn-timeline strip
  takes an edge off *both* shots, so the whole merge fails rather than one shot
  dropping), and it is the only set exercising the zero-lock un-refinement in
  `main` — with nothing to score against, `joint_register` walks both anchors
  1.1 tiles apart and the composite comes out visibly seamed.

  Two properties are worth knowing before judging it. Its **edge-only anchors
  are unusually good** — 0.007-0.023 cross-check tiles at *every* board size,
  better than most shots that do have fog, because a rim of explored terrain has
  none of the fog cube's scalloped bottom lip to bias the edge fit. And **nothing
  in the pipeline can measure its size**: `fog_period_scale` needs the fog as a
  ruler, and cross-check is scale-relative so it reads ~0.01 at *every* N. It used to
  need `--min-fog-lock 0`; it no longer does, since a *stated* size now warns
  rather than refuses when nothing locks (see `--min-fog-lock` above).

  **It is 16x16, and how that was established matters more than the number.** A
  first pass put it at 20 by eyeballing `--overlays grid`, and the merge at 20
  looked entirely healthy — 400/400 union, 4 conflicts, no visible seam. That is
  this file's standing warning firing in a new place: on a fogless board a wrong
  size cannot paste fog over terrain, because there is no fog, so the composite
  stays plausible and only the tile bookkeeping is wrong. What settles it is
  measurement, not appearance: **autocorrelating the terrain lattice** (the same
  shift-NCC `fog_period_scale` uses, over the whole board region rather than the
  fog-colored subset) gives an 80px fundamental with clean harmonics at
  160/240/320, against a span of 1330.6px in *both* directions on *both* shots —
  `1330.6/80 - 0.78 = 15.85`. For 20 the period would have to be 64px and there
  is no peak there. Only then does the grid overlay confirm it, and at a crop
  where it is unambiguous: at 16 the lines land on the sand/water boundaries and
  the small island's border, at 20 they cut through both.

  Two corroborating signals, both weak individually and worth knowing anyway:
  the merge reports **0 conflicts at 16 against 4 at 20**, and the union is
  256/256 rather than 400/400. Conflicts are the only tracked number that moves
  with the size here, since with no fog every other check is blind to it.

  Note `basin_treaties` **has an Elyrion player**, which its entry above does
  not mention and which nothing in the corpus made obvious while it was
  reporting a single ruin. It has five.
- Current `--cross-check` baselines, worst disagreement: **test_screenshots
  0.031, ss2 0.027, ss3 0.032, goon2 0.037, ss5 0.021, archers_test2 0.034,
  beautiful_test3 0.024, goon_test 0.019, badland_test 0.011,
  badland_test3 0.022,
  pol_archi_test 0.012, star_change 0.050, badland_test2 0.019,
  perilous_test 0.011, missized_test 0.026, xizauh 0.020, u_forest 0.018,
  vengir_cultist 0.029, scorched_earth 0.013 tiles**. These moved on the
  fixed-angle basis (see that standing decision), then on the fog-colour tile
  prefilter, then on the zoom-pivot fix — which is why `star_change` and
  `vengir_cultist` swapped places, the latter coming back under the bar while
  the former went past it — and then on the fog-ish `top_k` cap, which brought
  `star_change` back to **0.050**. **No set in the corpus is now above the 0.05
  healthy bar**, which has not been true at any earlier point in this file's
  history. Compare against these after touching anything in the registration
  path. Cross-check
  is *deterministic* (verified: repeated runs give identical numbers), so a
  change in these is real and not RANSAC noise.
  **`badland_test3`'s 0.027 is only partly independent**: `cym.png` takes one
  of its two pan offsets from a SIFT hint (see `pan_hint` above), and
  cross-check measures against that same SIFT geometry. Its other offset, its
  zoom and both other shots are measured normally, so the number is not
  vacuous — but read it as a consistency check rather than an independent one,
  and judge that set on its union (331) and fog lock (10/68/104) as well.
  **`pol_archi_test`'s 0.044 went *up* from 0.035 and is the stronger number of
  the two.** That set's old figure was the partly-vacuous kind described just
  above: `kick.png` took its zoom from SIFT against `pol.png`, and cross-check
  then measured it against that same SIFT geometry. Since `_board_component`
  recovered kick's real edges it anchors on its own evidence, so 0.044 (a
  3.6px corner gap against the old 2.8px) is a fully independent measurement
  where 0.035 was a partial self-check. Both sit well under the 0.05 bar. This
  is the one case in this list where a *larger* number is an improvement — do
  not "fix" it back.
  **`test_ss_fruit` reports 11.1
  tiles, `test_ss_elyruins` 17.4 and `u_forest2` 6.3, and all three are false
  alarms** — see the cross-check caveat below.
  **`u_forest` used to head this list at 18.5 and no longer belongs on it**: its
  flagged `e1` vs `e2` pair was 39 inliers of *identical HUD*, not fog, and once
  SIFT is confined to the board that pair vanishes and the set reads **0.016**
  (see the SIFT note in the anchoring section). The three above are unchanged to
  three decimals by that fix, which is the evidence that their diagnosis really
  is the fog one. **`basin_treaties` reports `n/a`**, which is
  neither: its two shots show disjoint islands, so no pair has both an anchor
  and a SIFT transform and there is nothing to measure. `u_forest2` is the
  in-between case that produces the misleading *number* rather than the honest
  `n/a`: its two turn-1 shots show disjoint starting islands too, but enough
  fog matches across them to yield **48 inliers**, far under
  `SIFT_ZOOM_MIN_INLIERS` and nowhere near a genuine terrain match. Judge it on
  its fog lock (86/142) and its zero conflicts, and note its ruin at (10,7)
  lands on a tile the *other* shot independently explored — which two anchors
  6 tiles apart could not do. **`fogless` reports 0.035 and is unreliable for a
  different reason from all of those** — not a fog mismatch but a measurement of
  the wrong thing. (It read 16.6 before SIFT was confined to the board, which is
  the figure this entry used to carry; the board-region table below records the
  drop.) `--cross-check` returns before the merge path, so it reports
  the *refined* anchors, and on a board with no fog the merge discards those in
  favor of each shot's own unrefined edge anchor (see the zero-lock block in
  `main`). Those agree to **0.023 tiles**. Same shape as `star_change` below:
  the number is the quality of an anchor nothing uses. Judge the set on its
  union (256/256) and conflicts (0). It has read 16.6, 13.5, 0.511, 0.253, 0.378
  and 0.035 across changes that left that union and those conflicts untouched,
  which is the clearest demonstration in the file that the number measures
  nothing here. `replay_ss2`'s 0.808 is the same, for the same reason.

  Every set except `star_change` now sits at or below **0.039**, where this
  list previously ran to 0.078. That is the beam search plus the tile-sample
  fix (both in the anchoring section); it is a real accuracy gain and not a
  change of measurement, and it recovered fog lock the old code was silently
  losing — `badland_test2`'s `cym.png` locked 124 tiles and now locks 150.

  **`star_change` used to head this list at 0.162 and no longer does** — the
  fog-colour tile prefilter took it to **0.044**, and `oum.png` from a zero fog
  lock to **6**. That is the largest single move any change has produced here,
  and the mechanism is the one the prefilter was built on: `oum.png` has ~7 fog
  tiles in frame, so under the old grid 393 of its 324 sampled tiles were
  terrain and `top_k`'s quota was filled almost entirely with noise. Note the
  consequence for coverage — a shot locking 6 rather than 0 is no longer
  eligible for the anchor borrow, so **the corpus now exercises no set's borrow
  path at all**. Keep the reasoning in the misanchor-guard section; it is no
  longer regression-tested. The paragraph below describes the old behavior:

  `star_change` was the one set above the ~0.05 healthy bar, and its number
  did not measure what the merge does. Its `oum.png` has ~7 fog tiles in
  frame and locked **zero**, so the merge discarded that anchor entirely and
  borrowed one by SIFT — which cross-check deliberately does not reproduce (see
  the misanchor guard section). What cross-check reports is therefore the
  quality of an anchor nothing uses. Judge that set on its union (290) and
  conflicts (27) instead, both of which are stable. The number is also
  unusually *sensitive* for the same reason: a shot with almost no fog has
  nothing holding its zoom, so it inherits the period measurement's phase
  sensitivity in full — it has read 0.083, 0.106 and 0.141 across changes that
  left the merge output identical. Read a change here against the companion
  baselines before treating it as a registration regression.
- Companion baselines worth checking alongside, since cross-check is a proxy
  and these are the actual output. In table order — explored union **371/400,
  371/400, 261/400, 238/324, 202/400, 190/400, 278/400, 361/400, 237/324,
  90/400, 295/400, 330/400, 279/324, 290/324, 350/400, 214/324, 50/324, 69/324,
  247/400, 50/324, 78/324, 256/256, 256/256, 224/324, 233/324**; conflicts
  **16, 19, 3, 4, 0, 0, 12, 23, 2, 0, 0, 27, 2, 27, 10, 1, 4, 0, 15, 0, 0, 0, 0, 1, 10**; city population bars found (`--city-bars`) **16, 18, 18, 8, 9, 7, 17, 16, 9, 3, 7, 16, 8, 17, 9, 6, 3, 2, 11, 2, 2, 1, 1, 8, 10** (221 here, 242 with `control_c` and `control_d`); ruins found
  (`--ruin-vision`, after adjacency clustering) **3, 3, 0, 0, 0, 0, 0, 3, 0, 11,
  0, 0, 0, 0, 0, 0, 0, 5, 0, 9, 3, 0, 0, 0, 0** — 37 in total, on the seven sets
  with an Elyrion player and zero everywhere else.
  `fogless` is the only set at a **full** union (256/256), and trivially so: a
  replay shows the whole board, so its union is a check that nothing was *lost*,
  not that anything was explored. Its **0 conflicts** is the number to watch
  there instead — see its entry above.
  **The ruin count is only diffed as of the `RUIN_VIVID_*` work**, and that
work is now retired but the lesson is not. It was being
recorded in the JSON and displayed and compared by nothing, which is how two
separate ruin regressions sat in the corpus unnoticed — and nothing else could
have caught them, since every other number here is invariant under ruin
detection by construction (markers are drawn after every decision). Both were
eventually found by eye, on sets whose ruin count was *non-zero* and so looked
healthy, which is the reason to read this column per set rather than as a
corpus total.

Union and conflicts held unchanged across the ruin-vision, city-bar,
  `PERIOD_MIN_PROMINENCE`, badge-halo, bar-span, vision-promotion and
  sweep-floor work, so a move in either is a real signal. They moved on the
  template switch, by at most **3 tiles** per set (263→260, 203→201, 193→191,
  296→295, 352→350) with conflicts flat or lower everywhere — which is the
  size of movement to expect from a different fog reference, not a regression.
  The bar counts have legitimately moved three times: the span fix roughly
  doubled them (they were 10, 8, 7, 3, 8, 3, 14, 7, 1, 3, 2, 3, 7) while losing
  none; the template switch then cost about 4% corpus-wide (188 → 180), because
  the new renders put 21% fewer pixels in a tile so a segment is a smaller
  component; and the **south-vertex floor** (see the city-bar section) then took
  the corpus from 263 to 192 by discarding 71 detections that were never
  bars at all — city name text and pairs of round terrain sprites. Read that
  third move as the column becoming *meaningful*, not as a loss: it is the only
  one of the three that removed nothing real, and `fogless` is the clearest
  illustration — that board has **exactly one** bar (Tetesum at (12,4),
  confirmed with the project owner), the 17 it used to report were seventeen
  pairs of red fruit crops, and after the floor plus the grouping fix in the
  city-bar section it reports **1**, the right one.

  A fourth move followed immediately, and it is the mirror image: relaxing the
  segment alignment to *either* horizontal edge and capping a group's span while
  it grows added **7 cities and lost none**, taking the corpus to **203**. Both
  changes came out of the same two screenshots with a known answer; see the
  city-bar section.

  A fifth took it to **186**, and it is the cleanest of the lot because it
  rests on two placement guarantees rather than on any measurement: cities are
  never adjacent and never sit on the rim. It dropped **17 detections, added
  none, and every one dropped was a fragment** — no complete bar anywhere in the
  corpus lost. `replay_ss2` went 5 → 2 against a ground truth of 1.

  The **plate tiebreak** that followed is deliberately *not* a fifth move: it
  reorders claims without creating or destroying a detection, so every column
  here including `bars` is unchanged by it. Its whole effect is in the
  spliced-bar report. If a future change to the claim ranking moves this column,
  the gating is broken rather than the rule.

  **All five of those moves belong to the bottom-up detector, and the
  anchor-first rewrite superseded them: the corpus count is now 217** (see the
  city-bar section for how that scores against ground truth). Read the history
  above as a record of what each mechanism was worth, not as the current state.

  It also closes the **template-switch loss**, which stood here as an open
  question — a 4% corpus-wide drop when the `Overlays/` renders replaced the
  larger pair, with `SEG_H_MIN`/`SEG_H_MAX` and the `0.45 * w * h` solidity test
  named as the candidates. All three constants went with that detector, and the
  replacement expresses its geometry in **tile widths**, so there is no longer a
  px threshold for a change of render scale to move. Nothing is left to examine.

  Still live, and the reason this column is worth watching at all: bar promotion
  costs sharpness around a few cities and never map truth, because the union is
  *invariant* under it by construction — it only reorders sources that already
  witnessed a tile as explored. If a union figure ever moves when promotion
  changes, the gating is broken rather than the rule.
- Thresholds in this file that cite "all four test sets" were calibrated
  before `test_ss_5` and `test_ss_fruit` existed; they have not been
  re-derived against those two.

## Discord bot (`polybot.py`)

A thin Discord front end, **deployed and working**: it runs in the project
owner's team server and real users have merged with it successfully. The plan
is to share it with the broader community once the owner is confident there
are no further major bugs or missing features — so treat channel-facing
behavior (message wording, what gets posted vs logged) as
production-sensitive, not scaffolding. `badland_test` came from a real user's
failure report; expect more sets to arrive that way.

### Where it actually runs (confirmed with the project owner)

None of this is visible from the code, and several decisions below only make
sense against it:

- **A game gets its own channel, not a thread.** Threads are the occasional
  case — players sometimes want to merge in one — but the normal unit of a game
  is a dedicated channel. So the 🗺️-reaction workflow usually runs over a whole
  game channel's history, which is well inside `HISTORY_LIMIT`.
- **Those channels are created and destroyed by a *different* bot**, not by
  polybot and not by hand. Old game channels are normally **archived rather than
  destroyed**, so they persist and stay scannable.
- **One team server per team, and the game channels live in a specific category
  in each.** polybot is therefore in several guilds at once — which is the
  concrete justification for `MAX_UPLOAD_BYTES` being one fixed number rather
  than a per-guild lookup, since a per-guild figure would have the bot quote a
  different limit in each server.
- **The category carries the permissions** (bots and team members only), and the
  game channels take theirs from it.

That last point is the one with teeth, because Discord does not do inheritance
here — it does **permission syncing**. A child channel with the same overwrites
as its category is "synced" and tracks further category changes; *any* edit to
the child de-syncs it permanently, and it stops tracking. Two consequences:

- **The category is a single point of control over every game channel in a team
  server**, and a new channel the other bot creates is synced to it from birth.
  So a permission the category grants or withholds is not a one-off — it is
  replicated into every game of that season automatically.
- **A category-level fix does not necessarily reach every existing channel.** A
  game channel someone once edited by hand — to add one player, say — is
  de-synced and will not pick the fix up. Expect a fix applied at the category
  to leave a tail of older channels behind, and check rather than assume.

**`on_guild_channel_update` watches categories, not only text channels**, and
given the above that is the half that matters. It used to early-return on `not
isinstance(after, discord.TextChannel)` — and a category is a `CategoryChannel`,
verified not a subclass — so the single edit that can change the bot's
permissions across every game channel in a server was dropped before
`perm_report` ever ran. The handler was watching the channels that merely follow
orders and not the place the orders are given. A category line also names the
*cause* rather than N copies of the effect.

Do not remove it on the theory that the children cover it: whether Discord
additionally dispatches per-child `CHANNEL_UPDATE` for synced children on a
category edit is **not established here**. The category line is correct either
way; the child lines may not exist.

A category takes no `#` in the log — that prefix means a text channel, and
printing one sends whoever reads it hunting for a channel by that name — and the
line carries "(affects synced channels in it)", which is the operationally
important half.

**Both permission handlers report on `WATCHED_PERMS`, not on what the bot needs
where it stands.** The two questions are different: `required_perms` answers
"what does the bot need *here*" (and swaps in the thread bit inside a thread),
while `WATCHED_PERMS` is the union — everything needed in the channel plus
`send_messages_in_threads` — because a text channel governs merges in itself
*and* merges in threads under it. Without the union a category that simply never
granted the thread bit reads as fully healthy right up until a player tries to
merge in a thread.

`on_guild_channel_create` uses it for the same reason and is the better of the
two places to catch it: game channels are created by the other bot, so that
handler is **already a per-game permission audit running on its own**. A
category missing the thread bit is then reported once per channel at creation,
which is where an operator can act on it, rather than being discovered by a
player whose merge could not be posted.

Screenshots reach a merge one of two ways: attached to the command itself —
`!merge 20` with the shots attached to that same message — or, when players
just post their shots as separate messages into a thread over time
(interleaved with unrelated chatter/images), by reacting 🗺️ on each screenshot
and then running `!merge 20` with no attachments. In that second case the bot
scans the channel/thread history for 🗺️-marked images and, after a successful
merge, reacts ✅ on each source message so a later merge in the same thread
doesn't re-merge them. The reactions *are* the state — this still isn't the
bot accumulating a session across messages in its own memory, which was
considered and rejected in favor of one-message-in/one-composite-out; marking
via reactions keeps that property (no session to leave open, no window to
manage) while still letting a thread fill up naturally.

**The ✅ is applied at the *end* of a merge, and that ordering is deliberate.**
It is the only thing making a merge idempotent, so marking at scan time instead
looks tidier and is much worse: a merge that then fails or gets dropped would
leave its shots marked consumed, the retry would find nothing, and the player
would have to un-react every screenshot to recover — silent data loss traded
for tidiness. The visible consequence of marking late is that two merges started
in one channel seconds apart both see the shots unmarked and produce the same
composite twice. That is degenerate rather than a defect: a channel is one game,
so a second simultaneous merge has nothing to add, and it costs a duplicate
image rather than a wrong map. Don't "fix" it by moving the mark.

**And "at the end of a merge" now means after the composite was actually
delivered — the same argument, one step further.** The paragraph above rules out
marking at scan time because a merge that then fails would leave its shots
marked consumed; the residual case is marking at the end but after a *failed
post*, which has the identical consequence and was live until recently.

The two steps need **different permissions**, which is what makes it reachable
rather than theoretical: posting needs `SEND_MESSAGES`
(`SEND_MESSAGES_IN_THREADS` in a thread) while reacting needs `ADD_REACTIONS`,
and a thread inherits the latter normally. So "posted nothing, reacted fine" is
an ordinary state. `Caller.send` swallows a `Forbidden`, logs it and returns
`None` — which from the caller's side is indistinguishable from success — and the
✅ loop ran unconditionally on the result. The player got no composite, every shot
was checked off as already merged, and re-running answered *"No usable screenshots
found"*, with no remedy but to hunt up the channel un-reacting by hand.

The fix is to gate the loop on `Caller.send`'s return value, and the console says
so when it fires. Note the two front ends differ in how bad the silent case is:
on `/merge` the player at least gets `Caller.send`'s ephemeral fallback naming
the missing permission, while `!merge` leaves them with nothing at all — which is
an argument for the gate, not against it, since the marks are destroyed either
way. It stays best-effort *within* the delivered case: a missing `ADD_REACTIONS`
must still not fail a merge that did reach the channel. The general lesson is
worth keeping: **a helper that swallows an error must not return the same thing
on success and failure if any caller acts on what happened.**

**There are two front ends, `!merge` and `/merge`, and they differ only in how
the options arrive.** `!merge [size] [layers...]` parses free text; `/merge`
takes the same two as typed options that Discord validates and describes at the
point of typing. Both call `do_merge`, which is what keeps them on **one**
queue: `MERGE_LOCK`, `_waiting`, `_running_*` and `merge_speed` are module state
reached only through that function, so a `/merge` queues behind a `!merge` and
`wait_estimate` covers both. Do not give either front end its own path to the
semaphore.

**`/merge` deliberately takes no attachments — it is the reaction workflow
only.** A slash command has no variadic attachment option, so parity with
`!merge`'s drag-and-drop would mean `MAX_SHOTS` separate `shot1..shot8` slots
cluttering the picker and one file dialog each. `!merge` keeps that job, where
dropping four files onto one message already works well. The reaction path is
the one most players use, so this costs the common case nothing — and it is the
path slash commands suit best, since everything a player supplies there is an
option rather than a file. `Caller.can_attach` is what player-facing copy keys
on, so the "no screenshots found" reply does not tell a `/merge` user to attach
files to a command that cannot carry them.

**Three things slash commands do *not* change, all of which look like they
should.**
- **Guild operators still grant the same five `REQUIRED_PERMS`, in the same
  channels.** The composite is an ordinary channel message either way. What
  changes is only the *diagnosis*: an interaction is delivered to the
  application directly, so `/merge` arrives whatever the channel overwrites say
  and the bot can answer ephemerally naming the permission it lacks. That is the
  one improvement on the failure this file records as unfixable — someone edits
  an overwrite, the bot loses `view_channel`, and `!merge` produces no event at
  all. *Considered and rejected:* posting the composite through an interaction
  followup would bypass `send_messages`/`attach_files`, since interaction
  responses are exempt from channel permission checks. It saves two of five
  permissions and buys them with the token expiry below.
- **`message_content` is still required.** `collect_marked_shots` reads
  `message.attachments` off arbitrary history messages, and that privileged
  intent gates attachments exactly as it gates content. Shedding it is the usual
  headline reason to migrate to slash commands and it does not apply here.
- **Nothing was deleted.** `parse_overlays`, the alias table, the legacy
  `no`-prefix words and both unrecognized-input replies still serve `!merge`.
  Discord validating the typed options means the slash path cannot *reach*
  those replies; it does not make them dead.

**The interaction token is why `/merge` uses ordinary channel messages rather
than followups, and this is the load-bearing design decision in that path.** An
interaction imposes two deadlines a channel message does not: **3 seconds** to
respond at all, and **15 minutes** for the token thereafter, after which
`edit_original_response` and `followup.send` both 404. Both bite this bot
specifically:
- The 3-second one because `collect_marked_shots` walks `HISTORY_LIMIT` = 500
  messages at 100 per API call — five sequential round trips — before anything
  is sent. Measured expectation is 0.3–0.75s from a well-connected host and
  1–2s from a loaded one, so the risk is low rather than acute. **Do not cut
  `HISTORY_LIMIT` to shrink it**: `defer(ephemeral=True)` is the first statement
  in `merge_slash`, so the deadline is already satisfied before the scan starts,
  and 500 is how far back into a chatty game thread the bot can still find
  someone's 🗺️.
- The 15-minute one because wall clock is *queue wait + downloads + merge*
  against one semaphore shared by every guild, with `MERGE_TIMEOUT_S` at 300s
  and the queue uncapped — three hung merges is the whole window. On expiry the
  composite is already on disk and is then deleted by the `finally:
  shutil.rmtree`, so the player gets a dead spinner after up to five minutes of
  CPU. That is `shrink_for_upload`'s failure arriving by another route.

So the token is used **once**, to defer, and never again; every visible message
is `channel.send`/`message.edit`. That makes expiry structurally impossible
rather than merely handled, collapses `Caller.send` to one implementation for
both front ends, and is what lets the queue notice below be edited for as long
as the queue takes. The ephemeral placeholder the deferral leaves is cleared
with `clear_placeholder` once the public ack is up — a step `!merge` has no
analog for, since it posts its ack directly.

**The queue notice updates live, and this changed `_waiting`'s contract.** It
used to hold bare shot counts, justified by "only the sum is ever read, so
entries with equal counts are interchangeable and `.remove()` by value is
exact". A waiting merge now has to find its own *position*, which a bare int
cannot supply — two 3-shot merges are the same int and different places in the
queue — so it holds `_Queued` records and removes by identity. Two details:
`refresh_queue_notices` is driven by the queue changing (fired after
`MERGE_LOCK.release()`) rather than by a timer, since those are the only moments
the numbers move; and it skips the edit when the rendered text is unchanged,
which keeps it clear of Discord's per-channel edit rate limit for free, because
`human_wait` already rounds to 5-second buckets under a minute and whole minutes
above. A notice whose text comes back `None` has reached the front and is left
alone deliberately — its own `MERGE_LOCK.acquire()` writes `starting_text()`
over it a moment later, and editing it to "your turn" first would put two
messages where the player needs one.

**`MAX_QUEUE_WAIT_S` refuses a merge that would wait more than ~10 minutes.**
The queue is unbounded and serialized across every guild, so without it a player
can be committed to a wait far longer than the merge is worth, having been shown
the number only after they were already in it. It benefits `!merge` equally —
the problem is pre-existing and `!merge` merely hides it by never expiring. Read
it as a bound on the absurd, not a scheduling policy: the estimate behind it is
rough by construction (board content matters nearly as much as shot count) and
should not be tuned as though it were not.

**Command sync is the bot's only deploy-time state, and `Dockerfile`/
`.dockerignore` is the cautionary precedent.** `setup_hook` syncs the tree —
globally in production, or to `POLYMERGE_DEV_GUILD` when that is set, which is
instant and is what a beta instance should use. The signature then lives on
Discord's side, so a container running old code can leave a command shape
published that it no longer implements: the same class of failure as the image
that shipped without `Overlays/`, a deployment quietly disagreeing with its
source. `on_ready` therefore prints what actually synced rather than assuming.
A failed sync is logged and non-fatal, since `!merge` does not need the tree.

**Whether a guild can see `/merge` at all is not observable from inside the
bot.** Slash commands appear only in guilds that authorized the
`applications.commands` scope, and a bot invited with `bot` alone sees no
commands however cleanly they synced — indistinguishable from a sync failure.
The fix is re-authorizing that guild through an OAuth2 URL carrying the extra
scope, which **does not kick the bot or reset its roles and overwrites**. This
also makes the rollout safe rather than risky: the code deploy and the
user-visible change are decoupled, so `/merge` can ship to production invisible
everywhere and be enabled per guild afterwards, with no flag day.

**`COMMAND_PREFIX` is env-overridable (`POLYMERGE_PREFIX`) so a second instance
can run in a guild that already has one.** A beta bot otherwise answers the same
`!merge` as production; give it a different prefix, and different
`POLYMERGE_MARK_EMOJI`/`POLYMERGE_DONE_EMOJI` so the two do not race on the same
🗺️ reactions. `/merge` does not collide — Discord disambiguates slash commands
by application in the picker.

**The board size is a command argument but no longer a required one.** `!merge
20` still works and is still obeyed outright; a bare `!merge` measures the size
instead (`detect_map_size`, above), which is a measurement rather than a guess
and refuses rather than defaulting when the shots cannot answer. polymerge's
refusal text goes straight to the channel, so a player whose shots don't span
the board is told to state the size. The caption reports what was measured
("Board measured as 20x20") — the size is the one input a player would
otherwise have supplied, and the one whose being wrong ruins a merge
invisibly, so stating it lets them catch a wrong board before trusting the
composite. The console line records it too, tagged `(detected)`.

Two details in `run_polymerge` follow from this: a `map_size` of None omits
`--template` along with `--map-size` (without a size there is no template to
name), and polymerge therefore has to find its own — which is why
`template_path_for` and `overlay_path` both fall back to the script's
directory, since the bot runs polymerge with `cwd` set to a per-merge temp dir.

**The sizes are 11, 14, 16, 18 and 20** (`MAP_SIZES`, kept in step with
polymerge's `MAP_SIZE_CHOICES`; 30 is deferred — see the `Overlays/` section).
`template_for` resolves `Overlays/<name>-blank.png` and nothing else; the old
`template_NxN.png` fallback is gone with the files. Two bits of channel copy
had to change for five sizes rather than two: the unrecognized-size reply lists
them comma-separated with a final "or" instead of four "or"s, and the
"board measured as" caption names **no** alternative size at all — listing five
buried the actual result, and it briefly suggested the nearest one instead,
which reads as the bot holding a second guess it does not have. It now just
says to re-merge with the size stated if the measurement looks wrong.

**A bare `!merge` used to print the help text and no longer does** — it
attempts a merge. Spending the shortest form of the command on help cost the
common case (shots attached, wanting a merge) an extra round trip once the
size became measurable. `!merge help` (or `!merge ?`) still prints it, and the
two replies a lost player actually reaches — an unrecognized size, and "no
usable screenshots found" — both name it, which is the moment it is wanted.
`help_text` interpolates the configured emoji, prefix, sizes and limits rather
than hardcoding them.

**The help command's name is `HELP_COMMAND`, and the first name it had was a
trap worth recording.** It was `merge-help`, and `merge` is a strict prefix of
that — so typing `/merge` matched *both* commands and Enter took whichever
Discord had highlighted, which on the beta bot was the help. The ranking rule is
undocumented and evidently personalized, so it converges on the right answer for
a player who merges often and is wrong for one who has never run either — i.e.
exactly the person least able to tell the picker mis-fired, and the person a
shared community bot sees most of. Do not rely on the ordering settling; make
the collision impossible, which is the same call as using channel messages over
interaction followups for the token.

**`polymerge-help` does not escape the collision, and that is now measured
rather than assumed.** Typing `/merge` in a real guild lists both commands, so
the picker matches a **substring** of the command name — "merge" is inside
"polymerge-help". Only a name with no "merge" in it (`polyhelp`) would separate
them, and changing `HELP_COMMAND` is the whole edit.

It is kept anyway, as the project owner's call: the *ranking* appears to favor
prefixes, so `/merge` sorts above `/polymerge-help` and Enter takes the right
one. Note what that concedes — the guarantee is now "the ordering happens to
work" rather than "there is nothing to order", which is a weaker thing than the
rename set out to buy, and it depends on behavior Discord does not document.
If a report ever comes in of Enter landing on the help, that is this, and the
fix is one constant.

Either way `/merge`'s **own description names the help command**, and that is
where most of the discoverability lives: the picker shows that line while
someone is typing `/merge`, which is exactly where a player who needs the
instructions already is. It costs nothing and survives any rename.

**`/polymerge-help` exists because the option descriptions carry only half the
help.** Discord renders the command and per-option descriptions inline as you
type, so under `/merge` the board size and the four layers document themselves —
that part of `help_text` is redundant there. Everything else in it has nowhere
to appear: the 🗺️/✅ workflow, `MAX_SHOTS`, the accepted formats, the
two-adjoining-edges rule, the 15% crop, the purple ruin outlines, the
winner-selection summary and the credits. Hence a command of its own, replying
ephemerally — someone reading the instructions does not need to post them into a
game thread. The "no screenshots found" reply names **both** routes to the help,
because which one is reachable depends on whether that guild authorized slash
commands at all.

**A board with no fog merges on the plain command, as long as the size is
stated.** `!merge 16` works on a replay; nothing in polybot special-cases it.
The rule lives in polymerge and is described in the anchoring section: a run
where nothing locks refuses when the size was *detected* and warns when it was
*stated*. Bare `!merge` on such a board still refuses, and correctly — the size
is measured from the fog's repeat, so a board with no fog cannot be measured,
and `detect_map_size` says exactly that.

**Both of polymerge's size warnings reach the channel** (`size_unconfirmed`,
`size_suspect`), and for a long time neither did. They are printed on a
*successful* run, where the bot posts no stdout at all and its console filter
matched neither — so a merge at a mistyped size came out looking entirely
normal, with the one signal that could have caught it discarded. `help_text`
had promised for just as long that the bot "will say so".

Prefer the conflict-fraction one when both fire: it is polymerge's backstop for
a stated size nothing else could check, and it measures what an out-of-phase
lattice actually *did* rather than reporting that the usual check could not run.
`tests/pol_archi_test` at `--map-size 20` produces both (70% against the 18%
bar) and `tests/fogless` at 16 produces only the first, which is the honest
replay case and must stay un-alarming. Neither says *why*, for the reason the
`DROPPED` caption doesn't: nothing at that point separates "no fog left" from
"wrong size", and asserting the first tells a player who mistyped the size that
all is well.

This was briefly built the other way, as an opt-in `replay` word that passed
`--min-fog-lock 0`. It is recorded here because the reasoning for it was wrong
in an instructive way: "every shot locked 0" does have exactly two causes and
the run genuinely cannot tell them apart, but that argues for asking *who
claimed the size*, not for adding a word. It also made the rare case cost two
pieces of knowledge the player might not have.

`--ruin-vision` and `--city-bars` are passed on every merge rather than
exposed as command arguments: each detects nothing when no relevant content
is present (verified across the test corpus), so there is no wrong answer to
guess at, and asking players to know their teammate's tribe would be one more
way to get a merge subtly wrong. The per-tile reports go to the bot console
with the fog-lock line; the channel gets one plain sentence appended to the
merge caption when ruins were marked, since a yellow outline means nothing to
a player who has never seen one.

**The decorative layers *are* exposed, unlike those two, because there is no
right answer** — whether a grid helps depends on what the player is reading the
map for. `!merge [size] [layers...]` takes them as trailing words in any order:
a bare word switches a layer on (`grid`, `spawns`, `push`, `shade`). **Nothing
is on by default** — a merge nobody asked a question of hands back the map as
the game draws it. `shade` was on by default once, and the cost was not the
shading but the second thing every player then had to learn in order to turn it
off. `no`-prefixed words (`noshade`) and `plain` still parse, and are
deliberately no longer named in the help or in the unrecognized-word reply:
with an empty default they remove nothing, but a player who learned `noshade`
under the old behavior should get a merge rather than an error. Each layer now
gets a one-line explanation in `!merge help`, built from `OVERLAY_HELP` so the
help cannot name a layer the parser rejects or miss one it accepts. Three
details in `parse_overlays` and the command signature:
- **The board size is a word like any other, not a position.** It is the first
  digit-only word *wherever it sits*, so `!merge grid 20` and `!merge 20 grid`
  are the same command and `!merge grid` means "measure the size, add the
  grid". Position-based parsing looked equivalent and was not: only the first
  argument was tested, so a trailing `20` reached `parse_overlays`, which
  strips non-letters, left an empty stem, and came back as an unrecognized
  word. The help tells players the layer words go in any order and they
  reasonably assume the number does too. A *second* number is deliberately not
  consumed — `!merge 20 16` is ambiguous, so the spare falls through to the
  unrecognized-word reply rather than one of the two being picked silently.
- **Synonyms are accepted** (`shading`, `checkerboard`, `zones`, `arrows`, …)
  and case and punctuation are stripped. This is typed into a chat box, not a
  shell, and a player who guesses a reasonable word should not get an error.
- **An unrecognized word is an error, not a silent ignore.** Silently dropping
  a typo'd layer would mean the player gets a composite missing the thing they
  asked for and no reason why.
Layers a board size does not have are skipped rather than refused, and the
caption says which — `skipped_overlays` lifts polymerge's `NO-OVERLAY` line.
A player who asked for the grid and silently got none would reasonably assume
the merge went wrong.

**The image must ship `Overlays/` and `Assets/`, and `.dockerignore` is half
of that.** The Dockerfile used to copy `template_18x18.png`/`template_20x20.png`
and *not* `Overlays/`, so the deployed container ran on the legacy fallback:
`!merge 11/14/16` refused outright, no decorative layer worked at any size, and
18 and 20 registered against different fog art from every other size. Deleting
those two files removed the fallback, so a container missing the renders now
refuses at startup rather than merging wrongly.

The trap worth remembering is the second half. `.dockerignore` carried a
blanket `*.png` (to keep the ~100MB of test screenshots out) with
`!template_18x18.png` / `!template_20x20.png` exceptions — so once those two
files were deleted, adding `COPY Overlays/` and `COPY Assets/` to the Dockerfile
copied **nothing at all**, and the fix read as complete while shipping an empty
image. `tests/` and `shoreline/` are already excluded wholesale, so the `*.png`
rule was redundant as well as harmful; it is gone and should not come back.

It calls `polymerge.py` as a **subprocess**, not an import. polymerge is a
CLI: it reads `sys.argv` and reports every failure via `SystemExit`.
Importing it would mean catching `SystemExit` throughout and sharing a
process with OpenCV for a ~15-20s CPU-bound job that would otherwise block
the bot's event loop. The subprocess gets isolation, a timeout that actually
works, and stdout/stderr for free — and polymerge's failure text (e.g. the
wrong-`--map-size` message) is passed straight through to the channel rather
than replaced with a generic error.

**A refusal is also logged to the console** (`merge FAILED:`), and that line was
missing for a long time. The error path returns before the fog-lock, dropped-shot
and ruin lines, so a refused merge left the log showing the command arriving and
then nothing at all — indistinguishable from the bot having silently dropped it,
and the explanation went only to the player who ran it, who is generally not the
person reading the log. Found in production, on a bare `!merge` over
`pol_archi_test`: the operator could see two commands and one composite, with no
way to tell which of the two very different refusals had fired. That matters
because the two want opposite advice — a board with no fog left cannot be
measured at any zoom, whereas a board no shot spans just needs zooming out — and
`_no_measurement_reason` distinguishes them precisely so the right one is said.

**polymerge's refusal text *is* channel copy, so it may not name a command-line
flag.** This is the whole reason `SystemExit` messages are passed through rather
than replaced — but it cuts both ways: `Pass the size explicitly (--map-size 11
or 14 …)` was reaching players as the headline of the commonest refusal, and a
player has no command line to pass anything on. The bot's own equivalent is a
bare word (`!merge 20`), and telling someone to type `--map-size` sends them
looking for something that does not exist in Discord.

`size_list()` and `RESTATE_SIZE` in polymerge are the one remedy sentence all
five size refusals end with — *"Please retry including the map size (11, 14, 16,
18 or 20)"* — kept in one place so they cannot drift apart, since to the player
they are the same sentence whichever internal check produced them. `size_list`
uses polybot's comma-then-"or" shape for the same reason polybot does: four
"or"s read badly at five sizes. Nothing is lost on the CLI side, where `--help`
and the usage line already document the flag to the only person who can use it.

Three conventions come with it, and the third is the one that keeps being
relearned:
- **The first line carries the cause *and* the remedy; measurements go below,
  if they go at all.** polybot promotes line one to the headline and renders
  the rest in a code block, so a per-shot table in the headline buries the
  answer. Several refusals were rearranged for this, not just reworded — and
  the wrong-stated-size one then had its code block dropped outright, since
  every shot already prints its own *"board size implied by span/fog-period"*
  line to stdout during anchoring. **Check stdout before writing a second
  line**: the diagnostic is usually already there, and a code block in the
  channel is a cost paid by every player to serve nobody.
- **Only offer a remedy that can work.** The no-fog refusal deliberately does
  *not* suggest re-photographing the board — there is no fog to bring back — and
  the no-span one does, because a wider shot really is the better fix. This is
  the same distinction `_no_measurement_reason` exists for, now visible in the
  advice rather than only in the diagnosis.
- **The cause is not the *mechanism*.** The first pass at this shipped
  *"no screenshot spans the whole board, so there is nothing to count the tiles
  across"* and *"these screenshots have no fog left to measure the board
  against"*, plus a line explaining that the fog's repeat is used as a ruler.
  All of that is this file's business, not the player's: they cannot act on it,
  and a smart player infers the shape of the problem from the remedy anyway.
  The clauses are gone — *"no screenshot spans the whole board"*, *"these
  screenshots have no fog left to measure"* — and the reasoning lives in the
  code comments where it was always meant to. **This is the failure mode to
  watch when adding a refusal here**: explaining the merge to someone who only
  wants their map back is the natural thing to write and the wrong thing to
  send.

The same sweep removed internal vocabulary from the refusals that had it
(*"every input was dropped as misanchored"*, *"detected a 15x15 board, but the
only templates available are…"*). **Never name a template, a board render or an
`Overlays/` file in channel copy**: players have no idea the merge registers
against blank board images and do not need one — an install fault reads to them
as *"can't merge 20x20 right now, ask whoever runs the bot"*, with the filename
logged to the console where the person who can fix it is reading. polybot's two
replies used to name `huge-blank.png`; polymerge's two now say only that it is
not installed correctly. `--single`'s message still names its
flag, correctly: nothing but a command line can reach it.

**Oversized composites are re-encoded, not refused** (`shrink_for_upload`).
The composite is a little under the template's own size (2880x1800 at 20x20)
and a densely-explored board makes a big one — the largest in the corpus is
**4.6 MB** against Discord's default per-file limit, which is **10 MiB**
(`MAX_UPLOAD_BYTES` is set to 10e6, deliberately just under it). The composite
was also 5.7 MB before the `Overlays/` renders replaced the larger old
templates, so the fallback should still rarely fire — but the margin is 2.2x,
not the 4x this file used to claim.

**That claim was wrong in the one direction that matters, and it is worth
knowing why.** This section read "**20 MB** as of August 2026 (it was 8 when
this was written, then 10)", i.e. a limit assumed to ratchet upward, so the
constant was set to 20 MB — nearly twice what Discord actually accepts. Checked
against the official API documentation, the default went **25 MiB → 10 MiB on
16 January 2025** and has not moved since; there is no 20 MB anywhere in the
change log. Nothing in the corpus reaches either number, which is exactly why
it sat unnoticed: the guard was inert at 4.6 MB and would have stayed inert
right up until the first composite between 10 MiB and 20 MB, which
`shrink_for_upload` would then have waved through to a failed upload after the
merge had already cost ~20s. **Do not re-raise this on the assumption that
limits only grow.**

Two related facts from the same source, both now recorded in the code. Since
April 2025 the limit is checked **per attachment** rather than per message,
which for this bot is the same thing — it uploads exactly one file. And the
25 MiB in `MAX_ATTACHMENT_BYTES` is a different quantity that happens to be a
documented one: the maximum *request* size for sending a message, hence a
ceiling no attachment a player posted can have exceeded.

It is kept because none of this is under this program's control: the limit has
moved in both directions, a merge can be posted somewhere with a lower one, and
it will bind if 30x30 is ever enabled, since that renders at 4500x3000, ~2.6x
the pixels of 20x20 — enough on its own to put a dense board over the ceiling. `MAX_UPLOAD_BYTES` is deliberately one fixed number rather than the guild's
real limit. A boosted server's is higher and discord.py would supply it as
`Guild.filesize_limit`, but one bot serves several servers and this figure is
channel-facing copy — per-guild it would quote a different limit in each one.
Don't "fix" it into a lookup. Blowing it would be the worst way to fail: the
merge has already succeeded and cost ~20s, and the player would get nothing.
So the bot falls back to JPEG, which on that same composite gives 1.4 MB at
quality 95 — a 4x reduction at a mean absolute error under 1/255, invisible
on the game's flat color art. The lower quality rungs should never be
reached; they exist so a pathological board degrades instead of failing. Two
details worth keeping: OpenCV is imported inside that function rather than at
module scope (the event loop should not carry it for a path that almost never
runs), and the upload uses `out_path.name` rather than a hardcoded
`merged.png`, or a JPEG would go out with an extension that lies about it.

**New channels are picked up live; silence there means permissions.**
discord.py updates its channel cache from the gateway, and nothing in polybot
caches or gates on a channel list — `on_ready`'s listing is a startup *log*,
not state — so a channel created after the bot started works without a
restart. When the bot appears to ignore a channel it is essentially always a
permission overwrite, usually inherited from the category. The console
distinguishes the cases, which is the whole point of the logging there:
- **Nothing printed at all** when someone types `!merge` → the bot never
  received the message, i.e. no `view_channel`. **This failure is
  unobservable from inside the bot and has no fix** — Discord simply stops
  delivering messages, so there is no event, no context to reply in, and no
  way to know anyone tried. It has happened in production, from someone
  editing an existing channel's overwrites. All that can be done is catch the
  permission change *as it happens*: `on_guild_channel_update` logs whenever
  the bot's own required permissions in a channel change,
  `on_guild_channel_delete` covers losing sight of a channel (which looks
  identical to deletion from the gateway), and `on_guild_channel_create`
  reports each new channel. Between them the console gets a timestamped line
  naming the channel, which is the difference between an investigation and a
  lookup.
- **The `!merge ... :` line prints, followed by a `MISSING` report** → the bot
  saw it and cannot answer. `say()` catches the `Forbidden` rather than
  letting it escape; without that, a missing `send_messages` raised inside
  `on_command_error` — the error handler failing while reporting an error.

**In a thread the permission that lets the bot post is not `send_messages`**
(`THREAD_PERM_SWAP`, `required_perms`). Threads inherit the parent channel's
permissions with exactly one exception, and this is it: per Discord's docs,
`SEND_MESSAGES` "has no effect in threads" and `SEND_MESSAGES_IN_THREADS` is
the bit that governs. discord.py's `Thread.permissions_for` returns the
*parent's* `send_messages` untouched, so reading it in a thread answers a
question about a different channel.

That went unnoticed because it never breaks a merge — it breaks the **console
line that explains why a merge did not happen**, which this section exists to
make trustworthy, and it was wrong in both directions. With `SEND_MESSAGES`
allowed on the parent and `SEND_MESSAGES_IN_THREADS` denied, `say()` caught the
`Forbidden` and then printed *"all required permissions present"*. With the
parent's `SEND_MESSAGES` denied but thread posting allowed, it reported a
missing permission the bot neither needed nor lacked. Note the first case was
not wholly silent: discord.py zeroes `attach_files` when
`send_messages_in_threads` is unset, so it surfaced as a missing `attach_files`
— which sends whoever is reading the log to the wrong permission entirely.

**Threads are the occasional path, not the normal one** — a game gets its own
channel (see the deployment note above), so most merges never touch a thread and
the ordinary `send_messages` check is the one that applies. But the thread case
is worse than its frequency suggests, for a reason that comes straight from the
deployment: the bit that governs it is set on the **category**, so if that
category grants Send Messages without Send Messages in Threads, *every* game
channel in that team server carries the gap, and every player who tries to merge
in a thread hits it. It is rare per merge and systematic per server.

`attach_files` is worth calling out: without it every merge succeeds and then
fails at the upload, after ~20s of work.

**The message-content intent gates `attachments`, not just `content`**, and the
two failures look different. Without it `message.content` arrives empty so
`!merge` never parses and the command silently never fires — but
`message.attachments` arrives empty on other people's messages too, so
`collect_marked_shots` walks a thread full of marked screenshots and reports
finding none. That second one is the misleading half: the bot is plainly alive
and answering while insisting the shots are not there. Note also that once the
app is verified the intent must be *applied* for, not merely checked in the
developer portal.

**Merges are serialized, and a player waiting behind one is told roughly how
long.** A merge is charged `MERGE_FIXED_S + MERGE_PER_SHOT_S * n`, and the ack
carries that estimate whether or not anyone is queued (`starting_text`), while
someone behind other merges gets their position and the sum over the queue
(`wait_estimate`). Three things about it are deliberate:

- **The intercept is real and the model used to lack it.** The estimate was
  `n * rate` with `rate` learned as `held / n`, so a deque mixing 2-shot and
  8-shot merges converged on a per-shot figure right for neither. Template load,
  process start and output encode do not scale with `n`. Measured at ~1.5s,
  about 8% of a 4-shot merge — smaller than it first looked, and positive, which
  the first attempt at measuring it got wrong.

  **Measure it on one board at a time**, by merging the same set's first 1..k
  shots: `archers_test2` fits `1.83 + 4.38n`, `test_screenshots` `1.47 + 4.61n`,
  `goon_test` `1.22 + 3.65n` (18x18, and cheaper per shot — board *size* moves
  the slope by ~20%). Regressing `tools/baseline.py --jobs 1` across the corpus
  instead is the obvious move and is **confounded**: the 2-shot sets are also the
  cheaper boards, so board content masquerades as shot count and the intercept
  comes out at **−2.3s**. That fit is excellent over n = 2..5 (R² 0.92) and
  nonsense outside it — it predicts 42.5s at `MAX_SHOTS` against the honest
  36.7s, and no corpus set has more than 5 shots to catch it.
- **Only *one* number is learned on the deploy host** (`merge_speed`), a
  multiplier on the whole estimate. `a` and `b` describe the algorithm, which is
  the same wherever the container lands; what is unknown is the host's speed.
  That is not just tidier — one factor is learnable from the first completed
  merge at any shot count, where refitting both terms needs merges at two or more
  distinct counts before it means anything, and fits them badly from ten noisy
  samples even then. **Don't "improve" this into a two-parameter online fit.**
- **The aggregate is a median, and the sample is clamped.** The samples have a
  long tail on one side only — a merge can be arbitrarily slow (a fog-heavy
  board, a loaded host, a hang running to `MERGE_TIMEOUT_S`) and cannot be faster
  than the work. Measured: averaged, one clamped 300s timeout sample takes the
  factor to 1.93 and nearly doubles every estimate for the next ten merges; with
  a median it is outvoted by the third sample. The clamp still earns its place,
  since with one sample the median is that sample.

It is all in memory, so a restart falls back to the seed — which keeps the "no
persistent state, no volumes" property the Dockerfile's opening comment states,
and a fitted constant is not worth breaking that for. Expect the estimate to be
rough by construction: board content matters nearly as much as shot count
(`badland_test2` takes 40.5s at n=2 where `goon_test` takes 16.2s), and nothing
here chases that residual.

Other design points: attachments are saved under an index-prefixed,
sanitized filename (`00_imp.jpg`, `01_q.jpg`) — this closes a path-traversal
risk from user-supplied filenames, and also stops two attachments that
happen to share a basename from colliding, since polymerge keys its
per-image dicts on basename. Merges are serialized behind a semaphore, since
concurrent merges are CPU-bound and would only make each other slower — see the
wait-estimate note above for what a queued player is told.
For testing bot-side logic without a live server, drive `run_polymerge`
directly — it reproduces polymerge's behavior, including failure text
passthrough, with no Discord connection.

## What the game guarantees

These are established facts about Polytopia's renderer, confirmed with the
project owner — not inferences from the screenshots. Most of the pipeline is
built directly on top of them, so if one turns out to be wrong, the code that
exploits it has to change with it.

- **The camera is fixed orthographic isometric and never rotates.** Zoom is
  continuous (pinch), within limits. Two views of one board therefore differ
  by pan + zoom only — a 4-DOF similarity, never a homography.
- **The board is always a full NxN diamond.** Never clipped, never missing a
  corner, always square.
- **A tile's footprint is constant but its height is not.** The width:depth
  ratio of a tile's top face is a fixed constant of the projection, but every
  tile is a 3D box whose *height* depends on its content: a fog cube stands
  taller than a plains tile, which stands taller than water — and **shorter
  than a mountain or a large city**, so fog sits in the middle of the height
  range rather than at the top. That ordering matters wherever a rim tile's
  top face is the evidence; see the edge bullet below. Three consequences
  run all through this codebase — a board silhouette includes a side wall and
  so overstates the board's extent; tall content is drawn extending toward the
  viewer, so mountains slightly occlude and large cities can wholly occlude the
  tile(s) *north* of their own; and the four board edges are not equally good
  evidence (next bullet).
- **The two bottom edges are the good ones, but only against a matching rim.**
  The boxes stand on a common base, so the SE and SW silhouette edges show that
  base rather than a tile top, which makes them far better evidence than the NW
  and NE edges — those are the rim tiles' *top* faces and so sit lower in a
  screenshot than in the all-fog template wherever the rim has been explored.
  In the oblique basis `dir_a` points southeast and `dir_b` southwest, so
  **a-min = NW, a-max = SE, b-min = NE, b-max = SW**; the max-offset edge of
  each pair is the bottom one. Per-edge error against the refined anchor over
  all four sets: SE 1.2px std / 2.8px worst, against NW's 6.3px / 19.8px and
  NE's 4.6px / 15.4px.
  They are *not* pixel-exact, though, and the reason is that a fog cube's
  bottom lip is drawn with an uneven, scalloped silhouette where explored
  terrain has a clean straight one. The template is all fog, so a bottom edge
  matches it almost perfectly when that shot's rim is also fog, and is offset
  when the rim is explored.

  **That offset was once recorded here as one pooled number (-0.8px for fog
  rims against +7.0px for explored ones, correlation -0.80, "not yet
  demonstrably a single constant"). It is not one number, and it is not one
  mechanism** — the pooled figure was averaging four edges of two different
  kinds with *opposite signs*. Measured per edge over 210 well-supported edge
  observations across 24 sets (residual against each shot's own fog-refined
  anchor, restricted to shots locking >= 20 fog tiles so the reference means
  something):

  | edge | corr(rim fog, error) | fog rim | explored rim | slope per unit rim fog |
  |---|---|---|---|---|
  | SE `a-max` (bottom) | **+0.88** | +0.43 ± 0.59 | -2.11 ± 0.60 | **+3.02 px** |
  | SW `b-max` (bottom) | **+0.92** | +0.87 ± 0.97 | -6.55 ± 0.86 | **+8.11 px** |
  | NW `a-min` (top) | -0.81 | +1.06 ± 1.14 | +13.32 ± 3.97 | -12.08 px |
  | NE `b-min` (top) | -0.55 | -0.84 ± 0.65 | +6.74 ± 0.88 | -7.03 px |

  **Only the bottom pair is a function of the rim's fog fraction.** They show
  the common base plane, so tile *height* cannot reach them and the only
  fog-vs-terrain difference is the scalloped lip — a shape term. Their residual
  after a linear fit is **0.56px (SE) and 1.38px (SW)**, and the spread *within*
  narrow fog-fraction bins is 0.49-0.70 on SE at every bin, which is the real
  test: the fraction determines the offset.

  **The top pair is not a function of it, and cannot be made into one.** Their
  within-bin spread runs to **8.30px (NW) and 6.48px (NE)** — at the same rim
  fog fraction. The worked cases: `goon_test2/imp` NE at 0.36 reads **+14.11**
  while `badland_test2/yad` NE at 0.29 reads **+0.64**; `control_d/one` NE at
  0.62 reads **+15.20** while `archers_test2/yad` NE at 0.62 reads **-4.28**.
  Same fraction, opposite signs.

  The reason is a height fact this file states but which is easy to over-read:
  fog is taller than plains and water, and **shorter than mountains and large
  cities** — it sits in the *middle* of the height range, not at the top (which
  is why tall content occludes the tile north of its own at all). A top edge
  shows the rim tiles' top faces, so an explored rim can sit either below fog
  (plains, water → positive error) or above it (mountains, cities → negative),
  and "how much of this rim is fog" cannot tell you which. Distinguishing them
  needs terrain classification, which is the one thing this codebase has a
  standing decision against. So the top edges are not correctable by this route,
  and this is *why* they are the bad edges rather than merely that they are.

  **A correction was fitted and withdrawn; don't rebuild it.** The obvious
  payoff is the board-size measurement, since `implied_n = span/period - 0.78`
  pairs a top edge with a bottom edge whose errors have opposite signs and so
  *add*. Fitting all four edges takes the span error from mean -0.040 tiles
  (sd 0.062, worst 0.250) to mean -0.001 (sd 0.040, worst 0.172), which looks
  decisive. It is not: correcting only the half that is genuinely modellable
  gives mean -0.026, **sd 0.061, worst 0.257** — a third of the bias, none of
  the spread, and a slightly worse maximum. The entire apparent gain was the
  top-edge terms fitting a confound.

  Two things survive it. The bottom-edge model is real, and it explains the
  per-edge error stats above mechanistically rather than descriptively. And the
  documented "18-boards all read slightly low, so `BOARD_SPAN_WALL_TILES` is a
  touch large there" is at least partly *not* the wall constant: the raw span
  error has a real -0.040-tile mean, and the worst contributors are
  `goon_test`/`goon_test2` `q.jpg` at -0.22/-0.24, both 18-boards with a 0%-fog
  NW rim against a 100%-fog SE rim. Unexplained and worth knowing: SW's slope is
  2.7x SE's despite both being base edges, and the slopes are well determined
  (within-bin sd 0.15-0.97), so the asymmetry is real rather than sampling.
  All of this also biases the *zoom*, since a span always pairs a top edge with
  a bottom one — the likely cause of the systematically positive zoom
  correction (mean +0.28%, 10 of 12 shots positive).
- **A city's sprite grows with its level**, so how far a city reaches into the
  tiles north of it is *variable*, not a constant of the projection. That is
  why `tile_top_wedge`'s fixed 55% wedge can never cover every case, and why
  the general fix for occlusion had to be `--fog-frac-margin` — comparing the
  sources against each other on the disputed tile — rather than a smarter
  geometric probe.
- **Fog artwork is completely deterministic.** One identical render per tile,
  with no per-tile rotation, jitter or variation. This is what makes
  correlation against a blank all-fog template both a reliable fog detector
  and a usable zoom/pan reference, and it is why a lattice that is even
  slightly out of period destroys the signal outright rather than degrading it.
  Fog is the *only* deterministic art on the board — see the standing decision
  against cataloging terrain.
  Note the *lattice*, though, is not fog's alone: crop fields, tile borders and
  territory dashes all repeat at the same tile step, so an autocorrelation can
  read a correct period off a frame with almost no fog in it
  (`star_change/oum.png`). That is a happy accident for `fog_period_scale` and
  a trap for anything that infers "this shot was anchored on its own fog" from
  the fact that the period was measurable — see the per-image misanchor guard.
- **Zoom limits exist and are fixed**, and the full pinch range spans
  **2.857x** between extremes — measured by SIFT between the two shots of the
  since-removed `archers_test3` set, which the owner confirmed were at minimum
  and maximum zoom. But a bound in *template* units still differs per board
  and per device, so it is not a clean constant to exploit. Observed across
  the current corpus, the image-to-template scale (`scale[n]`, the factor that
  blows a shot up to template size) runs 0.60 (`test_ss_elyruins/hood.png`,
  the most zoomed-in shot) to 1.70 (`tests/sunrise.jpg`, the most zoomed-out)
  — but that reflects capture habits as much as the game's limits.
- **Every board corner carries a lighthouse, and only the corners do.** A
  visible lighthouse is therefore an absolute landmark, unlike anything else on
  the board. It is not usable as a foundation — most screenshots do not show a
  corner — but it is the one candidate for an independent anchor check that
  does not route through the silhouette or the fog.
- **Terrain, cities, roads, ruins and territory borders render identically for
  every player**, so two shots of the same tile should agree on content. The
  known exceptions are listed under deferred work below.
- **Elyrion sees ruins through fog**, each ruin marked with a **cluster of
  several small rainbow diamonds** drawn on top of the fog cube — not a single
  diamond. Only an Elyrion player's screenshot shows these. The cluster is not
  centered on its tile and is not contained by it, but its pooled centroid does
  land inside the correct tile. Crucially the diamonds *tint* the fog rather
  than replacing it — measured over 32 genuine marker components, mean V runs
  218–247 and mean S 104–117, against fog's own V 230+ / S below 92. That
  pastel signature is what `--ruin-vision` keys on; see below.
- **The city label and the population bar are different signals, and only one
  of them is owner-only.** A city's on-screen label carries its name, and for
  some cities a `★ N`. That `N` is **the stars per turn that city generates
  for that player — not the city's level**, and it renders on *another*
  player's city too when an embassy has been built there. So `★ N` does not
  mean "this is my city" and cannot be used as an ownership test.
  **Nor does its absence mean "not my city".** Every city shows its `★ N`,
  capital or not — *unless it is under siege*, i.e. an enemy unit is standing on
  it, in which case it produces no stars and the number is hidden (confirmed
  with the project owner). So the star is missing from some of the owner's own
  cities and present on cities the owner does not own: it fails in both
  directions at once. `vengir_cultist`'s Ckdis at (12,12) is the worked example
  — a complete 4-segment bar, its owner's own capital, besieged, and no star
  anywhere in its label. See the city-bar section for why this rules out
  `Assets/star.png` as a corroborating test, and for the two further reasons it
  would fail even if the co-occurrence held.

  **The capital is marked differently, and this is the label's one reliable
  structural landmark**: a capital's name is **underlined** and carries a
  crown-in-a-circle icon at the left of the plate; an ordinary city's name is
  not underlined (confirmed with the project owner). Observed across the corpus:
  Ckdis, Tetesum, Bergo, Limlala, ~fiiba and Wego are underlined and crowned;
  Imtudis, Hest, Disth, Kegh, Bala and Gulak are not. Note the two marks are
  independent of the star — Ckdis and Wego are underlined capitals with no star
  (both besieged), and Hest and Disth are un-underlined cities with one. **One
  city per player**, so it is a landmark for a single bar, not a general anchor;
  do not build bar detection on it.
  The **population bar** drawn below the label is the genuinely owner-only
  element: an embassy shows you the stars, never the bar. Six further facts
  about the bar, all confirmed with the project owner:
  - **Its height is static relative to the tile** — measured **0.176 tile
    widths** (15.8 px at `REFERENCE_TILE_PX`) as the median over the 71
    uncontaminated complete bars in the corpus, range 13.5–19.1. Read a
    departure from that as *evidence*, not as tolerance to allow: 8 of the 79
    complete bars measure above 20, and every one is a component welded to the
    plate above it. The retired bottom-up detector's height window bracketed
    10–26 — about 5x looser than the object, on the provenance of three segment
    samples from the deleted `archers_test3`, which is the shape of mistake the
    anchor-first rewrite exists to avoid.
  - **Its width varies with the city's size and caps at a maximum** (confirmed
    with the project owner). So width cannot infer the shot's zoom, and a
    detector must not assume one fixed length. Measured over the corpus's 203
    detections the spans are bimodal — a tight cluster at **84–88** and another
    at **130–137**, nothing beyond 143.8 — consistent with a small-city length
    and a cap. **Whether intermediate widths exist between them is unresolved**:
    the 100–125 band is populated, but those may be partial detections of capped
    bars rather than genuine sizes, and pixels alone cannot separate the two.
    This file previously asserted exactly two legal lengths (~84–90 at 2
    segments, a fixed ~135 from 3 on); treat that as too rigid until settled.
  - **The segment count a detector reports is "segments it resolved", not the
    bar's true subdivision count.** Dividers do not survive every capture — at
    `vengir_cultist`'s `v2` zoom the whole bar is 66 px in the shot's own pixels
    — so the count is a lower bound and nothing should be built on it.
  - **The bar is centered on its city tile's south vertex**, sitting just above
    it (measured: bottom edge ~10px below the vertex). That is what locates the
    city from a bar, and it makes an occluded bar's true extent recoverable —
    mirror the visible side about the vertex.
  - Segments are not uniform. Observed states include a blue segment, a **red**
    segment, a white segment with a dark dot, and an empty segment; a segment
    can carry a dot in any of those colors. `beautiful_test3/ely.jpg` is the confirmed red case — the
    city at (18,13) has a complete 135px 4-segment bar reading red, white, white,
    white, with the first segment measuring BGR [72,101,232] at hue 6. **The
    semantics are not documented here and should not be guessed at** — see the
    ranking note below about why re-rendering the bar is the wrong approach.
  - Other UI (unit icons, shields) can overlap the bar, so any detector must
    tolerate partial occlusion rather than assume a clean rounded rectangle.
  There is **no tribe icon** in the city label; do not look for one.
- **The capture badge is a pin, drawn above the tile it marks, with a glow
  around it.** So a capture on a rim tile floats it out over the sky beyond the
  board, joined to the silhouette by nothing but its own halo — never assume it
  overlaps the board. Both facts matter to geometry rather than to color: the
  halo is bright enough to pass `--dark-thresh`, so anything fitting the board
  outline must exclude the badge *and* its glow (`badge_halo`), or the
  silhouette grows a bump where there is no board.
- **Ruins are never adjacent.** No two ruins occupy neighboring tiles, in
  either the edge- or corner-sharing sense. This is a placement guarantee, so
  two detections on adjacent tiles are not two ruins — they are one diamond
  cluster straddling a tile border, and must be merged (`cluster_ruin_tiles`).
  It also doubles as a free correctness check: adjacency surviving into the
  output means something upstream is wrong.
- **Cities are never within two tiles of each other, and never sit on the
  board's rim.** Both are placement guarantees (confirmed with the project
  owner), and both are used as hard contradictions in the city-bar path rather
  than as heuristics:
  - *Separation* — no two cities sit within `CITY_MIN_GAP` = 2 tiles, which is
    stronger than the "never adjacent" this file used to record. **Verified
    against the 50 confirmed cities in the ground-truth table: the minimum
    Chebyshev separation is exactly 3 on every labeled set, never 1 or 2.** So
    two detections that close cannot both be real, and the weaker on the
    evidence is dropped.
  - *Rim* — row or column 0 or n-1 holds no city, so a detection snapping there
    is wrong whatever it looks like. Measured over the old detector's 203
    detections, 4 landed on a rim tile and **not one was a complete bar**. It is
    also the cheapest possible saving now that detection is anchored per tile:
    only (n-2)^2 of n^2 tiles are probed, about 80% at either board size.

  Using the separation rule the *other* way -- to stop scanning near a confident
  detection, since nothing can be there -- was tried and measured inert (0.44s
  against 0.46s on a 5-shot merge). There is little to save, because the color
  test already rejects most tiles before any geometry runs, so the tiles a skip
  would remove are the cheap ones.

  Note this is the same shape of reasoning as the ruin rule above — a placement
  guarantee turned into a correctness check — and it is the cheapest kind of
  evidence available here, because it needs no new measurement at all.

## Board renders and overlay layers (`Overlays/`)

`Overlays/` holds the blank all-fog board render for every board size, plus the
board's decorative elements as **separate alpha PNGs** rather than baked into
the fog art. `Overlays/<name>-blank.png` is the template; the rest are optional
layers `--overlays` composites onto the finished merge.

Board sizes, by the name the game gives each. The mapping is **measured**, not
assumed — feeding each blank through this program's own span/fog-period
measurement returns 11.01, 14.00, 16.01, 17.86, 20.03 and 30.05:

| size | name | blank | gridded | shaded | push | spawns |
|---|---|---|---|---|---|---|
| 11 | tiny | yes | yes | yes | — | — |
| 14 | small | yes | yes | yes | yes | 2spawns |
| 16 | normal | yes | yes | yes | yes | 2spawns |
| 18 | large | yes | yes | yes | yes | 2spawns |
| 20 | huge | yes | yes | yes | yes | 3spawns |
| 30 | massive | yes | — | — | — | — |

Facts about these files worth knowing before touching them:

- **They are drop-in templates.** RGB is 0 wherever alpha is (premultiplied
  against black), so a plain `cv2.imread` yields exactly the black-sky image the
  pipeline expects. `normal-*.png` are **16-bit** and are normalized on load.
- **Every layer shares its blank's exact pixel frame.** Verified per size: same
  canvas. So overlays need **no warping or registration at all** — `main`
  builds the composite in template space and the layers alpha-blend straight
  on. (This bullet used to add "and the grid lines land exactly on the blank's
  fog tile boundaries"; that is false for two files — see the two bullets
  below.)
- **The board's edge slope is one constant of the projection rather than a
  property of any render — but it is 0.5986, not 3:5.** `dir_a` = **30.9047°**
  and `dir_b` = **149.0953°** (`BOARD_EDGE_SLOPE`); atan(3/5) would be 30.9638°
  / 149.0362°, which is **0.059° away** and is what this bullet used to assert.
  See the standing decision on `edge_lines`, where four independent routes
  settle it and the code takes its basis from it.

  **What survives here is the agreement, not the absolute value**, and the
  distinction is the one this bullet's own caution below already draws. Measured
  on the fog-tile lattice *inside* each blank — gradient energy over the eroded interior, so
  neither the rim nor the slab's side wall votes — by maximizing the sharpness
  of the projected point profile, an estimator calibrated to **±0.001°**
  against synthetic antialiased grids. All five blanks agree to **0.0008°** in
  both families: 30.9645 / 30.9644 / 30.9643 / 30.9640 / 30.9641 for huge /
  large / normal / small / tiny. That agreement is real and is a *within-file
  relative* measurement; the ~0.06° by which those absolute numbers sit above
  the shipped constant is this estimator's own bias, which is exactly the size
  the caution below gives it. The two families meet at 118.07°, not 90 —
  never orthonormalize the basis.
- **`large-gridded.png` and `tiny-gridded.png` have one line family uniformly
  rotated; their blanks are fine.** Same projection-sharpness measurement on the
  *overlay* files: every render's b-family is right (149.0359–149.0365), but
  `large` reads **30.8823** in the a-family and `tiny` **30.7468** — one-family
  rotations of **0.081°** and **0.217°**. Run twice by different routes (a dense
  global scan over the raw alpha, and again after morphologically isolating each
  family), agreeing to ~0.001° both times.

  **Fitting each grid line separately is what makes this a diagnosis rather than
  an observation**, and it is a *within-file relative* measurement, so it
  survives that estimator's absolute bias: `large`'s 19 a-lines all read
  30.8825–30.8826 (spread ±0.0002°), and `tiny`'s read 30.7503–30.7508 over the
  first eleven with the last at 30.6946. So the whole family moved by one amount
  — not sloppy lines, not a subset redrawn.

  **Only the a-family moved, and that is the useful part.** It rules out the two
  easy explanations: an anisotropic scale (exported at slightly different x and
  y) moves *both* families by equal amounts in *opposite* directions, and a
  rotation of the whole layer moves both the same way. What fixes one family
  exactly and rotates the other is a **shear along the fixed family's
  direction** — equivalently, a grid built from two step vectors with one of them
  slightly wrong. If these files are generated, that a-direction step is the
  parameter to look at, with `huge`/`normal`/`small` as the working reference.

  Cost is **2.1px at 18x18 and 3.4px at 11x11**, corner to corner, computed from
  the angle. Nothing in the merge reads the grid, so it is cosmetic; regenerate
  those two rather than compensating anywhere in code, and never take a
  *gridded* file as the reference for the projection angle. The blanks are the
  reference.

  **Two estimators were tried here and are wrong; don't repeat either.**
  - **A comb-vs-comb phase drift test** — overlay the gridded file on its own
    blank, and compare the grid/tile phase in the near half of the board against
    the far half. It looks like the ideal check, because it measures the thing
    that actually matters, and it produced a confident table (huge −0.01px,
    large +2.74, tiny +12.01) that was written into this file as independent
    confirmation. **It is an artifact.** A comb correlated against a comb has
    near-equal peaks at *every* repeat, so which one wins is decided by noise and
    by where the correlation search is clipped: widening the window from 15px to
    a full period turns that same table into large **−38.76**, normal **+2.74**,
    tiny **0.00**. The 12.01px that made `tiny` look like it also had a
    line-spacing error was the search hitting its own limit. There is no evidence
    of a spacing error in any of these files.
  - **Local gradient orientation** reads all five *blanks* at −4.38° ± 0.006, an
    obvious constant bias from 3x3 Sobel orientation quantization. It reproduces
    the rank order and nothing else.

  **And read the 3:5 constant's precision accordingly.** The five blanks agreeing
  to 0.0008° is agreement *with each other under one estimator*, which is strong;
  the absolute tie to atan(3/5) runs through that same estimator, calibrated on
  *synthetic* grids where it recovers a known angle to ±0.001°. Real renders are
  not synthetic, and the per-line fit — differently biased — puts `huge`'s
  families 0.012° and 0.062° elsewhere. A third estimator — plain TLS on each
  grid line isolated by an oriented open — puts them at −0.016° and +0.061°,
  and reads `small`'s b-family at +0.016° where the projection-sharpness one
  read it exact. So **treat the absolute value as good to ~0.06°, not 0.01°**:
  the estimators disagree with each other by as much as the offsets anyone would
  want to measure. Only *within-file relative* comparisons under one estimator
  are trustworthy at this scale — which is what the `large`/`tiny` skew above
  rests on, and why it survives. Nothing in the code depends on the absolute
  value (see the standing decision against feeding it to `edge_lines`), so this
  costs nothing operationally; it is a caution against building a precision
  claim on it later.
- **The silhouette is a 3:5 diamond squashed vertically by ~0.23%, and one
  constant describes all four of its edges.** This was measured to test whether
  the *screenshots'* board edges could supply a cleaner "true" angle than the
  gridded overlays do — the idea being that the two bottom edges are the clean
  base plane (see the game-facts edge bullet) and each must be parallel to the
  top edge opposite it. Fitting each silhouette edge as a free-angle TLS
  (iterative outlier trim, ends trimmed 10%) on the blanks:

  | render | NW | SE | NE | SW | implied squash `k` |
  |---|---|---|---|---|---|
  | `huge` | +0.064 | +0.070 | −0.055 | −0.054 | 0.9976 (spread 0.0006) |
  | `large` | +0.049 | +0.041 | −0.049 | −0.062 | 0.9980 (0.0008) |
  | `normal` | +0.056 | +0.052 | −0.057 | −0.061 | 0.9978 (0.0004) |
  | `small` | +0.047 | +0.093 | −0.060 | −0.068 | 0.9974 (0.0018) |
  | `tiny` | −0.077 | −0.081 | −0.196 | −0.199 | — (0.0111) |

  Degrees from exact atan(3/5); `k = |tan(measured)| / 0.6`. That is a reference
  datum here, not a claim — the whole point of the table is that the edges do
  *not* sit at atan(3/5). **Opposite edges
  are parallel to ≤ 0.013°** on every render but `small` (0.046° on its
  a-pair), so the premise holds and the silhouette really is a clean
  parallelogram. The two families then sit off atan(3/5) with *opposite* signs
  and near-equal magnitude, which is the signature of a vertical scale rather
  than a rotation, and one `k` per render reproduces all four edges to
  0.0004–0.0018.

  **`tiny` is the exception and is a second anomaly in that size.** All four of
  its edges deviate the *same* way, which no squash can produce — it is a
  squash plus a ~−0.14° rotation. `tiny-gridded` separately carries the
  largest one-family shear (0.217°, above). Nothing tests 11x11 — the corpus
  has no set at that size — so treat both as provisional and worth a look if
  11x11 is ever exercised for real.
- **A real screenshot's bottom edge reproduces its blank's silhouette to
  ~0.003°, and that is the operationally important number.** The replay sets
  are the cleanest lines available anywhere, because an explored rim has none of
  the fog cube's scalloped lip: `fogless/s1` SW fits at 30.9068° and
  `fogless/s2` SE at 149.0953° (rms **0.36 px**, ~1210 boundary points each),
  and `replay_ss2` gives 149.0927° / 30.9031° on an independent board. Against
  an all-fog rim the same fit reads rms 0.71 on `missized_test/z2.png`, and
  corpus-wide over long edges the bottom pair scatters at sd **0.12°** against
  the top pair's **0.21°** — so the bottom edges are the better ruler, by about
  1.7x, exactly as the game facts predict.

  Those four screenshot edges imply `k` = **0.99771**, against **0.99776** for
  `normal-blank`, which is the render both replay boards (16x16) are matched to.
  They agree to 0.00005, i.e. **0.0013°**. That is the whole point: `edge_lines`
  compares a screenshot's silhouette against a template's silhouette, and the
  two are the same shape to a thousandth of a degree — which is what matters
  operationally, since `edge_lines` compares the two against each other.

  **This paragraph used to end "whether that shared shape is *really* atan(3/5)
  is unresolvable with these estimators and does not matter", and both halves
  are now stale.** It was resolved — the harmonic trend fit on the silhouette
  and the phase-drift fit on the interior lattice agree to 0.005°, both landing
  ~0.058° off atan(3/5) — and there is no longer a standing decision against
  feeding a fixed angle into `edge_lines`, because the code now does exactly
  that. Note the four screenshot fits above already read 30.90 / 149.09, i.e.
  they sat on the answer all along.

  The parallelism self-check cannot be run *within* a replay shot, incidentally:
  each has only one long edge per family (the opposite corner is out of frame),
  so the pair has to be assembled across shots. That is not the crop's doing —
  the same fits come back identical at `--top-crop`/`--bottom-crop` 0.00.
- **Straight, not premultiplied, alpha.** `*-push` and `*-Nspawns` carry pixels
  whose color exceeds their alpha, which only makes sense unpremultiplied; the
  dark layers composite identically either way.
- **The spawn filename encodes the zone grid, not the player count**:
  `2spawns` is a 2x2 grid of 4 zones, `3spawns` a 3x3 of 9. The 9 zones on
  20x20 are the candidate spawns for a 6-player game, so 3 end up empty. Never
  hardcode the digit — `overlay_layer_path` globs it.
- **`shade` and `spawns` are clipped to fog** (`OVERLAY_FOG_ONLY`), confirmed
  with the project owner; `grid` and `push` cover the whole board. The split is
  between layers that *fill* and layers that *reference*. A color wash over
  real terrain dulls the map art the merge exists to show, while over fog — a
  flat expanse of one repeated render — it is what makes the area readable as
  tiles at all. A lattice or an arrow is read *against* the map rather than
  laid over it, is wanted most where the cities and units are, and costs far
  less legibility as a thin stroke than a wash does. **None of them is on by
  default**; see the bot section.
- **They are ~78.5-80.5 px per tile against the old templates' ~89.8.** That
  difference is not cosmetic; see `REFERENCE_TILE_PX` and the sample-density
  note in the anchoring section, both of which exist because of it.
- **Their fog is uniform tile to tile, and the old templates' was not.** Measured
  over all 400 tiles at 20x20: the old template's per-tile mean brightness spans
  183.3-230.6 (std 23.1) and tiles differ from each other by a median of 25.4
  gray levels, while the new blank spans 228.6-230.2 (std 0.39) at a median 3.3.
  So the old renders carried shading *on the fog itself* — not the checkerboard
  layer (adding `shaded` to a blank makes the match to the old template worse,
  0.55 → 0.37; it is `blank+gridded` that reproduces it), just a darker,
  unevenly-lit render.

  **This does not mean the illumination-invariant matching can be dropped, and
  it is not a speedup.** It was checked directly. NCC's invariance was never
  only about the template: screenshots vary by device, exposure, JPEG and the
  game's sunrise, so the shot side still needs it. And the cost is not there
  anyway — inside one `_fog_alignment_score` call the two *image-side* gathers
  cost 0.63ms and 0.66ms against the template-side arithmetic's 0.13ms, about
  3% of the call, so collapsing the template to a single broadcast row wins ~5%
  and changes the score (the rows are not exactly identical — 2.14 gray levels
  of residual from antialiasing and sub-pixel sampling offsets). Not worth it.
  What the uniformity *does* buy is that `fog_illumination` now fits out only
  the shot's lighting rather than the shot's and the template's together.

**These replaced `template_18x18.png`/`template_20x20.png`, which had the tile
grid and the spawn-zone outlines baked into the fog art.** Those two have since
been **deleted**, and the fallback that loaded them with them; `--template`
still overrides everything. Keeping the fallback looked like free
compatibility and was not, because the only state that could reach it was
`Overlays/` being absent — which is precisely the state the deployed container
was in, since its Dockerfile copied the legacy pair and not `Overlays/`. It
then failed silently and in the worst direction: `!merge 11/14/16` refused
outright, no decorative layer at any size, and 18 and 20 registering against
different fog art from every other size. A missing render now refuses at
startup instead. That change is what
makes the grid and the spawn zones *optional* at 18 and 20, which they could
not be while they were part of the reference the fog test correlates against.
It is also the more faithful reference: real screenshots' fog carries no grid
lines (checked on `missized_test/z2.png` and `goon_test2/q.jpg`), and
compositing `huge-blank` + `huge-gridded` reproduces the old `template_20x20`
almost exactly, which is the evidence that the old one was rendered with the
in-game grid on. The old templates' pink (BGR ~`116,51,220`, hue 336°) spawn
rhombuses were deliberate content, not artifacts, and are recorded here so
nobody "cleans" them out of those files either.

**The spawn zone's color changed when `Overlays/` replaced those templates,
and this file never caught up.** The live `Overlays/*spawns.png` layer — what
every merge actually draws today — measures BGR ~`(9,31,251)`, hue **6°**: a
saturated, near-pure red, not the old templates' magenta-pink at hue 336°.
Confirmed across every size that has a spawn layer (`huge`, `large`, `normal`,
`small`); `overlay_layer_path` doesn't care which shade it is, but anything
choosing a color to sit *next to* this one — the ruin marker below is the one
example — has to measure the live layer, not the retired templates.

Note the spawn layer coexists with `--ruin-vision`'s ruin markers, which are
also diamond outlines. The two are told apart by color and are deliberately
far apart in hue: **spawn zone (a layer) is hue 6°, ruin under fog (detected)
is `RUIN_MARK_BGR`, a deep violet at hue 274° — 92° away, the largest
separation of the candidates measured.** `RUIN_MARK_BGR` used to be amber
(0,215,255): distinguishable in hue but a poor *contrast* choice, since fog
itself is near-white (V 230-255) and amber's perceived brightness (202) sat
only 38 levels below it — the marker read faintly. Violet's brightness (70)
gives a 170-level difference, 4.5x the contrast, which is why it was chosen
over an equally-distinguishable magenta/pink. See the ruin-vision section.

**30x30 is deferred** (`MAP_SIZE_DEFERRED`) even though its render is present
and correct. Nothing in `tests/` is a 30x30 board, and — the serious reason — a
30x30 board's 2x fog-period harmonic is ~15, which sits within
`MAP_SIZE_PLAUSIBLE_TOL` of **both** 14 and 16. On every other size a halving
lands nowhere near a real board (5.5/7/8/9/10) and is discarded, which is the
property that filter depends on. Leaving 30 out means such a shot measures ~30,
matches no supported size, and is refused rather than merged as a 14 or a 16.
In a synthetic round-trip a 30x30 pair anchors fine when the size is stated
(+0.03% and +0.00%) but one view read 14.52 tiles instead of 29. Restoring it
wants real 30x30 screenshots plus the fog-lock adjudication in the deferred
section below.

## Architecture

The pipeline has two halves that are easy to conflate but solve different
problems: **per-image anchoring** (where does this screenshot sit on the
board?) and **per-tile compositing** (given all anchored images, what does
each tile actually show?).

### 1. Anchoring (`anchor_to_template`, `joint_register`)

Each screenshot is mapped onto the blank template independently — never
against each other — via a pan+zoom-only similarity transform (the game's
camera never rotates; this is verified, not assumed: a homography buys
nothing over a plain similarity between real shot pairs).

Zoom and pan come from different evidence, each because it's uniquely suited
to the other's weakness:
- **Board edges** (`board_boundary` + `edge_lines`) unambiguously fix *which*
  tile a point is on, but the board is a slab of 3D tiles, not a flat
  diamond, so a silhouette edge includes the tile's side wall and slightly
  overstates scale.
- **Fog artwork** (`fog_period_scale`, and the whole-board correlation inside
  `joint_register`) pins zoom precisely, but fog is a *periodic* texture, so
  on its own it can't tell which tile it's looking at — only where a point
  sits within one. That is why pan always comes from the edges.

**How the fog fallback reads zoom, and why it changed.** It used to match
small fog patches against the template (`fog_candidates` + `fog_scale`), and
that had a fatal, silent failure mode: because fog is periodic, a patch at the
*wrong* scale can still correlate strongly against a different repeat of the
pattern, and any zoom outside the swept 0.50–1.10 range guaranteed a confident
wrong answer rather than no answer. `test_ss_elyruins/hood.png` is that case —
zoomed to 1.66x the template, so its true scale was never even in the sweep.
It anchored ~2% off with every other signal reading healthy, locked **zero**
fog tiles, and pasted its own fog over the other players' terrain.

`fog_period_scale` measures the fog's **repeat period** instead: autocorrelate
the fog region against itself along `dir_a` (known exactly — the camera never
rotates), and the peak *is* one tile step in that image's own pixels, so zoom
= template step / measured step. No template, and no aliasing risk of that
kind: a shifted repeat is the quantity being measured, and harmonics sit a
factor of 2 away rather than a few percent, so taking the smallest strong peak
keeps the fundamental.

**It must require a real peak, not just a high score** (`PERIOD_MIN_PROMINENCE`).
The region it autocorrelates is chosen by a *color* test, and that test is
exactly as unreliable as the standing decision says color tests are: pale
sand, white city roofs, snow and mountains are all bright and unsaturated like
fog. On `badland_test` — a desert board, mostly explored — 27% of the frame
was admitted as "fogish", and a non-periodic region's autocorrelation simply
*decays* from the shortest shift rather than peaking, so the highest score sat
at the low end of the sweep and produced a confident 35px period where the
truth was 118px. Requiring the peak to stand proud of the valley before it
(a periodic texture dips and comes back up; a smooth one does not) rejects
that and finds the true 117.7px peak instead — within 0.1% of the scale SIFT
independently derives. Coarse sweep at quarter resolution, then a
full-resolution pass with parabolic sub-pixel refinement; ~0.2% accurate
against the ±3% window `joint_register` explores, and it costs ~0.2s per shot
against the old ~1.3s. On `hood.png` it reads 149.3px at ncc 0.92 and the
refinement then moves the prior by +0.00% and 1px, with 95 fog tiles locked.

**"Jointly" means the search evaluates the whole (zoom, dx, dy) product rather
than optimizing one then the other — but the *parameterization* still couples
them, and that had to be fixed separately; see the zoom-pivot standing
decision.**

`anchor_to_template` builds an edge-derived prior for both zoom and pan when
an opposite edge pair is available (falling back to `fog_period_scale` only
when no pair exists at all — an edge pair is still preferred because it
cross-checks itself), then `joint_register` refines *zoom and pan together* on
a coarse-to-fine image pyramid against the fog artwork. Refining jointly
matters because the two are coupled — optimizing one while the other is
wrong walks toward the wrong answer. This replaced an earlier two-stage
design (separate zoom search, then separate pan search) that was both far
slower (~220s vs ~17s for a 4-image merge) and less accurate.

Two support thresholds that look similar but aren't:
`--min-edge-support` gates trusting a *single* edge's absolute position
(used for pan, where there's no cross-check available). `--min-scale-support`
is deliberately much lower — it gates whether an edge can join its *opposite*
edge to form a pair for the zoom prior, and a pair validates itself (both
sides should imply the same scale) even when individually weak. Conflating
these two used to force weak-but-real edge pairs into an unreliable
fog-only zoom fallback.

**SIFT zoom fallback, for a shot that can anchor no other way.** A shot with
only one edge per direction has enough for pan but no opposite pair to size
itself against, and may have no usable fog either — a zoomed-in view of a
mostly-explored board is both at once. Rather than drop it, its zoom is
borrowed from a shot that *did* anchor, via SIFT (`SIFT_ZOOM_MIN_INLIERS`).
This is **not** a return to the old register-the-group-then-anchor design:
shots that can self-anchor still do so independently, only an otherwise-dropped
shot borrows, pan still comes from its own edges, and the borrowed quantity is
a single scalar.

**The gate counts only inliers that land on terrain** (`SIFT_TERRAIN_MIN_INLIERS`).
The hazard is fog matching the wrong repeat of itself, and that hazard is made
entirely of fog — so rather than raise a bar by however much fog is in play,
the fog-borne inliers are simply not counted. Raw counts do not separate the two
populations at all: the spurious `test_ss_elyruins` pair reaches **115** inliers
(17.4 tiles wrong) while a genuine match can be as low as **108**
(`replay_ss2`). Restricted to inliers sitting on terrain at both ends:

| population | on-terrain inliers |
|---|---|
| genuine | replay_ss2 **100**, fogless 257, star_change 540, badland_test3 883, pol_archi 939 |
| spurious | elyruins **0**, fruit yad/zeb 0, u_forest2 22, fruit oum/yad 25 |

The elyruins pair scoring **zero** is the whole point: 115 confident inliers,
not one of them on anything but fog. 60 sits 2.4x above the worst spurious and
1.7x below the weakest genuine, where the old flat 150 both admitted the
spurious case and rejected a genuine one.

The saturation mask used for this **never classifies a tile** — it only decides
whether a *correspondence* counts — which is the distinction that makes
`RUIN_NOMINATE_SAT` acceptable where a color-based fog test is not. Do not
promote it into one.
This path **is** load-bearing, on `badland_test3/cym.png`, which has no
opposite edge pair and borrows both a zoom (1908 inliers against `yad.png`) and
a pan offset. It is written as a last resort deliberately — tried only after
edges and the fog period, and gated on a high inlier count.

It used to be load-bearing on `pol_archi_test/kick.png` too, and that entry is
now **historical**: kick's "only edge pair has a phantom side" was
`_board_component`'s defect, not a property of the screenshot. With the
detached chrome dropped it finds all four edges and self-anchors, landing on
exactly the scale (1.0040) this path used to borrow for it — which is worth
knowing as corroboration, since the two derivations share no evidence.

**The same pass also lends a pan *offset* (`pan_hint`), for a shot missing a
whole direction's edge.** One edge pins one of the two offsets, so a shot with
only one has exactly one number missing, and fog cannot supply it (it is
periodic — which is why the number is missing in the first place). The composed
transform `M_of[m] @ M_nm` is already in hand at that point and used to be
discarded; only the direction with no edge of its own is taken from it, and the
direction that has an edge keeps that edge. `anchor_to_template` prints how far
the kept edge sits from the hint, which is a free cross-check on both. **A
borrowed pan is then not refined** — `joint_register` scores by fog alignment
and such a shot has almost none, so refining moved `badland_test3/cym.png` from
0.006 to 0.212 tiles. See the deferred section for the full measurements, and
for the trap that `borrow_pan` must mean "an offset was taken" and not "a hint
exists" (getting that wrong silently skipped `pol_archi_test/kick.png`'s
refinement and cost that set its whole fog lock — measured before that shot
began self-anchoring, so the corpus no longer reproduces it; the trap is still
real and the reasoning still applies to any shot re-anchored in the second
pass).

Both `anchor_all`'s passes are shared by `--cross-check` and the merge. They
were separate once and diverged: cross-check reported `pol_archi_test`
unanchorable while the merge handled it, because only the merge had the
second pass.

**Board-size check — the real wrong-`--map-size` guard.** Any shot that spans
the whole board in one direction can *count* the tiles across it, owing
nothing to `--map-size`: divide its board span (from `edge_lines`) by its fog
repeat period (from `fog_period_scale`), both in that shot's own pixels. The
silhouette overstates the board by the slab's side wall, so the quotient lands
high by a fixed `BOARD_SPAN_WALL_TILES = 0.78` — measured across the 30
edge-pair shots in the ten sets that existed at calibration time, span/period
sits in [N+0.61, N+0.90], and consistently so on both the 18x18 and 20x20
boards, as it should for an absolute wall height expressed in tiles. Subtracting it
recovers N to within ±0.13, leaving a ~0.4-tile margin before the answer would
round differently. The run fails with the correct size named when the median
across shots disagrees by more than 0.4.

This is now the primary wrong-`--map-size` guard, and it is strictly stronger
than `--min-fog-lock`, which `fog_period_scale` can defeat (see the standing
decision on not matching fog patches, below). Verified both ways:
`test_ss_elyruins` at 18 reports 19.84
and `goon_test2` at 20 reports 17.98, both naming the right size, while no set
at its correct size trips it. It costs ~0.15s per shot.

**Detecting the map size outright (`detect_map_size`), when `--map-size` is
omitted.** The same measurement answers the stronger question: instead of
checking a supplied N, just report the one measured. Nothing about it is
circular — the board span and the fog period are both in the shot's *own*
pixels, and the template contributes only `dir_a` (the fixed projection angle,
identical at every N) and the center of `fog_period_scale`'s 12x-wide sweep
(`lo=0.30` to `hi=3.75`; this file said 5x, from before the floor and ceiling
moved).
Verified directly: `goon_test2` reads 17.93/17.87 with the 18 template loaded
and 17.96/17.99 with the 20.

It is safe here for a reason that does *not* hold for the general guard above:
the supported sizes stay at least two tiles apart (11, 14, 16, 18, 20), so the
rounding has a whole tile of margin either way. Measured on all nineteen sets,
eighteen detect correctly and the nineteenth — `pol_archi_test` — produces no
measurement at all and says so. Verified at the new sizes too, by round-tripping
each blank render back through the pipeline as a synthetic pair of screenshots:
11, 14, 16, 18 and 20 all detect correctly.

**A measurement rounds to the nearest integer and then requires a template of
exactly that size — it does not snap to the nearest supported size.** That is
what keeps the widened list safe: a shot measuring 14.52 is reported as a 15x15
board and refused, rather than being pulled to 14 and merged wrong. Do not
"improve" this into a snap.

**The per-shot margin is thinner than this file used to claim**, and the claim
was stale rather than wrong-at-the-time. It said every measurement lands within
**0.20 tiles** of the truth, i.e. a 5x margin on the rounding. Re-measured over
the whole corpus that is now **0.31** (`archers_test2/cym2.png` reads 19.69) —
and it was already 0.32 before the sweep-floor change, on `perilous_test`,
a set added after the 0.20 was written. Still a 1.6x margin, but read it as
"comfortable" rather than "an order of magnitude".

Watch the **spread** rather than the individual readings, since that is what
actually refuses a run: `MAP_SIZE_DETECT_MAX_SPREAD` is 0.5 and the worst
intra-set spread is now **0.36** (`badland_test2`, 20.22 against 19.86), up
from 0.16 before the sweep floor moved. That is the headroom to keep an eye on,
and the deferred item on period jitter is where it went.

Three properties are what make it not-a-guess, and all three matter:
- **It replicates `anchor_to_template`'s phantom-edge rejections**, rather than
  taking any pair it can find. A sole pair must clear `--min-edge-support` on
  both sides and two pairs must agree within `EDGE_PAIR_MAX_SPREAD`. That is
  what makes a phantom pair unusable. Note the reason `pol_archi_test` yields
  nothing is *not* this, despite what this file long claimed: `detect_map_size`
  runs on the plain brightness mask and has no sunrise-sky fallback, and both
  that set's shots need one, so both report `[none]` — every edge, not just a
  phantom pair. Verified identical before and after `_board_component`, so it
  was never about kick's phantom. Normalize each pair by the *template's* span in its own
  direction when comparing them — the a and b spans differ by 0.17% even on a
  square board (1858.93 vs 1862.05 at 20x20), which is nothing against the 3%
  threshold but not nothing against the 0.00–1.24% healthy pairs report.
- **It refuses rather than defaulting.** No shot spanning the board, shots
  disagreeing by more than `MAP_SIZE_DETECT_MAX_SPREAD`, or a size with no
  template all raise with the reason named. A guessed size is the most
  destructive failure in this program, so "ask" is always the right answer.
  There is one evidence-based exit before that refusal, and only one — the
  plausibility filter below. It does not guess between sizes; it discards
  numbers that describe no board at all.
  **The refusal names the reason it actually hit** (`_no_measurement_reason`),
  rather than asserting one cause for all five. Counting tiles is span / fog
  period, so it needs *both* an edge pair and a readable fog repeat, and the two
  failures want opposite advice — zoom out, versus state the size because no
  amount of zooming will help. The text used to name only the first, which on a
  replay or a finished game is simply false: `fogless`'s two shots each have an
  opposite edge pair agreeing to **0.03%** and are short only the fog. That
  mattered more than it looks, because polybot reads `tail(stderr) or
  tail(stdout)` and `SystemExit` goes to stderr — **the correct per-shot lines
  go to stdout and never reach the channel, so the one wrong sentence was
  everything a player saw.** Same mistake, same fix, as the dropped-shot caption
  described in the bot section. A mixed run names the reasons per shot, so the
  summary can never contradict the detail lines printed above it.
- **The disagreement check is a new capability, not just a safety net.** Two
  screenshots of *different boards* handed to one merge were previously
  undetectable; they now report `disagree about the board size by 1.91 tiles`
  (verified with `goon_test2/imp.jpg` + `test_ss_2/cym1.jpg`).

**A measurement that describes no board is discarded, not weighed**
(`MAP_SIZE_PLAUSIBLE_TOL`, `plausible_sizes`). One broken number used to fail an
entire merge. `missized_test/z2.png` read its fog period as the 2x harmonic and
so measured 8.60 tiles, which refused the run two different ways — as a spread
disagreement with `z1.jpg`'s 17.93 under a bare `!merge`, and as "this looks
like a 13x13 board" under `--map-size 18`.

The key fact is that **the count and the anchor are separate measurements from
separate evidence.** `implied_n = span / period - BOARD_SPAN_WALL_TILES` is a
derived count; a shot with an opposite edge pair takes its *zoom* from the edges
and never consults the period for it. So `z2.png` measured 8.60 and still
anchored to +0.04% and locked 228 fog tiles, more than either other shot. A
wrecked count says nothing about the screenshot, and the shot stays in the
merge — this drops the number, never the shot.

0.9 separates the two populations by an order of magnitude both ways: the worst
honest measurement in the corpus sits **0.32** from its true size
(`archers_test2/cym2.png` 19.69, `perilous_test` 17.68) and the harmonic sat
**9.4** away. It cannot swallow a real disagreement either, because a halving
never lands on a board size — half of 11/14/16/18/20/30 is 5.5/7/8/9/10/15,
none of which are sizes — and staying under 1.0 keeps a genuine reading of a
*neighboring* size plausible, so two different boards still reach the spread
check rather than being filtered apart here. Verified: `goon_test2/imp.jpg` +
`test_ss_2/cym1.jpg` still report the 1.91-tile disagreement.

It applies in **both** consumers, and the second is the one that needed it
most. `main`'s board-size check takes a median specifically "so one odd shot
cannot fail an otherwise good run" — but a median only delivers that from three
measurements up. With two it *is* their mean, so one broken number drags it half
way, which is exactly how 17.93 and 8.60 produced a 13x13 board. Two-measurement
runs are the common case, not the corner: only **6 of 18 sets** have three or
more (see the standing decision against majority voting).

**No corpus set reaches the filter at the current sweep floor** — the harmonic
that motivated it is fixed upstream — so this is defense in depth. It is still
reproducible on demand by forcing `fog_period_scale(lo=0.45)`, which puts
`z2.png` back to 8.60; the expected result is the measurement named and
discarded, size detected as 18, and **all three shots merged**.

**It used to cost ~0.22s per shot in duplicated work** — an edge fit and a fog
period `anchor_to_template` would compute again, 0.81s on a 4-shot merge. This
file recorded that duplication as a deliberate choice, on the grounds that
sharing the measurements "means changing how the registration path gets its
inputs — the half of the pipeline where mistakes are silent." That reasoning was
right about the risk and wrong about it being unavoidable.

**What makes sharing safe is that the cache key carries every input that can
change the answer** (`ShotCache`), so a hit is by construction the same
computation and returns the same bits, and a miss recomputes exactly what the
old code did. Nothing is approximated and no number is permitted to drift. The
key is the shot, a mask *generation counter*, the projection basis (which
reaches `_board_component`'s angle test), and — for the period — the tile step,
because that sets the phase of the coarse sweep grid and a different phase moves
the answer by up to 0.9% (see the deferred item on it).

That last term is what turns the second of the two obstacles this file used to
name into a non-issue rather than a hazard: the pre-pass has to choose a
template before it knows the board size, so its basis and tile step are only
*sometimes* the ones the anchor will use — and when they are not, the key simply
misses. **`_probe_basis` therefore iterates 20, 18, 16, 14, 11** rather than
ascending, which is what makes it hit: on a 20x20 board the pre-pass's
parameters are the anchor's, every key hits, and the pre-pass becomes free. On
any other size nothing hits and behavior is bit-identical to not having the
cache, at the cost of loading the larger render first (+213ms on an 18x18 board
against ~960ms saved on a 20x20 one, counting `template_geometry`'s dedup of the
load and corner fit — 294ms at 20x20).

The first obstacle, `sky_rebuild` re-fitting the boundary, is handled by putting
`cache.invalidate` in `anchor_to_template` immediately after `mask, valid =
sky_rebuild()` rather than inside `sky_rebuild_for`. That keeps the obligation
next to the reassignment that creates it, and it holds for a caller that passed
no cache at all — which matters because `shoreline/polyshore.py` calls both
`detect_map_size` and `anchor_to_template` directly. Both default to a private
cache, so they work unchanged and still dedup a single call's own repeats (the
sky re-fit, and `anchor_all`'s second pass re-anchoring a shot).

**Verified on both paths against the pre-change code, because they are different
paths and only one of them is covered by `tools/baseline.py`:** that harness
passes `--map-size` for every set, so it never populates the shared cache at all
— it proves nothing was broken and cannot prove the dedup works. Stated size
came back *identical on every set and every tracked field*; a separate run of
every set with **no** `--map-size`, old code against new, came back **0 of 27
differing**, refusal text included (`fogless`, `pol_archi_test` and `replay_ss2`
still refuse identically). An empty diff is the *expected* result here rather
than a happy one — any movement would have meant a broken key.

An explicit `--map-size` skips all of it, so nothing here can override a size
someone actually meant.

**A refinement that locked nothing is not adopted.** `joint_register` scores
candidates by fog alignment, so a shot with no fog in frame is not being refined
at all — it is walking to the argmax of noise. This is the same reasoning that
already stops a borrowed pan being refined (`borrow_pan`, below); the difference
is that a fogless board cannot be recognized *up front* the way `borrow_pan` can,
so the check has to be after the fact. In `main`, any shot whose refined anchor
locks **zero** fog tiles is put back on its own unrefined edge/fog-period prior.

`tests/fogless` is the case and the only set that reaches it: a replay of a
fully-explored board where every shot locks 0. Its edge-only anchors are
*excellent* — 0.007–0.023 cross-check tiles at every board size, better than
most shots that do have fog, because a rim of explored terrain has none of the
fog cube's scalloped bottom lip to bias the edge fit (see the edge bullet in the
game-facts section). Refinement moves them +2.3–2.7% and **1.1 tiles apart**,
and the composite comes out visibly seamed through the middle. Reverting takes
that set from 396/400 union with 25 conflicts to **400/400 with 4**.

Three things about the rule, all load-bearing:
- **The prior wins even on a tie at zero, and that tie is the whole point.** Fog
  lock cannot separate two anchors when neither has any fog; what decides is
  that one of them was fitted to noise and the other was not. Getting this
  backwards — keeping the refinement on a tie — makes the rule inert on exactly
  the case it exists for.
- **Only a shot locking *zero* is eligible.** One locked tile is evidence, and
  such a shot keeps its refinement untouched. That is what makes this unable to
  move an ordinary merge, and measured over the corpus it does not: every
  tracked field identical on all 21 other sets.
- **It runs before the fog-lock report and before `--min-fog-lock`'s guard**, so
  the printed numbers are the ones actually used and a recovered prior can
  satisfy the guard. It is deliberately *not* gated on `--min-fog-lock > 0`,
  since a fogless board has to pass 0 to get that far at all — gating it there
  was the first attempt and it excluded precisely the case it was written for.

It composes with the borrow below rather than competing: `star_change/oum.png`
locks 0, so it is reverted to its prior first and *then* offered the borrow,
which still wins on its own fog (imp's anchor lands 7 locked tiles against
oum2's 6) and still produces that set's documented union of 290.

**Per-image misanchor guard.** `--min-fog-lock` is deliberately a *per-run*
check (a single zoomed-in shot can honestly have almost no fog in frame), but
there is one class of shot for which per-image is provable: one whose zoom
came from `fog_period_scale`. Its zoom was just measured on a large expanse of
its own fog, so if none of its tiles then lock onto the template's fog art,
its anchor cannot be right — and a misanchored shot calls its own fog
"explored" and pastes it over everyone else's terrain. Such a shot is dropped
with a message and the rest of the merge continues. It is a safety net, not a
routine path: with `fog_period_scale` in place it does not fire on any current
test set.

**That premise is not airtight, so the drop is now gated on a second opinion**
(`corroborate_anchor`, `MISANCHOR_CORROBORATE_MAX_TILES`). The hole is that
**the whole board is periodic at the tile step, not just the fog** — crop
fields, tile borders and territory dashes repeat on the same lattice — so a
shot with almost no fog in frame can still autocorrelate to a *correct* period
off ordinary terrain. `star_change/oum.png` does exactly that: 81.2px at ncc
0.62 (weak against a genuine fog read's 0.92+) and within 0.01% of what SIFT
independently derives. It then has too little fog to lock and too little for
`joint_register` to pull the last few px into phase, so it sits 0.082 tiles out
with its seven fog tiles scoring 0.35–0.49 against the 0.7 lock bar — and got
dropped, costing 81 tiles of union on a two-shot merge.

So a shot with **zero** fog locked is not dropped on that evidence alone. Such
a shot has had no say in its own refinement either — `joint_register` scores
candidates by fog alignment, so with nothing to align it simply keeps the
edge-derived prior, bias and all — and the fix for both problems is the same:
take the whole anchor from a shot that *does* have fog evidence, via SIFT.

**Borrowing pan, not just zoom.** `anchor_all`'s existing fallback lends only a
zoom to a shot that cannot anchor at all; this lends the entire transform to a
shot that anchored but is fog-blind. Three conditions keep it from sliding back
into the old register-the-group-then-anchor design: only a shot with zero fog
evidence is eligible, a lender must itself clear `--min-fog-lock`, and the
borrowed anchor must **prove itself on the borrower's own fog** — it is adopted
only if it locks more tiles than the anchor it replaces (`oum.png`: 7 against
0, which is every fog tile it has).

That last condition is also what picks *which* lender, and it has to, because
inlier count does not. `star_change/oum2.png` is the same player's near-identical
view, so it matches `oum.png` at 4494 inliers against `imp.png`'s 829 — and back
when oum2 was itself a tile out (the badge-halo bug), lending by inlier count
handed oum the wrong answer and dragged it a whole tile off. Every eligible
lender's anchor is therefore tried and the borrower's own fog picks. It costs a
warp and a sample per candidate, on a path that never runs on an ordinary merge.

**On `star_change` that pick is currently a tie, so the corpus does not test
it.** This file used to say imp's anchor landed 7 locked tiles against oum2's 2;
that is stale — both land 7 today, and oum2 wins on iteration order. (Verified
at two different sweep floors, so it is not a consequence of that change.) The
outcome is harmless, since the two lenders put oum within 0.004 tiles of each
other and the merge output is identical either way, but it means the only set
exercising this path no longer demonstrates that the fog test is what decides.
The badge-halo history above is the reason to keep the rule regardless.

**A shot that keeps its own anchor is still corroborated before being dropped**
(`corroborate_anchor`): SIFT against a shot that anchored on its own, scored by
exactly `--cross-check`'s measurement. It is kept when some anchored shot gives
>= `SIFT_ZOOM_MIN_INLIERS` inliers *and* puts it within
`MISANCHOR_CORROBORATE_MAX_TILES` (0.20) of its own anchor. Both bars are
load-bearing and guard different failures: the inlier floor rejects fog matching
the wrong repeat of itself (confident, high-scoring, badly wrong), the agreement
bar rejects a genuine match that simply disagrees. 0.20 sits clear on both sides
— every set at its correct map size reports at most 0.083, while the failures
this must still catch are a few percent of the whole board, i.e. ~0.36 tiles for
the 2% `hood.png` case on 18x18.

The key safety property throughout is that none of this can drop a shot that
would otherwise have survived — it only rescues. SIFT features are built on
demand, so it costs nothing until a drop is imminent: no current set except
`star_change` runs any of it, and all thirteen sets' union, conflict, city-bar
and `--cross-check` baselines are unchanged.

**`--cross-check` deliberately does not reproduce the borrow.** It returns
before the merge path, so it reports how well each shot anchored *independently*
— which is the question it exists to answer, and it would read a vacuous ~0 for
a shot whose anchor was taken from another shot by SIFT. `star_change`'s 0.083
is `oum.png`'s own edge-derived anchor, not the one the merge ends up using.

**Formerly an open problem, now largely fixed — but read this before changing
`joint_register`.** The refinement used to move an already-correct edge-based
prior to a *worse* position, seemingly at random, and it was recorded here as
having no known general fix. It has two causes and both are now addressed.

**Cause 1: each pyramid level handed only its single best zoom to the next**
(`JOINT_LEVELS`' last field, `_prune_beam`). Taking the argmax assumes the
coarse level's best-scoring zoom is in the same basin as the true one, and it
is not — the downsampled score surface is noisy and near-flat at the top, so
its top three candidates routinely differ by under 1% in score while the fog
lock across those same candidates swings 2-3x. The score function was never
the problem: measured on `archers_test2/cym1.png`, the search settled on a zoom
scoring 54.48 while a point 0.5% away scored **58.54** and locked **215** tiles
against 112. It simply never evaluated it. Carrying several separated
candidates forward and letting the sharper levels arbitrate fixes it.

The tell that this was a search failure and not a property of any one template:
with candidates carried forward, two renders differing by 12% in tile size
**agree** on the answer (cym1 locks 222 either way); without, each template
produced its own idiosyncratic result (222 against 111). A correct anchor
should not depend on which reference it was measured against. A 0.045% change
to the *old* template's tile step — nothing else — was enough to move that set
from 0.028 to 0.097 cross-check tiles, which is how arbitrary this was.

Widths taper 3, 2, 1 because scoring is 90-99% of the phase, so each extra
candidate costs a full pan sweep. A 4-shot merge went 13.3s → 22.0s at a flat
3 and 17.2s at the taper. Two cheaper shapes were tried and are **not** enough:
width 2 at the coarsest level puts `archers_test2` back to 0.128, and pruning
to 1 before the full-resolution level puts three sets back above the 0.05 bar —
that level is where the discrimination happens, so it is the one that must see
more than one hypothesis.

**Cause 2: sample density silently depended on the template's pixel size**
(`_tile_sample_grid`). The cap is an absolute pixel count and the code strided
by an integer, so the number of probes per tile fell out of however many pixels
the render happened to put in a tile: at div=4 the old templates gave 276
px/tile → step 2 → **138** samples, and the `Overlays/` renders give 222 → step
2 → **111**, a fifth fewer at exactly the level that chooses the branch. That
is the thinning this function's own note warns about. Taking `cap` evenly
spread pixels instead of every step'th makes the count a property of the board
(160/160/320 at every template scale) rather than of the render.

That second one is the reason a smaller template anchored worse *systematically*
rather than randomly, and it is worth knowing how it was found: upscaling the
new template recovered the fog lock almost completely (111 → 223), and since
upscaling is pure interpolation and adds no detail, the loss could not have been
detail. It was sampling. **Do not "fix" a future version of this by
re-rendering the templates larger** — that treats the symptom.

`--cross-check` is still the way to catch a residual case, and `star_change`
still behaves oddly for its own documented reason (almost no fog in one shot).

One class of that behavior turned out **not** to be an algorithm problem at
all, and is worth ruling out first: when the lattice period is wrong (wrong
`--map-size`), there is nothing to lock onto, so the refinement optimizes
noise and wanders to the edge of its search window. The tell is a large,
inconsistent correction — on `test_ss_3` at 18, `yad1` and `yad2` have priors
agreeing to 0.01% yet refined 1.7% apart (+2.46% vs +0.79%). So a refinement
correction above ~1%, or two same-zoom shots disagreeing after refinement,
should send you to check the fog-lock count before you go looking for a
subtler bug in the optimizer.

Note the old form of this claim — "at the correct map size every shot corrects
by at most 0.36% and moves pan 1-6px" — was already stale and is not a usable
tripwire. The `cym` shots in `test_screenshots`/`test_ss_2`/`beautiful_test3`
routinely correct 0.6-0.9% and move pan 20-27px at the *correct* map size,
and they are anchored fine. The reliable tells remain the fog-lock count and
two same-zoom shots disagreeing with each other, not the size of a single
shot's correction.

**Sizes measured in template pixels must be scaled** (`REFERENCE_TILE_PX`,
`tile_px_scale`). The sprite detectors work in template space
precisely so their thresholds can be constants — after warping, a segment is the
same height whatever the shot's zoom. That argument is sound but assumed one
more thing: that every template renders a tile at the same number of pixels. It
no longer does (78.5-80.5 px/tile in `Overlays/` against the old pair's 89.8),
so such a constant is written as the pixel count it was measured at and
multiplied by `tile_px_scale()` at the point of use. Areas scale as the square.
Note `REFERENCE_TILE_PX` stays at 89.8 even though the renders it names are
deleted: it is a *reference scale*, not a file, and re-basing it means
re-deriving every constant that depends on it in one go.

**Only `PLATE_BAND`/`PLATE_HALF_W` still need this**, and that is the direction
of travel. The city-bar geometry is expressed in **tile widths** (`BAR_HEIGHT`,
`BAR_HALVES`, …) and so is scale-free by construction, and the ruin detector
sizes its kernel from `|u_col|` directly. Both are the same idea taken to its
conclusion, and are the better pattern for anything added here. The constants
this section used to list — `SEG_H_MIN`/`SEG_H_MAX`, `SEG_ASPECT`,
`BAR_SPAN_MAX`, `BAR_PITCH_TOL`, `BAR_VERTEX_DY` — went with the bottom-up bar
detector and no longer exist.

**Round the scaled value when the bound is compared against an integer**, and it
is not cosmetic. At a ~0.1% scale a `<= 10` px bound becomes `10.01 <= 10` and
drops a real bar segment. Measured back when the city-bar detector was built on
px constants: raw multiplication cost 5 of the then-16 sets a city bar each while
changing nothing else — invisible without `tools/baseline.py`.

There is **no rounding helper in the file today**. `PLATE_BAND`/`PLATE_HALF_W`
are the only scaled bounds left and they only index slices, so they take the raw
float; the `int(round(...))` helper that existed for this went when the bar
rewrite removed its last caller. Bring it back rather than open-coding the
rounding if you add a bound that is compared against a count — the note above
`REFERENCE_TILE_PX` in polymerge.py carries the same warning.

The same hazard once bit an **inline literal rather than a named constant**: the
old bar-completeness test in `main` (`span_of`) compared a detected bbox against
a bare `128` and `78..96`, so on the `Overlays/` renders a genuine 4-segment bar
measured 122px, was demoted to "fragment", tied on completeness with a false
positive competing for its own SW tile, and lost that tile on proximity — the
`beautiful_test3` (18,10) vs (18,11) case, silently reopened by the template
swap. `span_of` is now `nseg >= 3` and has no literal in it, but the lesson
stands: when adding a length here, prefer a named constant so the next sweep can
find it.

Deliberately *not* scaled: the small px floors in
`_region_ncc` (40), `sample_tile` (50) and `tile_fog_fraction` (60), which are
"too few pixels to say anything" guards rather than measurements, and which
`--min-valid-frac` already gates far more strictly (702 px on the smallest
render).

**`detect_corners` takes the side corners from the first *full-height wall*
column** (`_side_corner`, `SIDE_CORNER_MIN_WALL`), not from the outermost one.
The extreme column is sometimes a thin antialiasing spur a few px tall whose
vertical position is arbitrary, and taking its top puts the corner wherever the
spur landed: `small-blank`'s west extreme is a 16px spur at y=713 against a real
61px wall at y=670 one column in, and `tiny-blank` has spurs on both sides at
y=520 and y=550. The result was a board whose two lattice steps differed by 2% —
not a plausible shape for a square board, and a skew every tile position
inherits. Requiring the full wall costs the sizes that never had a spur nothing
at all: their extreme column already qualifies, so the answer is unchanged to
the pixel (`huge`, `normal`, `large`, `massive` and `template_20x20` all
identical; only `template_18x18` moved, 89.89 → 89.67, and it moved *toward*
square, 1.0030 → 1.0005).

**The silhouette is the board's own component, not every bright thing in the
mask** (`_board_component`, `BOARD_COMPONENT_MIN_EDGE_RUN`). `board_boundary`
outlines every component it is given, and `edge_lines` fits each edge to
whatever lies furthest out in that direction — so one scrap of bright chrome
sitting *outside* the board captures that edge outright and leaves the real one
orphaned, supported by nothing. It is not a near miss and it does not degrade
gracefully:
- `u_forest2/ely.png` carries the game's collapsed side-drawer tab (a dark-gray
  rounded panel with a `<` chevron, glued to the right frame edge). Its gray
  clears `--dark-thresh` and its chevron gives it enough texture to survive
  `sky_mask`, so it enters the mask — and it sits **577px past the true NE
  rim**, taking `b-min` with it. That rim's 800 boundary points then support
  nothing, `b-min` reports **18** against `--min-edge-support` 150, and the
  shot has no `b`-direction edge at all, so it cannot pan-anchor.
- `pol_archi_test/kick.png` is the same defect from different chrome — score
  banner glyphs landing just *below* the `--top-crop` band — and it is the
  origin of that shot's long-documented "phantom" `a-max` of 30 points.
- `fogless/s1.png` and `s2.png` carry the **replay's turn-timeline strip**,
  which also lands just below the `--top-crop` band. It takes `a-min` on one
  shot and `b-min` on the other, so each is left with a single edge, cannot
  pan-anchor, and **both are dropped** — the run reports "no valid images
  found" and merges nothing at all.

**The discriminator is the edge's *angle*.** The camera is fixed isometric and
never rotates, so a board edge is only ever at `dir_a` = **30.7°** or `dir_b` =
**149.0°**, identical at every board size. Chrome is docked to the screen frame
and runs at 0° or 90°: the replay strip is horizontal, the drawer tab vertical,
the banner glyphs too small to sustain a run at any angle.

**But angle alone is not enough at a small smoothing window — a triangle has
diagonals.** What makes the test discriminating is the *size* of that window:
`BOARD_ANGLE_SMOOTH` (35) averages the outline tangent over ~70px, which
suppresses rasterization and the fog rim's scalloping, and also means a fragment
must sustain the angle across ~70px of outline before it registers at all. A
board edge runs for hundreds of pixels; a UI glyph's straight edge runs for tens,
and its corners contaminate the estimate long before a run accumulates. So the
window discriminates by edge *length* as much as by angle, which is what a small
tolerance alone cannot do.

The **replay play button** is the case that forced this, and it is worth
understanding rather than treating as a freak. It is a triangle, and its upper
edge runs at **29.6°** against `dir_a`'s 30.7 — a 1.1° miss — so at the original
k=7/tol=12 it scored a 58px run, was kept as board, captured `b-min` and dragged
that edge line ~400px off the real rim. It is not an unlucky angle either — a
play glyph is near-equilateral and an isometric board edge is ~30°, so both are
natural angles and the next such glyph will land there too. `tests/replay_ss2`
is the regression test, and the reason that set exists.

Widening the window separates the populations instead of stacking a second bar
on top. Measured at k=35, tol=5 over every detached component in the corpus
(n=69, area ≥ 400) against board halves severed by a synthetic full-width dialog:

| population | longest board-angle run |
|---|---|
| all corpus chrome — timeline strip 29–30, play button 30, drawer tab, banner glyphs, badges | **≤ 30 px** |
| board halves severed by a synthetic full-width dialog | **≥ 173 px** |

So the rule is a **single** bar: `BOARD_COMPONENT_MIN_EDGE_RUN` (80px), which
sits 2.7x above the chrome and 2.2x below the fragments. Sweeping k and the
tolerance together, k=35/tol=5 is the widest margin available (5.8x); the
original k=7/tol=12 managed only 1.8x, and no tolerance at k=7 does better. The
largest component is always kept regardless, and `BOARD_COMPONENT_MIN_AREA`
(1000 px) is a cheap runtime prefilter — too small to sustain such a run anyway —
not a share of the board. This runs after the open/close (so a scrap the open
already dissolved is never tested) and before the pad.

**Two formulations that do not work, so nobody reintroduces them.** Component
*area as a share* was the first rule here and it is a proxy for "big enough to be
board" — the replay strip defeats it outright at **8.4%**, which is what
motivated the angle test, and keeping it as a second bar alongside the angle test
would only risk discarding a genuinely small board fragment. The *fraction* of
the outline at a board angle fails worse and more subtly, and is no use at all:
board components read min
**0.060** against chrome's max **0.380**, fully overlapping, because a board
component's outline is mostly *not* board edge. It runs along the image frame
and along the `--top-crop`/`--bottom-crop` band boundaries, which are horizontal
and *interior*, so they survive the frame-margin drop and swamp the ratio
(`pol_archi_test/pol.png` reads 0.905 axis-aligned). The longest *run* is immune
because it asks for positive evidence of a board edge rather than a ratio
against whatever else is in the outline.

An edge-support test — fit each component with `edge_lines`, require support
≥150 — also separates (chrome ≤52 against fragments 430–1174), but is **4x
slower** (206ms/shot against 53ms on full-canvas masks) and scores two *real*
board components at **11**: `pol_archi_test`'s two shots under the brightness
mask, where the sunrise has fused board with sky. The angle test scores that
same shot **18**, and neither number matters — a fused board is the *largest*
component, kept unconditionally, so it never reaches either test. What is
actually tested is detached fragments (≤30) against severed board halves (≥173),
and there the angle test buys the same separation 4x cheaper.
Cost in place, measured on component bboxes rather than the whole canvas, is
**16–19ms** on a shot carrying chrome and ~**0ms** on one that does not.

Measured across the corpus, the area rule left **19 of 20 sets bit-identical**,
moving only `pol_archi_test`: `kick.png` goes from two phantom edges to all four
(`a-min=376 a-max=587 b-min=658 b-max=730`), so it now self-anchors from its own
edge pairs instead of borrowing a zoom from `pol.png` by SIFT — and the two
routes agree exactly, both landing on **scale=1.0040**, the strongest evidence
available that the recovered edges are real. Adding the angle test alongside it
then moved **nothing at all**: every tracked field identical on all 21 sets,
while `fogless` goes from refusing outright to merging and `replay_ss2` recovers
both shots' edges (that set still cannot derive a *zoom* — see the deferred item
on a shot with no opposite pair and no fog).

**SIFT takes its features from the board, not from whatever else survived the
crop** (`board_region`, `sift_mask_for`). Every SIFT consumer — the zoom borrow,
the `pan_hint`, `corroborate_anchor` and `--cross-check` — used to build features
from `valid`, which includes chrome. That is harmless on ordinary gameplay shots
because their HUD *differs* between captures (score, turn, whose go it is), and
it is a trap on any two shots of the same **replay**, whose UI is byte-identical:
identical pixels match perfectly, so RANSAC locks onto the chrome and reports
that two different views are the same image.

On `tests/replay_ss2` that is **330 inliers on a flat identity transform**,
against the genuine board match's 113 and a true pan of (-1091, +53) px. It is
not a corner case confined to replays, either — see `u_forest` below.

Confining features to the board component leaves **every union, conflict, bar,
ruin and fog-lock figure identical on all 22 sets**, and moves cross-check on
five:

| set | before | after | why |
|---|---|---|---|
| `u_forest` | 18.537 | **0.016** | the flagged pair was chrome, and is now gone |
| `fogless` | 13.483 | **0.524** | same cause, on a set whose number is unreliable anyway |
| `test_ss_3` | 0.039 | 0.045 | fewer, board-only correspondences |
| `test_ss_5` | 0.020 | 0.021 | " |
| `beautiful_test3` | 0.023 | 0.024 | " |

**`u_forest`'s 18.5 was never a fog artifact, and this file said it was.** It was
recorded here as the clearest example of fog matching the wrong repeat of itself
— `e1` vs `e2` at 39 inliers on an 85% fog board. Those 39 inliers were the
*identical HUD* of two shots by the same player. With chrome excluded the pair
produces no transform at all, cross-check reports only the pair it can actually
measure (`e1` vs `e3`, 107 inliers, 0.016 tiles), and the set comes off
`CROSS_CHECK_UNRELIABLE`. The three sets still on it for the fog reason —
`test_ss_fruit` 11.126, `test_ss_elyruins` 17.438, `u_forest2` 6.313 — are
**unchanged to three decimals** by this, which is what confirms their diagnosis
is the right one.

The lesson generalizes past SIFT: *two screenshots agreeing about pixels that
are not the board is not evidence about the board.*

**Do not derive the template silhouette from the alpha channel** — it was tried
and it is a trap. The `Overlays/` renders sit on transparency, so `alpha > 128`
looks like the obvious clean silhouette, but it cuts the antialiased fringe that
`--dark-thresh` keeps, and the screenshots are still masked by brightness. The
edge fit then compares two things measured differently. It moved
`template_20x20`'s tile step by 0.045% (89.78 → 89.74) and that alone took
`archers_test2` from 0.028 to 0.097 cross-check tiles. Use the same brightness
test the screenshots get; the lattice skew that motivated the idea belongs to
`detect_corners` and is fixed there.

### 2. Mask taxonomy

Four mask variants exist per image and mixing them up is the most common
class of subtle bug in this codebase:
- `valid` / `valid_raw`: for *witnessing/classification* — excludes UI
  chrome, out-of-frame pixels, and pixels too dark to trust for color
  judgment (`build_valid_mask`).
- `frame` / `frame_raw`: the *pasting* counterpart — excludes UI chrome and
  out-of-frame pixels but **not** darkness, because a tile's winning source
  can legitimately have real dark content (roof shadow, a tree trunk) that
  isn't "unphotographed." Conflating this with `valid` previously caused
  layered pasting to fall through to a second, misaligned source at every
  dark speck in the winning source, speckling the composite.
- The `_raw` variants additionally omit capture-badge exclusion; the
  non-`_raw` variants have detected badge pixels subtracted
  (`detect_capture_badges`). Both exist because a tile with no *clean*
  witness should still fall back to a badge-covered source rather than show
  nothing — see `badge_fallback` in `main`.
- `edge_mask`: erosion-free version used specifically for `board_boundary`/
  edge fitting, since `--erode-px` erosion eats a different amount of board
  in each image's own pixels depending on zoom, which would bias the fit.
  It is the one mask that subtracts the badge **halo** rather than the badge
  (`badge_halo`), and it is the only mask that needs to: a few glowing pixels
  do not change what color a tile is, but they do change where the silhouette
  appears to end. `star_change/oum2.png` is the case — see that function.

### 3. Per-tile compositing (`sample_tile`, winner selection, paste loop)

Each tile is sampled per source (`sample_tile`) and classified fog/explored
by correlation against the template's fog art (`--fog-ncc`) — never by
saturation/color, since mountains/snow/ice are exactly as desaturated as fog.
`tile_top_wedge` catches fog tiles whose whole-tile score is diluted by a
city or mountain overlapping from the south (tall sprites are drawn
extending toward the viewer, i.e. into the tile north of their own).
`--fog-wedge-ncc` must stay high (0.80) for the same reason the whole-tile
test works — fog is one fixed render, so a real fog wedge scores ~0.95.
Measured over 4011 (tile, source) observations across all four sets,
apparently-explored tiles (whole-tile <= 0.20) have a wedge 95th percentile of
0.334, and raising the threshold 0.65 → 0.80 cuts the tiles it flips from 15 to
5; anything in 0.75–0.85 behaves identically. The old 0.65 default sat inside
the false-positive band and turned `test_ss_3` tile (18,18) from forest into
fog. The one flip at 0.80 that looks wrong isn't: `goon_test2` q.jpg tile
(14,13) scores 0.986 on the wedge and its neighbors score 0.93–0.95 whole-tile
fog in that same shot, so it is genuinely occluded fog.

Winner-per-tile is ranked by **ascending** `scale[n]` among sources that
witness a tile as explored. Mind the direction: `scale[n]` is the factor that
blows that shot *up* to template size, so the smallest value is the shot that
already had the most of its own pixels on that tile — the sharpest witness.
This was inverted (`-scale[n]`, i.e. sharpest-last) until it was caught on
`test_ss_3`, where it handed every contested tile to the zoomed-*out* `cym`
shots, which have the fewest of their own pixels per tile. (An earlier form
of this note also claimed zoomed-out shots lose because "constant-screen-size
UI covers more board area" — wrong on both counts: the city UI scales with
board zoom, verified in the city-bar section, and what looked like unit
health bars are animal horns.)

`priority[key]` keeps the *entire* eligible order, not just the winner,
because the final paste loop layers through it: a source that's only partially
in-frame for a tile falls through per-pixel to the next-best source, rather
than pasting that source's out-of-frame black.

A near-zero fog-lock count (see `--min-fog-lock`) means the fog test matched
nothing, so *every* tile came back "explored" and this ranking silently
becomes the only thing deciding the composite. That is the mechanism behind
the `test_ss_3` failure, and why the guard is worth more than it looks.

**Sharpness is only the tiebreak; fog evidence outranks it**
(`--fog-frac-margin`, `fog_pixel_mask`/`tile_fog_fraction`). A tall city can
fill a tile's inset center in *every* shot, so the fog test sees nothing but
towers and calls the tile explored even in a shot where it is really fog —
which then wins on sharpness and pastes its own fog fringe. Confirmed on
`test_ss_3` tile (10,9) = Ichphy, a cym city sitting right on yad's
exploration frontier: tile (9,8) is genuine fog in both `yad` shots and
genuine grass in both `cym` shots, yet yad's whole-tile score reads 0.14
against cym's 0.17 — indistinguishable, and the wrong way round — and even
the top wedge reads only 0.43 because the towers reach into the wedge too.
The same mechanism is what the "fog slivers along merge seams" were: a
source's seam *is* its fog frontier, so that is exactly where its
mis-witnessed tiles are.

What resolves it is comparing the sources against each other on the *same*
rhombus, per pixel and over the full tile rather than the inset one. Both
shots are looking at the same towers, so the occluder cancels and only the
disagreement is left: fog fraction runs 0.089/0.084 for the yad shots against
0.000/0.000 for the cym shots. Ordinary disagreement between co-eligible
sources is nothing like that large — median 0.001, 95th percentile 0.019
across `test_ss_3`'s 186 multi-source tiles — so the 0.04 margin is clear of
both. Demoted sources are pushed to the back of `priority`, not dropped, so
they can still fill pixels nobody cleaner photographed.

### 4. Elyrion ruin vision (`detect_ruin_vision`, `--ruin-vision`, off by default in the CLI, always on in the bot)

Detects the rainbow flame clusters an Elyrion player sees on fogged ruin tiles,
reports their tiles, and outlines them on the composite's fog so the merge keeps
that knowledge.

**The detector matches the game's own sprite.** `Assets/Rainbowflame.png` is the
actual asset, so nothing here has to infer what a marker looks like from
screenshots — it predicts what one would look like on this fog and asks how well
that matches. Alpha compositing is exact and invertible:

```
C = f·α·S + (1 − f·α)·F
```

`S`, `α` are the sprite's color and alpha, known per pixel. `F` is the fog
behind it, known per pixel because fog is one deterministic render and the shot
is anchored to it — `fog_illumination` already fits the shot's lighting onto the
template and `fog_pixel_mask` already trusts that prediction to ±26 gray levels.
So the only unknown is `f`, this frame's fade, and with `D = C − F` and
`K = α(S − F)` it falls out as a one-parameter projection `f = <D,K>/<K,K>`.

**Score the correlation, not the residual — this is the whole design.** A
residual is minimized by there being nothing there: measured, blank fog scores a
*better* residual (4.9) than a genuine flame (23.9), because a flame is a large
departure from fog and fitting it leaves a larger absolute error than fitting
noise. `corr = <D,K>/(|D||K|)` asks the question that discriminates — of whatever
departure from fog is here, how much of it is flame-shaped — and `f` cancels out
of it entirely. That is the capture-independence the old thresholds lacked.

Three game facts carry the rest, and none of them is a tuned number: the flame is
always drawn at the same size relative to the tile (confirmed with the project
owner), so there is one kernel and no scale search; the flames move and fade,
which is why position is searched and `f` is fitted rather than assumed; and
ruins are never adjacent, which `cluster_ruin_tiles` already uses.

| constant | what it is | how it was set |
|---|---|---|
| `RUIN_FLAME_TILE_FRAC` 0.26 | flame width in tile steps | swept: median corr 0.689 at 0.16, **0.894 at 0.26**, 0.480 at 0.44 — a clean single peak, and one scale fits every flame across two board sizes |
| `RUIN_MATCH_MIN_CORR` 0.68 | the bar | mid-gap. Control sets report 0 markers at 0.56 and 2–4 each at 0.54; weakest genuine flame anywhere is 0.815, in-frame ones 0.913–0.954 |
| `RUIN_MATCH_MIN_SUPPORT` 0.35 | fraction of the flame on in-frame pixels | **inert on the corpus** — see below |
| `RUIN_MATCH_MIN_FADE` 0.05 | a flame can only *darken* fog | a statement about the sprite, not a threshold |
| `RUIN_NOMINATE_SAT` 100 | only search near saturated pixels | every Elyrion set reports its exact count at 0-120; only at 140 does the corpus lose ruins (37 → 31) |

**This replaced a detector built on HSV statistics fitted to the corpus**
(`RUIN_MIN_SAT`, `RUIN_MIN_MEAN_VAL`, `RUIN_MAX_MEAN_SAT`, and a three-margin
`RUIN_VIVID_*` band). All of them are gone, along with the island test
(`RUIN_RING_PX`), the hue-spread tests, the area bounds, the morphological close
and `_fog_borne_pieces`. The reason they had to go is worth keeping, because any
future color threshold here will fall into it: **mean saturation was computed
over pixels already above a saturation floor, so it measured how crisply the
marker was captured rather than what the marker is.** The sprite proves this
directly — composited over fog at rising opacity it produces mean S
110.7 → 141.2 → 161.4 at mean V pinned to 246.7–252.1, which is the corpus's
entire observed 104–159 spread out of one sprite.

The close and `_fog_borne_pieces` are not replaced by anything: a score map has
no components, so there is nothing to bridge into neighboring explored terrain.
`u_forest` (2,1) — the tile the close used to swallow whole — is still detected.
The island test is likewise unnecessary; terrain bleeding across a tile border is
rejected on *shape* now, and keeping it would only endanger the frontier markers
it used to.

**Result: 37 ruins, per-set identical to the old detector** (3, 3, 3, 11, 5, 9,
3 across the seven Elyrion sets), with **zero detections on all fourteen sets
with no Elyrion player**. Every tracked baseline — union, conflicts, bars,
shorelines, `--cross-check` — is unchanged on all 21 sets.

**Three traps found while building this, all of which produced confident wrong
answers rather than obvious failures:**

- **Fitting at a cluster's centroid instead of at a flame.** A merged blob's
  center is not where any flame is, and genuine markers scored as low as 0.033
  that way, against 0.89 when scored as a map. This is the same trap the old
  morphological close set, in a new place.
- **`pmask` is the wrong mask here; use `wmask`.** The taxonomy makes `pmask`
  look right ("was this pixel photographed"), but it deliberately keeps pixels
  too dark to judge color by, and those add their darkness to `|D|` in the
  correlation's denominator without adding anything a flame kernel explains.
  Measured: `u_forest` drops from 9 ruins to 7 on that change alone.
- **Non-max suppression must run inside the accepted set.** Dilating the raw
  score map lets a position rejected by a gate shadow an accepted neighbor, and
  that is not a corner case — a flame at the edge of a photo sits right beside
  windows that hang further off it and score higher on a sliver. On
  `basin_treaties` (0,9) the ruin was found (corr 0.815), gated in, and then
  silently suppressed by a neighbor that had been gated out. **No threshold
  change could have fixed it**, and both thresholds were swept before the cause
  was found.

- **A cropped correlation invents edges, and a small epsilon turns them into
  huge scores.** `matchTemplate` zero-pads its input, so every crop boundary is
  a fictional edge where the `|D|` denominator is truncated and the score
  inflated. Harmless with one crop around the whole fog region — the only edges
  were real canvas edges — and *not* harmless once `RUIN_NOMINATE_SAT` made one
  box per nominated cluster. Compounded by a `1e-9` clamp that turned "no
  support here" into an enormous number rather than no number: measured corr
  values of **1279** and **2.6e7**, where the valid range is [-1, 1]. Some of
  that garbage cleared the acceptance bar and **put ruins on six boards that
  cannot contain one**. The tell is unmistakable and worth remembering:
  *restricting* the search made the detector find **more**. Fixed by slicing
  each box with half a kernel of *real* canvas pixels around it, so only the
  true canvas edge is ever padded, and by excluding zero-support positions
  instead of dividing through them.

**`RUIN_MATCH_MIN_SUPPORT` is currently inert and deliberately kept.** Swept over
0.00/0.15/0.25/0.35/0.45 nothing in the corpus moves — same 5 ruins on
`basin_treaties`, same 9 on `u_forest`, same zero on every control set. It is
inert because `wmask` has already removed the out-of-frame pixels, so the sliver
case cannot arise the way it does against a rawer mask (measured there: a false
peak at **0.931**, higher than most genuine flames). What it still buys is the
numerical guard — as support goes to zero so does the correlation's denominator,
and 0/0 is not a score.

**Runtime went up and this is the one cost of the rewrite.** The phase runs
**0.4–1.3s** against the old 0.4–0.7s, worst on fog-heavy boards. A naive
implementation was **7.6s**.

The structural reason for the increase is worth stating, because it is not
something to tune away: the old detector thresholded on saturation and then
labeled components, so its work scaled with the number of *saturated pixels*,
and fog has almost none. A matched filter asks its question at every position,
so its work scales with **area searched**, whatever is there. That is the price
of the property that made it correct.

Five things brought the 7.6s down, and all five matter:

- Sum over channels *before* convolving wherever the kernel does not depend on
  the channel: `sum_c conv(v, K_c²)` is `conv(v, sum_c K_c²)`. Nine full-canvas
  passes become three plus two cheap ones, bit-identical.
- `cv2.matchTemplate` rather than `filter2D`.
- Crop to the fog region; a marker only exists on fog.
- **Build the fog prediction on the crop, not the canvas.** Whole and in
  float64 it is a 121MB array of which about a third is read, and it measured
  0.146s per shot against the correlation's 0.282s — 30% of the phase spent
  predicting fog nobody looks at.
- **Keep the maps in crop coordinates.** This is most of what makes the
  non-maximum suppression cheap, since it dilates with a kernel about a third
  of a tile across.

The last two together took ~35% off, with byte-identical output on all 21 sets.

A sixth, `RUIN_NOMINATE_SAT`, takes a further **~35%**: search only near
saturated pixels (`ruin_search_boxes`). This is the retired HSV detector's idea
kept for the one job it is actually good at, and the distinction matters.
Saturation failed as a *classifier*; "is there anything colorful here" is a
different and much easier question. Per-*flame* it is still hopeless — the
weakest genuine flame peaks at **S=71**, below bare fog's own 99th percentile of
90, so no threshold separates them pixel by pixel. What makes it safe is a game
fact: a ruin's marker is a **cluster**, and a cluster is not made only of faint
flames, so dropping its weakest one or two changes nothing after
`cluster_ruin_tiles`. Swept against the real pipeline, every Elyrion set reports
its exact count at every threshold from 0 to 120, and only at 140 does the
corpus start losing ruins.

Boxes come from the **components** of the nomination, not its bounding box, and
that is the whole point: measured over 16 Elyrion shots the nomination's
bounding box is still **80%** of the fog region — markers are scattered, so one
box round them all saves nothing — while the sum of component boxes is **12%**.
Note the realised saving is ~35%, not the ~8x that 12% suggests: the nomination
itself costs a color convert and a component pass, and per-box overhead eats
the rest.

Note `matchTemplate` only evaluates windows that fit wholly inside its input, so
the crop is **zero-padded by half a kernel** — without that the outermost
half-kernel is never scored, and `basin_treaties`' rim ruin at (0,9) is exactly
there.

**What is left, and why the obvious next cut does not work.** Fog is only 45–62%
of its own bounding box — the rest is the players' explored islands sitting
*inside* the fog region — so some of the correlation is still computed on tiles
that cannot hold a marker. Those results are discarded rather than believed: a
peak is only ever accepted on fog. Measured, correlation cost is **linear** in
area (8.7 ms/Mpx, flat over a 16x range), so trimming area really would pay
proportionally. But carving the islands out needs many rectangles, and each one
costs a kernel-sized halo plus its own call: the same total area in 4 pieces is
**14% slower** than in 1, and in 64 pieces **40% slower**. So a decomposition
only wins if it is into *few* pieces removing *a lot* of area — which is the
disjoint-fog case (`basin_treaties`, `u_forest2`), not the contiguous one.

The genuinely promising cut is a **half-resolution nominate pass with
full-resolution refinement near the candidates**, a straight 4x on the bulk
since cost is linear in area. Unlike everything above it is *not* guaranteed
output-identical — a coarse pass can plausibly miss a faint flame — so it needs
the full 21-set diff before it lands.

**Marking, and copying the tile.** A fogged ruin tile gets the Elyrion
player's own view of that tile pasted in, plus a violet outline
(`RUIN_MARK_BGR`) around it, so a player sees the actual flame cluster rather
than taking the outline's word for it.

This reverses an earlier "mark, never copy" rule, but the old reasoning still
constrains *how much* is copied, so it is worth keeping: the flames are that
player's private UI rather than map content, nothing else can corroborate them,
and the cluster is drawn offset from the tile it refers to and spills across the
border. So **the copy is clipped to the ruin tile's own rhombus** — a cluster
straddling a border shows only its share, and no sprite lands on a tile that did
not earn one. Three details make it sit right:
- It runs **after** the decorative overlays, so `shade` cannot dull the flames.
  Same reason the outline is drawn last.
- The patch is carried back through the **inverse of its own illumination fit**
  (`fog_illumination`'s gain) into template space, so the pasted fog matches the
  fog around it instead of showing a rectangle of that shot's exposure.
- It uses **`pmask`, not `wmask`** — this is a *pasting* operation, and the mask
  taxonomy reserves `wmask` for judging color. This is the one place in the
  ruin path where the taxonomy points the other way; see the trap below.

Violet because it sits 92° from the spawn-zone layer's hue and gives 4.5x the
brightness contrast against near-white fog that the original amber (0,215,255)
did — see the `Overlays/` section. A tile another player has actually *explored*
is skipped entirely: their real terrain is better information than either a
marker or a copy, and the report names those tiles so the knowledge is not lost.

**Then merge adjacent detections** (`cluster_ruin_tiles`), unchanged by the
rewrite, because a ruin's marker is a *cluster* of flames and ruins are never
adjacent (see the game facts above) — so neighboring detections are one cluster
straddling a tile border. Flood-fill over the 8-neighborhood (three of the five
clusters on `test_ss_elyruins` meet only at a tile *corner*), then assign the
cluster to the tile holding the centroid of all its pixels pooled across sources.

Only after merging is the count meaningful, and the cross-set evidence is what
says it is right: `test_screenshots`, `test_ss_2` and `beautiful_test3` are the
same board shot by different people at different zooms, and agree on the same
ruin tiles; `test_ss_elyruins`' two Elyrion shots independently agree on the
(8,7) cluster.

**A missing sprite switches the feature off and says so** (`NO-RUIN-SPRITE` on
stdout, mirroring `NO-OVERLAY`), and the merge still runs. There is deliberately
**no fallback detector**: a second, unmeasured detector that only runs when
something has already gone wrong is the same silent-degradation shape the legacy
templates provided, and it is why they were deleted. A shot that locked too
little fog to fit a fog reference against is likewise named and skipped rather
than matched against a guessed background.


### 5. City population bars (`detect_population_bars`, `--city-bars`, off by default in the CLI, always on in the bot)

**Vocabulary, which is the game's — the code got this wrong once and it caused
real confusion in review:**

| term | what it is |
|---|---|
| **bar** | the oblong meter under a city's name plate. Two legal widths: **0.965 tile widths** (short) and **1.44** (capped), a clean 3:2 with nothing in between |
| **segment** | one of the N subdivisions of that oblong. **Nothing in the detector looks at segments** — see below |
| **dot** | the small dark or white disc inside a segment. Never detected |
| **plate** (or banner) | the horizontal rounded rectangle above the bar: icon, name, `★ N` |

Keeps the owner-only population bar in the composite. Without it the merge
discards it: winner selection ranks by sharpness, so a non-owner's shot can win
the tiles the bar sits on and the population vanishes — confirmed in practice.

The feature turns on one observation: **the shot showing a bar *is* that city's
owner's shot**, since nobody else renders one. So no ownership has to be
inferred, and `★ N`'s embassy ambiguity never matters.

#### Detection is anchored, not searched

**A bar is always centered on its city tile's south vertex, and the merge already
knows every south vertex exactly.** So there is nothing to look for. Go to the
vertex, examine the fixed region a bar would have to occupy, and ask whether it
is one — a hypothesis test with three outcomes per tile: no bar, short bar,
capped bar.

That is the whole design, and it deletes the machinery the old bottom-up
detector needed in order to *find* candidates: connected-component labeling, a
segment height window, an aspect window, a solidity test, run grouping and an
even-pitch test are all gone, along with `SEG_*`, `BAR_SPAN_MAX` and
`BAR_PITCH_TOL`. Everything left is in **tile widths**, so none of it passes
through `REFERENCE_TILE_PX` at all — the geometry is a property of the board,
not of the render.

Three pieces of evidence, and they are independent:

1. **The silhouette** (`_bar_at`). A bar is an oblong, so its top and bottom are
   two opposite horizontal steps at fixed rows. The board is isometric — every
   board edge, tile border, territory dash and terrain facet runs at `dir_a`
   (30.7°) or `dir_b` (149°) — so *nothing on terrain is horizontal*. This is
   `_board_component`'s chrome test applied to a much smaller object.
2. **The color** (`_bar_mode`). The modal color inside a preset box.
3. **The width.** Only two are legal, so the extent is *snapped*, never measured.

**The bands and boxes are fixed, not searched, and that is load-bearing.**
Leaving the rows open made an early version fire 209 times across the corpus:
the name plate sits directly above the bar and is also a bright horizontal
rectangle, so an unconstrained search returns the *plate's* two edges — readable
in the output as a bottom edge *above* the vertex, which no bar can have.

#### Why the color test is allowed here

This file's standing rule is against identifying things by color, and a color
*fill* score does fail badly here: `light` means "bright and desaturated", which
is exactly fog, snow and pale sand, and it called **225 tiles bar-like across
three sets**. But "is the modal color inside this already-known rectangle the
color a bar is painted" is a different and much easier question — the same
distinction that makes `RUIN_NOMINATE_SAT` safe where a saturation classifier is
not.

Measured over 55 labeled tiles: a real bar's mode is **228 off-white**, a
saturated blue, or a saturated red, while every white false positive — ice,
snow, UI panels — reads **252**. The game does not paint the bar pure white, and
those ~24 gray levels are the entire margin.

Two details that are not tuning:

- **The box is preset, one per legal width, and never derived from the
  silhouette.** The short bar's footprint is a subset of the capped one, so the
  small box is inside the bar whichever length this one is — which is what lets
  color run *first*, independently, and reject a tile before any geometry
  happens. Sampling the *detected* rectangle instead couples the two tests, and
  it runs off the frame on tiles near a shot's edge.
- **Filter by `wmask`.** That is `valid` — chrome, out-of-frame and too-dark
  pixels dropped. Out-of-frame pixels otherwise win the mode outright, and they
  are not even black after JPEG: at `badland_test3` (9,15), 2 pixels of 520 are
  true zero against 43 under a channel max of 12.

#### Red bars invert the silhouette, which is why polarity is tried both ways

**A bar is not always brighter than what is behind it.** Pure red converts to a
gray of about 76 while grass sits near 130, so a red bar is a *darker* oblong on
*brighter* ground and both its edges step the other way. `scorched_earth`'s
Icalus at (15,6) is six red segments with no white, and a bright-on-dark test
finds no row pair there whatsoever — not a weak score, nothing.

So both polarities are tried. But the dark one is **scoped to red**, which is
its only justification: white and blue bars are bright and the ordinary polarity
finds them. Unscoped it admits four false positives corpus-wide, every one water
or ice, and **color cannot separate those from a blue bar** — water reads
S=186 against a real blue bar's 187. Scoping costs nothing: the one real bar the
dark polarity added, `beautiful_test3` (12,11), is found in that set's other
shot at score 0.57 anyway.

#### Segments are deliberately not counted

The detector reports a *width class* (short or capped), never a segment count.
Dividers do not survive every capture — `replay_ss2`'s Bergo has none at all,
its two segments fused into one blob — so requiring them is what made the old
detector miss it entirely. The old reports' "N segments" meant "segments the
detector resolved", which was never the bar's true subdivision count.

The claim ranking's `span_of` therefore now asks the question it actually wants:
does this bar physically reach its S/SW/SE neighbors? That is exactly the
capped width, and the short one does not.

#### Measured against the ground truth

Scored against the six labeled sets (see the ground-truth table in the test-set
section):

| | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| anchor-first, absolute rows | 49 | **0** | 1 | **1.000** | 0.980 |
| anchor-first, **relative rows** | **50** | **0** | **0** | **1.000** | **1.000** |

For comparison, on `test_ss_3` the old detector scored 7 of 9 with 3 real bars
missed.

**Every confirmed bar in the six labeled sets is found, and none of the labeled
false positives is.** That is 50 of 50 with 0 FP — see the relative-geometry
entry in the standing decisions for what closed the last one (`test_ss_3`
(10,9), Ichphy).

**Two entries this file used to carry here were stale and are gone.** The
"single miss" was recorded as `badland_test3` (15,16), a bar the `cym` player
had not wholly photographed; the zoom-pivot change moved the miss to `test_ss_3`
(10,9) without this section being updated, and (15,16) has been found ever since.
Read a claim about *which* bar is missing as needing a re-measurement, not as a
standing fact — `tools/baseline.py` cannot see it, since the bar column counts
detections and not which ones are right.

Corpus-wide the count is **242 over 27 sets** (221 over the 25 in the table
above), and every other tracked baseline — union, conflicts, ruins, fog lock,
`--cross-check` — is **identical on all 27 sets**, which is what bar promotion
is supposed to guarantee: it only reorders sources that already witnessed a
tile.

**Runtime is at parity with the old detector** — ~0.46s on a 5-shot merge, 2%
of it — but only after the modal color was written correctly, and how that went
is worth recording because two of the three obvious implementations are *slower*
than the naive one.

The phase probes every interior tile in every shot, so the work is (n-2)² per
shot rather than one component pass, and the mode is the hot spot. Measured on a
representative 520-pixel patch, 3000 calls each:

| implementation | per call |
|---|---|
| pack to int32, then `np.unique` on the **1-D** array | **0.032 ms** |
| `np.unique(patch, axis=0)` | 0.263 ms |
| pack to int32, then `np.bincount` | 1.094 ms |

`np.unique(axis=0)` has to sort a structured view; `np.bincount` allocates a
262k-element array on every call. The packed 1-D form gives a bit-identical
answer 8x faster than the next best, and it is what took the phase from ~0.9s to
~0.46s. **Do not "simplify" it back to `axis=0`.**

The other cut available -- using the two-tile city separation to stop scanning
near a confident detection -- was tried and measured inert (0.44s against
0.46s). The color test already rejects most tiles before any geometry runs, so
a skip only removes the cheap ones.


### The name plate, and why it is a claim tiebreak rather than a filter

**Game facts, both confirmed with the project owner: a name plate is *always*
present when a bar is, and it sits directly above it.** The plate is a
horizontal rounded rectangle — and the board is isometric, so every board edge,
tile border, territory dash and terrain facet runs at `dir_a` (30.7°) or `dir_b`
(149°). **Nothing on the terrain is horizontal.** That is the same discriminator
`_board_component` uses to throw chrome off the silhouette, applied to the
banner instead.

This is *not* the retired "detect the label plate and search beneath it" idea in
the standing decisions. That one tried to segment the plate by **color** and
failed because the plate is translucent and tinted by the player's color over
whatever terrain is behind it. This asks only for a long horizontal *intensity
step*, which needs no color at all.

Measured over the corpus's 203 detections — longest horizontal edge run in the
band a plate would occupy (8–56px above the tile's south vertex, ±95px wide),
in `REFERENCE_TILE_PX` units:

| population | plate run |
|---|---|
| the 79 **complete** bars | median **107**, p05 79, **min 52** |
| the 124 fragments and suspects | median 92, p05 34, **min 18** |

**As a hard filter it is marginal** and should not be built as one: a cut at 40
touches no complete bar but rejects only 10 of 124 fragments and none of the
known false positives (`goon_test` (8,2) reads 42, `pol_archi_test` (3,10) 57,
`beautiful_test3` (13,15) 52); a cut at 60 catches all three but takes
`badland_test2`'s real 135px bar at (9,18) with it.

**As a claim tiebreak it looks strong, and that is where the corpus actually
hurts.** On both contested pairs the separation is 2x or better:

| tile | what it is | span | plate run |
|---|---|---|---|
| `beautiful_test3` (12,14) | real 5-segment bar | 115 | **132** |
| `beautiful_test3` (13,15) | orange cubes | 74 | **52** |
| `beautiful_test3` (18,10) | real 4-segment bar | 134 | **147** |
| `beautiful_test3` (18,11) | false positive | 59 | **69** |

**Built** — `plate_edge_run`, ranked *after* completeness and before the
own-tile proximity rule, in `main`'s claim comparison:

```
cand = (-w, full, -plate, d, scale[n], n)
```

That position is what the (12,14)/(13,15) row requires: completeness ties (both
are under `span_of`'s bar at this render) and proximity then hands the tile to
the impostor, because it is the impostor's own tile. Vision claims carry no
plate measurement and score 0, which is neutral rather than a penalty — strength
already separates vision from detected-bar claims, so a plate value is only ever
compared against another of the same kind.

**It moved no tracked baseline at all**: union, conflicts, ruins, fog lock,
`--cross-check` *and* the bar counts are identical on all 24 sets, which is
exactly right for a change that reorders claims without creating or destroying a
detection. The whole effect is in the spliced-bar report, which no tracked
column can see: `beautiful_test3`'s real 5-segment bar at (12,14) leaves the
list and the orange-cube false positive at (13,15) is cut instead.
`badland_test3` (18,7) remains the only **complete** bar spliced.

**What it cannot do, and must not be asked to do: reject a bar-shaped thing that
really is under a plate.** `vengir_cultist`'s Xasna letters read 91 — high,
correctly, because `v1` genuinely shows that city's banner; it just shows no
bar. That family is the **south-vertex floor**'s job, and the two tests are
complementary rather than alternatives: the plate says *is there a banner here*,
the floor says *is this row the bar row or the name row*. Neither substitutes
for the other.

### Historical: the bottom-up detector, and why it is gone

**Everything in this sub-section describes code that no longer exists.** It is
kept because the failures are properties of the *screenshots*, and any future
detector will meet them again.

The old detector found segment-shaped blobs by connected components and grouped
>=2 of them into a bar, which made the divider between segments load-bearing —
it was the only thing separating a bar from any other bright oblong. That
inverts the object: the game draws **a bar which is then subdivided**, so
assembling one out of its subdivisions fails whenever a subdivision is damaged.
Four ways it was damaged, all real and all now moot:

- a segment **welds to the plate** above it and its bbox is dragged upward
  (`fogless` Tetesum, whose middle segment fuses into a 101x90 blob);
- two segments **fuse** when the divider is lost, leaving one blob where the
  grouping needs two (`replay_ss2` Bergo — the case the anchor-first detector
  finds trivially, since the fused blob *is* the whole bar);
- segments **shred into slivers** at extreme zoom-out and fail the aspect test
  (`vengir_cultist` Xasna in `v2`);
- **city name text** groups into a false bar, because round letters are
  segment-sized and sit at a typeface pitch (`Xasna` → `an`, `Annuu` → `nuu`,
  `Chowas` → `howas`). This was the worst family: the name is *not* owner-only,
  so it manufactured a detected-bar claim for a shot that did not own the city,
  which outranked the real owner's vision claim and destroyed a real bar.

Two attempts at fixing the grouping are worth recording, both failed:

- **Order-independent grouping.** The loop compared each candidate against the
  *seed* segment rather than the group, and claimed segments first-come across
  seeds. Growing a maximal run from every seed, deduplicating and taking them
  best-first **lost two real bars** (`badland_test`'s Lahaji, `beautiful_test3`'s
  Ryley), because growth is maximal so every seed inside one run yields the same
  run, and the smaller sub-runs the greedy version produced as a side effect are
  no longer candidates at all. One lesson survives and is worth keeping for any
  future grouping code: **a rejected run must claim nothing**, or the valid
  smaller runs inside it never get their turn.
- **Labeling the color arms separately**, so a white UI element touching a
  blue segment did not weld into one component (`badland_test3`'s Zirhi read
  36x24 instead of 36x14). Specified, measured at +8ms/shot, never built — and
  moot now, since nothing labels components any more.

Also retired with it: the **south-vertex floor** and the **span/pitch group
tests**. Those were doing real work against the old detector's fragments, and
they are unnecessary against a detector that only ever emits a bar at a legal
width centered on a vertex.


### Three ways of finding a bar that were tried and do not work

(Four, counting vertex offset — but that one is about telling a real detection
from a false one rather than about finding a bar at all, so it lives with the
splice discussion above.)

All three were measured on `star_change`, and all three fail for the same
reason, which is the standing decision about color restated: **the game paints
terrain in every color its UI uses**, so nothing about a bar can be isolated by
appearance alone. Do not retry these without new evidence.

- **Detecting the dividers directly.** The divider is described above as "the
  entire discriminator", which makes a divider detector look obviously right. It
  is not: roughly half of them do not survive as clean thin-tall dark components
  (they merge with the dark dot inside a segment, or lose contrast), and the
  surviving pitch sequences are irregular — 19/63/6 px on Nunusum, 36/24 on city
  (1,8), a single 73 on city (8,16). An even-pitch run test over those would
  drop bars that the current detector finds today. The dividers are a real
  discriminator *between adjacent segments already found*; they are not
  independently recoverable.
- **Detecting the bar's periodicity.** A bar is periodic, so autocorrelating a
  horizontal band's column profile looks promising. Genuine bars score ncc
  0.33–0.55 — and 400 random board locations score a 95th percentile of **0.503**
  and a max of 0.615. There is no separation, because the board is itself full
  of periodic structure: the tile lattice, crop rows, fences, territory dashes.
- **Detecting the city label plate and searching beneath it.** The bar always
  sits ~6px under a name plate, so anchoring the search there would let every
  per-segment test be loosened. But the plate is not color-separable, and fails
  *inconsistently*, which is worse than failing outright: `imp.png`'s blue plate
  sits over blue water and its pixels come back as one **1462x1334** component
  spanning half the board, while `oum2.png`'s identically-colored plate comes
  back as a clean 105x49, and `oum.png`'s orange plate over sand does not enter
  the mask at all. This is almost certainly what killed the earlier
  `city_tiles`/`propagate_city_owner` attempt recorded in the standing decisions,
  which "detected almost nothing" rather than failing loudly.

**What replaced all of them is not a detector at all** — the vision rule above,
which identifies a city's owner from the sight guarantee rather than from any
appearance. It is what finally preserved Nunusum's bar. The one class it cannot
help is a city several sources see completely (43 of 103 measured), where
sharpness still decides; `star_change`'s Icasum is that case, and note the star
cannot break it either, since `oum2` shows "Icasum ★4" against `imp`'s "★12" —
the embassy exception. The *higher* star number belongs to the owner, so
comparing the two numbers would resolve it, but that needs reading digits at a
resolution where glyph segmentation already measured 59% recall.

What remains untried for that residue is **differential detection**: a bar is
by definition present in exactly one source and absent in the others at the same
template location, so comparing sources like-for-like — the move
`--fog-frac-margin` already makes for occluded fog — cannot be fooled by the
palette. It also covers exactly the cases that matter, since a bar is only
*lost* when another shot wins those tiles, which requires overlap. A related
idea worth pursuing with it: find the city by its **text** (a structural signal,
unlike the plate's color), then use the vision guarantee — if the three tiles
S/SW/SE of that text are non-fog in exactly one shot, that shot is the owner's;
if in several, compare those tiles between them to see which one holds a bar.

The **city tile comes from where the bar sits**: a bar is centered on its city
tile's **south vertex**, with its bottom edge ~10px below it (confirmed with the
project owner; measured 0.070–0.149 tile widths over the 49 labeled bars, with
`BAR_BOT_BAND` bracketing it and `BAR_HEIGHT` constraining its distance from the
top edge — see the relative-geometry standing decision). That vertex is `origin + (i+1)*u_col +
(j+1)*u_row`, so inverting the basis at the bar's center names the city
outright — no dependence on the city sprite's height, which grows with its
level and so could not have served. Measured over the corpus's 33 complete
bars, the bar centers within a median 1.1px of that vertex in x (p90 3.1) and
its bottom sits 10.3 +- 11.7px below in y.

**The snap cannot be ambiguous**, which is what makes it better than the
bounding box: a bar reaches at most ~67px from its vertex, while south vertices
at the same height sit `u_col - u_row` ~154px apart, so the nearest vertex is
the right one even from a fragment.

That matters because **fragments are common** — an occluder splits one bar into
two detections — and the old rule took the `(min i, min j)` corner of the bbox,
which lands a fragment on a different tile from the whole bar. The tell is
*adjacent* detected cities, which the game forbids: the old rule produced 25
such pairs across the corpus, the vertex snap 19. It also mislocated
`star_change`'s Icasum to (13,13), so that city never claimed its own tile
(12,13) during promotion, and a false detection took it instead — which is why
the composite spliced Icasum's label together from two shots that render it
differently ("★12" in `imp`, "★4" in `oum2`). Complete bars are unaffected: all
33 snap to the tile the old rule already gave.

**Historical, and retired with the bottom-up detector — but keep the two
families it found.** The same vertex used to supply that detector's one working
filter: a bar hangs *below* it, so a run of blobs whose bottom sat *above* the
vertex was not a bar whatever else it looked like. It was needed because the
snap rounds to the nearest vertex and so always names *some* city, which without
a floor made every segment-shaped thing on the board a bar somewhere. The
anchor-first detector never has that problem — it only ever tests the fixed
region a bar would occupy, so a row above the vertex is not a candidate to
reject. What is worth keeping is what the floor *revealed*, below.

Measured over that detector's 263 detections, in `REFERENCE_TILE_PX` units:

| population | bottom edge relative to the south vertex |
|---|---|
| all 77 **complete** bars (span >= 100) | **+9.1 to +20.1** |
| the 115 fragments that survive | +0.0 to +50.7 |
| the 71 detections rejected | **-32.3 to -1.2**, not one of them a bar |

The cut is at **0** because 0 is the physical statement, not a fitted floor —
and the nearest genuine bar is 9px clear of it. The 71 it rejects fall into two
families, both of which are systematic rather than incidental, and neither of
which anything else in the detector can see:

- **The city's own name text.** Round letters (`a` `o` `n` `e` `s` `u`) are
  segment-sized, segment-solid, and sit at the even pitch of a typeface, so a name is a
  ready-made bar: `Xasna` → `an`, `Annuu` → `nuu`, `Chowas` → `howas`,
  `Limlaia` → `laia`, `Xi-cha` → `cha`, `Tjaol` → `aol`. It is much the worse
  family, because **the name is not owner-only**. A text bar is a detected-bar
  *strong* claim asserted for a shot that does not own the city, and it
  outranks the real owner's vision claim — so it does not merely add a spurious
  city, it actively destroys a real bar. `vengir_cultist`'s Xasna is that case
  and is the regression test.
- **Pairs of round terrain sprites** — red fruit crops, blossom trees, red
  roofs. Harmless by comparison, and the reason `fogless` reported 17 bars on a
  board where the detector never found one at all.

Corpus effect: **union, conflicts, ruins, fog lock and `--cross-check` identical
on all 24 sets**, the spliced-bar report identical (`badland_test3`'s (18,7)
still the only complete bar cut), and bar counts down from 263 to 192.

**A star-icon test does not work, and the star asset in `Assets/star.png` is
kept only so nobody has to re-derive that.** The idea is a good one on its face
— a city label carries a `★ N`, the star is a fixed sprite, and the ruin
detector proves that matching the game's own sprite beats any color threshold.
It fails for three independent reasons, each measured:
- **The premise is false, and in both directions.** Every city shows a `★ N`
  *unless it is besieged* — an enemy unit standing on it stops it producing
  stars and the number disappears — so an owner's own city can have a bar and no
  star. `vengir_cultist`'s Ckdis at (12,12) is exactly that: a complete 4-segment
  bar on the player's own besieged capital, with no `★` in its label. And an
  embassy puts a `★ N` on a *foreign* city that shows no bar. Confirmed with the
  project owner; see the game-facts section. Note this is not a capital-only
  quirk, which was the first (wrong) guess from the screenshots — the capital is
  marked by the **underline**, and that is independent of the star.
- **The populations overlap, in the wrong direction.** Scoring
  `Assets/star.png` by masked NCC over the label band above each detection
  (sprite at ~17.8 `REFERENCE_TILE_PX`, which is where the match peaks on a
  known star): complete bars score a median 0.711 but a p05 of **0.458**, with
  Ckdis lowest at **0.408** — while the Xasna text false positive scores
  **0.547**. Any threshold that rejects the false positive rejects a genuine bar
  first, and 23 of the 77 complete bars at 0.55.
- **It is weakest exactly where it is needed.** A bar is only ever *lost* to a
  sharper shot, so the shot needing help is always the blurriest one — and a
  ~17px sprite is what blur destroys first. `v2`'s Xasna star, on the shot that
  actually owns the bar, scores **0.457**: lower than the false positive it
  would have to beat. At s_it=1.843 that star is 9 pixels in `v2`'s own capture.

Note the star is also **not owner-only** — an embassy renders `★ N` on a foreign
city — so even a perfect star detector could not confer ownership. Its only
possible role was as a corroborating landmark, and the numbers above close that
off. A color-threshold version is worse still and was tried first: gold blobs
fire on yellow roads, ruin sprites and a capital's orange crown icon, matching
66% of the *false* detections.

**Vision nominates an owner too, with no detection at all.** The game
guarantees a city's owner sight of all 8 neighbors, so a source that *alone*
sees every tile of some 3x3 block is the only candidate owner of a city there.
That signal is already sitting in `samples`, and it reaches bars no detector
can: `star_change`'s Nunusum welds 7 of its 8 segments onto the white ice city
behind them (see the fusion note below), leaving one where two are needed, yet
its owner is identifiable from vision alone. Measured against the 103 cities
whose bar *is* detected, so the true owner is known: decisive on 53 and correct
on 50 of those, with the 3 misses costing sharpness rather than truth.

The rule is self-limiting, which is what stops it becoming a general "prefer
whoever sees more" policy: inside anyone's own territory every source sees the
whole block, so all of them qualify, the claim cancels, and sharpness decides
exactly as before. It only discriminates where sight genuinely differs —
frontiers and frame edges — which is where bars actually get lost. Measured
churn is 0–80 tiles per set, and a displaced tile goes to a source at most
1.39x blurrier (median 1.00–1.33), the same trade the bar promotion already
makes.

Preservation is a **priority** change, not a compositing one: promote that
source to the front of `priority` around the city. Three points matter:
- **Claim strength depends on whether a bar could really be there.** The bar
  never extends past the city tile and its S, SW and SE neighbors, so those
  four are a *strong* claim and the rest of the 3x3 a weak one. Both mechanisms
  emit both, ranked: detected-bar-strong > vision-strong > detected-bar-weak >
  vision-weak, sharpest first on a tie, with everything collected before
  anything is applied so overlapping blocks cannot be resolved by iteration
  order. **At equal strength a city's own tile beats another city's claim on it
  as a neighbor** — a bar certainly covers the tile its city stands on,
  whereas a neighbor's claim there is speculative — and only then does
  sharpness decide. That last tiebreak is what keeps a *label* whole. A city's
  name plate is 155px wide and centered on the same south vertex as its bar
  (measured on Icasum: plate x 1283–1438, center 1360.5 against the vertex's
  1362.6), so it spans three tiles — its own, S, and SE — all of which sit
  inside the city's strong claim. Without the proximity rule the city's own
  tile fell to sharpness and the label was assembled from two shots that render
  it differently ("★12" in `imp` against "★4" in `oum2`, different tribe icon),
  which reads as scuffed text rather than as a seam. That ranking is
  load-bearing, not tidy-minded. On `star_change`,
  `oum2` reports a bar at (11,12) — a **false positive on the white ice city
  sprite** of the larger city at (12,13), whose towers rise north into that
  tile (cities are never adjacent, so a "city" one tile from another is the
  tell). Promoting a flat 3x3 for it handed `oum2` tile (10,11), which no bar
  of its own could ever reach and which Nunusum's bar at (9,11) needs. The
  composite then showed *half* of Nunusum's bar, the one outcome worse than
  showing none. Ranking a bar-reachable claim above a merely-adjacent one fixes
  it without having to detect the false positive at all.
  **That example no longer reproduces**: `star_change` reports no bar at
  (11,12) today (see the note in the segment-window section — it predates the
  south-vertex floor, which is not what removed it). Keep the rule and keep the
  history — what it defends against is a false positive competing with a real
  bar for a neighboring tile, and the corpus still has 14 adjacent detected
  pairs, of which the `beautiful_test3` (18,10)/(18,11) one exercises it.
- Still promote a *superset* of the tiles the bar can touch, within a claim:
  promoting only some of them would cut the bar at a tile border. The 3x3 is
  also exactly the block a city's owner is guaranteed vision on, so this can
  never paste fog over another player's terrain.
- Promotion is still gated on the source having witnessed the tile as
  **explored**. That is belt-and-braces on the same guarantee: a mis-located
  bar can then cost sharpness but never truth.
- When several shots show one city's bar (two shots by the same player),
  arbitrate by the ordinary ascending-`scale` sharpness rule rather than dict
  order. Skipping this let iteration order decide and moved 45 tiles on
  `archers_test2` where 15 was right.

Residual, accepted: a city sprite spanning two tiles that go to different
sources now shows a visible sharpness seam through the sprite. That is
inherent to compositing tile-wise and is much the lesser artifact.

**The merge reports bars that came out spliced**, and this is the number to
watch rather than the detection count. A bar is only preserved if *every* tile
its pixels cross went to a source showing it; one tile lost splices it. None of
the other figures can see that — the explored union is invariant under
promotion by construction, and "bars found" counts detections — so a spliced
bar leaves every tracked baseline completely unchanged. It is nearly free to
check, since `winner` and the bar bboxes are already in hand.

Read it with the width and the `complete` flag it prints, because the two cases
want opposite reactions:
- a **complete** bar losing a tile is the real defect (half a bar on the
  composite);
- a short **fragment** losing one is usually the system working. Cities are
  never adjacent, so a 2-segment blob beside a complete bar is a false positive,
  and overriding it is the point.

Current state: **one complete bar is spliced, on `badland_test3`** — Caum at
(18,7), a 120px 4-segment bar seen only by `cym.png`. Its bar crosses its own tile
plus S, SW and SE; `cym` wins three of those and loses **(19,7)** to `yad`, so
the right end of the bar is cut. The mechanism is the promotion gate rather
than the ranking: `cym` holds a strength-3 claim on (19,7), but only 76.6% of
that tile is inside its frame, so it does not clear `--min-valid-frac` and
reports `witness=False` — and a source that did not witness a tile is not in
`priority[key]`, so its claim is skipped silently. That gate is deliberate
(a mis-located bar must never paste fog over real terrain), so the fix is not
to relax it; the candidates are to let a *strong* bar claim carry a lower
valid-frac bar, or to accept the cut. Note the set is new rather than regressed
— before `pan_hint`, `cym` was dropped entirely and that bar was absent
altogether.

**Three incomplete ones are also spliced**, and all three are false positives
being correctly cut: `archers_test2` (3,13), `beautiful_test3` (7,16) and
`goon_test` (8,2). The list was seven; four came off it, and each for a reason
worth knowing rather than by tuning:

- `beautiful_test3` (12,14), a real 5-segment bar, was losing (13,15) to a
  false positive on a pair of orange cubes. **Plate evidence** now settles it —
  132 against 52 — where completeness tied and the own-tile rule had handed the
  tile to the impostor.
- `test_ss_3` (16,11), `beautiful_test3` (18,11) and `archers_test2` (12,10)
  were all impostors sitting next to a real bar, and the **adjacency
  contradiction** removed them outright rather than merely out-ranking them.

That is the pattern to expect from this section from here on: the guarantees
delete a false positive, and the ranking only has to arbitrate what survives.

**Vertex offset does not reduce the false-positive rate — tried, measured, and
not kept.** It is the most promising-looking idea available, because unlike the
three below it rests on a confirmed game fact rather than on appearance (a bar
is centered on its city's south vertex), and the numbers look decisive: over the
corpus's 219 detections, those ≥100px wide sit a median **1.4px** from their
vertex (p90 9.8) while narrower ones sit at 18-20px (p90 42), and on the
`beautiful_test3` case the genuine 122px bar is 0.9px off against the two false
positives' 18.9 and 18.3 — a 20x separation. It fails twice over anyway:
- **As a filter**, because a genuine 135px bar centered on its vertex reaches
  67.5px out *by definition*, which is exactly where the threshold must sit.
  Rejecting on furthest-edge distance removed 78 of 219 detections including
  **35 of the 52 complete bars** — it clips real bars before impostors.
- **As a claim tiebreak**, because a genuine fragment is off-center by
  construction (seeing half a bar puts its bbox center half a bar off), so
  offset really separates complete-from-narrow, which `span_of` already does
  directly and better. Wired in after completeness it left every tracked
  baseline identical and every complete bar intact, moving one contested tile
  between two *competing false positives* where nothing says which should win.

The adjacency contradiction
that used to be listed here alongside it **has since been built** and removed
those pairs outright (see the placement-guarantee note above), which is the
contrast worth keeping: offset is an appearance, adjacency is a rule the game
enforces. What remains genuinely untried is the **differential** idea below — a
bar is present in exactly one source and absent from the others at the same
template location.

## Standing decisions (don't relitigate without new evidence)

- **No rotation, ever.** Verified strongly (see above). A non-trivial fitted
  rotation means bad input, not something to compensate for.
- **Don't assume the sky is black.** The game runs a slow *sunrise* that
  progressively lightens the background the longer it is left open, so the
  sky's brightness is not a constant of the render: on
  `pol_archi_test/pol.png` it runs V=13 at the top of the frame to V=60 at the
  bottom, sailing past `--dark-thresh`. When that happens the silhouette fuses
  with the background and **all four board edges come back as phantoms**.
  Identify the sky by what it is instead — *empty*. It carries no content, so
  its local standard deviation is ~0 against the board's 24-27 (`sky_mask`).
  Two things matter about that test:
  - Smoothness alone is **not** enough and actively breaks things: where the
    board is genuinely flat (desert sand, calm water, ice) it deletes real
    silhouette, costing `badland_test` both b-direction edges at every
    threshold tried. It must also require **connectivity to the image
    border**, which sky always has and an interior flat patch never does.
  - It deliberately never looks at brightness, which is the whole point —
    however far the sunrise goes, empty space stays empty. Verified identical
    at std thresholds 2.0/4.0/8.0 across every set.
  - **It is a fallback, applied per shot and only on failure, and it costs
    the black-sky case nothing.** It hangs off the edge fit inside
    `anchor_to_template` (`sky_rebuild`), which is already computing the
    boundary and the supports, and is invoked lazily only when those come
    back with no edge usable for pan. A black-sky shot takes the first branch
    and never builds the second mask — verified: a 4-shot merge still makes
    exactly 4 `board outline + edge fit` calls at the same 0.14s as before.
    Don't hoist this into a pre-pass over every shot; an earlier version did
    and doubled that work for the common case to serve a rare one.
  - Applying it to *every* shot rather than on failure fixes `pol_archi_test`
    and **breaks** `test_ss_2`: `cym1.jpg` has two weakly supported edges, and
    nibbling the rim moved their implied zooms from 0.20% apart to 2.22%,
    dragging that set from 0.037 to 0.115 cross-check tiles. A shot with clean
    edges has nothing to gain here and something to lose.
  - `tests/sunrise.jpg` is the reference case, kept as a loose file rather
    than a set because it is a single shot and cannot be merged or
    cross-checked. It is the extreme: sky at **V=254, saturated pink**,
    brighter than most of the board, with `--dark-thresh 25` admitting 88.7%
    of the frame. Brightness-only supports are `[11,11,11,11]`; with the sky
    test they are `[326,464,921,158]`. Any future change here should be run
    against it.
- **A lone edge pair needs both sides properly supported.** The low
  `--min-scale-support` bar is justified by pairs cross-checking each other,
  and with two pairs the printed spread exposes a weak side. With only one
  pair there is nothing to check against, and an edge barely above the phantom
  floor is simply believed: `pol_archi_test/kick.png` had a-min=400 with
  a-max=30 and produced a zoom **7.8% off** — far outside `joint_register`'s
  ±3% window, so nothing downstream could recover it, and the merge came out
  at 1.74 tiles of cross-check disagreement with 93 conflicts. Requiring a
  sole pair to clear `--min-edge-support` on both sides sent that shot to the
  SIFT fallback instead, which landed it within 0.19% (0.038 tiles, 4
  conflicts).
  **The rule stands, but the support count is no longer how it is enforced.**
  That a-max of 30 was chrome capturing the edge, and `_board_component` fixes
  it at source — kick now reads a-max=587 and takes an ordinary two-pair zoom.
  Meanwhile the support bar was rejecting a *genuine* weak pair:
  `replay_ss2/s1`'s a-pair is 1704/69, and its span is right to 0.12% (1330.3px
  against the 1331.9 the other shot independently implies — its weak `a-min`
  sits **1.6px** from where `s2` fits the same line with 1438 points). A weak
  edge here is short, not misplaced.

  So a lone pair whose weak side misses `--min-edge-support` is now put to a
  question the board itself answers (`LONE_PAIR_EXTENT_LO/HI`): **the board is
  square, so the pair's span must match how wide the silhouette already looks in
  the other direction.** The observed extent along the other axis is a lower
  bound on that direction's span — equal when both its edges are in frame, short
  when one is cut — so a real pair lands at ratio ~1 or a little above.

  | population | ratio |
  |---|---|
  | genuine lone pairs | 0.985, 0.997, 0.998, 1.026 |
  | phantoms, reconstructed by switching the chrome filter off | 0.691, 0.699, **0.873**, 1.307, 1.331 |

  The 0.873 is `kick.png` — the shot the rule was written for. `[0.95, 1.15]`
  clears the nearest genuine by 3.5% and the nearest phantom by 8%, and it is
  only ever consulted when the old bar already failed, so nothing that passes
  today can start failing. **The evidence is four genuine samples**; it fails
  safe (a rejected pair falls back to hunting another zoom source, exactly as
  before) but that is thinner calibration than most numbers in this file.
- **Never identify fog by color/saturation.** Use correlation against the
  template's fog art. This was gotten wrong once already and silently
  dropped mountain tiles from the composite. **Ruin-vision detection used to
  be the one exception and no longer is** — it now matches the game's own
  sprite against a prediction of the fog behind it, so no color threshold
  decides anything there either. That change was not tidying: the saturation
  statistic it removed was measuring how crisply a marker had been
  photographed, and had silently cost two sets most of their ruins.
- **Don't measure zoom by matching fog patches against the template.** Fog is
  periodic, so a patch at the wrong scale correlates strongly against a
  different repeat, and a zoom outside the swept range returns a confident
  wrong answer rather than no answer — `hood.png` at 1.66x anchored ~2% off
  and locked zero fog tiles, silently. Measure the fog's own repeat *period*
  by autocorrelation instead (`fog_period_scale`): the period is the quantity
  wanted, harmonics are a factor of 2 away rather than a few percent, and
  there is no swept range to fall outside of. It is also ~6x faster.
  **"No swept range to fall outside of" is the one part of that which is not
  true, and `missized_test/z2.png` is the proof** — there is still a sweep, and
  a shot zoomed out past its floor loses its fundamental and picks up the 2x
  harmonic, reading half the board size. The floor is now `lo=0.30` (was 0.45),
  which admits shots to s_it=3.33. What makes this *recoverable* where the old
  patch-matching was not is that the failure is a clean factor of 2 rather than
  a few percent, so it lands far outside the board-size guard and refuses the
  merge loudly instead of anchoring 2% off in silence. Note also that the
  smallest-strong-peak rule only defends the *upper* side: nothing guarantees
  the shortest strong peak is the fundamental, only that no harmonic of the fog
  is shorter than it. Lowering the floor widens the undefended side — see the
  deferred item.
  **What moving the floor cost the existing corpus, measured directly:** 13 of
  the then-16 composites came out **bit-identical**, and on the other three only
  the shots that take their zoom from the period moved at all — every
  edge-anchored shot was unchanged to 0.00px. The moves were
  `badland_test/oum.jpg` 1.40px, `test_ss_elyruins/cym.jpg` 1.44px and
  `hood.png` 0.69px, and
  `test_ss_fruit/oum.webp` 1.36px: at most **0.016 template tiles**, against a
  0.05-tile healthy bar. Explored union and conflict counts were identical on
  all of them. Where a trustworthy cross-check exists it improved
  (`badland_test` 0.018 → 0.011). If this sweep is ever re-run, that is the
  shape to expect: a sub-pixel resample on the fog-fallback shots and nothing
  anywhere else.
  **The ceiling `hi` moved later, 2.30 → 3.75, and that one is strictly
  additive.** `basin_treaties/q.png` needed it (see that set above). Swept
  across every shot in the corpus at hi = 2.30 / 2.75 / 3.00 / 3.75 / 4.50,
  **64 of 65 shots return a bit-identical period at every ceiling** — nothing is
  pulled onto a longer peak, which is the smallest-strong-peak rule holding up
  empirically and not just on paper. Only `q.png` moves, from `None` to
  202.3px/0.72, and it is stable from 2.75 up. Cost is +16 ms/shot
  (144 → 160 ms), ~11% of a phase that is ~3% of a merge.
  **Why 3.75 rather than the 2.75 that `q.png` alone needs:** the bound is not
  set by the game's pinch limit but by pinch limit × device pixel density. That
  same view captured wider scales the period proportionally — 202px at q's
  2752px-wide iPad capture becomes 282px at 3840 (4K), needing hi ≥ 3.51. So
  3.75 is "q's zoom on a 4K screenshot", not spare range for a zoom nobody can
  reach. Note the failure mode when the ceiling *is* exceeded is the loud one —
  `fog_period_scale` returns None and the shot is dropped with a message, not
  anchored wrong — so being slightly too generous costs 16ms and being slightly
  too tight costs a whole shot.
  **But note what that costs, and don't remove the compensating check**: a
  period measurement is scale-relative, so a shot anchored that way locks onto
  the *wrong* map size just as happily as the right one. On
  `test_ss_elyruins` at `--map-size 18`, `cym.jpg` and `hood.png` locked 88
  and 91 fog tiles, so `--min-fog-lock` passed and the run produced a silently
  wrong composite. That is why the board-size check exists (see the anchoring
  section above).
- **Don't resolve a board-size disagreement by majority vote.** It is the
  obvious move once you accept that one shot can measure wrong, and it does not
  work here, because **only a shot spanning the whole board in one direction
  measures at all** — the rest abstain. Across the corpus that is **41
  measurements from 55 shots**, and only **6 of 18 sets** have the three or more
  a majority needs (`pol_archi_test` produces 0 from 2 shots, `star_change` 1
  from 3, `badland_test` 1 from 2, `basin_treaties` 1 from 2 — its zoomed-in
  `q.png` cannot span the board). `missized_test` is the case this would have
  been built for and it has exactly two, one each way: `y.png` shows only the NE
  corner (`a-min` + `b-max`, no *opposite* pair) and abstains, so the vote is
  17.93 against 8.60 with nothing to break it. What resolves that set is the
  plausibility filter — 8.60 is not near any board size — and what should
  resolve a genuine conflict is the fog lock, not a headcount; see the deferred
  item.
- **Don't try to catalog or classify terrain appearance.** There are ~16
  tribes, each with its own skin for plains/forest/mountain plus variants, so
  the same logical terrain has hundreds of possible appearances — an
  appearance catalog is not a finite job. This closes off the obvious idea
  of replacing the mean-color `--consistency-thresh` check with a terrain
  classifier. Fog is the only art on the board that is one fixed render, which
  is exactly why the whole pipeline is built on it and not on terrain.
- **The old `group -> template` fit-residual metric was vacuous** — fitting a
  4-DOF similarity to 4 corners is near-exactly determined, so the residual
  reads ~0.7px regardless of whether the anchor is right or several percent
  off. `--cross-check` (SIFT-based, independent of any single anchor) is the
  real correctness signal; don't reintroduce residual-based self-checks as
  evidence of anything.
- **Don't drop or narrow the div=1 level.** It is 58% of runtime, so it is the
  standing temptation whenever a merge feels slow, and the obvious cuts were
  all measured across the full 13-set corpus (worst `--cross-check`, explored
  union, conflicts, bar count, wall time) against a base run that reproduced
  every documented baseline exactly. Total wall for the corpus, base 134.7s:

  | variant | wall | what it cost |
  |---|---|---|
  | drop div=1 entirely | 96.6s (-28%) | cross-check ~2x worse on 8 sets, 6 past the 0.05 bar; `goon_test2` lost a union tile; `test_ss_2` lost 5 bars |
  | drop div=1, finer zoom at div=2 | 138.5s (**+3%**) | *slower than base* and still worse — the extra div=2 warps cost more than div=1 saved |
  | narrow div=1's zoom span to +-0.001 | 111.7s (-17%) | 6 sets worse, `test_ss_5` lost a union tile, 4 bars lost |
  | that plus `max_px=160` | 104.4s (-22%) | same 6 regressions |
  | `max_px=160` alone (halves div=1 samples) | 118.7s (-12%) | all 13 unions intact, 12 sets flat or better, but `star_change` 0.083 -> **0.109** and a bar lost |

  The narrowing result is the one that teaches something, because it refutes
  the reasoning that motivates it. `JOINT_LEVELS`' comment says each finer
  level "only has to cover the previous level's step size", which makes div=1's
  +-0.003 zoom span look like 2x over-coverage against div=2's 0.003 step. It
  is not waste: the coarse level's score surface is noisy, so its optimum is
  *not* reliably within one step of the true one, and the full-res level is
  genuinely re-searching a wider zoom range rather than polishing inside a
  bracket. The comment describes the design intent, not the reason it works.
  `max_px=160` is the only near-miss, and it fails for the reason
  `_tile_sample_grid`'s own note already predicts — thinning samples hurts the
  shots with least fog to constrain the fit, so the set it damages is
  `star_change`, whose `oum.png` has ~7 fog tiles in frame. Trading the most
  fragile shot in the corpus for 1.5s is the wrong direction here.

  **This entry used to open "there is no cheap speedup left in the
  `joint_register` pyramid", and that is now false** — see the fog-colour tile
  prefilter below, which took the corpus 25% faster with the explored union,
  the bar count and the ruin count identical on all 27 sets. Everything in the
  table above still stands. What all those variants have in common, and what
  the prefilter does not, is that they bought speed by evaluating **fewer
  hypotheses**. The prefilter evaluates every hypothesis and pays less per one.

  **Three updates since this was written**, all consistent with it. First, the
  phase got *more* expensive on purpose: the beam widths in `JOINT_LEVELS` now
  carry 3/2/1 zoom candidates between levels, roughly +30% wall, because
  single-candidate selection was picking the wrong branch (see the anchoring
  section). Note how well the narrowing result above predicted this — it had
  already established that the coarse optimum is not reliably near the true
  one, which is exactly why one candidate is not enough. Second, there *was*
  one cheap speedup left after all, and it is a pure win rather than a trade:
  `_fog_alignment_score` was re-gathering the template at (Y, X) on every call
  even though that gather depends on neither the zoom nor the pan, so it is
  identical for all several hundred calls in a level. Hoisting it out of the
  loop cut a 4-shot merge from 22.0s to 18.4s with byte-identical output.

  Third, the **fog-colour tile prefilter** below — the same shape again and
  much the largest, since it is work whose result was computed at every
  candidate and then thrown away by the sort. Fourth, the **closed-form coarse
  scorer**, also below, which is a third shape: machinery only a minority of
  rows need, paid for on all of them. If you go looking for more, look for those
  three shapes — an invariant recomputed in the inner loop, work whose result is
  discarded, and a general case charged to the common one — not for coverage to
  cut.
- **`joint_register` scores only the tiles that could be fog, and the keep-set
  is chosen once** (`_fogish_tiles`, `JOINT_TILE_FOG_FRAC`, `JOINT_TILE_FLOOR`).
  This is the largest speedup in the program's history and the reasoning is
  worth keeping in full, because most of it is about what makes a colour test
  admissible here at all.

  **Where the time is.** Profiled on a 4-shot `test_screenshots` merge:
  `joint_register` is 59% of wall, and `_fog_alignment_score` is **94% of
  that** — 56% of the whole merge. Warps and borders are 5%. Per level:

  | level | score time | calls | tiles x px |
  |---|---|---|---|
  | div=4 | 2.54s | 1568 | 400 x 160 |
  | **div=2** | **8.06s** | **4900** | 400 x 160 |
  | div=1 | 5.23s | 1400 | 400 x 320 |

  Note div=2 samples the *same* 160 px per tile as div=4, because
  `_tile_sample_grid`'s cap is `max(max_px // div, 160)` and the floor binds at
  both. It is not a cheaper level, only a more heavily visited one.

  **The observation.** The score sums only the top `JOINT_TOP_K` (60) per-tile
  correlations, so on a 400-tile board 340 tiles are gathered, correlated and
  then discarded by the sort — at every one of ~2000 candidates. A tile that
  cannot be fog by colour is never going to survive that sort, so it need not be
  sampled. Cost is linear in the tile count, so the saving is proportional.

  **Why a colour test is allowed here**, given the standing decision against
  identifying fog by colour: it is a *nominator*, not a classifier. It never
  decides what a tile is — it decides whether the tile gets a vote on the
  anchor. Every tile is still classified, merged and reported exactly as before.
  Same distinction as `RUIN_NOMINATE_SAT` and the SIFT terrain-inlier mask, and
  the same one that makes the city-bar modal-colour test acceptable.

  **Measured headroom**, over all 74 shots in the 27 sets, at the prior: the
  existing `fogish_mask` at a 50% per-tile threshold keeps **37.7%** of tiles
  (range 2%-75%), and 42.6% with the floor.

  **Safety, measured the only way that matters** — does it exclude a tile that
  goes on to *lock fog* at the final anchor? On 71 of 74 shots, no. Three lose
  some: `goon_test2/imp` 11 of 58, `control_c` 5 of 76, `control_d` 1 of 88.
  Those cost accuracy rather than truth (the tile is still merged; only its vote
  is dropped), and the corpus result below says the cost did not materialize.

  **Three things about the design are load-bearing:**
  - **The keep-set is fixed, not decided per candidate.** Deciding per candidate
    means gathering the fog-ish mask at exactly the coordinates you were trying
    to skip, which pays the gather you meant to save.
  - **It is computed once, at full resolution, from the incoming edge prior** —
    not per pyramid level. There is nothing to gain from recomputing it, since
    the prior moves by at most a few percent of zoom and ~24px of pan across the
    entire search, and a per-level version has to rescale the mask by `div`,
    which is one more thing to get wrong. Measured: once-only and per-level give
    **identical** cross-check numbers on every set tried.
  - **The floor is not optional.** 30 of the 74 shots keep fewer than 120 tiles
    on colour alone and several keep fewer than `JOINT_TOP_K` — `replay_ss2`'s
    two shots keep **5 and 6 of 256**, `star_change/oum` 11 of 324,
    `test_ss_2/cym1` 46 — so without it a fog-poor shot's objective collapses to
    a sum over almost nothing. Topping up from the ranking costs the fog-heavy
    shots nothing, since the threshold already keeps more than the floor there.

  **Thresholding, not ranking.** Taking the top N tiles by fog-ish fraction
  instead looks equivalent and is worse: the ordering *within* fog is arbitrary,
  so on a fog-heavy shot a cut at N discards real fog at random. Even top-200-of-400
  still drops final-top-60 tiles on 18 shots, where the threshold drops none.

  **Corpus effect, 27 sets:**

  | | before | after |
  |---|---|---|
  | explored union | 6296 | **6296** (identical on every set) |
  | city bars | 237 | **237** (identical on every set) |
  | ruins | 37 | **37** (identical on every set) |
  | conflicts | 180 | 182 (+2, all on `star_change`) |
  | corpus wall | 529s | **398s (-25%)** |

  Cross-check moved on five sets, **four of them better**: `star_change` 0.162
  -> **0.044**, `fogless` 0.511 -> 0.253, `pol_archi_test` 0.031 -> 0.020,
  `beautiful_test3` 0.029 -> 0.020. The one regression is `replay_ss2`
  0.056 -> 0.259, on a board with **no fog at all**, where both shots keep an
  unrefined edge anchor under the zero-lock rule — so cross-check is again
  reporting the quality of an anchor the merge discards. Its union stayed
  256/256 and its one real bar (Bergo) survived.

  Per-set saving run serially is **20-50%** (`badland_test3` -29%,
  `basin_treaties` -20%, `fogless` -33%, `pol_archi_test` -33%); the -25% corpus
  figure is measured under `--jobs 4` and is understated by contention. Three
  sets appeared *slower* in the parallel run and are not — that was scheduling.

  **The one coverage loss.** `star_change/oum.png` now locks 6 fog tiles rather
  than 0, so it is no longer eligible for the SIFT anchor borrow, and **no set
  in the corpus exercises that path any more.** The reasoning in the
  misanchor-guard section still stands; it is simply no longer regression-tested.

- **The zoom sweep pivots about the board centre, because `s * p_image + t`
  scales about the image corner** (`board_c` in `joint_register`). The search
  was always *joint* in the sense that it evaluates the whole (zoom, dx, dy)
  product rather than zoom-then-pan — that part of the docstring was right —
  but the two axes of that product were not independent, and the pan sweep was
  too small to absorb the difference.

  **The measurement.** `p_template = s * p_image + t` scales about the image
  origin, i.e. the top-left pixel of the screenshot. So holding `t` fixed and
  changing `s` does not rescale the board in place; it swings it by `(s_cur - s)`
  times the board's distance from that corner, which is most of a screenshot.
  On `test_screenshots`, whose board centres sit 371-1012 px from the origin:

  | level | zoom span | pan reach | swing at the board centre | covered? |
  |---|---|---|---|---|
  | div=4 | +-3.0% | +-24 px | +-26 to +-39 px | **no, 1.1-1.6x short** |
  | div=2 | +-1.0% | +-6 px | +-8.8 to +-13.0 px | **no, 1.5-2.2x** |
  | div=1 | +-0.3% | +-2 px | +-2.7 to +-3.9 px | **no, 1.4-1.9x** |

  Every level, every shot. So the ends of the zoom sweep were scored while
  *guaranteed* misregistered by 10-15 px, for a reason that says nothing about
  whether the zoom is right, and the score surface was pulled back toward the
  prior. That is plausibly part of the "coarse optimum is not reliably near the
  true one" behavior recorded above, and it means the effective zoom range was
  narrower than `JOINT_LEVELS` claims.

  **The fix is one line of arithmetic**: carry the translation that holds the
  board centre still, `t = t0 + (s_cur - s) * piv`, so each zoom is scored at
  its own best centring and `dx`/`dy` then search genuine pan.

  **Corpus, 27 sets:**

  | | before | after |
  |---|---|---|
  | explored union | 6296 | **6300** (+4) |
  | ruins | 37 | 37 |
  | conflicts | 182 | 182 |
  | real bars vs the six labeled sets | — | **net zero** |
  | false positives on those sets | 31 | 31 |
  | runtime, run serially | — | **~10% faster** |
  | cross-check, 21 reliable sets — mean | 0.0279 | 0.0274 |
  | " median | 0.0220 | 0.0240 |
  | " max | 0.0710 | **0.1120** |

  **Read the bar column as a swap, not a gain**: it loses `test_ss_3` (10,9)
  (Ichphy) and gains `badland_test3` (9,15), both confirmed real, with no false
  positive added. That is the column with a known answer, and it says the change
  is neutral there rather than positive.

  **`star_change` replaces `vengir_cultist` as the only set over the 0.05 bar**
  (0.044 -> 0.112 while vengir goes 0.071 -> 0.029), and the mechanism is
  consistent: pivoting genuinely *widens* the zoom range explored, which helps
  every shot with fog to score against (`u_forest` 0.049 -> 0.018, `test_ss_5`
  0.050 -> 0.021, `badland_test` 0.027 -> 0.011) and hurts the one shot in the
  corpus with almost none — `star_change/oum.png` and its ~7 fog tiles, whose
  score surface is close to noise. That set's merge output is unchanged.

  **Pivoting about the centroid of the *scored* tiles instead is worse — tried
  and reverted.** The theory was that the score only reads the fog-ish tiles
  `keep` selected, which on a partly-explored board sit well off centre, so
  `star_change/oum.png`'s cornered seven tiles would still swing. It does not
  work: star_change reads **0.123** (no better than the board centre's 0.112)
  and `test_ss_3` 0.032 -> 0.046 and `xizauh` 0.020 -> 0.033 both regress. The
  board centre is the pivot to keep.

  **Note the corpus `seconds` column said this was 30% *slower* and that was
  wrong** — `tools/baseline.py` runs `--jobs 4`, so its wall figures are
  contention, not measurement. Timed serially the same three sets run 17.8 ->
  15.9, 21.9 -> 19.6 and 7.2 -> 7.3. This is the second change in a row where
  that column misled; time a change serially before believing it.

- **The score gathers through a flat `take`, not a 2-D fancy index** — the one
  remaining pure win, and the only change in this file's history that is
  **bit-identical on every set and every tracked field** while still being worth
  ~20% of a merge.

  `_fog_alignment_score` read its two arrays as `img[Y + dy, X + dx]`. Numpy
  builds a coordinate pair per element for a 2-D fancy index and does not for a
  1-D `take`, and on this function's sample grid (226 tiles x 160 px) that is
  the difference between **0.630 ms and 0.086 ms** for the two gathers — 7.3x on
  them, **1.76x on the whole call**. Nothing about the arithmetic changed, so the
  result is the same bits.

  What makes it fit is that a pan is a *scalar* offset in flat coordinates:
  `base = Yp * pw + Xp` is invariant for a whole pyramid level, and a pan of
  `(dx, dy)` is `off = dy * pw + dx`. So the per-call address work is one integer
  add over the sample grid (0.004 ms at int32) rather than a full 2-D index.
  `tgtp`, `wgp` and `wvp` share the padded width, so one `base` serves all three,
  and `ravel()` on a contiguous array is a view, so the per-zoom cost is zero.

  Measured serially, four sets: `test_screenshots` 12.8 -> 9.9s, `archers_test2`
  14.7 -> 12.7, `goon_test2` 5.7 -> 4.1, `xizauh` 10.9 -> 8.6 — **14% to 28%**.
  `tools/baseline.py --compare` reports *identical on every set and every tracked
  field*, which is the expected result and the whole point: a change that cannot
  move the corpus needs no judgement call about whether the movement was worth it.

  **Hoisting the float32 conversion out of the loop buys nothing on top**, and is
  a trap at div=1. Precomputing `img.astype(np.float32).ravel()` once per zoom
  measured **0.709 ms against the flat-take's 0.711** — the conversion of a 36k
  gathered array is not where the time was — while at div=1 it would convert a
  5.2M-pixel canvas per zoom candidate to save 4 ms of per-pan `astype`. Take the
  indexing win and leave the conversions on the small array.

  **Where the time is now** (4-shot `test_screenshots`, after the prefilter and
  the zoom pivot): `joint_register` is **40%** of wall, down from 59%, and
  `_fog_alignment_score` is 88% of it — 35% of the merge. Per level, 0.93s /
  2.61s / 1.52s at div=4 / 2 / 1 over 1568 / 4459 / 1300 calls. div=2 is still
  the expensive level for the reason recorded above.

- **The coarse levels score only the tiles with no invalid sample, in closed
  form** (`_fog_full_score`, `fast` in `joint_register`). With the gathers down
  to 0.086 ms the per-call breakdown was arithmetic **0.469 ms**, gathers 0.086,
  top-k sort 0.004 — so there was no addressing left to win, and no point
  replacing `np.sort` with `np.partition` (0.004 against 0.005 — the array is
  ~150 long). What was left was the masked centring, and most tiles do not need
  it.

  **Why a tile's validity moves with the pan at all**, since this is the part
  that reads wrong: it does not. `valid` is a property of a screenshot pixel and
  never changes. The shot and its mask are warped into *template* space, where
  `warpAffine`'s `BORDER_CONSTANT` makes every position the shot does not reach
  read 0; the tile sample grid is fixed; and the pan is applied to the **sample
  coordinates**, not to the image. So the pan chooses which pixels a tile reads,
  and a tile at the edge of what this shot photographed has all 160 samples on
  real pixels at one offset and three on the zero border at the next. What
  depends on the pan is the *count of valid samples in a tile*, and that is
  exactly what the masked correlation keys on — `b - mean(b over valid)` is a
  different vector at every offset, which is why the template side cannot be
  hoisted out of the loop the way `tmpl_vals` is.

  For a tile with **no** invalid sample it can be: `bc_pre = b - mean(b)` and
  `|bc_pre|` precompute per level, `sum(ac*bc)` collapses to `sum(a*bc_pre)`
  because `sum(bc_pre) = 0`, and `sum(ac^2)` to `sum(a^2) - sum(a)^2/n`. Three
  reductions over the shot's samples instead of ~ten passes, and no validity
  gather at all: **0.079 ms against 0.534** on a captured div=2 call.

  **The set is settled once per *level*, as the intersection over that level's
  zoom candidates.** Two things force it up to that scope, and they are
  different:
  - *Not per pan*, because deciding per pan means gathering the validity mask at
    exactly the coordinates you were trying to skip. So a tile qualifies only if
    it is valid at every pan, which `cv2.erode` with the level's own pan grid as
    the structuring element answers in one pass (`borderValue=0`, or the border
    reads as no constraint rather than as invalid). It costs **0.057s over 128
    calls** on a 4-shot merge, i.e. nothing.
  - *Not per candidate*, because a different zoom warps the shot differently, so
    its coverage boundary in template space moves and the boundary tiles flip —
    **151 to 171 tiles across div=4's eight candidates** on
    `test_screenshots/IMG_3061`, 29 of them unstable. The score is a sum over the
    top `JOINT_TOP_K` per-tile correlations, so a candidate whose set happened to
    be larger would draw its top-k from more tiles and win for a reason that says
    nothing about alignment. Intersecting makes every candidate in a level answer
    the same question — a *stronger* property than the masked path has ever had,
    since its own `min_valid` gate varies per pan.

  **Per-candidate was built first and the corpus caught it**, which is the reason
  to record it: it moved four cross-check numbers (`goon_test` 0.019 → **0.033**,
  `test_ss_2`, `pol_archi_test`, `scorched_earth`) where the level-fixed version
  moves one. Same speed to within this machine's noise, measured three times.
  The intersection only shrinks, so the pre-pass stops the moment it drops below
  `top_k` rather than warping the rest for an answer already settled — which is
  what keeps it from costing the fog-poor shots anything.

  **The coarse levels are the *worst* fit for this and are taken anyway.** Pan
  radius is in each level's own pixels, so div=4 slides the sample grid ±24
  template px against div=1's ±2, and erodes four times as much boundary.
  Measured over 21 shots, the mean fully-valid share is **0.631 / 0.736 / 0.795**
  at div=4 / 2 / 1 — the opposite order to where it would help most. They are
  simply where the time is (~69% of scoring), and **div=1 stays on the exact
  masked score**, so the final answer is still chosen at full fidelity and the
  coarse levels only nominate branches. That is the same nominator-not-classifier
  split as the fog-colour tile prefilter, `RUIN_NOMINATE_SAT` and the SIFT
  terrain-inlier mask.

  **The floor is what makes it safe, and it is `top_k`.** A fog-poor shot keeps
  almost nothing — `star_change/oum` holds 25 of 120 tiles at div=4,
  `test_screenshots/Screenshot_...349217` 12 of 120 — and below `JOINT_TOP_K` the
  objective would be a sum over fewer terms than it is meant to select from. Such
  a level falls back to the exact masked score **in full, never a mix**: the two
  forms agree only to ~1e-5 relative, and the beam compares candidates within a
  level against each other, so one fast candidate scored against one slow one is
  the same comparability bug in miniature. Same reasoning as `JOINT_TILE_FLOOR`,
  and it lands on the same shots — the call split is **4116 fast / 2917 slow** on
  a 4-shot `test_screenshots` merge (the slow ones being all of div=1 plus that
  one zoomed-in shot's coarse levels) against **980 / 4431** on `star_change`,
  where all three shots fall back.

  **Corpus, 27 sets: one number moved.** Explored union, conflicts, city bars,
  ruins, every per-shot fog lock and `--cross-check` on 26 of 27 sets are
  identical; `test_ss_2` reads 0.028 → 0.027. That is a far better result than
  this file expected for a change that is *not* bit-identical (the closed form
  reaches the same quantity by a different route and agrees to ~1e-5 relative),
  given the recorded chaos of the beam search under 1px perturbations — and it
  is the level-fixed set that buys it, since the per-candidate version moved four.

  **Timed serially, back to back** — the harness's `seconds` column is `--jobs 4`
  contention, as two earlier entries record, and this machine drifts ~30% between
  runs, so before and after must be measured in one sitting:
  `test_screenshots` 11.35 → 10.07s, `archers_test2` 21.34 → 19.09,
  `goon_test2` 5.22 → 3.93, `xizauh` 10.76 → 8.94, `badland_test2` 6.24 → 5.08,
  `star_change` 6.98 → 6.59. **5-25%, about 15% typical**, and `star_change`'s
  5.6% is the floor firing on all three of its shots. Per level on
  `test_screenshots`, div=4 **0.57 → 0.23s** and div=2 **1.81 → 0.78**, both down
  ~58%, with div=1 flat at 1.4 → 1.3.

  **Why 15% and not the ~6x the per-call figure implies:** the fallback shots run
  at full masked cost, and the pyramid phase also carries the warps, resizes and
  borders, which are now a much larger share of it than they were.

  **What is left.** div=1 has the *best* fully-valid share (0.795) and is ~1.3s of
  a 10s merge, so extending the fast path to it is the next ~6% — but it is the
  level this file says does the discriminating, and keeping it exact is the most
  likely reason the corpus came back this clean.

- **`top_k` is capped at the number of tiles that could be fog, and `60` was
  never derived.** `JOINT_TOP_K = 60` entered as a bare `top_k=60` default in the
  initial commit with no recorded provenance, and it is the *only* number in the
  scoring path that was never measured. It is also the wrong shape: the score
  sums the best `k` per-tile correlations against fog art, so `k` is a claim
  about how much fog evidence a shot has, and that is a property of the shot.

  **What a fixed 60 does to a fog-poor shot.** `star_change/oum.png` has ~7 fog
  tiles in frame and 11 that pass the colour test. Summing 60 terms there adds
  its 7 signals to ~49 correlations of *terrain* against fog art — and those are
  not zero, they move with the candidate, for reasons that say nothing about
  alignment. The noise term's swing across candidates is comparable to the whole
  signal. That is the same mechanism the fog-colour prefilter was built on,
  stopped one step short: the prefilter fixed *which tiles are sampled* and left
  *how many are summed* alone.

  `top_k = min(JOINT_TOP_K, n_fogish)`, where `n_fogish` is the count passing
  `JOINT_TILE_FOG_FRAC` **before** the floor tops the keep-set up. Two properties
  make that the right quantity to cap by:
  - It is a *generous upper bound* on the fog — the colour test admits 83.5% of a
    Polaris shot's pixels — so it errs toward leaving `k` alone. Only **14 of 77
    shots** see a smaller `k`, and the list is a roll-call of this file's fragile
    cases: `fogless` 4 and 6, `replay_ss2` 5, `star_change/oum` 11 and `oum2` 28,
    `vengir_cultist/v1` 42, `pol_archi_test/kick` 43,
    `test_screenshots/Screenshot_...349217` 46, `test_ss_2/cym1` 46,
    `goon_test2/imp` 53, `basin_treaties/q` 57. The median shot reads 142.
  - It is fixed per shot, not per candidate, so every candidate in a level still
    sums the same number of terms — the comparability property the level-fixed
    fully-valid set exists to protect.

  **Corpus, 27 sets. Union and ruins identical everywhere, and all six labeled
  sets' bar counts identical:**

  | set | before | after |
  |---|---|---|
  | `star_change` cross-check | 0.112 | **0.050** |
  | `star_change` `oum.png` fog lock | 4 | **7** |
  | `star_change` conflicts | 29 | **27** |
  | `pol_archi_test` cross-check | 0.033 | **0.012** |
  | `pol_archi_test` conflicts | 3 | **2** |
  | `fogless` cross-check | 0.378 | 0.035 |
  | `goon_test2` cross-check | 0.031 | 0.037 |
  | `replay_ss2` cross-check | 0.657 | 0.808 |
  | `test_screenshots` bars | 17 | 16 |

  **`star_change/oum.png` now locks 7 fog tiles, which is every fog tile it
  has**, and that set comes off the 0.05 bar it has been over for this file's
  whole history. The two moves in the wrong column are both on sets whose
  cross-check this file already records as measuring nothing — `replay_ss2` and
  `fogless` have no fog at all, so the merge discards the refined anchors the
  number reports (union 256/256 and 0 conflicts on both, unchanged).

  **The lost bar is a false positive, and the corpus proves it rather than
  arguing it.** `test_screenshots` drops (13,17), a *complete* bar seen only by
  `Screenshot_...349217`. That board is photographed by three sets, and every
  other city `test_screenshots` reports — (14,6) (15,3) (18,1) (18,4) (18,7)
  (2,13) (6,12) (7,16) (9,12) (12,11) (12,14) (15,9) (18,10) (18,13) — is also
  reported by `test_ss_2` or `beautiful_test3`. **(13,17) is the only one that is
  not**, and neither of the other two sets finds a bar there in any shot. It was
  also expensive: it promoted a 9-tile block ((12..14, 16..18)) to that shot for
  a bar that is not there, and the promotion drops from 22 tiles to 13.

  Note what that means for reading this column in future: **a bar count going
  down is not evidence of a loss**, and on this board the three-set overlap is
  the check that settles it. Use it.

  **The fast-path floor was deliberately left on the constant** rather than
  following the new per-shot `top_k`. They were the same number until this
  landed, and tying them would have put every fog-poor shot onto the closed-form
  path as a side effect of shrinking its `k` — two changes wearing one constant's
  name. The floor asks how much evidence a level needs before approximating is
  worth it; `top_k` asks how much of that evidence the score sums. Tying them is
  a reasonable *separate* change and is untested.

  **60 is now measured, and it is right — swept at 40 and 80 over all 27 sets**
  (scoring `k` only; the fast-path floor held at the constant, per the note
  above, so this measures the objective width and nothing else). **Both ends
  lose a confirmed real bar**, and 60 is the only one of the three that loses
  nothing:

  | | k=40 | **k=60** | k=80 |
  |---|---|---|---|
  | explored union | **6297** | 6300 | 6300 |
  | cross-check mean, 21 reliable sets | 0.0261 | 0.0237 | **0.0216** |
  | " median | 0.0260 | 0.0220 | **0.0190** |
  | " sets over the 0.05 bar | 0 | 0 | 0 |
  | real bars lost | **1** | — | **2** |

  - **k=40** drops `badland_test3` **(15,16)** — which is in that set's labeled
    real-bar list — and loses three union tiles on `control_c` (240 → 237). Union
    is the strongest signal in the corpus and 40 is the only value that moves it.
  - **k=80** drops `goon_test2` **(6,2)** and **(6,5)**, both complete bars seen
    by `q.jpg`. `goon_test` is *the same board at a different turn* and reports
    both, from its own `q.jpg` — the same three-way corroboration that settled
    (13,17), and the reason those two sets are worth keeping.

  **Read the aggregate cross-check column and then distrust it**, because this is
  the cleanest demonstration in the file of why it is a proxy. It improves
  *monotonically* with `k` — 0.0261 → 0.0237 → 0.0216 — while bar recall degrades
  at **both** ends. Optimising on it alone picks 80 and quietly costs two real
  bars. The metric order this file keeps asserting (union, then the labeled bar
  counts, then cross-check) is not a stylistic preference; here it is the
  difference between the right answer and a wrong one that looks better.

  Mechanism, for anyone re-running this: at k=80 `goon_test2/q.jpg` has enough
  fog-ish tiles that its `k` really does rise to 80, its anchor shifts, and that
  set's cross-check *improves* to 0.010 while two bars sitting near a band edge
  fall out — exactly the ~2px bar sensitivity recorded in its own standing
  decision below. `imp.jpg` is capped at 53 either way and does not move.

- **A coarser pyramid level (div=8) does not help, and the reason generalizes.**
  Never tried before; measured now. Prepending a div=8 level and narrowing div=4
  to match takes a 4-shot merge from **25.5s to 28.3s** with identical fog lock.
  A coarse level cannot *choose* — that is the entire reason the beam exists —
  so it must hand several candidates forward, and those multiply the next
  level's work: div=4 went 1568 to 3724 calls, costing more than the 1.35s div=8
  saved. Adding levels at the top can only pay if the level below them gets
  narrower, and narrowing is what the table above says breaks. The coarse level
  was never where the money was anyway: div=4 is 16% of the scoring cost against
  div=2's 51%.

  Two things tried at div=2, where the money actually is:
  - **pan radius 3 -> 2** (25 pans instead of 49): saves 3-5s and takes
    `test_screenshots` from 0.020 to **0.081**. Same verdict as narrowing div=1.
  - **emitting 1 candidate instead of 2**: `test_screenshots` 0.020 -> 0.020,
    `archers_test2` 0.046 -> 0.046, `star_change` 0.162 -> 0.118, and ~10%
    faster (div=1's calls halve). The table above records this as measured and
    bad — *"pruning to 1 before the full-resolution level puts three sets back
    above the 0.05 bar"* — but that measurement predates the beam-width taper,
    both sweep-range moves, the fixed-angle basis and the tile prefilter, and
    three sets do not reproduce it. **Untested corpus-wide**; it is the cheapest
    remaining candidate and the claim blocking it may simply be stale.

- **A "fast mode" skipping badge, ruin and city-bar detection is not worth
  having.** Measured with the bot's own flags: city bars 0.46s, ruin vision
  0.41s (0.67s on the fog-heaviest set — the "~2s" figure elsewhere in this
  file is stale), and badge detection a fraction of the 0.47s it shares with
  image loading and mask building. That is ~1s of a ~13s merge, ~7%, which no
  player notices against the bot's ~20s round trip. Badge detection cannot be
  skipped anyway: `badge_halo` feeds `edge_mask`, and `star_change/oum2.png`
  anchors a full tile out without it. So the flag would buy ~0.9s by disabling
  the two features that exist specifically to stop the merge silently
  discarding information.
- **If the population bar is ever merged, prefer winning the tiles to
  compositing the pixels — and never re-render it from a decoded value.**
  The intended design, in order:
  1. **Promote the source that shows a bar** to the front of `priority` for
     the tiles around that city, and let the ordinary paste do the rest. The
     key enabler is a game guarantee: *a city's owner always has vision on the
     8 tiles adjacent to it*, so those tiles are never fog in the shot showing
     the bar, and promoting it can never paste fog over someone's terrain.
     This needs only *detection that a bar exists* plus rough localization —
     never a pixel-accurate outline — because the shot containing a bar **is**
     the owner's shot by definition (nobody else renders one). No ownership
     inference is required, which is what makes `★ N`'s embassy ambiguity
     irrelevant. Promote a *superset* of the touched tiles (the 3x3 block is
     the safe choice): promoting only some of them cuts the bar in half at a
     tile border, which looks worse than not preserving it at all.
     The same guarantee doubles as a free correctness check — a shot showing a
     bar must not have fog on that city's neighbors; if it does, the
     detection is wrong.
  2. **Copy the bar's pixels** as a fallback where promotion is too costly.
     Faithful by construction, but leaves a sharpness seam where UI from one
     source lands on another source's terrain.
  3. **Never re-render from a decoded value.** Reconstructing the bar means
     counting a variable, unbounded number of segments *and* classifying each
     one's state (blue / dotted / empty) with semantics nobody has written
     down, on a graphic other UI can partially cover — so it must also invent
     the segments it cannot see. Getting that wrong fabricates game state: a
     clean, confident, wrong population no screenshot ever showed.
  Note (1) and (2) are the *opposite* call to `--ruin-vision`'s "mark, don't
  copy", and the difference is real: the ruin prism is private UI drawn at an
  offset from the tile it refers to and corroborated by nobody, whereas the
  bar is legible, correctly positioned, and simply absent from other players'
  shots.
- **Don't use the owner-only city population bar as an authority signal.**
  It is genuinely owner-only (only that city's owner's screenshot renders it),
  and it was considered as a way to decide which source to trust around a
  city — but the project owner ruled it out, and correctly: the bar sits
  *below* the city, whereas the problem it would solve is occlusion of the
  tiles *above* it, and the same occlusion arises for cities that have no bar
  showing at all. `--fog-frac-margin` solves that case directly instead, by
  comparing the sources' own fog evidence on the disputed tile.
- An earlier attempt at "hand a city's neighboring tiles to whichever source
  shows its label" (`city_tiles`/`propagate_city_owner`) was removed after it
  failed silently (detected almost nothing). If reattempting this class of
  feature, detect the thing you actually care about, not a proxy for it.
- **To find fog at a scale finer than a tile, compare pixels directly — not a
  windowed correlation.** Fog is one deterministic render, so an anchored
  shot's fog pixel simply *equals* the template's pixel there once the shot's
  overall illumination is fitted out (`fog_illumination`, fitted on that
  shot's own fog-locked tiles). A local NCC cannot do this job however it is
  tuned: an 11x11 window centered in a ~10px fog fringe still straddles the
  occluder, and on the Ichphy tile it scored the fogged shots 0.034 against
  the clear ones' 0.023 — no separation — where the windowless pixel
  comparison gives 0.089 vs 0.000. Don't retry the windowed version.
- **The fog cube being taller does *not* make it bleed into the tile south of
  it.** This looks like it should follow from the variable-height fact and it
  was measured and rejected: the north-rim fog NCC of an explored tile is
  -0.069 when its northern neighbors are fog in that source, versus +0.017
  when they are not. No contamination, and the sign is backwards.
- **A better prior is not a better answer.** Pan was switched from the
  support-weighted blend of both edges to "use the bottom lip, fall back to the
  top edge" — justified, since the bottom lips really are the exact ones (see
  above). It improved the prior a lot: median pan error 4.4px → 2.2px overall,
  and on `goon_test2` 10.1px and 14.0px → 1.8px and 1.5px. It then made
  `--cross-check` *worse* on three of four sets (ss2 0.021 → 0.042, ss3 0.015 →
  0.025, goon2 0.006 → 0.012 tiles; only ss1 improved, 0.056 → 0.050), so it was
  reverted. Two reasons, both worth remembering: `joint_register` already
  absorbs pan error of this size, so a better prior buys no accuracy at all;
  and cross-check measures how far shots disagree with *each other*, so a bias
  shared by every shot of one board cancels — which rewards a consistent prior
  over an individually accurate one. The bottom-lip fact is still the right
  lever for *narrowing the search window* (a runtime win, see timing above);
  it is simply not an accuracy fix. Don't re-land it as one.
- **Don't feed the exact 3:5 angle into `edge_lines` — but the reason is that
  3:5 is the wrong constant, not that a constant is wrong.** This entry
  previously argued the opposite and was wrong; the correction is below and the
  open item is at the end.

  Forcing `atan(3/5)` was built and measured over the whole corpus twice and
  reverted both times (numbers below). The explanation recorded here was that
  `edge_lines` fits the *silhouette* while 3:5 describes the *lattice*, so the
  per-template corner estimate was the right frame. **That does not survive
  measurement.** The board's silhouette edges do not sit at atan(3/5), and three
  independent routes agree on where they do sit:

  | evidence | implied slope `k`·0.6 |
  |---|---|
  | the four blanks' own silhouettes (huge/large/normal/small) | 0.9974–0.9980 |
  | the two replay sets' bottom edges (explored rim, rms 0.36px) | 0.99771 |
  | 30 clean bottom edges, extent > 700px, across **21 sets** | median 0.99798 |

  So the edges run at about **30.91° / 149.09°**, a slope of 0.5986 — **0.058°
  off** atan(3/5), consistently, at every board size and on real captures from
  different devices. It is one fixed number, exactly as the projection being
  fixed requires; it is simply not the number this file assumed.

  **The estimator was checked twice, and the second check is the one that
  matters.** A diamond rasterized at exactly atan(3/5), antialiased, thresholded
  at `--dark-thresh` and pushed through `board_boundary` plus a robust TLS fit
  comes back at **0.0001°**, with and without a synthetic side wall. **That
  control is insufficient on its own**, because it has a *straight* edge and
  every edge of an all-fog blank is scalloped — the fog cube's lip repeats once
  per tile — and fitting the outer envelope of a scallop is not the same as
  fitting the line the cubes stand on. Measured on a synthetic scallop whose true
  tilt is **exactly zero**, that envelope fit reads:

  | scallop shape (amplitude) | envelope TLS |
  |---|---|
  | none, flat | +0.0001 |
  | symmetric cosine, 8px | **−0.0405** |
  | asymmetric sawtooth, 8px | **−0.0523** |
  | asymmetric, 16px | **−0.1694** |
  | clipped cosine ("lip"), 12px | **+0.0338** |

  So a selection window around the extreme really can manufacture a tenth of a
  degree out of nothing. **Use a harmonic trend fit instead**: model the edge
  profile as `perp(s) = c + m·s + Σ cos/sin at the tile period`, ordinary linear
  least squares over every profile point with no selection window. It is exactly
  the "there is a line that follows the cube, and the lattice runs along it"
  statement, made estimable — the periodic term absorbs whatever shape the cube's
  lip has, and `m` is the trend through it. It returns **0.000** on every zero-tilt
  scallop above and recovers a *known* tilt to 0.0003° (+0.05 → +0.0499, −0.05 →
  −0.0502, +0.20 → +0.1997).

  **It gives the same answer on the real renders**, which is what makes the
  0.058° survive:

  | render | NW | SE | NE | SW | profile residual |
  |---|---|---|---|---|---|
  | `huge` | +0.055 | +0.067 | −0.051 | −0.065 | 0.42–0.45 px |
  | `large` | +0.055 | +0.056 | −0.055 | −0.058 | 0.48–0.51 |
  | `normal` | +0.060 | +0.058 | −0.055 | −0.059 | 0.40–0.43 |
  | `small` | +0.058 | +0.089 | −0.057 | −0.055 | 0.39–0.43 |

  A sub-pixel residual means the periodic model explains the edge essentially
  completely, so the leftover trend is not unmodelled lip shape. Scaling the
  assumed period by ±1% moves each figure by at most ±0.01°. **`tiny`'s two
  b-edges do not fit the model at all** (residual 17.7 and 18.6 px) and its
  a-edges read −0.10/−0.10, which is a third independent oddity in that size.

  **What this does weaken is the screenshot leg of the evidence.** The clean
  estimator needs the whole edge profile, and in the oblique basis that works
  only when the board is a complete rectangle in frame — on a partial capture the
  per-bin extreme picks up the image frame instead (residuals of 14–261 px on all
  four replay shots). So "the screenshots agree with their blank to 0.0013°" rests
  on the *envelope* fit and is now provisional. An explored rim has no fog lip, so
  the bias there should be small, but that is an argument rather than a
  measurement.

  **What is actually wrong today is the opposite of what this entry claimed: the
  code's basis is not a constant at all.** `edge_directions` derives it from
  three corner *pixels* per render, and across the five blanks `dir_a` scatters
  **0.24°** — 30.7247 / 30.9593 / 30.9098 / 30.8824 / 30.9699 for tiny / small /
  normal / large / huge. A fixed projection cannot do that. On `huge` the
  three-pixel estimate sits **0.061°** from a 2400-point fit of that same file's
  own edges, so it is noise rather than a per-render property — and `normal`
  landing 0.004° from the measured constant is luck, not measurement.

  **`tiny` is the exception and may be a genuinely bad file**, not just noise:
  its corner basis is 0.24° out *and* all four of its silhouette edges deviate
  the same way (a rotation, which no squash produces), *and* `tiny-gridded`
  carries the largest one-family shear. Three independent oddities in one size.
  Nothing tests 11x11.

  Corpus effect of forcing the exact angle on the edge fit (27 sets, against a
  captured baseline): **25 sets moved, in both directions.** It bought
  `pol_archi_test` 0.044 → 0.015, `xizauh` 0.035 → 0.009, `goon_test2` 0.035 →
  0.016, `test_ss_3` union 260 → 263 and `control_c` union 237 → 242; it cost
  `archers_test2` 0.038 → **0.072**, `badland_test` 0.013 → **0.055**,
  `vengir_cultist` 0.023 → **0.065**, and `replay_ss2`'s **only real bar**
  (Bergo at (4,3), the ground truth for that set) — 1 → 0. Snapping
  `build_lattice`'s step directions as well, instead of only the edge basis,
  changes the mix but not the verdict, and loses the same bar.

  **Read the size of the perturbation before reading the table**: on a 20x20
  board this moves `dir_a` by 0.006° and `dir_b` by 0.062°, about **1px at the
  board corner**. That cannot mechanically swing a fog lock by 13%, so most of
  what moved is `joint_register`'s beam search landing in a different basin —
  the same sensitivity already recorded above, where a 0.045% change to the
  template's tile step alone took `archers_test2` from 0.028 to 0.097. A
  perturbation this small is *below the corpus's resolving power*: the corpus
  can veto it, and did, but it could not have endorsed it either. **Read that
  the other way round too** — it means the corpus never actually tested the
  angle, so "it made things worse" is not evidence that a constant is wrong.
  What the run really established is that `joint_register`'s beam search is
  chaotic under a 1px perturbation.

  **The interior lattice sits at the same angle as the rim, so there is one
  number and not two** (stated by the project owner; corroborated on `huge`).
  Measure it by **phase drift**, not by a sharpness optimum: if the assumed
  direction is off by δ, the lattice's periodic signal along the normal advances
  in phase as you move along it, `φ(s) = 2πδs/P`. Take the Fourier coefficient at
  the tile frequency in each strip and fit `arg(Z)` against strip position. Two
  properties are what make it trustworthy where the projection-sharpness
  estimator is not: it is a *relative* measurement, so a constant bias in the
  estimator cancels; and a wrong `P` cannot tilt it, provided every strip covers
  the same normal-range — a wrong period shifts all strips equally. It recovers a
  known tilt on a synthetic lattice to **~1%** (0.058 → 0.0575, 0.200 → 0.198),
  i.e. 0.0006° on the effect being measured.

  On `huge` — the largest interior, and much the cleanest fit (phase residual
  **0.02–0.10 rad**, stable across gray/gradient signals and 8/20 strips):

  | | a-family | b-family |
  |---|---|---|
  | interior fog lattice | **−0.060** | **+0.056** |
  | silhouette edges (harmonic trend, above) | −0.058 | +0.061 |

  **They agree to ~0.005°**, and both sit ~0.058° off atan(3/5). Two independent
  structures — the tile art inside the board and the line the rim cubes stand on —
  measured by two independent estimators, landing on the same angle.

  `large` and `normal` **cannot corroborate or refute it**: their interiors are
  smaller, the residual runs 3–10x higher, and the a-family swings 0.28° across
  estimator variants (−0.23 to +0.05 on `normal`). Read them as no evidence
  rather than as disagreement. If this is ever revisited, more interior area is
  what the estimator needs, so `massive` is the render to try.

  **Built** — `BOARD_EDGE_SLOPE` = 0.5986, with `BOARD_DIR_A`/`BOARD_DIR_B`
  derived from it. `edge_directions` returns them and ignores the corners;
  `build_lattice` takes the two step *directions* from them and only the step
  *lengths* from the corners, which are genuinely per-render. Under one angle
  that is the coherent edit — the earlier worry about "changing two things at
  once" applied only while the lattice angle was unknown, and it is the *split*
  that would now be wrong, since it would deliberately put the edge basis and the
  tile grid at different angles.

  **Corpus effect, and read the bars first because they are the part with a
  known answer:**

  | | before | after |
  |---|---|---|
  | city bars | 235 | **237** (+2, **none lost**) |
  | explored union | 6297 | 6296 (−1; five sets moved by ±1) |
  | conflicts | 176 | 180 (+4) |
  | ruins | 37 | 37 |
  | cross-check, 20 reliable sets — mean | 0.0237 | 0.0281 |
  | " median | 0.0230 | 0.0250 |
  | " max | 0.0450 | **0.0710** |
  | " sets over the 0.05 bar | 0 | **1** |

  **Both replay ground truths survive at the right tiles** — `replay_ss2` Bergo
  (4,3) and `fogless` Tetesum (12,4), each a full bar. That is the result worth
  having: the atan(3/5) attempt *lost* Bergo, and this one keeps it and adds two
  detections elsewhere.

  **The corpus does not endorse the change, and should not be reported as
  though it did.** Cross-check moved on 22 sets — 11 better, 11 worse — with the
  aggregate modestly worse and `vengir_cultist` crossing the healthy bar (0.023 →
  **0.071**). That is exactly the both-directions movement predicted above, and
  the reason it is not evidence *against* the constant either.

  One observation makes the cross-check column easier to read, and it is the
  useful part: **the four largest regressions are on sets whose merge output is
  completely unchanged.** `vengir_cultist` (0.023 → 0.071), `u_forest` (0.016 →
  0.049), `missized_test` (0.004 → 0.022) and `badland_test` (0.013 → 0.027) have
  identical union, conflicts, bars and ruins before and after — what moved is how
  well two anchors agree with each other, not the composite. The largest
  improvements are the same shape in reverse: `test_ss_3` 0.045 → 0.020,
  `test_screenshots` 0.034 → 0.020, `pol_archi_test` 0.044 → 0.031,
  `replay_ss2` 0.229 → 0.056.

  So the case for keeping it rests on the physical argument — four independent
  routes agree on the angle, and a 0.24° per-render scatter has no cause — rather
  than on the corpus, which cannot resolve the perturbation. If it is ever
  reverted, revert `BOARD_EDGE_SLOPE` and both consumers together; a half-revert
  reintroduces exactly the edge/lattice split this replaced.
- **Bar geometry is expressed relative to the bar, not absolutely against the
  vertex — otherwise the detector is only as accurate as the anchor.** This
  entry used to read "bar detection tolerates about 2px of anchor error, and
  that is worth knowing", i.e. it recorded the sensitivity as a property of the
  problem. Most of it was a property of the *parameterization*, and it is gone.

  **Where the sensitivity was, measured.** Probing every accepted detection in
  the six labeled sets and recording where each edge landed inside its band, in
  tile widths:

  | quantity | min | p05 | median | p95 | max |
  |---|---|---|---|---|---|
  | bar height (`yb - yt`) | 0.138 | 0.150 | **0.175** | 0.201 | 0.213 |
  | top edge `yt` | -0.093 | -0.083 | -0.047 | -0.031 | -0.020 |
  | bottom edge `yb` | 0.070 | 0.114 | 0.127 | 0.144 | 0.149 |

  The two bands were `(-0.090, 0.020)` and `(0.070, 0.170)`, ~9px and ~8px at an
  80px tile — so **12 of the 49 bars sat within 0.02 tile widths of a band's
  outer wall and three sat exactly on it**, both replay ground truths among them.
  Meanwhile the bands *jointly* admit heights from 0.050 to 0.260 against an
  object that measures 0.138–0.213. The tight quantity was doing no work and the
  loose one was doing all of it.

  **The fix is to constrain the pair rather than each row** (`BAR_HEIGHT`), which
  buys 0.04 tile widths of slack in each direction — about 3px — for a constraint
  that is *stronger*, not weaker. The bands stay only to keep the pair off the
  name plate above, which is the one thing they were physically for.

  **The color box was the same disease one step worse, and is the half that
  mattered.** `BAR_BOX_ROWS` was a preset `(0.010, 0.115)`, whose bottom sits a
  median **0.012 tile widths** inside the bar's bottom edge and *below* it on
  four of the 49 — so a couple of px walks it onto the white name plate and the
  mode reads **252**, the exact signature this file records for a false positive.
  Two changes: the second, post-geometry call now takes its rows from the bar it
  just measured (its *columns* already followed the detected width class, so this
  finishes a job half done), and the prefilter box, which by construction has no
  geometry to lean on, moved to `(0.000, 0.080)` — centred on the median bar
  interior, with the largest minimum margin at both ends of the five spans swept.

  **Result: 50 of 50 on the labeled sets with 0 false positives**, up from 49/50,
  and on the whole 27-set corpus union, conflicts, ruins, fog lock and
  `--cross-check` are **identical everywhere** with only two bar counts moving,
  both up (`test_ss_2` 17 → 18, `test_ss_3` 16 → 18). It is **strictly additive**
  — every prior detection on every set survives. The gains are the two the corpus
  can corroborate: `test_ss_3` (10,9) Ichphy, in the labeled real list, now found
  by *both* cym shots; and a new tile **(3,16)**, found independently in
  `test_ss_2` and `beautiful_test3` — different capture files of the same board —
  and ≥3 tiles from every other detection, as the placement guarantee requires.
  Runtime is unchanged (0.33s against 0.33s on a 5-shot merge, timed back to
  back): the height constraint prunes the wider bands' extra row pairs.

  **What does not go away.** Anchor accuracy is still a real ceiling on bar
  recall, and any change to the edge basis must still be checked against the bar
  counts and not only against `--cross-check` — the bands are absolute against
  the template lattice while cross-check is relative between shots, so
  cross-check structurally cannot see a bar falling out. `replay_ss2` remains the
  most exposed set (no fog at all, so both shots keep an unrefined edge anchor,
  and Bergo's two segments fuse into one blob). The worked case is `goon_test2`
  at `JOINT_TOP_K` 80, where `q.jpg` moves ~2px and used to drop (6,2) and (6,5):
  it now keeps all eight bars. What changed is the size of the perturbation that
  costs a bar, not the fact that one can.
- **Never trust a plausible-looking composite as evidence the geometry is
  right.** The `test_ss_3`-at-18 merge rendered a perfectly coherent board
  with sharp tile boundaries and correctly-placed cities for one player; the
  only visible symptom was that the *other* player's territory was quietly
  replaced by fog. Every self-consistency signal available at the time
  (anchoring succeeded, all four edges found, zoom priors agreeing to 0.02%)
  read healthy. `--cross-check` and the fog-lock count are the two signals
  that actually failed, and they are the ones to look at first.

## Deferred (known, deliberately not handled yet)

### A shot with only *one* board edge in frame

**Built** — `pan_hint` in `anchor_to_template`, fed from `anchor_all`'s second
pass. `tests/badland_test3` is the regression test. What remains deferred is
the *zero*-edge case, at the bottom of this section.

Pan comes exclusively from the board edges, and each edge is a line of constant
`a` or constant `b`, so **one edge pins exactly one of the two offsets**. The
requirement is therefore `(a-min or a-max) and (b-min or b-max)` — one edge per
*direction*. Three consequences that are easy to get backwards:

- **Any two non-opposite edges are enough.** Four corpus shots run on nothing
  more: `badland_test/oum.jpg` and `test_ss_elyruins/cym.jpg` (NW+SW),
  `u_forest2/ely.png` (NW+NE), `test_ss_fruit/oum.webp` (SE+SW).
  (`pol_archi_test/kick.png` was this list's NW+NE example until
  `_board_component` recovered its other two edges.)
- **An opposite pair *alone* is not enough**, counter-intuitively: both its
  edges are in the same direction, so they pin the same offset twice and the
  other direction has nothing. A pair is what gives the *zoom* directly; it is
  not what satisfies pan.
- **The corner between the two edges does not have to be in frame.** Each edge
  is fitted independently from its own boundary points (`edge_lines`), and
  nothing ever needs the vertex — `detect_corners` is only ever run on the
  *template*, precisely because a screenshot's coverage can stop short of the
  true vertex. Measured: `badland_test/oum.jpg` anchors with its W corner at
  x=-60, and `test_ss_elyruins/cym.jpg` with its W corner at x=-23, both off
  the left of the frame. So "include two board edges" is the whole rule; do
  not tighten it to "show a corner".

**A shot with one edge is short exactly one number, and SIFT supplies it.**
Fog cannot: it is periodic, so it says where a point sits *within* a tile and
never which tile, which is the whole reason the offset is missing. Terrain is
not periodic, so a SIFT match onto an already-anchored shot has no such
ambiguity. `anchor_all`'s second pass already computed that match and used only
its scale; it now also passes the composed transform as `pan_hint`, and
`anchor_to_template` takes **only the direction that has no edge of its own**
from it. The direction that has an edge keeps that edge, so the shot still
anchors itself as far as its own evidence reaches.

Three properties keep this from sliding back into the old
register-the-group-then-anchor design: it is reached only by a shot that
already failed to self-anchor, at least one real board edge is still required,
and the borrowed quantity is one scalar offset. `SIFT_ZOOM_MIN_INLIERS` (150)
is the whole gate — deliberately high, because fog matches the wrong repeat of
itself at 115 inliers on `test_ss_elyruins`, where a genuine terrain match runs
1000+. There is no second opinion available: a borrowed *zoom* can be checked
against the shot's own fog, but a borrowed *offset* cannot, since the fog test
cannot tell one lattice repeat from the next.

**A borrowed pan must not then be refined, and this is the difference between
the feature working and not working.** `joint_register` scores candidates by
fog alignment, and a shot that had to borrow an offset is by construction one
the board edges could not place — in practice a zoomed-in shot with almost no
fog in frame. Its score surface is noise, and the search walks off a good prior
into the argmax of that noise. Measured on `badland_test3/cym.png`, which locks
10-12 fog tiles: the borrowed prior sits **0.006 tiles** from `yad.png`'s SIFT
geometry and refining it moves it to **0.212**, a 35x loss, with a +1.18% scale
correction — which is precisely the ">1% correction means check the fog lock"
tell recorded in the anchoring section, firing as designed. Skipping the
refinement gives 0.027 tiles. Nothing is given up: both halves of the anchor
come from SIFT relative geometry, good to ~0.2px, where fog has no absolute
position to offer at all.

**`borrow_pan` must mean "an offset was actually taken", not "a hint exists".**
The second pass hands a hint to every shot it re-anchors, including one that
has both directions in frame and merely needed a zoom — which is what that pass
was originally for. Treating those as borrowed skips their refinement too, and
`pol_archi_test/kick.png` is exactly that shot: it lost its whole fog lock
(17 → 0) and took that set from 0.035 to 0.191 cross-check tiles. The corpus
catches this instantly, so run `tools/baseline.py --compare` before believing
any change here.

**What this does not fix, and what it costs.** It cannot help a shot with *no*
edge at all: that shot would take its entire position from another shot, has no
independent evidence left to be judged on, and is still refused. Nor can it
help a shot with one edge and no overlapping partner — there is simply nothing
to supply the missing offset, and refusing is the honest answer. Runtime cost
on an ordinary merge is **zero**: the whole path lives inside the second pass,
which no healthy shot reaches, and it in fact *saves* three pyramid levels on
the shot it rescues.

One idea deliberately not taken: borrowing **both** offsets when a hint is
available would close the last 1.7px on `badland_test3/cym.png` (0.027 → about
0.006 tiles), since that residual is the SE edge disagreeing with the hint. It
was left alone because a shot using its own edge where it has one is the
property that keeps this a hint rather than a group registration, and 0.027 is
already half the healthy bar. `anchor_to_template` prints the disagreement
between the kept edge and the hint on every borrow, so the cost of the choice
stays visible.

### The 15% top crop can cost a shot an edge it really has

Separate from the above and not fixed. `badland_test3/cym.png` is short its NE
edge only because `--top-crop` 0.15 slices it: NE's support runs 148 / 167 /
207 / 278 / 298 at crops 0.15 / 0.12 / 0.10 / 0.08 / 0.05, against a
`--min-edge-support` of 150. So it is a near-miss two-edge shot, not truly a
one-edge shot. Two measurements before anyone tries to reclaim it:

- **Relaxing the crop globally is not the fix.** At 0.08 the corpus loses 9
  shots across 7 sets, `pol_archi_test` fails outright and `star_change`'s
  cross-check goes 0.141 → 1.04 with 97 conflicts; HUD chrome entering the
  mask manufactures board. 0.12 drops nothing but pushes `badland_test` from
  0.013 to 0.052 cross-check tiles, past the healthy bar, and has no basis
  beyond fitting this one screenshot.
- **Recovering that edge would be worse than borrowing the offset anyway.** NE
  is one of the two bad edge types (4.6px std, 15.4px worst) and 167px is a
  sliver of it, where the SIFT hint carries 1908 inliers. Note also that a crop
  retry inside `anchor_to_template` would *preempt* the borrow entirely, since
  a shot anchored in pass 1 never reaches the second pass.

**This was retried after `_board_component` landed, and both bullets held.** The
reasoning for the retry was sound and is worth recording so the next person does
not repeat it: the first bullet's stated cause is "HUD chrome entering the mask
manufactures board", and the chrome filter removes exactly that — so with it in
place, sweeping every corpus shot at 0.15/0.12/0.10/0.08/0.05 and flagging any
edge good at 0.15 whose offset then moved, **zero shots move at any crop**, down
to 0.05. That really does retire the first bullet's mechanism.

It does not matter, because the *second* bullet is the binding one, and moving
the default to 0.12 demonstrated it directly. `cym.png` gains `b-min=ok(167)`,
so it self-anchors, never reaches the second pass, and takes its zoom from the
fog period with a **+1.09%** correction — the ">1% means check the fog lock"
tell firing as designed. It then disagrees with all three other shots by
**16.5px = 0.207 tiles**, against 0.022 when it borrows the 1908-inlier hint.
`badland_test` regressed too, 0.013 → 0.052, from a different mechanism again
(its `oum.jpg` admits more of the NW edge and the fit moves). Corpus-wide the
change bought real gains — fog lock up on six shots, +2 bars, +4 union tiles on
`badland_test` — and they are not worth two sets past the healthy bar.

So the two harms are separate and only one of them is a chrome problem. Chrome
*outside* the board captures an edge and is `_board_component`'s job; the crop's
remaining job is chrome *overlapping* the board, which merges into the board's
own component where no component filter can reach it, and which is why the band
cannot simply be dropped. Do not relax it again without a mechanism for that
second case.

A residual artifact of the same crop is visible on `badland_test3`: the bottom
~40px of cym's "Waiting for yodagem…" banner survives the 15% band and is
pasted onto the board near the N corner. That is the documented job of
`--ui-mask` (a mid-screen dialog the band crops cannot cover), which the bot
does not expose.

### A genuine size conflict still refuses; the fog lock should adjudicate it

**A board with no fog no longer needs this** — see the zero-lock rule in the
anchoring section, which refuses on a *detected* size and warns on a *stated*
one. What the adjudication below would still buy is telling the player which
size is right, rather than only that theirs looks wrong.

Three tests for "is there fog here?" were tried while looking for something that
could decide it automatically. The first two are **unsafe — do not ship
either**; the third is what shipped, as a warning:

- **`fog_period_scale` returning None on every shot.** This looks like the
  discriminator, and nearly is: it never consults `--map-size` (it takes
  `tile_px` only to center a 12x-wide sweep, and the answer is invariant to which
  template supplies it — `test_ss_3/yad1.png` reads 80.2/80.3/79.8/79.9/79.9px
  across all five), it returns None on both `fogless` shots, and it finds a
  period on every board in the corpus that has fog, including the cases built to
  defeat fog detection (`xizauh/pol.jpg` 64.8px where Polaris ice reads 83.5%
  "fogish", `star_change/oum.png` 81.4px on ~7 fog tiles, `basin_treaties/q.png`
  202.0px at the zoom extreme). It is still wrong, because None means "not enough
  *contiguous* fog to autocorrelate" and not "no fog": **`pol_archi_test` is ~86%
  explored and returns None on both shots while holding 45 fog tiles.** Wired in,
  it waves that set through at 14, 16 *and* 20 — a silent wrong-size merge, the
  most destructive failure available here. Branching only the *hint* on it is no
  better: it invites the player to force that same merge.
- **A fog-ish color fraction.** `fogless` reads 0.083/0.090 against
  `star_change/oum.png`'s 0.248, which looks like a 2.8x margin until you notice
  the only things in between are `goon_test/fogless.png` (0.105) and
  `archers_test2/fogless.png` (0.203) — excluded reference renders that are
  themselves fogless. That is a threshold calibrated on one set, and it is a
  color-based fog test, which this program does not do.
- **The conflict fraction after the merge** (`CONFLICT_FRAC_SUSPECT`) — which
  works, and is the one that shipped. It succeeds because it stops asking about
  fog and measures the *harm* instead: an out-of-phase lattice puts each
  source's fog on another source's terrain, and fog against terrain is an
  enormous color distance, so `--consistency-thresh` sees it directly. It is
  the only signal here that catches a wrong size without having to find fog.

  **The denominator has to be comparable tiles, not the board.** Conflicts need
  two witnesses, so dividing by the board dilutes the number by however little
  the shots overlap — `basin_treaties`, whose two shots show disjoint islands,
  reads **0.020 of the board** at a wrong size, under any usable bar, while the
  few tiles they do share disagree wholesale. Over comparable tiles instead,
  measured by forcing all 21 sets to all five sizes:

  | population | conflict fraction |
  |---|---|
  | correct size | n=18, max **0.167** (`badland_test3`; `star_change` 0.146) |
  | `fogless`, any size | n=4, max **0.074** |
  | wrong size, board has fog | n=71, median **0.761**, p05 0.380, min **0.284** |

  0.18 sits between the two populations that can actually reach the check — a
  stated size on a fogless board, and a wrong stated size on a fogged one.

  **It only rules a size out, never in.** Two wrong-size rows read **0.000**
  (`badland_test` at 11 and 14, where only 18 and 31 tiles are comparable at
  all), and `fogless` reads the same at 20 as at 16 because with no fog there is
  nothing for a bad lattice to smear. So a low number is evidence of nothing and
  gets no message at all — an earlier version printed "nothing contradicts NxN"
  and that was reassurance the measurement cannot support.

The plausibility filter handles a *broken* measurement. What is still
unhandled is two or more **plausible** sizes genuinely conflicting — the
`goon_test2/imp.jpg` + `test_ss_2/cym1.jpg` case, 17.93 against 19.85. That
refuses the whole merge, which is safe but unhelpful: the shots of one of those
boards would merge perfectly well on their own.

The design, specified but not built:

1. Candidate sizes = the distinct sizes the surviving measurements round to.
2. For each candidate, in descending order of how many measurements back it:
   load its template, anchor every shot, count each shot's fog lock. Stop at
   the first candidate that locks healthily, so the common cost is one pass.
3. Adopt that size. Any shot locking below `--min-fog-lock` at it is not on
   that board — drop it through the existing `DROPPED` path, merge the rest,
   report it.
4. If no candidate produces a shot clearing `--min-fog-lock`, refuse as today.

**The fog lock is the right adjudicator, and a vote is not**, for the reason
the whole pipeline rests on: fog is one deterministic render, so a shot on the
right board at the right size locks 100–250 tiles and a shot that is not locks
2–4. That is the separation `--min-fog-lock` already keys on, and it is the
same acceptance test `corroborate_anchor` and the SIFT anchor borrow use —
adopt a candidate only by proving it against that shot's own fog. A shot
dropped this way is dropped for failing to match the board, not for losing a
headcount.

The obstacle is structural rather than algorithmic: `main` loads the template
once and `anchor_all` closes over it, so step 2 needs the span from template
load through the fog-lock computation extracted into a function of `map_size`.
That refactor is the bulk of the work and it touches the registration path, so
it wants the full 16-set before/after even though the new branch should be
unreachable on every one of them.

When built, the reporting is already half there: extend the `DROPPED` line with
a per-name reason (keeping the prefix and `n/m` shape stable, as the comment
there asks), have `dropped_shots` in polybot return it, and pick the caption
per reason — *"Image 3 of 3 looks like a different board and was skipped.
Merged the other 2 in 21s."* Until then the caption deliberately says only
*what* happened ("couldn't be placed on the board"), because the `DROPPED`
line does not carry a cause and the bot must not guess one. It used to read
"does not look like a Polytopia screenshot", which is a claim about the
*image* and is simply false for the commonest remaining cause — an ordinary
screenshot the merge could not place. Getting told your real screenshot isn't
a screenshot sends a player looking in the wrong place entirely.

### `fog_period_scale`'s answer depends on its own sweep floor

The measured period moves by up to **0.9%** when `lo` changes, with nothing
else different. Measured on the pipeline's real masks:

```
badland/oum   0.45:117.72  0.40:118.14  0.35:117.75  0.30:118.16  0.25:117.77
archers/cym2  0.45:65.78   0.40:66.41   0.35:65.81   0.30:66.43   0.25:65.83
bt2/cym       0.45:58.61   0.40:58.39   0.35:58.62   0.30:57.97   0.25:58.63
```

`t_lo = tile_px * lo` sets the *phase* of the coarse grid, so a different `lo`
picks a different winning coarse sample `t0`, which slides the fine pass's
narrow ±5px window. When the top of the peak is near-tied between adjacent
samples — badland's full-resolution curve has 114 and 115 both at 0.572 —
`argmax` jumps and the 3-point parabola swings with it. Note a synthetic
all-valid mask does *not* reproduce this: the peak is sharp enough there to be
stable at every floor, so test it with the real masks or you will conclude the
effect does not exist.

This is pre-existing, not a consequence of moving the floor to 0.30 — the same
sensitivity is there at 0.45, and the old corpus simply sat on a good phase.
What moving the floor did was land `badland_test2` on a bad one, taking the
worst intra-set detect spread from 0.16 to 0.36 against the 0.5 refusal bar.

**Do not fix this by hunting a lucky `lo`.** That is fitting to today's corpus
and leaves the next zoomed-out screenshot in the same trap. The fix is in the
fine pass: a 3-point parabola on `argmax` over 11 samples is too fragile for a
peak this broad, and fitting over the top of the peak instead would make the
answer phase-independent.

That also unblocks a better version of the **smallest-strong-peak** rule, whose
justification is weaker than it reads. It defends only against picking a period
that is too *large*; nothing guarantees the shortest strong peak is the
fundamental, only that no harmonic of the fog is shorter. A real tile lattice
emits a full comb of multiples, and `missized_test/z2.png`'s coarse curve is a
textbook one — 39:0.68 79:0.81 123:0.76 159:0.68 199:0.83. So the physical test
is "does this candidate have its own multiples?", not "is it the smallest?", and
picking the strongest peak then dividing down through the comb would have
recovered 40 from 80 whether or not 40 was ever swept — i.e. it fixes z2
without depending on `lo` at all. Note z2's fundamental is *not* its strongest
peak (0.68 against 0.83), so "take the strongest" alone is also wrong; the comb
is what separates them. This needs the stable period measurement above first.

### Content differences that are real, not geometry errors

None of these produce wrong *geometry* — they surface as spurious
`--consistency-thresh` conflicts, which is why the conflict report is left
intact rather than tuned to hide them.

- **Resource icons are tech-gated per player**: a player without the relevant
  technology does not see a resource another player does, so two shots of one
  tile can legitimately differ.
- **Unit art desaturates once that unit has moved this turn**, so the same
  unit differs in color between two players' shots of the same moment.

For scale, at the correct map size the conflict counts run 0–28 per set (see
the companion baselines above) — mostly small color distances consistent
with the above. `star_change`'s 28 is the high end and is **not** explained
away: two shots of one board are expected to agree, and a unit that moved
between them is user error on the players' part, not a case the merge should
be tuned around. Do not write it off as timing.
