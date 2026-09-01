#!/usr/bin/env python
"""Anchor-first population-bar probe, for measurement.

Not shipped code -- polymerge.py and polybot.py never import it, the same way
they never import tools/baseline.py.

**The design this settled has since shipped**: polymerge.py's
detect_population_bars, _bar_at, _bar_mode and _bar_edges are the authoritative
implementation, and this harness deliberately keeps its own copy so an
experiment can change the algorithm without touching the merge. Expect the two
to drift; when they matter to each other, re-derive from polymerge. What this
still earns its place for is the measurement modes the merge has no reason to
carry -- the near-miss sheet (candidates just under the accept bar, the only
view onto false negatives) and --crops for labeling.

The idea is the project owner's: a bar is *always* centered on its city tile's
south vertex, and the merge already knows every south vertex exactly. So there
is nothing to search for. Go to the vertex, look at the fixed region a bar would
have to occupy, and ask whether it looks like one.

That turns detection from a search into a hypothesis test with three outcomes
per tile -- no bar, small bar, capped bar -- and removes every threshold the
current detector needs in order to *find* candidates: no connected components,
no height window, no aspect or solidity test, no grouping, no even-pitch test.

Three signals, in order of how much they discriminate:

  1. the bar's own silhouette -- a rising step along its top, a falling step
     along its bottom, and both stopping at one of two legal half-widths;
  2. the **name plate**, always present when a bar is, at a known offset above;
  3. the **differential** -- every shot that sees a tile sees its terrain, but
     only the owner's shot sees the bar. This is the one that separates a bar
     from the fruit, blossom and roof pairs that survive everything else.

Usage:
    .venv/Scripts/python.exe tools/barprobe.py                    # all sets
    .venv/Scripts/python.exe tools/barprobe.py --only vengir_cultist
    .venv/Scripts/python.exe tools/barprobe.py --raw           # no differential
    .venv/Scripts/python.exe tools/barprobe.py --only fogless --crops out/
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import baseline as bl                                     # noqa: E402

# **The band is fixed, not searched.** A bar sits at one place relative to its
# tile's south vertex, so these are the rows it can occupy -- not a tolerance to
# widen. Measured over bars the project owner confirmed: the top edge lands at
# -0.06..-0.01 tile widths from the vertex and the bottom at +0.09..+0.15, so
# the bar straddles the vertex with about a sixth of a tile below it.
#
# Leaving these open is what made an earlier version fire 209 times across the
# corpus: the name plate sits directly above the bar and is also a bright
# horizontal rectangle, so an unconstrained search returns the *plate's* two
# edges instead -- readable in the output as a bottom edge above the vertex,
# which no bar can have.
TOP_BAND = (-0.090, 0.020)
BOT_BAND = (0.070, 0.170)

# **A bar is one of two widths, not a free measurement.** Confirmed with the
# project owner and measured against a tile-unit ruler: the small (2-segment)
# bar spans 0.965 tile widths and the capped one 1.44, a clean 3:2, with nothing
# between. In REFERENCE px that is ~87 and ~129, a little under the ~84-90/~135
# the component-bbox figures in CLAUDE.md record, because an edge-to-edge
# measure sits inside the antialiased fringe a bbox includes.
BAR_HALVES = (0.482, 0.720)

EDGE_MIN = 18.0               # gray levels across a row
END_MARGIN = 0.06             # how far past an end to require absence
END_INSET = 0.04              # ignore this much at each end when scoring the
                              # edges themselves -- the caps are rounded, so the
                              # steps genuinely fade there
SEARCH_UP, SEARCH_DN = 0.68, 0.26     # window, in tile widths -- SEARCH_UP
                                      # must cover PLATE_BAND, or the plate
                                      # test silently sees only a sliver of it
HALF_WIN = 0.95
MIN_EDGE_COLS = 0.30          # of the narrow width, before a row pair counts
SCORE_MIN = 0.34              # accept a hypothesis at or above this. Low,
                              # because BAR_MODE below is what carries the
                              # discrimination -- at 0.55 the corpus loses 13
                              # real bars that the project owner confirmed.

# **The bar's own color, as a corroborator at a known place -- not as a way to
# find anything.** The distinction matters: a color *fill* score fails badly
# here (see edge_rows), because "bright and desaturated" is fog, snow and sand.
# Asking "is the modal color inside this already-located rectangle the color a
# bar is painted" is a different and much easier question, the same way
# RUIN_NOMINATE_SAT is safe where a saturation classifier is not.
#
# Measured over 31 confirmed bars and 13 confirmed non-bars: the modal color of
# a real bar is **228** off-white (222-234) or a saturated blue, while every
# white false positive -- ice, snow, UI panels -- reads **252**. The bar is
# simply not painted pure white, and that ~24 gray levels is the whole margin.
BAR_MODE_V = (198, 240)       # off-white body
BAR_MODE_S = 60               # ...must be this desaturated
BAR_BLUE_S = 180              # a filled segment is vividly blue; a washed-out
                              # blue at S=128 is pol_archi_test's false positive
# **The color box is fixed per tile, and independent of the silhouette.** The
# *small* bar's footprint is a subset of the capped one, so a box comfortably
# inside it is inside the bar whichever length this bar turns out to be -- which
# means the color test needs nothing from the edge test, and the two are
# genuinely separate pieces of evidence rather than a pipeline.
#
# Sampling the *detected* rectangle instead couples them and costs accuracy: it
# inherits whatever the width snap got wrong, and it runs off the frame on tiles
# near a shot's edge, where out-of-frame black then wins the mode outright.
#
# Measured over 55 labeled tiles, this box on its own keeps 32 of 35 real bars
# and rejects 16 of 20 non-bars. Two of its three misses are out-of-frame in
# that shot and the tile is detected in another; the four it admits are pale
# water and ice, which is exactly what the edge test throws out.
#
# The box comes in two *presets*, one per legal bar length, chosen by the edge
# test's discrete short/long verdict. That keeps the geometry preset rather than
# measured -- there is no free-form rectangle to get wrong -- while using the
# whole bar when it is the long one, which matters because the small box is only
# a few rows tall and its mode is correspondingly thin.
BOX_ROWS = (0.010, 0.115)     # below the vertex, in tile widths
BOX_HALVES = (0.40, 0.62)     # inside the small bar's 0.482 and the capped
                              # one's 0.720 respectively
BOX_DARK = 12                 # a channel max at or below this is out of frame.
                              # Not zero: JPEG leaves the black beyond a shot's
                              # edge merely near-black, and at badland_test3
                              # (9,15) exactly 2 pixels of 520 are true zero
                              # against 43 under 12 -- dropping only the former
                              # leaves the mode at (0,0,0) and loses a real bar,
                              # dropping the latter gives (222,228,228).

# The plate: always present when a bar is, and directly above it. Same trick as
# _board_component's chrome filter -- ask for a long horizontal run in a world
# where every board edge, tile border, territory dash and terrain facet runs at
# dir_a (30.7 deg) or dir_b (149 deg).
PLATE_BAND = (-0.62, -0.09)
PLATE_MIN = 0.0               # of a tile width, as a contiguous run.
                              # **Disabled**: measured over eight confirmed bars
                              # this reads 0.14-0.58, so no threshold keeps them
                              # all, and at 0.45 it rejected seven of the eight.
                              # The plate is certainly there -- the measurement
                              # is what is wrong, most likely because only the
                              # rising edge is counted and a translucent plate
                              # over dark terrain steps the other way at its
                              # lower boundary. Left in to report, not to gate.

# The differential. A margin rather than a ratio, because a terrain feature
# scores about the same in every shot that sees it while a bar scores near zero
# in every shot but one.
DIFF_MARGIN = 0.18


def edge_rows(bgr):
    """Signed horizontal-edge strength per pixel.

    A bar is a bright oblong on darker terrain, so going down the image its top
    is a *rising* step and its bottom a *falling* one. That signed pair is the
    signature, and it needs no color at all -- which matters, because the
    obvious color-fill score does not work: `light` is "bright and
    desaturated", which is precisely what fog, snow and pale sand are. Measured,
    it called 225 tiles bar-like across three sets, most of them open board.
    """
    g = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
                         .astype(np.float32), (3, 3), 0)
    sy = cv2.filter2D(g, cv2.CV_32F, np.float32([[-1], [0], [1]]))
    sx = cv2.filter2D(g, cv2.CV_32F, np.float32([[-1, 0, 1]]))
    sy[np.abs(sy) < 2.0 * np.abs(sx)] = 0.0
    return sy


def _band_rows(lo, hi, tile, vy, ry0, rows):
    a = max(0, int(round(lo * tile + (vy - ry0))))
    b = min(rows - 1, int(round(hi * tile + (vy - ry0))))
    return a, b


def probe(sy, origin, u_col, u_row, i, j):
    """Test the bar hypotheses at tile (i, j)'s south vertex, both polarities.

    **A bar is not always brighter than what is behind it.** The obvious
    reading of the silhouette -- a rising luminance step along the top and a
    falling one along the bottom -- holds for the off-white and blue bars, and
    fails outright for a red one: pure red converts to a gray of about 76 while
    grass sits near 130, so a red bar is a *darker* oblong on brighter ground
    and both its steps run the other way. scorched_earth's Icalus at (15,6) is
    six red segments with no white at all, and a bright-on-dark test finds no
    row pair there whatsoever.

    So try both polarities and keep the better. What the bar actually
    guarantees is a step *in* and a step *out* at fixed rows -- not which way
    the luminance happens to go.
    """
    best_r = None
    for flip in (False, True):
        r = _probe_polarity(sy, origin, u_col, u_row, i, j, flip)
        if r and (best_r is None or r["score"] > best_r["score"]):
            best_r = r
    return best_r


def _probe_polarity(sy, origin, u_col, u_row, i, j, flip):
    tile = float(np.linalg.norm(u_col))
    vx, vy = origin + (i + 1) * u_col + (j + 1) * u_row
    ry0 = int(round(vy - SEARCH_UP * tile))
    ry1 = int(round(vy + SEARCH_DN * tile))
    rx0 = int(round(vx - HALF_WIN * tile))
    rx1 = int(round(vx + HALF_WIN * tile))
    if (ry0 < 0 or rx0 < 0 or ry1 >= sy.shape[0] or rx1 >= sy.shape[1]
            or ry1 - ry0 < 6):
        return None
    win = sy[ry0:ry1 + 1, rx0:rx1 + 1]
    rows, w = win.shape
    pos, neg = win >= EDGE_MIN, win <= -EDGE_MIN
    if flip:
        pos, neg = neg, pos
    npos, nneg = pos.sum(axis=1), neg.sum(axis=1)

    t0, t1 = _band_rows(*TOP_BAND, tile, vy, ry0, rows)
    b0, b1 = _band_rows(*BOT_BAND, tile, vy, ry0, rows)
    floor = MIN_EDGE_COLS * 2 * BAR_HALVES[0] * tile
    best = None
    for yt in range(t0, t1 + 1):
        if npos[yt] < floor:
            continue
        for yb in range(max(b0, yt + 2), b1 + 1):
            if nneg[yb] < floor:
                continue
            sc = min(npos[yt], nneg[yb])
            if best is None or sc > best[0]:
                best = (sc, yt, yb)
    if best is None:
        return None
    _sc, yt, yb = best

    tol = max(1, int(round(0.02 * tile)))

    def rowband(m, y):
        return m[max(0, y - tol):min(rows, y + tol + 1)].any(axis=0)

    top_col, bot_col = rowband(pos, yt), rowband(neg, yb)
    both = top_col & bot_col
    cx = vx - rx0

    def cols(a, b):
        lo, hi = int(round(cx + a * tile)), int(round(cx + b * tile))
        return slice(max(0, min(lo, w)), max(0, min(hi, w)))

    scored = []
    for h in BAR_HALVES:
        # Score each side on its own and keep the better one. A bar is centered,
        # so the two sides measure the same object, and one clean side settles
        # it -- which is what makes a unit standing on an end harmless.
        #
        # Coverage and the end test must come from the *same* side, or the two
        # halves of the evidence contradict each other: Xasna's left reaches the
        # capped width while its right is buried under a unit, so taking the
        # best coverage from the left and the cleanest end from the right scores
        # the small hypothesis highest and calls a capped bar small.
        for sgn in (-1, 1):
            a, b = sorted((0.0, sgn * (h - END_INSET)))
            inner = cols(a, b)
            if inner.stop - inner.start < 4:
                continue
            t_f = float(top_col[inner].mean())
            b_f = float(bot_col[inner].mean())
            e0, e1 = sorted((sgn * h, sgn * (h + END_MARGIN)))
            o = both[cols(e0, e1)]
            end = 1.0 - float(o.mean()) if o.size else 0.0
            scored.append((min(t_f, b_f) * end, h, t_f, b_f, end))
    if not scored:
        return None
    score, half, top_f, bot_f, end_f = max(scored)

    # Plate corroboration, at its own fixed offset above the vertex.
    p0, p1 = _band_rows(*PLATE_BAND, tile, vy, ry0, rows)
    run = 0
    for y in range(p0, p1 + 1):
        cur = 0
        for v in pos[y]:
            cur = cur + 1 if v else 0
            run = max(run, cur)
    return {
        "tile": (i, j), "score": score, "half": half, "span": 2 * half,
        "top_f": top_f, "bot_f": bot_f, "end_f": end_f,
        "plate": run / tile,
        "top": (ry0 + yt - vy) / tile, "bot": (ry0 + yb - vy) / tile,
        "px": (int(round(vx - half * tile)), ry0 + yt,
               int(round(2 * half * tile)), yb - yt),
        "dark": flip,
    }


def modal_color(bgr, origin, u_col, u_row, i, j, half=BOX_HALVES[0]):
    """Modal BGR in the fixed box at tile (i, j), and what color it is.

    Returns (bgr, is_a_bar_color, is_red).
    """
    tile = float(np.linalg.norm(u_col))
    vx, vy = origin + (i + 1) * u_col + (j + 1) * u_row
    y0 = int(round(vy + BOX_ROWS[0] * tile))
    y1 = int(round(vy + BOX_ROWS[1] * tile))
    x0 = int(round(vx - half * tile))
    x1 = int(round(vx + half * tile))
    if (x1 <= x0 or y1 <= y0 or y0 < 0 or x0 < 0
            or y1 >= bgr.shape[0] or x1 >= bgr.shape[1]):
        return None, False, False
    patch = bgr[y0:y1 + 1, x0:x1 + 1].reshape(-1, 3)
    # Out-of-frame pixels carry no color, and in a warped shot they are black
    # -- so leaving them in lets them win the mode outright. Both bars this
    # probe missed against the project owner's labels (test_ss_3 (10,9),
    # badland_test3 (15,16)) scored well on the silhouette and were then
    # rejected for a modal color of (0,0,0). The mask taxonomy excludes these
    # pixels everywhere else; inside the merge `valid` does it properly.
    patch = patch[patch.max(axis=1) > BOX_DARK]
    if len(patch) < 20:
        return None, False, False
    q = patch // 6 * 6
    vals, counts = np.unique(q, axis=0, return_counts=True)
    b, g, r = (int(v) for v in vals[counts.argmax()])
    H, S, V = (int(z) for z in cv2.cvtColor(
        np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0, 0])
    red = (H <= 8 or H >= 172) and S >= 150 and V >= 150
    ok = ((S <= BAR_MODE_S and BAR_MODE_V[0] <= V <= BAR_MODE_V[1])
          or (100 <= H <= 118 and S >= BAR_BLUE_S and V >= 150)
          or red)
    return (b, g, r), ok, red


def probe_shot(bgr, origin, u_col, u_row, n):
    """Every interior tile whose south vertex scores as a bar.

    Rim tiles are skipped outright: cities never sit on row or column 0 or n-1,
    so only (n-2)^2 of n^2 tiles are looked at -- about 80% at either size.
    """
    sy = edge_rows(bgr)
    tile = float(np.linalg.norm(u_col))
    out = {}
    for i in range(1, n - 1):
        for j in range(1, n - 1):
            # **Color takes part in the selection, it does not just filter
            # afterwards.** Two polarities are on offer, and picking the
            # better-scoring one first and checking its color second throws
            # away a good candidate whenever a wrong-polarity reading of the
            # same tile happens to score higher.
            #
            # And the dark polarity is scoped to *red*, which is the only
            # reason it exists: red converts to a low gray, so a red bar is
            # darker than the ground. White and blue bars are bright and the
            # ordinary polarity finds them. Left unscoped it admits four false
            # positives corpus-wide, every one of them water or ice -- where a
            # dark oblong on bright ground occurs naturally -- and it cannot be
            # told from a blue bar by color, because water reads S=186 against
            # a real blue bar's 187. Scoped, it keeps scorched_earth's Icalus
            # and costs nothing: beautiful_test3 (12,11), the one real bar the
            # dark polarity added, is found in that set's other shot anyway.
            # Color first, because it is independent of the edge test and
            # far cheaper -- one patch and a mode, against a row-pair search
            # over the whole band. Order is otherwise free: neither test needs
            # anything the other produces.
            # Color on the *small* preset box first: it is independent of the
            # edge test, far cheaper -- one patch and a mode against a row-pair
            # search over the whole band -- and it sits inside the bar whichever
            # length this one is, so it can reject a tile before any of the
            # geometry runs.
            mode, ok, red = modal_color(bgr, origin, u_col, u_row, i, j)
            if not ok:
                continue
            best = None
            for dark in (False, True):
                # The dark polarity exists only because red converts to a low
                # gray, so a red bar is darker than the ground it sits on.
                # White and blue bars are bright and the ordinary polarity
                # finds them. Unscoped it admits four false positives corpus
                # wide, every one water or ice, and color cannot separate
                # those from a blue bar: water reads S=186 against a real blue
                # bar's 187.
                if dark and not red:
                    continue
                m = _probe_polarity(sy, origin, u_col, u_row, i, j, dark)
                if m is None:
                    continue
                if best is None or m["score"] > best["score"]:
                    best = m
            if best:
                # Now that the edge test has said short or long, re-read the
                # color from the matching preset box. Nothing is measured --
                # one of two fixed rectangles is chosen -- and the wider one
                # gives the mode several times as many pixels to work with.
                wide = BOX_HALVES[BAR_HALVES.index(best["half"])]
                m2, ok2, _ = modal_color(bgr, origin, u_col, u_row, i, j, wide)
                best["mode"], best["mode_ok"] = (m2, ok2) if m2 else (mode, ok)
                if not best["mode_ok"]:
                    continue
                out[(i, j)] = best
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--crops")
    ap.add_argument("--raw", action="store_true",
                    help="skip the differential, to size what it removes")
    args = ap.parse_args()

    names = args.only or list(bl.SETS)
    kept, cut = [], {"unseen": 0, "score": 0, "color": 0, "plate": 0,
                     "diff": 0}
    for name in names:
        d = os.path.join(ROOT, "tests", name, "debug")
        if not os.path.exists(os.path.join(d, "anchor.json")):
            print(f"{name}: no debug/anchor.json -- run baseline --in-place")
            continue
        a = json.load(open(os.path.join(d, "anchor.json")))
        origin = np.array(a["origin"])
        u_col, u_row = np.array(a["u_col"]), np.array(a["u_row"])
        n = a["map_size"]
        seen = {s: {tuple(t) for t in v.get("explored_tiles", [])}
                for s, v in a["shots"].items()}
        per, imgs = {}, {}
        for shot in [os.path.basename(p) for p in bl.shots_for(name)]:
            p = os.path.join(d, f"warped_{shot}.png")
            if not os.path.exists(p):
                continue
            imgs[shot] = cv2.imread(p)
            per[shot] = probe_shot(imgs[shot], origin, u_col, u_row, n)
        for shot, tiles in per.items():
            for t, m in tiles.items():
                # A bar only ever sits on a city this shot can see. The merge
                # already answers that -- `samples` holds it, and `valid`
                # (build_valid_mask) is what makes the answer trustworthy, since
                # it drops UI chrome via the crop bands along with out-of-frame
                # and too-dark pixels.
                #
                # This is not a tidy-up: the probe's whole discriminator is
                # "nothing on an isometric board is horizontal", which is true
                # of terrain and false of the game's own HUD. u_forest2's "Game
                # Stats" and "End Turn" score 0.56 and 0.67 as bars, and neither
                # tile is witnessed by any shot.
                # Counted, not enforced. The gate was added because the
                # probe's discriminator -- "nothing on an isometric board is
                # horizontal" -- is true of terrain and false of the game's own
                # screen-aligned HUD, and u_forest2's "Game Stats" and "End
                # Turn" scored 0.56 and 0.67 as bars. But the *color* test
                # rejects both on its own (modal (48,48,48), a dark UI panel),
                # so the gate is redundant for that job -- and it is not free:
                # `--min-valid-frac` asks whether enough of a tile is
                # classifiable, which is a different question from whether the
                # bar is visible, and it costs two real bars that everything
                # else accepts cleanly. scorched_earth's Tofgru at (2,3) scores
                # 0.73 with a modal (228,228,228), and badland_test3 (15,16)
                # likewise; both sit on tiles their own shot does not witness.
                if t not in seen.get(shot, ()):
                    cut["unseen"] += 1
                if m["score"] < SCORE_MIN:
                    cut["score"] += 1
                    continue
                if not m.get("mode_ok"):
                    cut["color"] += 1
                    continue
                # The plate test is reported, not enforced. Measured on eight
                # bars the project owner confirmed it reads 0.14-0.58 tile
                # widths, overlapping whatever a non-bar reads, so as built it
                # rejects real bars -- see the note by PLATE_MIN.
                if PLATE_MIN and m["plate"] < PLATE_MIN:
                    cut["plate"] += 1
                    continue
                # The differential: among the shots that witnessed this tile as
                # explored, a bar should stand clear. Terrain scores about the
                # same in all of them.
                rivals = [per[o][t]["score"] if t in per[o] else 0.0
                          for o in per if o != shot and t in seen.get(o, ())]
                # Reject only when *every* witnessing shot scores high, not when
                # the best rival does. A player often contributes two shots, so
                # a real bar legitimately appears in several of them: test_ss_3
                # is four shots from two players, and comparing against the best
                # rival threw away 8 of its 10 detections, because each player's
                # bar shows in both of that player's shots. Terrain is the case
                # where *all* the witnesses show it, not merely more than one.
                if not args.raw and rivals and \
                        min(rivals) >= m["score"] - DIFF_MARGIN:
                    cut["diff"] += 1
                    continue
                m = dict(m, set=name, shot=shot)
                kept.append(m)
                if args.crops:
                    os.makedirs(args.crops, exist_ok=True)
                    x, y, ww, hh = m["px"]
                    pad = int(0.5 * float(np.linalg.norm(u_col)))
                    c = imgs[shot][max(0, y - pad):y + hh + pad,
                                   max(0, x - pad):x + ww + pad].copy()
                    cv2.imwrite(os.path.join(
                        args.crops, f"{name}_{shot}_{t[0]}_{t[1]}.png"),
                        cv2.resize(c, None, fx=4, fy=4,
                                   interpolation=cv2.INTER_NEAREST))

    print(f"{len(kept)} bars   (rejected: {cut['unseen']} unwitnessed, "
          f"{cut['score']} on score, {cut['color']} on color, "
          f"{cut['diff']} on the differential)")
    print(f"{'set':17s} {'shot':12s} {'tile':9s} {'span':>6s} {'score':>6s} "
          f"{'top':>5s} {'bot':>5s} {'end':>5s} {'plate':>6s}")
    by = {}
    for r in sorted(kept, key=lambda r: (r["set"], r["tile"])):
        by[r["set"]] = by.get(r["set"], 0) + 1
        print(f"{r['set']:17s} {r['shot']:12s} {str(r['tile']):9s} "
              f"{r['span']:6.3f} {r['score']:6.2f} {r['top_f']:5.2f} "
              f"{r['bot_f']:5.2f} {r['end_f']:5.2f} {r['plate']:6.2f}")
    print("\nper set:", ", ".join(f"{k} {v}" for k, v in sorted(by.items())))


if __name__ == "__main__":
    main()
