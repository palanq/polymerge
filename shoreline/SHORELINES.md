# Shoreline inference

Reads the shoreline the game draws on a water tile's rim to infer whether an
adjacent *fogged* tile is land or water. It rests entirely on the game
guarantees below, and it is the one thing in this project that tells a player
something no screenshot showed them.

**That is why it lives here and not in `polymerge.py`.** Merging only pools what
players already photographed; this extracts something nobody read off their own
screen. That is additional assistance, and the project owner requires it to be
available league-wide before running the bot on real games is authorized
(2026-08-17). It used to be `polymerge --shorelines`, which meant the guarantee
rested on a flag nobody passed. Now it rests on the code not being there — a
property you can check by looking. Do not "fix" that by matching the
`--ruin-vision` / `--city-bars` precedent, which *are* always-on in the bot.

## Staging

1. **Done.** Excised into `shoreline/`, with a single-image CLI: one screenshot
   in, per-tile verdicts out, plus an optional washed render.
2. **Next.** A separate bot on that CLI, deployed to the project owner's
   server, to gather real screenshots.
3. **Later.** Re-integration, with `polymerge.py` driving this as a subprocess.

Everything below *How it reads* was measured while this was a phase inside the
merge, and the measurements carry over unchanged, because the reader itself was
lifted verbatim. Where a passage describes the merge integration it is kept as
the specification stage 3 has to restore, not as a description of what runs
today.

## Layout

```
shoreline/
    polyshore.py            the reader, plus the single-image driver
    SHORELINES.md           this file
    shoreline_basis.npz     the learned basis; only --method joint/hybrid needs it
    tools/
        fogpair.py          scores the reader against real ground truth
        learn_shorelines.py rebuilds shoreline_basis.npz
    fog_pairs/              six fog/fogless screenshot pairs -- the ground truth
    examples/               14 tile-detail popup renders, which set the constants
```

`polyshore.py` imports `polymerge.py` for the anchoring and tile-sampling
primitives — the arrangement `shoreline/tools/fogpair.py` has always used. The dependency
runs one way only: **`polymerge.py` and `polybot.py` must never import this.**

## Running it

```bash
.venv/Scripts/python.exe shoreline/polyshore.py shot.png --map-size 18 -o washed.png
```

- `--map-size` is optional; omitted, it is measured off the screenshot
  (`detect_map_size`), which needs the shot to span the whole board in one
  direction and refuses rather than guessing when it does not.
- `-o` writes a render. `--frame board` (default) is the whole board in
  template space — the blank all-fog render with this shot pasted over it, so
  board it never photographed reads as fog. `--frame shot` washes the
  screenshot's own pixels instead, which is what a player recognises, and is
  what stage 2's bot will want.
- `--method` is `ratio` (default), `joint` or `hybrid`; see the joint-model
  section. The latter two need `shoreline_basis.npz`.
- `--debug-dir` writes `shore_<name>.png` — every rim band measured, green =
  shoreline, blue = none, red = looked at and could not be called — and prints
  the near misses, which is the list to work from when the reader is missing
  shorelines a human can see.
- `--min-fog-lock` (default 8) is the wrong-`--map-size` guard. A single shot
  has no cross-shot signal, and a wrong size puts every tile out of phase,
  after which the fog test calls the whole board explored.

**The tiles it answers about are the ones the shot itself witnessed as fog** —
narrower than the merge's "every tile with no winner", which also swept in
tiles nobody photographed. A rim facing off the edge of the photo is a real
reading, but nothing here can show it or corroborate it, so it is not claimed.
That is also the set `shoreline/tools/fogpair.py` scores, so every number below describes
exactly this population. Verified at the excision: on three shots run both
ways, every tile the single-image reader reports matches what
`polymerge --single --shorelines` reported, verdict for verdict, and the only
tiles it drops are ones sampling marks `witness=False`.

## What the game guarantees

**A water tile is lightened along every edge that touches land**, and the
game draws that from the *true* terrain — so the rim facing a **fogged** tile
still says what the fog hides. Four facts make this exact rather than
suggestive, all confirmed with the project owner — they are the whole
foundation, so if one turns out to be wrong the reader has to change with it:
- **shoreline ⟺ land beyond.** Every side of a water tile that touches land
  shows one, and only those sides do. It is a biconditional, so the absence
  of a shoreline is evidence of water, not merely absence of evidence.
- **Ice counts as land** for this purpose, and ice tiles carry no shoreline
  of their own.
- **A water tile always has at least one shoreline.** A tile with water on
  all four sides is ocean (or land), never shallow water. That is what makes
  a per-tile positive control possible.
- **Ocean therefore has water on all four cardinal sides**, which resolves
  all four of its fogged neighbours at a stroke — built, and it reaches
  exactly where the rim reader is blind, in open sea where there is no
  shoreline anywhere to read.

Beware the tile-detail popup renders in `examples/`: they show the whole 3D
box including the sandy block underneath, most of which is never visible in a
game. Concretely, a *non*-shoreline rim reads 0.758 there and 1.000 in a real
screenshot.

## How it reads

**The reader.** In template space, per source, on tiles that source witnessed
as explored:
- The tile's water surface sits `SHORE_DROP_FRAC` = **0.14** of a tile step
  *below* its lattice rhombus, because the lattice comes from the all-fog
  template — i.e. from fog cube tops — and fog is much taller than water
  (measured fog wall 0.765–0.816 of a tile step across the five blanks against
  the sprites' water wall 0.50–0.52). That predicts ~0.27; the separation
  measures flat over 0.10–0.24, so 0.14 is the middle of a plateau, not a
  fitted value.
- A rim band 0.0625–0.203 of a tile inward from the edge, trimmed to the middle
  half so no corner enters it, versus the tile's own inset core. Comparing a
  tile **to itself** is what makes this immune to exposure, device and the
  sunrise.
- Both restricted to **water-chromatic** pixels (G/B 0.830, R/B 0.431). This is
  not a terrain catalogue: it identifies one tile type whose art is fixed, the
  way the fog test does, and only to decide which pixels of an
  already-classified tile are water.
- The band is read at its **70th percentile, not its median**, and the
  asymmetry is the point — a shoreline can only be *diluted* by what intrudes
  on the band (the taller fog cube to the south clipping it, a border fence, a
  boat) and never brightened. p70 took land recall 93% → 95% at unchanged zero
  false positives; p50 loses partly-occluded SE/SW edges, p90 starts lifting
  flat water.
- ratio ≥ **1.03** → shoreline → land beyond; < **1.02** → water beyond;
  anything else, or too little water left in the band, → **not called**. The
  three-way answer is the feature, not a hedge.

**Ocean is judged among the tile's *water* pixels, not over its whole rhombus**
(`SHORE_OCEAN_DOMINANCE` 0.70, plus floors `SHORE_MIN_OCEAN_PX` and
`SHORE_MIN_WET_FRAC`). An ocean tile at the fog frontier is partly hidden by
the taller fog cube beside it, and a whole-rhombus fraction counts that
occluder against it: `goon_test` (15,15) is 18% ocean and 6% shallow water by
area, so the old 0.55 whole-rhombus bar refused it, while the water it does
show is 75% ocean. Dividing the occluder out of both sides is the same move
`--fog-frac-margin` makes for occluded fog. This roughly doubled ocean
detections and added 13 water verdicts corpus-wide, with land verdicts, union,
conflicts, bars and `--cross-check` all unchanged.

**The ocean test's false-positive rate is still not properly measured, and the
obvious way to measure it does not work.** Scoring "does a detected ocean tile
have a land neighbour?" with a colour-threshold land test reports ~20-30%
violations — but it reports the *same* rate for the old strict rule on tiles
that are unambiguously ocean by every measure (dominance 0.82-1.00), so the
land test is what is wrong, not the detector. Do not tune ocean against that
harness. What is checked, and what to re-run after touching this: an ocean
claim must never contradict a shoreline reading, since a "land" call is the one
verdict measured at 0% false. Across all 19 sets that is **0 contradictions**.
That is necessary rather than sufficient — it only covers tiles a rim reading
also reaches — so real screenshots of open water remain the thing to collect.

**The two thresholds are now set against the fog pairs, and one of them was
set wrong by the older data.** Raising `SHORE_RATIO_LO` from 1.02 to 1.025 looks
free on two pairs (+1 correct, nothing wrong) and is the *only* setting in the
whole sweep that produces a false **water** call — `ocean_warrior` (15,6), read
from (15,5)'s SW rim at 1.0211. It stays at 1.02. `SHORE_MIN_CLEAN_FRAC` went
the other way: 0.75 -> 0.40 gains 8 correct calls with no new error of either
kind, because on this population the gate was only ever costing coverage —
every uncalled edge with a truth label behind it was water. 0.20 measures
better still (125 correct, same single error) but is held back until there are
more pairs; four boards is not enough to trust a gate that loose.

**The one surviving error is not a threshold problem.** `epic_blood` (8,17) is
called land when it is water, from tile (8,16)'s SW rim at 1.033, and it
persists at every threshold setting tried. (8,16) has real land on its **NW**
edge; the two edges meet at the west vertex and that genuine shoreline bleeds
around the corner into the SW band. Reading each edge independently is what
allows a neighbour edge's shoreline to be counted as this one's, so this is the
case for scoring whole-tile configurations jointly rather than four separate
rims — see the deferred note.

**All four edges are read.** SE/SW were expected to be unusable, since a taller
neighbour to the south clips them — but measured they are only slightly weaker
(recall NW 97%, NE 94%, SW 93%, SE 85%) at the same zero false-positive rate.
Do not drop them again without measuring.

**Absence is only evidence if the rim was visible** (`SHORE_MIN_CLEAN_FRAC`).
A "water" verdict needs 40% of its band to be unobstructed water, because a
fence or a hull sitting on the band reads exactly like calm water. "Land" needs
no such gate — a shoreline is its own evidence.

That replaced a positive control built on the game fact that a water tile
always has at least one shoreline: require the tile to show one somewhere
before believing its other rims. The rule is sound and it is **structurally
blind** — a tile whose only shorelines face the occluded south can never
satisfy it, which is exactly where it kept refusing correct answers (confirmed
by the project owner on `test_ss_fruit` tile (4,4), whose NE and NW rims are
genuinely shoreline-free and were being suppressed). The clean fraction
dominates it on both axes: 87% of true water edges called at a 1.4% wrong rate,
against the control's 82% at 2.5%. Don't re-land the control.

**A band clipped by the edge of the photo is not a measurement**
(`SHORE_MIN_FRAME_FRAC`). This is separate from occlusion and the occlusion
gates cannot see it: the surviving pixels are a biased sample, not merely a
small one. The corpus's one confirmed false "land" was exactly this —
`goon_test2` tile (17,4)'s NE rim, 78% in frame, reading 1.050 against a truth
of water (the project owner identified the tile beyond it as carrying a port,
which can only sit on water). Eroding the band did **not** fix it, so it is not
a fringe artifact. 96.9% of the corpus's 2236 bands are wholly in frame, so
requiring it costs ~3%.

**Measured performance — use `shoreline/tools/fogpair.py`, not the older numbers.**
`shoreline/fog_pairs/` holds six fog/fogless screenshot pairs: the same camera on
the same turn, once with fog and once without. The fogged one anchors normally
(it has fog to lock onto and all four board edges), and because the two are
pixel-aligned that transform is equally valid for its partner — so every tile
yields both what the detector sees and what is really there. That is the first
harness to score the population the reader is actually applied to.

**150 of 150 correct (100%), no false call in either direction**, resolving
65-88% of the fog tiles that are addressable (adjacent to explored water),
across six pairs. The shipped reader learns nothing, so there is no
training/test question here -- this is a direct measurement on every board.

**That figure has already been wrong once, and the way it was wrong is the
lesson.** With four pairs the reader scored 116/116 at `SHORE_RATIO_HI` = 1.03,
and that clean sweep did not survive the fifth and sixth: `mil_goon` (9,13) is
truly water and its SW rim reads 1.0389, so it was called land. Two more boards
were enough to move a threshold. Run this after *every* added pair, and read a
zero-error result as "not yet falsified" rather than as a guarantee:

```bash
.venv/Scripts/python.exe shoreline/tools/fogpair.py
```

The older figures — 277 land-adjacent and 337 water-adjacent edges over ten
sets, land 95% recall at 0.0% false, water 87% at 1.4% — are still the source
of the ratio distributions (land median 1.089, water 1.006, a void between
water's max 1.028 and land's p05 1.045), but they score edges whose neighbour is
**explored**. That is a different population from the one the reader is used
on, and it is how the `goon_test2` (17,3) false land call survived every number
in this file. Prefer the fog pairs; keep the two same-board sets
(`goon_test`/`goon_test2`) as the cheap consistency check.
Getting that ground truth right was most of the work — dimmed tiles, and boats
and units sitting on water, both masquerade as land and inflated the apparent
error rate from 2.6% to 21% before they were excluded.

**The shipped reader is the plain per-edge ratio test**
(`--method ratio`, the default), with `SHORE_RATIO_HI` at 1.045. It
needs no learned asset.

A hybrid was built and briefly shipped: the ratio verdict with the learned
templates given a veto over it, which at HI = 1.03 was the only configuration
that made no false call (116 correct against the bare reader's 115 with one
wrong). Raising the bar to 1.045 for the `mil_goon` failure made that veto
**inert** -- measured, identical numbers on all six pairs with the veto enabled
and disabled, because the higher bar already excludes everything the veto was
catching. So the default reverted to the simpler reader that carries no asset
dependency. `--method hybrid` still selects it, and it remains the
only design that can attribute a corner shared by two edges, which is worth
knowing if a future pair produces a corner error the ratio bar does not catch.

**`--method hybrid` and `joint` need `shoreline_basis.npz`** and skip
the feature rather than falling back when it is absent, since a silently
different method is worse than none. The default `ratio` needs no such file.

**Occlusion is decided without a colour prior**, which matters because the
obvious alternative is measurably lossy: keeping only water-chromatic pixels
throws away a median 34% of a shoreline band and more than 60% of it on a
quarter of them, since a strong shoreline leaves the water chroma window on its
way to sand. Instead a pixel counts as occluded when *no* hypothesis explains
it -- the per-pixel minimum residual across all fifteen templates, cut at
`SHORE_ROBUST_MAD` MADs above its median. Three things were tried on top of
this and measured to add nothing: a perpendicular-gradient statistic, a chroma
ratio in place of gray, and weighting pixels by how well-determined the basis is
(99% of basis pixels are fitted from 60+ samples, so there is no spread to
exploit). Do not re-land them without new evidence.

**Colour is load-bearing in the templates, and only there.** The same template
scheme scores 112 in gray and 116 in colour, and gray makes two false land calls
where colour makes none. But as a *band statistic* replacing the ratio's gray,
chroma is worse -- 46% recall against 84% at zero false positives. So colour
helps a whole-tile match and hurts a single-band contrast; the two results are
consistent, not contradictory.

**Occluders must still be masked, and cancellation does not substitute.** The
tempting argument is that an occluder adds the same error to every hypothesis
and so cancels in the margin. Measured, leaving occluders in gives **22-25 false
land calls against zero**. Cancellation needs the added error to be independent
of the hypothesis, and in the discriminating band it is not: that band is
*defined* as where brightness separates the hypotheses, so anything bright
intruding there is indistinguishable from evidence. Colour does not rescue it
either (22 against gray's 25) -- it makes the occluder's error large for both
hypotheses rather than equal, so the signal drowns instead of cancelling.

**Only edges facing the composite's fog are measured.** The merge is already
decided when this runs, so a reading about a tile somebody explored would be
discarded anyway — and computing it first was pure waste. `read_shorelines`
takes the unresolved set and skips a water tile outright when none of its four
neighbours is still fog, which on a developed board is most of them: it cut
edges measured by ~95% (`goon_test` 384 → 20, `pol_archi_test` 196 → 5) with
every verdict, and every tracked baseline, identical. The candidate list is
built *before* the per-source chroma masks, because those are full-canvas and
would otherwise be the whole cost of the phase on a shot with no fog frontier.
What is left (~0.25s per merge) is those masks, and they cannot be avoided —
deciding a tile is not water is what they are for.

**The merge cannot change.** Everything runs after winner selection and paints
after `paint_overlays` (so shading cannot dilute the wash) and before the ruin
markers (so a marker still reads over it). Verified: with `--shorelines` passed
on every merge in `tools/baseline.py`, all 19 sets' union, conflicts, bars and
`--cross-check` are identical to their documented values. Readings pointing at
a tile somebody explored are discarded — their real terrain is better
information than an inference about it — so a washed tile is fog by
construction and real terrain can never be tinted.


## The joint whole-tile model: built, measured, not yet the default

`--method joint` scores whole-tile *hypotheses* instead of asking each
rim in isolation. A hypothesis names which of the four edges carry a shoreline,
so it predicts the corners too, and each edge's answer is the **margin** between
the best hypothesis containing it and the best one without. Built because the
per-edge reader's one remaining error is structural: `epic_blood` (8,17) is a
flat SW rim called land because the genuine NW shoreline bleeds around their
shared west vertex, and no threshold separates those -- the reading is ambiguous
until both edges are decided together.

The model is nine images (`shoreline/tools/learn_shorelines.py` -> `shoreline_basis.npz`):
a water base, four edge contributions, four corner interaction terms, learned
from the fog pairs. Not sixteen per-configuration templates, because a
neighbour is fog / explored land / explored water / board rim, so the space the
detector meets is 6^4 -- measured, 87 distinct patterns among 113 tiles. Five
terms explain 79.2% of the configuration variance and the four corner terms take
it to **92.7%**. Two supporting measurements, both reusable: a shoreline looks
the same whether its neighbour is fog or land (0.001-0.007 against a signal of
0.03-0.09), *except* on NE where a fog neighbour darkens the rim by -0.043, so
four scalar fog offsets are fitted alongside.

**It does not beat the per-edge reader on honest evaluation, and more training
data will not fix that -- measured, not assumed.** Trained on all four pairs it
scores 122/124; held out one pair at a time, 117/122. The obvious reading is a
generalisation gap that more pairs would close, and that reading is **wrong**.
The learning curve, scoring each pair against a basis trained on N others,
flattens between two and three:

| margin | 1 pair | 2 pairs | 3 pairs |
|---|---|---|---|
| 0.001 | 7.6% error | 1.3% | **1.0%** |
| 0.0006 | 9.5% | 3.1% | **3.4%** |
| 0.00035 | 11.5% | 4.4% | **4.1%** |

It has already asymptoted, so the limit is the model or the features, not the
sample size. At matched coverage (~29 tiles/board) it errs 3.4% against the
ratio method's 0.9%; at matched error it resolves 24.8 against 29.0. Two levers
worth trying, both model changes: score in **colour** rather than gray (the
basis discards the chroma the ratio method leans on), and **weight pixels by how
well-determined the basis is** there, since a pixel fitted from a handful of
samples currently counts as much as one fitted from hundreds.

Swept against the margin under leave-one-out, its best error-matched operating
point resolves **99** tiles where the ratio method resolves **116**:

| margin | correct | wrong land | wrong water |
|---|---|---|---|
| 0.00035 | 117 | 4 | 1 |
| 0.001 (current) | 98 | 0 | 1 |
| 0.002 | 80 | 0 | 0 |

So the *pure* joint path is not the default -- but it is not discarded either:
its templates are what the shipped hybrid uses as a veto, which is where its one
real advantage (attributing a corner shared by two edges) pays off without its
disadvantage (a board-averaged template cannot adapt per tile). Re-run `shoreline/tools/fogpair.py --method both --loo` after any
change to it; if the leave-one-out number crosses the ratio method's 115/116,
switch the default. **More fog pairs are still worth collecting, but as
validation rather than training** -- 116 calls over four boards is a thin basis
for a 99.1% claim, and the informative ones are boards unlike these four:
complex coastline (three- and four-edge configurations are the rarest, at 8-10
samples) and an ice board, since ice counts as land here and no pair has one.

Two sources disagreeing about one tile is reported as a **conflict and marked
nothing**: shoreline ⟺ land is a biconditional, so both cannot be right. No set
in the corpus produces one.

## Test assets

`shoreline/examples/` — 14 tile-detail popup renders of water tiles,
named by which edges carry a shoreline (`NW-NE.png`, `SW-SE.png`, `SE,
fish.png`, `NW-SE, port, borders.png`, `ocean.png`, …). These calibrated
the shoreline constants and are the labelled test for the three-way answer:
the fish and most border cases read correctly, and a border sitting on a
rim reads far outside both bands, which is exactly the uncallable case. The
two carrying a bridge and a port cannot be registered from their silhouette
at all — the structure breaks the outline fit by 20% — so don't use them
for geometry.

`shoreline/fog_pairs/` — six fog/fogless screenshot pairs, the same camera
on the same turn photographed both ways. This is the ground truth and the
only harness that scores the population the reader is applied to; see
*Measured performance* above.

**Two screenshots this file used to point at are gone.** `q1.png` and
`z1.png` showed a small explored island in heavy fog on two *different*
boards, and neither could be anchored — one board edge each, which is the
deferred "no board edge from each direction" gap. They were reachable by
anchoring from the fog phase alone, since an unknown whole-tile offset does
not matter when every band is measured inside its own tile. The measurement
worth keeping: `z1`'s southernmost water tile is what motivated the p70 band
statistic, its SW edge reading 1.027 under a median and 1.037 under p70,
which is the correct call. Two shots of that shape would be worth
recollecting for stage 2.

## Corpus verdicts

Land/water verdicts over the 21 merge sets in `tests/`, in the order
`tools/baseline.py` lists them — **0/0, 0/0, 1/5, 6/12, 0/5, 2/13, 1/14,
0/0, 3/12, 0/0, 0/0, 0/0, 0/5, 0/0, 0/0, 1/8, 4/4, 3/13, 1/0, 0/0, 0/0**
(113 in all, 0 conflicts). The ten sets reading 0/0 have no water at their
fog frontier at all, which the water survey confirms independently — not a
detector failure.

These were produced by the merge, pooling every source, so they are not
reproducible from `polyshore.py` as it stands: a single shot answers about
fewer tiles (see *Running it*). They are kept as the stage-3 target — when
the merge drives this again, these are the numbers it should return to.
The live regression test meanwhile is `shoreline/tools/fogpair.py`.

One cross-set check is worth keeping in mind, because it is what caught the
corpus's one confirmed false "land" call. `tests/goon_test` and
`tests/goon_test2` are the same board shot on different turns, so the reader
sees it twice independently: the two sets share 6 resolved fog tiles at
identical coordinates and agree on all 6, with no contradiction. That
agreement is what made `goon_test2` tile (17,3) stand out as the exception.

## Deferred: validating the ocean rule as an inference

The ocean rule is built, but its *test* is
still only lightly validated. `water_chroma_masks` identifies ocean by colour,
and until now that mask was used only to **exclude** ocean tiles from rim
reading, where a false negative costs nothing. As an inference a false positive
washes four tiles at once, so the asymmetry matters.

What exists: the rule's own self-check, which says 33 of 34 explored neighbours
of a detected ocean tile are water or ocean. What is missing is a corpus with
enough open water to make that number mean something — single digits of ocean
tiles per set today. Fresh screenshots of open sea are the thing to collect.
