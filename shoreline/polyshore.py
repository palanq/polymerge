#!/usr/bin/env python
"""Read the shoreline the game draws on a water tile's rim, from ONE screenshot.

The game lightens a water tile's edge wherever it touches land, and it draws
that from the *true* terrain -- so the rim facing a fogged tile still says
whether the fog hides land or water. This reads those rims and reports what
each fogged tile beyond them must be.

This lived inside polymerge.py as --shorelines until it was excised. It is a
separate program on purpose, and the reason is not tidiness: merging only pools
what players already photographed, whereas this extracts something nobody read
off their own screen. That is additional assistance, and it needs to be
available league-wide before it runs on real games. Keeping it out of
polymerge.py and polybot.py is what makes that guarantee checkable by looking.

Stage 1 of three: one image in, verdicts out. Stage 2 is a separate bot on this
CLI, to gather real screenshots. Stage 3 is re-integration, with polymerge
driving this as a subprocess. See SHORELINES.md.

It imports polymerge for the anchoring and tile-sampling primitives -- the same
arrangement tools/fogpair.py has always used. polymerge does not import this,
and must not.

    .venv/Scripts/python.exe shoreline/polyshore.py shot.png --map-size 18 \
        -o washed.png --debug-dir d/
"""
import argparse
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import polymerge as pm                                        # noqa: E402
from polymerge import REFERENCE_TILE_PX, poly_mask_bbox, tile_poly  # noqa: E402


def _first_existing(*paths):
    """The first of these paths that exists, else the last one.

    Returning the last rather than None keeps the caller's error message
    pointing at a real filename instead of "None"."""
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[-1] if paths else None

# ------------------------------------------------------------- the reader ---
# The game lightens a water tile's rim along every edge that touches land, and
# it draws that from the *true* terrain -- so the rim facing a fogged tile
# still says whether the fog hides land or water. Four game facts make this an
# exact reading rather than a heuristic, all confirmed with the project owner:
#
#   * every side of a water tile that touches land shows a shoreline, and only
#     those sides do -- so shoreline <=> land beyond, a biconditional;
#   * ice counts as land here, and ice tiles carry no shoreline of their own;
#   * a water tile always has at least one shoreline. A tile with water on all
#     four sides is ocean (or land), never shallow water;
#   * ocean therefore has water on all four sides, so an ocean tile resolves
#     all four of its fogged neighbors at a stroke -- built, and it reaches
#     exactly where the rim reader is blind, in open sea where there is no
#     shoreline anywhere to read. SHORELINES.md records what is still only
#     lightly validated about it.
#
# Calibrated against the tile-detail popup renders in examples/ next to this
# script, the same fixed art at the same projection (sprite tile aspect 1.677
# against the template's 1.672). Two cautions about those sprites, both learned
# the hard way. They show the whole 3D box including the sandy block underneath,
# most of which is never visible in a game -- in particular a *non*-shoreline
# rim reads 0.758 there and 1.000 in a real screenshot, so the sprites calibrate
# the presence of a shoreline and the corpus calibrates its absence. And the two
# carrying a bridge and a port cannot be registered from their silhouette at all
# (the structure breaks the outline fit, 20% out), which is why nothing here
# reads the sprites at runtime: they set the constants below, exactly as the
# RUIN_* and PIP_* windows were set, and the ratio reader needs no assets.
SHORE_DROP_FRAC = 0.14   # how far *below* its lattice rhombus a water tile's
                         # surface is drawn, in tile steps. The lattice comes
                         # from the all-fog template, i.e. from fog cube tops,
                         # and a fog cube is much taller than water: measured
                         # fog wall 0.765-0.816 of a tile step across the five
                         # blanks against the sprites' water wall 0.50-0.52.
                         # That difference predicts ~0.27; the separation
                         # actually peaks flat over 0.10-0.24 and 0.14 sits in
                         # the middle of the flat part, so this is not a tuned
                         # knob -- see the table in SHORELINES.md.
SHORE_BAND_LO = 0.0625   # the rim band, as a fraction of the tile step inward
SHORE_BAND_HI = 0.2031   # from the edge. Wide enough to hold the whole
                         # lightened strip at every zoom in the corpus.
SHORE_EDGE_TRIM = 0.25   # drop this much of each end of the edge, so a corner
                         # (where two edges' bands meet, and where the game
                         # blends them) never enters either band.
SHORE_CORE_INSET = 0.35  # the tile's own interior, which the band is measured
                         # against. Comparing a tile to *itself* is what makes
                         # this immune to exposure, device and the sunrise.
SHORE_BAND_PCT = 70      # the band's brightness is read at this percentile, not
                         # at its median, and the asymmetry is the point: a
                         # shoreline can only ever be *diluted* by whatever
                         # intrudes on the band -- the taller fog cube to the
                         # south clipping it, a border fence, a boat -- and
                         # never brightened. Measured over the same corpus, p70
                         # takes land recall from 93% to 95% at an unchanged
                         # zero false positives; p50 loses the partly-occluded
                         # SE/SW edges and p90 starts lifting flat water too.
# The rim/core gray ratio. Land-adjacent edges run a median 1.073-1.095 on all
# four edge directions and every set, water-adjacent ones 1.000-1.005, so these
# bounds sit inside a void rather than being fitted.
#
# SHORE_RATIO_HI was 1.03 and is 1.045 because 1.03 was set on four fog pairs
# and did not survive the fifth and sixth. `mil_goon` (9,13) is truly water and
# its SW rim reads **1.0389** -- above the old bar, so it was called land. Over
# all six pairs the highest ratio ever read on an edge whose truth is water is
# 1.0391, so 1.045 clears the worst observed case by 0.006 rather than by the
# 0.001 that 1.040 would give. It costs coverage: 158 correct calls become 150.
# That trade is deliberate -- a wrong wash is worse than a missing one -- and it
# is the whole reason the bar is not simply placed at the top of the measured
# water distribution.
#
# Read this as the standing warning about the other thresholds here too: every
# one of them was set on the pairs available at the time, and the only reason
# this one was caught is that two more boards arrived. Re-run tools/fogpair.py
# whenever a pair is added, and expect a bar to move rather than hoping it will
# not.
SHORE_RATIO_HI = 1.045   # at or above: shoreline present -> land beyond
SHORE_RATIO_LO = 1.02    # below: no shoreline -> water beyond
# Water's own color, as chromaticity ratios so a shot's overall gain divides
# out. Measured off the sprites (G/B 0.830, R/B 0.431 for water; 0.574, 0.292
# for ocean) and confirmed on the corpus. This is *not* a terrain catalog --
# see the standing decision in CLAUDE.md. It identifies one tile type whose art
# is fixed, the way the fog test does, and it is used only to decide which
# pixels of an already-classified tile are water; nothing here classifies fog,
# and a tile that fails it is simply not read.
SHORE_WATER_GB, SHORE_WATER_RB = 0.830, 0.431
SHORE_OCEAN_GB, SHORE_OCEAN_RB = 0.574, 0.292
SHORE_CHROMA_TOL_G, SHORE_CHROMA_TOL_R = 0.10, 0.13
SHORE_MIN_BLUE = 60      # too dark for a chromaticity ratio to mean anything
SHORE_TILE_WATER_FRAC = 0.55   # of the core, before a tile is read as water
# Ocean is judged among the pixels that are *water at all* rather than over the
# whole rhombus, because an ocean tile at the fog frontier is partly hidden by
# the taller fog cube beside it and a whole-rhombus fraction counts that
# occluder against it. Measured on goon_test (15,15): 18% of the rhombus is
# ocean and 6% shallow water, so a 0.55 whole-rhombus bar refuses it while the
# water it does show is 75% ocean. The occluder drops out of both sides of a
# ratio, which is the same move --fog-frac-margin makes for occluded fog.
SHORE_OCEAN_DOMINANCE = 0.70   # of the tile's water pixels, to call it ocean
SHORE_MIN_OCEAN_PX = 300       # and this many ocean px outright, so a handful
                               # of dark specks on shallow water cannot do it
SHORE_MIN_WET_FRAC = 0.20      # and this much of the tile must be water at all,
                               # so the ratio is not decided from a sliver
SHORE_MIN_CLEAN_FRAC = 0.40    # how much of a band must be unobstructed water
                               # before its *flatness* is allowed to mean
                               # "water beyond". A shoreline is its own
                               # evidence and needs no such gate, but an absent
                               # one is only evidence if the rim was actually
                               # visible -- otherwise a fence or a hull sitting
                               # on the band reads exactly like calm water.
                               # Measured against the corpus: 87% of true water
                               # edges called at a 1.4% wrong rate, where the
                               # game-fact positive control it replaced (a tile
                               # must show one shoreline somewhere before its
                               # other rims are believed) managed only 82% at
                               # 2.5%. That control is sound but structurally
                               # blind: a tile whose only shorelines face the
                               # occluded south can never satisfy it, which is
                               # exactly the case it kept getting wrong.
SHORE_MIN_FRAME_FRAC = 0.98    # how much of a band the screenshot must
                               # actually contain. Measured over 2236 bands in
                               # the corpus, 96.9% are wholly in frame, so this
                               # discards ~3% and removes a failure mode that
                               # the ordinary occlusion gates cannot see.
SHORE_MIN_BAND_PX = 60   # "too few pixels to say anything" floors, not
SHORE_MIN_CORE_PX = 200  # measurements -- deliberately unscaled, as in
                         # _region_ncc and tile_fog_fraction
SHORE_LAND_BGR = (64, 200, 64)     # green wash: fog hiding land
SHORE_WATER_BGR = (230, 160, 40)   # blue wash: fog hiding water. Both are
SHORE_WASH_ALPHA = 0.45            # clear of the two colors already spoken
                                   # for on a composite -- red is a spawn zone
                                   # layer, violet is a ruin marker.
SHORE_NEIGHBOR = {"NW": (-1, 0), "NE": (0, -1), "SE": (1, 0), "SW": (0, 1)}


# ---- joint whole-tile shoreline model -------------------------------------
# The per-edge reader below asks each rim in isolation "is this band brighter
# than the tile's core". That cannot work at a corner, because the two edges
# meeting there share pixels: a real shoreline on one edge raises the other
# edge's band near their shared vertex. It is the one error the fog pairs still
# show (`epic_blood` (8,17), a flat SW rim called land because the NW shoreline
# bled around the west vertex), and no threshold fixes it -- the reading is
# genuinely ambiguous until you decide *both* edges together.
#
# So score whole-tile hypotheses instead. A hypothesis names which of the four
# edges carry a shoreline; it therefore predicts the corners too, and a corner's
# brightness becomes evidence to be explained rather than contamination to be
# trimmed away. Each edge's own answer is then the *margin* between the best
# hypothesis containing it and the best one without -- which makes the three-way
# answer intrinsic rather than bolted on: when the pixels that discriminate an
# edge are hidden, the two sides of that margin predict the same thing, the
# margin collapses, and the edge is simply not called.
#
# The basis is learned offline by tools/learn_shorelines.py beside this
# script; see that file for why nine images rather than sixteen templates.
SHORE_BASIS_K = 40                      # canonical tile grid, K x K in (u, v)
SHORE_BASIS_EDGES = ("NW", "NE", "SE", "SW")
SHORE_BASIS_CORNERS = (("NW", "NE"), ("NW", "SW"),
                       ("NE", "SE"), ("SE", "SW"))   # sharing N, W, E, S
SHORE_BASIS_FILE = "shoreline_basis.npz"
SHORE_MARGIN = 0.001     # mean squared-error advantage, over the pixels where
                         # the two competing hypotheses actually differ, before
                         # an edge is called. Set at the loosest value that
                         # makes no false *land* call under leave-one-out on the
                         # fog pairs; below it the errors climb fast (0.00035
                         # gives 5), above it coverage collapses (0.002 resolves
                         # 80 where this resolves 99).
SHORE_MIN_DISCRIM_PX = 30   # too little of the discriminating region visible to
                            # say anything -- the honest third answer


def shore_canon_patch(gray, keep, origin, u_col, u_row, i, j, drop,
                      k=SHORE_BASIS_K):
    """One tile's water surface resampled onto a canonical k x k grid, as
    (values, visibility). u runs from the NW edge toward SE, v from NE toward
    SW, so a band along any edge is a fixed slice -- which is what lets the
    basis images be shared across board sizes and zooms."""
    n0 = origin + i * u_col + j * u_row + np.float32([0, drop])
    u = (np.arange(k) + 0.5) / k
    U, V = np.meshgrid(u, u, indexing="ij")
    X = (n0[0] + U * u_col[0] + V * u_row[0]).astype(np.float32)
    Y = (n0[1] + U * u_col[1] + V * u_row[1]).astype(np.float32)
    h, w = gray.shape
    if X.min() < 0 or Y.min() < 0 or X.max() >= w or Y.max() >= h:
        return None
    patch = cv2.remap(gray, X, Y, cv2.INTER_LINEAR)
    vis = cv2.remap(keep.astype(np.uint8) * 255, X, Y, cv2.INTER_NEAREST) > 0
    return patch, vis


def shore_canon_patch3(bgr, keep, origin, u_col, u_row, i, j, drop,
                       k=SHORE_BASIS_K):
    """shore_canon_patch, in color. Color is not a refinement here: the same
    template scheme scores 112 in gray and 116 in color under leave-one-out,
    and gray makes two false *land* calls where color makes none."""
    n0 = origin + i * u_col + j * u_row + np.float32([0, drop])
    u = (np.arange(k) + 0.5) / k
    U, V = np.meshgrid(u, u, indexing="ij")
    X = (n0[0] + U * u_col[0] + V * u_row[0]).astype(np.float32)
    Y = (n0[1] + U * u_col[1] + V * u_row[1]).astype(np.float32)
    h, w = bgr.shape[:2]
    if X.min() < 0 or Y.min() < 0 or X.max() >= w or Y.max() >= h:
        return None
    return (cv2.remap(bgr, X, Y, cv2.INTER_LINEAR).astype(np.float32),
            cv2.remap(keep.astype(np.uint8) * 255, X, Y,
                      cv2.INTER_NEAREST) > 0)


def shore_band_region(d, k=SHORE_BASIS_K):
    """The rim band along one edge, in canonical grid coordinates."""
    lo = max(1, int(round(k * SHORE_BAND_LO)))
    hi = max(lo + 1, int(round(k * SHORE_BAND_HI)))
    trim = int(round(k * SHORE_EDGE_TRIM))
    m = np.zeros((k, k), bool)
    if d == "NW":
        m[lo:hi, trim:k - trim] = True
    elif d == "NE":
        m[trim:k - trim, lo:hi] = True
    elif d == "SE":
        m[k - hi:k - lo, trim:k - trim] = True
    else:                                     # SW
        m[trim:k - trim, k - hi:k - lo] = True
    return m


def load_shore_basis(path=None):
    """The learned basis, or None when it has not been built.

    Same working-directory-then-script-directory fallback as polymerge's
    template_path_for, for the same reason: a caller may run this from
    anywhere."""
    p = path
    if p is None:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            SHORE_BASIS_FILE)
        p = _first_existing(SHORE_BASIS_FILE, here)
    if p is None or not os.path.exists(p):
        return None
    z = np.load(p, allow_pickle=False)
    if int(z["K"]) != SHORE_BASIS_K:
        return None
    pack = {"basis": z["basis"].astype(np.float32),
            "delta": z["delta"].astype(np.float32),
            "trained_on": [str(t) for t in z["trained_on"]]}
    if "tpl" in z.files:
        keys = [tuple(k.split("-")) if k != "none" else ()
                for k in (str(x) for x in z["tpl_keys"])]
        pack["templates"] = dict(zip(keys, z["tpl"].astype(np.float32)))
    return pack


def _hypotheses():
    """Every subset of the four edges except the empty one -- a shallow water
    tile always has at least one shoreline (game fact); a tile with none is
    ocean, which is recognized by color and never reaches here."""
    out = []
    for bits in range(1, 16):
        out.append(tuple(d for k, d in enumerate(SHORE_BASIS_EDGES)
                         if bits & (1 << k)))
    return out


SHORE_HYPOTHESES = _hypotheses()


def shore_predict(basis, hyp, fog_dirs=(), delta=None):
    """The tile this hypothesis predicts, in normalized units."""
    pred = basis[0].copy()
    for k, d in enumerate(SHORE_BASIS_EDGES):
        if d in hyp:
            pred += basis[1 + k]
    for c, (a, b) in enumerate(SHORE_BASIS_CORNERS):
        if a in hyp and b in hyp:
            pred += basis[1 + len(SHORE_BASIS_EDGES) + c]
    # A fog neighbor shades the water along that edge slightly differently from
    # land. Measured negligible on three directions and -0.040 on NE, so it is
    # carried as four scalars rather than four images.
    if delta is not None:
        for k, d in enumerate(SHORE_BASIS_EDGES):
            if d in fog_dirs and d not in hyp and delta[k]:
                pred = pred + delta[k] * shore_band_region(d)
    return pred


def _shore_scan_setup(warped_bgr, wmask, u_col, explored, unresolved):
    """Which tiles have a rim worth reading, and the per-pixel masks to read
    them against. read_shorelines and read_shorelines_joint share this setup
    verbatim; only what they do per candidate afterward differs.

    `candidates` is a list of ((i, j), facing) for every explored tile with at
    least one edge facing `unresolved` -- empty when there is nothing to read,
    which the caller turns into an early return before paying for the masks
    below. The masks are full-canvas, so on a board with no fog frontier in
    this shot they would be the whole cost of the phase."""
    candidates = []
    for (i, j) in explored:
        facing = [d for d, (di, dj) in SHORE_NEIGHBOR.items()
                  if (i + di, j + dj) in unresolved]
        if facing:
            candidates.append(((i, j), facing))
    if not candidates:
        return candidates, None, None, None, None, None, None

    H, W = wmask.shape
    gray = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    water, ocean = water_chroma_masks(warped_bgr)
    water &= wmask > 0
    ocean &= wmask > 0
    drop = SHORE_DROP_FRAC * float(np.linalg.norm(u_col))
    return candidates, H, W, gray, water, ocean, drop


def read_shorelines_joint(warped_bgr, wmask, origin, u_col, u_row, explored,
                          unresolved, basis_pack):
    """The joint counterpart of read_shorelines: same contract, but every edge
    of a tile is decided together.

    Returns ({(i, j, d): (verdict, margin)}, {ocean tiles}) -- verdict "land",
    "water" or None, exactly as the per-edge reader, so the caller is unchanged.
    """
    basis, delta = basis_pack["basis"], basis_pack["delta"]
    out, ocean_tiles = {}, {}
    candidates, H, W, gray, water, ocean, drop = _shore_scan_setup(
        warped_bgr, wmask, u_col, explored, unresolved)
    if not candidates:
        return out, ocean_tiles

    k = SHORE_BASIS_K
    core = slice(int(0.35 * k), int(0.65 * k))
    for (i, j), facing in candidates:
        got = shore_canon_patch(gray, water, origin, u_col, u_row, i, j, drop, k)
        if got is None:
            continue
        patch, vis = got
        og = shore_canon_patch(gray, ocean, origin, u_col, u_row, i, j, drop, k)
        n_oc = int(og[1].sum()) if og else 0
        n_wet = int(vis.sum()) + n_oc
        # Same three ocean tests as the per-edge reader, expressed as fractions
        # of the canonical grid rather than template pixels -- the grid covers
        # the whole rhombus, so SHORE_MIN_OCEAN_PX (a count at
        # REFERENCE_TILE_PX) becomes the fraction of a tile it represented.
        oc_floor = SHORE_MIN_OCEAN_PX / (REFERENCE_TILE_PX ** 2 * 0.5)
        if (n_wet and n_oc / float(k * k) >= oc_floor and
                n_oc / n_wet >= SHORE_OCEAN_DOMINANCE and
                n_wet / float(k * k) >= SHORE_MIN_WET_FRAC):
            ocean_tiles[(i, j)] = (n_oc, n_oc / n_wet, n_wet / float(k * k))
            continue
        if float(vis.sum()) / (k * k) < SHORE_TILE_WATER_FRAC:
            continue
        cv_ = patch[core, core][vis[core, core]]
        if cv_.size < 40:
            continue
        obs = patch / float(np.median(cv_))
        # Score every hypothesis over the pixels actually visible.
        preds = {h: shore_predict(basis, h, facing, delta)
                 for h in SHORE_HYPOTHESES}
        err = {h: float(((obs[vis] - p[vis]) ** 2).mean())
               for h, p in preds.items()}
        for d in facing:
            with_d = [h for h in SHORE_HYPOTHESES if d in h]
            without = [h for h in SHORE_HYPOTHESES if d not in h]
            h1 = min(with_d, key=lambda h: err[h])
            h0 = min(without, key=lambda h: err[h])
            # Judge only where the two actually disagree, so the margin means
            # the same thing however much of the tile is hidden.
            diff = np.abs(preds[h1] - preds[h0]) > 0.004
            sel = diff & vis
            if int(sel.sum()) < SHORE_MIN_DISCRIM_PX:
                out[(i, j, d)] = (None, None)
                continue
            e0 = float(((obs[sel] - preds[h0][sel]) ** 2).mean())
            e1 = float(((obs[sel] - preds[h1][sel]) ** 2).mean())
            margin = e0 - e1          # >0 favors a shoreline on d
            if margin >= SHORE_MARGIN:
                out[(i, j, d)] = ("land", margin)
            elif margin <= -SHORE_MARGIN:
                out[(i, j, d)] = ("water", margin)
            else:
                out[(i, j, d)] = (None, margin)
    return out, ocean_tiles


def water_chroma_masks(warped_bgr):
    """(shallow water, ocean) per-pixel masks for one warped source."""
    b, g, r = (warped_bgr[:, :, i].astype(np.float32) for i in range(3))
    bs = np.maximum(b, 1.0)
    gb, rb = g / bs, r / bs
    bright = b > SHORE_MIN_BLUE
    water = ((np.abs(gb - SHORE_WATER_GB) < SHORE_CHROMA_TOL_G) &
             (np.abs(rb - SHORE_WATER_RB) < SHORE_CHROMA_TOL_R) & bright)
    ocean = ((np.abs(gb - SHORE_OCEAN_GB) < SHORE_CHROMA_TOL_G - 0.01) &
             (np.abs(rb - SHORE_OCEAN_RB) < SHORE_CHROMA_TOL_R - 0.03) & bright)
    return water, ocean


SHORE_VETO_MARGIN = 0.0004  # how strongly the templates must contradict the
                            # ratio reader before its verdict is withdrawn.
                            # Swept under leave-one-out: 0.0002, 0.0004 and
                            # 0.0006 all give zero errors of either kind, so
                            # this sits in the middle of a plateau rather than
                            # on a knife edge. At 0.0010 the veto stops catching
                            # the corner case and the false land call returns.
SHORE_ROBUST_MAD = 2.5      # an occluder is a pixel *no* hypothesis explains,
                            # cut at this many MADs above the median residual
SHORE_ROBUST_FLOOR = 0.04   # ...but never tighter than this, so a clean tile
                            # does not start discarding its own texture


def shore_template_margins(warped_bgr, wmask, origin, u_col, u_row, explored,
                           unresolved, templates):
    """Per-edge evidence from the learned color templates, as
    {(i, j, d): margin}, positive favoring a shoreline on that edge.

    Two things make this worth having despite the ratio reader being the more
    accurate of the two overall. It decides all four edges together, so a corner
    shared by two edges is attributed rather than trimmed away -- the one
    failure the ratio reader cannot fix by any threshold. And it decides what is
    occluded *without a color prior*: an occluder is defined as a pixel that no
    hypothesis explains, found from the per-pixel minimum residual across all
    fifteen templates and cut at a MAD-based threshold. That matters because the
    obvious alternative -- keep only water-colored pixels -- throws away a
    median 34% of a shoreline band and sometimes all of it, since a strong
    shoreline leaves the water chroma window on its way to sand.

    The margin is measured only where the two competing hypotheses actually
    differ, so it means the same thing however much of the tile is hidden, and
    collapses toward zero when the deciding pixels are covered."""
    out = {}
    keys = [h for h in templates if h]     # drop "none": that tile is ocean
    if not keys:
        return out
    cand = [((i, j), [d for d, (di, dj) in SHORE_NEIGHBOR.items()
                      if (i + di, j + dj) in unresolved]) for (i, j) in explored]
    cand = [c for c in cand if c[1]]
    if not cand:
        return out
    water, _ = water_chroma_masks(warped_bgr)
    water &= wmask > 0
    drop = SHORE_DROP_FRAC * float(np.linalg.norm(u_col))
    k = SHORE_BASIS_K
    core = slice(int(0.35 * k), int(0.65 * k))
    fin = {h: np.all(np.isfinite(templates[h]), axis=2) for h in keys}
    allfin = np.all(np.stack([fin[h] for h in keys]), axis=0)
    for (i, j), facing in cand:
        gA = shore_canon_patch3(warped_bgr, wmask > 0, origin, u_col, u_row,
                                i, j, drop, k)
        gW = shore_canon_patch3(warped_bgr, water, origin, u_col, u_row,
                                i, j, drop, k)
        if gA is None or gW is None:
            continue
        patch, inframe = gA
        _, wet = gW
        cc = patch[core, core][wet[core, core]]
        if cc.shape[0] < 40:
            continue
        med = np.median(cc, axis=0)
        if np.any(med < 1):
            continue
        obs = patch / med
        rmin = np.stack([np.abs(obs - templates[h]).max(axis=2)
                         for h in keys]).min(axis=0)
        rmin = np.where(allfin & inframe, rmin, np.nan)
        if not np.isfinite(rmin).any():
            continue
        mr = float(np.nanmedian(rmin))
        mad = float(np.nanmedian(np.abs(rmin - mr))) + 1e-9
        use = (allfin & inframe
               & (np.nan_to_num(rmin, nan=1e9)
                  <= max(SHORE_ROBUST_FLOOR, mr + SHORE_ROBUST_MAD * mad)))
        if int(use.sum()) < 60:
            continue
        err = {}
        for h in keys:
            ok = use & fin[h]
            if ok.sum() >= 50:
                err[h] = float(((obs[ok] - templates[h][ok]) ** 2).mean())
        if len(err) < 8:
            continue
        for d in facing:
            wi = [h for h in err if d in h]
            wo = [h for h in err if d not in h]
            if not wi or not wo:
                continue
            h1 = min(wi, key=lambda h: err[h])
            h0 = min(wo, key=lambda h: err[h])
            diff = (fin[h1] & fin[h0] & use
                    & (np.abs(templates[h1] - templates[h0]).max(axis=2) > 0.004))
            if int(diff.sum()) < SHORE_MIN_DISCRIM_PX:
                continue
            out[(i, j, d)] = (
                float(((obs[diff] - templates[h0][diff]) ** 2).mean())
                - float(((obs[diff] - templates[h1][diff]) ** 2).mean()))
    return out


def read_shorelines_hybrid(warped_bgr, wmask, origin, u_col, u_row, explored,
                           unresolved, templates):
    """The ratio reader, with the templates given a veto and nothing else.

    Each method has one thing it does better, measured on the fog pairs under
    leave-one-out. The ratio reader is more accurate overall (115 correct
    against the templates' best zero-error 107) because its per-tile
    normalization adapts to each tile, where a template averaged over boards
    cannot. But it is structurally blind at a corner, and that is its one
    remaining error. The templates decide all four edges at once and so are not.

    So the templates may only *withdraw* a verdict they positively contradict.
    They can turn a call into "not called"; they can never create one the ratio
    reader did not make, nor flip one to the opposite answer. Measured, that
    combination is the only configuration tested that resolves more than either
    method alone -- 116 -- while making **no false call in either direction**.
    """
    reads, oceans = read_shorelines(warped_bgr, wmask, origin, u_col, u_row,
                                    explored, unresolved)
    margins = shore_template_margins(warped_bgr, wmask, origin, u_col, u_row,
                                     explored, unresolved, templates)
    out, vetoed = {}, 0
    for key, (verdict, ratio) in reads.items():
        m = margins.get(key)
        if verdict is not None and m is not None:
            if (m <= -SHORE_VETO_MARGIN if verdict == "land"
                    else m >= SHORE_VETO_MARGIN):
                out[key] = (None, ratio)
                vetoed += 1
                continue
        out[key] = (verdict, ratio)
    return out, oceans, vetoed


def shore_band_poly(origin, u_col, u_row, i, j, d, drop):
    """The rim strip just inside one edge of tile (i,j)'s water surface.

    Built from tile_poly's own corners (0=N, 1=E, 2=S, 3=W) so it agrees with
    the rest of the pipeline by construction, then shifted down by `drop`
    because the lattice marks fog cube tops and water is drawn lower."""
    c = tile_poly(origin, u_col, u_row, i, j, 0.0) + [0, drop]
    p, q, inward = {"NW": (c[0], c[3], u_col),
                    "NE": (c[0], c[1], u_row),
                    "SE": (c[1], c[2], -u_col),
                    "SW": (c[2], c[3], -u_row)}[d]
    along = q - p
    a = p + SHORE_EDGE_TRIM * along
    b = q - SHORE_EDGE_TRIM * along
    return np.float32([a + SHORE_BAND_LO * inward, b + SHORE_BAND_LO * inward,
                       b + SHORE_BAND_HI * inward, a + SHORE_BAND_HI * inward])


def _poly_values(gray, keep, valid, poly, W, H):
    """(gray values inside one polygon that are `keep`, what fraction of the
    in-frame polygon that was, what fraction of the polygon is in frame at
    all), or None.

    The two fractions fail differently and are gated separately. `clean` is how
    much of a *visible* rim is unobstructed water -- a fence or a hull on the
    band. `frame` is how much of the band the photo even contains: a band
    running off the edge of the screenshot is not a poor measurement, it is not
    a measurement."""
    r = poly_mask_bbox(poly, W, H)
    if r is None:
        return None
    m, (x0, y0, x1, y1) = r
    poly_px = int((m > 0).sum())
    if poly_px == 0:
        return None
    inside = (m > 0) & (valid[y0:y1, x0:x1] > 0)
    n_in = int(inside.sum())
    if n_in == 0:
        return None
    sel = inside & keep[y0:y1, x0:x1]
    return (gray[y0:y1, x0:x1][sel], float(sel.sum()) / n_in,
            float(n_in) / poly_px)


def read_shorelines(warped_bgr, wmask, origin, u_col, u_row, explored,
                    unresolved):
    """What each water tile's four rims say about the tiles beyond them.

    Returns ({(i, j, d): (verdict, ratio)}, {ocean tiles}). Each verdict is
    "land" or "water" -- the tile *beyond* that edge -- and an edge that was
    looked at but could not be called is kept as (None, ratio_or_None), which
    is what the debug overlay draws and what keeps this a three-way answer
    rather than a forced choice.

    The ocean tiles are returned rather than read: ocean has water on all four
    cardinal sides by definition, so it resolves its neighbors outright and
    has no rim to read. That inference is the caller's to make.

    `explored` is the set of tiles this source witnessed as explored; a fogged
    tile has no water surface to read. `unresolved` is the set nobody explored,
    i.e. the fog still showing in the finished composite -- the only tiles an
    answer is wanted about. Runs in template space, so every size here is a
    constant regardless of the shot's zoom.

    Reading only the edges that face `unresolved` is what keeps this cheap. The
    merge has already chosen a winner for every other tile, so a reading there
    would be discarded anyway (real terrain beats an inference about it), and a
    water tile sitting well inside explored territory -- the common case on a
    developed board -- is skipped before its statistics are computed at all."""
    out, ocean_tiles = {}, {}
    candidates, H, W, gray, water, ocean, drop = _shore_scan_setup(
        warped_bgr, wmask, u_col, explored, unresolved)
    if not candidates:
        return out, ocean_tiles

    for (i, j), facing in candidates:
        core_poly = tile_poly(origin, u_col, u_row, i, j,
                              SHORE_CORE_INSET) + [0, drop]
        r = poly_mask_bbox(core_poly, W, H)
        if r is None:
            continue
        m, (x0, y0, x1, y1) = r
        inside = m > 0
        area = int(inside.sum())
        if area < SHORE_MIN_CORE_PX:
            continue
        # Ocean resolves its neighbors without any rim reading: it has water on
        # all four cardinal sides by definition, which is also why it carries no
        # shoreline and could never be read the ordinary way.
        n_water = int((inside & water[y0:y1, x0:x1]).sum())
        n_ocean = int((inside & ocean[y0:y1, x0:x1]).sum())
        wet = n_water + n_ocean
        if (n_ocean >= SHORE_MIN_OCEAN_PX and
                wet and n_ocean / wet >= SHORE_OCEAN_DOMINANCE and
                wet / area >= SHORE_MIN_WET_FRAC):
            ocean_tiles[(i, j)] = (n_ocean, n_ocean / wet, wet / area)
            continue
        if float(n_water) / area < SHORE_TILE_WATER_FRAC:
            continue
        core = gray[y0:y1, x0:x1][inside & water[y0:y1, x0:x1]]
        if core.size < SHORE_MIN_CORE_PX:
            continue
        core_med = float(np.median(core))
        if core_med <= 0:
            continue
        for d in facing:
            got = _poly_values(gray, water, wmask,
                               shore_band_poly(origin, u_col, u_row, i, j, d,
                                               drop), W, H)
            # Too little water left in the band means something is standing on
            # it -- a territory-border fence, a boat, a unit, a fish. That is
            # the third answer, not a reason to guess.
            if got is None or got[0].size < SHORE_MIN_BAND_PX:
                out[(i, j, d)] = (None, None)
                continue
            band, clean, frame = got
            # A band clipped by the edge of the photo reads whatever happens to
            # survive the cut, and that sample is biased rather than merely
            # small: the one confirmed false "land" in the corpus is a tile at
            # the frame edge whose band was 78% in frame and read 1.050 where
            # the truth is water. 97% of bands are wholly in frame, so this
            # costs almost nothing.
            if frame < SHORE_MIN_FRAME_FRAC:
                out[(i, j, d)] = (None, None)
                continue
            ratio = float(np.percentile(band, SHORE_BAND_PCT)) / core_med
            if ratio >= SHORE_RATIO_HI:
                out[(i, j, d)] = ("land", ratio)
            elif ratio < SHORE_RATIO_LO and clean >= SHORE_MIN_CLEAN_FRAC:
                out[(i, j, d)] = ("water", ratio)
            else:
                out[(i, j, d)] = (None, ratio)
    return out, ocean_tiles


# ------------------------------------------------------ single-image driver ---
# Everything above is lifted unchanged from polymerge.py, where it ran over
# every source of a finished merge. Below is what replaces that caller: one
# screenshot, anchored on its own.
#
# The one deliberate difference in behavior. polymerge asked about the tiles
# with no winner -- fog in the finished composite, which also sweeps in tiles
# nobody photographed at all. With a single shot the honest set is narrower:
# the tiles this shot itself witnessed as *fog*. A rim facing off the edge of
# the photo is a real reading, but nothing here can show it or corroborate it,
# so it is not claimed. That is also the set tools/fogpair.py has always scored
# against, so the measured numbers in SHORELINES.md describe exactly this.


def load_shot(path, args):
    """One screenshot in the mask flavors the anchor and the sampler need.

    A dict rather than five returns because sky_rebuild has to write back into
    it: everything downstream -- the warp, the tile sampling -- must see the
    same masks the anchor was fitted on."""
    im = cv2.imread(path)
    if im is None:
        raise SystemExit(f"cannot read {os.path.basename(path)} -- it appears "
                         f"invalid")
    S = {"img": im, "badge": None, "halo": None}
    S["valid"] = pm.build_valid_mask(im, [], args.dark_thresh, args.erode_px,
                                     args.top_crop, args.bottom_crop)
    # The paste-time counterpart: darkness never disqualifies a pixel from
    # being drawn, only from being judged. See build_frame_mask.
    S["frame_raw"] = pm.build_frame_mask(im, [], args.top_crop,
                                         args.bottom_crop)
    S["frame"] = S["frame_raw"]
    # Geometry comes off the *un-eroded* mask -- --erode-px eats board edge in
    # the image's own pixels, which would bake a scale error into the fit.
    S["edge"] = pm.build_valid_mask(im, [], args.dark_thresh, 0, args.top_crop,
                                    args.bottom_crop)
    S["hsv"] = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    if not args.no_badge_filter:
        badge, found = pm.detect_capture_badges(im, S["valid"])
        if found:
            print(f"excluding {len(found)} capture-badge blob(s) {found}")
            S["badge"] = badge
            S["valid"] = S["valid"] & ~badge
            S["frame"] = S["frame"] & ~badge
            # The halo, not the badge, comes off the edge mask: a few glowing
            # pixels do not change what color a tile is, but they do change
            # where the silhouette appears to end.
            S["halo"] = pm.badge_halo(badge, found)
            S["edge"] = S["edge"] & ~S["halo"]
    return S


def sky_rebuild_for(S, args):
    """Rebuild the masks with the sunrise-sky test, lazily.

    Handed to anchor_to_template and called only when the ordinary masks yield
    no usable board edge, so a black-sky screenshot never builds these at all.
    See sky_mask for why smoothness-plus-connectivity rather than brightness."""
    def rebuild():
        im = S["img"]
        S["valid"] = pm.build_valid_mask(im, [], args.dark_thresh,
                                         args.erode_px, args.top_crop,
                                         args.bottom_crop, drop_sky=True)
        S["edge"] = pm.build_valid_mask(im, [], args.dark_thresh, 0,
                                        args.top_crop, args.bottom_crop,
                                        drop_sky=True)
        if S["badge"] is not None:
            S["valid"] = S["valid"] & ~S["badge"]
            S["frame"] = S["frame_raw"] & ~S["badge"]
        if S["halo"] is not None:
            S["edge"] = S["edge"] & ~S["halo"]
        return S["edge"], S["valid"]
    return rebuild


def wash_polys(shore_tiles, origin, u_col, u_row, shape):
    """The wash as its own layer: (color image, coverage mask).

    Kept separate from the blend so the same tiles can be painted either on the
    board view or, inverse-warped, back onto the screenshot's own pixels."""
    H, W = shape[:2]
    lay = np.zeros((H, W, 3), np.uint8)
    cov = np.zeros((H, W), np.uint8)
    for (i, j), verdict in sorted(shore_tiles.items()):
        poly = tile_poly(origin, u_col, u_row, i, j, 0.0)
        r = poly_mask_bbox(poly, W, H)
        if r is None:
            continue
        m, (x0, y0, x1, y1) = r
        sel = m > 0
        lay[y0:y1, x0:x1][sel] = (SHORE_LAND_BGR if verdict == "land"
                                  else SHORE_WATER_BGR)
        cov[y0:y1, x0:x1][sel] = 255
    return lay, cov


def blend_wash(base, lay, cov):
    """A copy of base, washed wherever cov says so."""
    out = base.copy()
    sel = cov > 0
    out[sel] = np.clip(
        out[sel].astype(np.float32) * (1 - SHORE_WASH_ALPHA)
        + lay[sel].astype(np.float32) * SHORE_WASH_ALPHA,
        0, 255).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="read a water tile's shoreline to say what the fog beyond "
                    "it hides, from a single screenshot")
    ap.add_argument("image")
    ap.add_argument("-o", "--out",
                    help="write a render with the resolved tiles washed green "
                         "(land) or blue (water). See --frame.")
    ap.add_argument("--frame", choices=("board", "shot"), default="board",
                    help="what the render shows. 'board' is the whole board in "
                         "template space -- the blank all-fog render with this "
                         "shot pasted over it, so board it never photographed "
                         "reads as fog. 'shot' washes the screenshot's own "
                         "pixels instead, which is what a player recognizes.")
    ap.add_argument("--map-size", type=int, choices=list(pm.MAP_SIZE_CHOICES),
                    help="board is this many tiles on a side. Omit it to "
                         "measure it off the screenshot (see detect_map_size); "
                         "that needs the shot to span the whole board in one "
                         "direction, and fails loudly rather than guessing "
                         "when it does not.")
    ap.add_argument("--template",
                    help="override the board render to register against")
    ap.add_argument("--method", choices=("ratio", "joint", "hybrid"),
                    default="ratio",
                    help="how an edge is decided. 'ratio' asks each rim in "
                         "isolation whether it is brighter than the tile's "
                         "core; 'joint' scores whole-tile hypotheses against a "
                         "learned basis and reads each edge off as a margin, "
                         "which is the only way a corner shared by two edges "
                         "can be attributed correctly; 'hybrid' is the ratio "
                         "reader with the templates given a veto over it. The "
                         f"latter two need {SHORE_BASIS_FILE} (build it with "
                         "tools/learn_shorelines.py).")
    ap.add_argument("--debug-dir",
                    help="write shore_<name>.png -- every rim band measured, "
                         "green = shoreline, blue = none, red = looked at and "
                         "could not be called -- and print the near misses")
    ap.add_argument("--top-crop", type=float, default=0.15)
    ap.add_argument("--bottom-crop", type=float, default=0.15)
    ap.add_argument("--dark-thresh", type=int, default=25)
    ap.add_argument("--erode-px", type=int, default=5)
    ap.add_argument("--tile-inset", type=float, default=0.25)
    ap.add_argument("--min-valid-frac", type=float, default=0.5)
    ap.add_argument("--fog-ncc", type=float, default=0.4)
    ap.add_argument("--fog-wedge-ncc", type=float, default=0.80)
    ap.add_argument("--min-edge-support", type=int, default=150)
    ap.add_argument("--min-scale-support", type=int, default=25)
    ap.add_argument("--min-fog-lock", type=int, default=8,
                    help="fail unless this many tiles match the template's fog "
                         "art at NCC >= 0.7. A single shot has no cross-shot "
                         "signal, and a wrong --map-size is the most "
                         "destructive mistake available here: it puts every "
                         "tile out of phase, after which the fog test calls "
                         "the whole board explored.")
    ap.add_argument("--no-badge-filter", action="store_true")
    args = ap.parse_args()

    name = os.path.basename(args.image)
    S = load_shot(args.image, args)
    im = S["img"]

    if args.map_size is None:
        args.map_size = pm.detect_map_size(
            [name], {name: im}, {name: S["edge"]}, {name: S["valid"]},
            {name: S["hsv"]}, args.dark_thresh, args.min_edge_support,
            args.min_scale_support)
    N = args.map_size

    template_path = args.template or pm.template_path_for(N)
    template, _, edge_t = pm.load_template(template_path, args.dark_thresh,
                                           args.erode_px)
    if template is None:
        raise SystemExit(f"cannot read template {template_path}")
    tmpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    print(f"template: {template_path}")
    t_top, t_right, _, t_left, _ = pm.detect_corners(edge_t)
    dir_a, dir_b = pm.BOARD_DIR_A, pm.BOARD_DIR_B
    origin, u_col, u_row = pm.build_lattice(t_top, t_right, t_left, N)
    t_edge_off, _ = pm.edge_lines(pm.board_boundary(edge_t))

    print(f"anchoring {name}:")
    M, _, _, _ = pm.anchor_to_template(
        im, S["edge"], S["valid"], S["hsv"], tmpl_gray, t_edge_off, dir_a,
        dir_b, origin, u_col, u_row, N, args.min_edge_support, name,
        refine=True, min_scale_support=args.min_scale_support,
        sky_rebuild=sky_rebuild_for(S, args))

    Wt, Ht = template.shape[1], template.shape[0]
    warped = cv2.warpAffine(im, M[:2], (Wt, Ht), flags=cv2.INTER_LANCZOS4)
    wmask = cv2.warpAffine(S["valid"], M[:2], (Wt, Ht), flags=cv2.INTER_NEAREST)
    pmask = cv2.warpAffine(S["frame"], M[:2], (Wt, Ht), flags=cv2.INTER_NEAREST)

    explored, fog, lock = set(), set(), 0
    for i in range(N):
        for j in range(N):
            s = pm.sample_tile(
                warped, wmask, tmpl_gray,
                tile_poly(origin, u_col, u_row, i, j, args.tile_inset),
                args.fog_ncc, args.min_valid_frac,
                wedge_poly=pm.tile_top_wedge(origin, u_col, u_row, i, j),
                fog_wedge_ncc=args.fog_wedge_ncc)
            if s is None:
                continue
            if s.get("fog_ncc", 0.0) >= pm.FOG_LOCK_NCC:
                lock += 1
            if s.get("witness"):
                (explored if s["explored"] else fog).add((i, j))

    print(f"\nfog lock (tiles matching the template's fog art at NCC >= "
          f"{pm.FOG_LOCK_NCC}): {lock}")
    if args.min_fog_lock > 0 and lock < args.min_fog_lock:
        raise SystemExit(
            f"this shot did not lock onto the fog artwork ({lock} tiles, need "
            f"{args.min_fog_lock}) -- the tile lattice does not match it.\n"
            f"Almost always --map-size is wrong: a board that is really NxN "
            f"fitted to a template of a different size puts every tile out of "
            f"phase, after which the fog test calls the entire board "
            f"explored.\nIf the board genuinely has no fog left anywhere, pass "
            f"--min-fog-lock 0 to skip this check -- though with no fog there "
            f"is nothing here to answer about either.")

    templates, basis_pack, n_vetoed = None, None, 0
    if args.method == "hybrid":
        pack = load_shore_basis()
        templates = (pack or {}).get("templates")
        if templates is None:
            # Deliberately *not* a fallback to the bare ratio reader. That
            # reader is measured to make one false land call the templates
            # exist to veto, and a wrong answer is worse than no answer -- so
            # with no templates this declines to answer at all.
            raise SystemExit(
                f"{SHORE_BASIS_FILE} not found or has no templates -- build "
                f"it with tools/learn_shorelines.py, or pass --method ratio "
                f"to accept the unvetoed reader")
        print("ratio reader + template veto, trained on "
              + ", ".join(pack["trained_on"]))
    elif args.method == "joint":
        basis_pack = load_shore_basis()
        if basis_pack is None:
            raise SystemExit(f"{SHORE_BASIS_FILE} not found -- build it with "
                             f"tools/learn_shorelines.py, or pass "
                             f"--method ratio")
        print("joint whole-tile scoring, basis trained on "
              + ", ".join(basis_pack["trained_on"]))

    if templates is not None:
        reads, oceans, n_vetoed = read_shorelines_hybrid(
            warped, wmask, origin, u_col, u_row, explored, fog, templates)
    elif basis_pack is not None:
        reads, oceans = read_shorelines_joint(
            warped, wmask, origin, u_col, u_row, explored, fog, basis_pack)
    else:
        reads, oceans = read_shorelines(warped, wmask, origin, u_col, u_row,
                                        explored, fog)

    readings = list(reads.items())
    # An ocean tile has water on all four cardinal sides, so it claims all four
    # without a rim reading -- and it reaches exactly where the rim reader
    # cannot, in open sea where there is no shoreline anywhere to read.
    for (i, j) in oceans:
        readings += [((i, j, d), ("water", None)) for d in SHORE_NEIGHBOR]
    claims = {}                   # (i, j) -> {verdict -> [(d, ratio)]}
    for (i, j, d), (verdict, ratio) in readings:
        if verdict is None:
            continue
        di, dj = SHORE_NEIGHBOR[d]
        key = (i + di, j + dj)
        if key not in fog:        # off the board, explored, or unphotographed
            continue
        claims.setdefault(key, {}).setdefault(verdict, []).append((d, ratio))

    shore_tiles, shore_conflict = {}, []
    for key, per_verdict in claims.items():
        if len(per_verdict) > 1:
            # Two water tiles disagreeing about one fogged neighbor is a
            # defect signal, not noise to average: shoreline <=> land is a
            # biconditional, so both cannot be right. Report it, mark nothing.
            shore_conflict.append((key, per_verdict))
            continue
        shore_tiles[key] = next(iter(per_verdict))

    n_land = sum(1 for v in shore_tiles.values() if v == "land")
    n_water = len(shore_tiles) - n_land
    read_edges = sum(1 for v, _ in reads.values() if v is not None)
    ocean_note = (f", {len(oceans)} ocean tile(s) claiming all four sides"
                  if oceans else "")
    veto_note = (f", {n_vetoed} reading(s) withdrawn by the template veto"
                 if n_vetoed else "")
    print(f"\nshorelines: {len(shore_tiles)} of {len(fog)} fogged tile(s) "
          f"resolved -- {n_land} land, {n_water} water "
          f"({read_edges}/{len(reads)} water-tile edges readable"
          f"{ocean_note}{veto_note})")
    for (i, j), v in sorted(shore_tiles.items()):
        print(f"  tile ({i},{j}): {v}")
    for (i, j), per_verdict in sorted(shore_conflict):
        detail = "; ".join(
            f"{v} from " + ", ".join(
                f"{d} " + ("ocean" if r is None else f"{r:.3f}")
                for d, r in hits)
            for v, hits in sorted(per_verdict.items()))
        print(f"  tile ({i},{j}): CONFLICT, not marked -- {detail}")

    if args.debug_dir:
        os.makedirs(args.debug_dir, exist_ok=True)
        if oceans:
            print("  ocean: " + " ".join(
                f"({i},{j}) px={st[0]} dom={st[1]:.2f} wet={st[2]:.2f}"
                for (i, j), st in sorted(oceans.items())))
        # Near misses: fog tiles a water tile looked at and could not call.
        # This is the list to work from when the reader is missing shorelines a
        # human can see -- it names the tile, the edge, and how far the ratio
        # fell from the bar, which is the difference between "occluded" and
        # "just under".
        missed = {}
        for (i, j, d), (verdict, ratio) in reads.items():
            if verdict is not None:
                continue
            di, dj = SHORE_NEIGHBOR[d]
            key = (i + di, j + dj)
            if key in shore_tiles or key not in fog:
                continue
            missed.setdefault(key, []).append(((i, j), d, ratio))
        if missed:
            print(f"  {len(missed)} fogged tile(s) looked at and not called:")
            for key, hits in sorted(missed.items()):
                detail = ", ".join(
                    f"({i},{j})/{d} " +
                    ("no clean band" if r is None else f"{r:.3f}")
                    for (i, j), d, r in hits)
                print(f"    tile ({key[0]},{key[1]}): {detail}")
        # Outlines, not fills: the whole point of this overlay is to let a
        # human check the band against the shoreline actually under it, and a
        # filled poly hides the evidence it is supposed to show.
        vis = warped.copy()
        drop = SHORE_DROP_FRAC * float(np.linalg.norm(u_col))
        for (i, j, d), (verdict, ratio) in reads.items():
            poly = shore_band_poly(origin, u_col, u_row, i, j, d, drop)
            col = {"land": SHORE_LAND_BGR,
                   "water": SHORE_WATER_BGR}.get(verdict, (0, 0, 255))
            cv2.polylines(vis, [np.round(poly).astype(np.int32)], True, col, 1,
                          cv2.LINE_AA)
        for (i, j) in oceans:
            poly = tile_poly(origin, u_col, u_row, i, j, 0.15) + [0, drop]
            cv2.polylines(vis, [np.round(poly).astype(np.int32)], True,
                          SHORE_WATER_BGR, 2, cv2.LINE_AA)
        cv2.imwrite(os.path.join(args.debug_dir, f"shore_{name}.png"), vis)

    if args.out:
        lay, cov = wash_polys(shore_tiles, origin, u_col, u_row, (Ht, Wt))
        if args.frame == "shot":
            h, w = im.shape[:2]
            Minv = cv2.invertAffineTransform(M[:2])
            lay = cv2.warpAffine(lay, Minv, (w, h), flags=cv2.INTER_NEAREST)
            cov = cv2.warpAffine(cov, Minv, (w, h), flags=cv2.INTER_NEAREST)
            base = im
        else:
            # The blank render underneath, so board this shot never
            # photographed reads as fog rather than as a hole.
            base = template.copy()
            sel = pmask > 0
            base[sel] = warped[sel]
        cv2.imwrite(args.out, blend_wash(base, lay, cov))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
