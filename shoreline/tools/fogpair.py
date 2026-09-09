#!/usr/bin/env python
"""Score the shoreline reader against real ground truth, from fog/fogless pairs.

Each pair in shoreline/fog_pairs/ is the same camera on the same turn,
once with fog and once without. That is what makes it ground truth rather
than another proxy: anchoring the *fogged* image (which has fog to lock onto, and all four
board edges) yields a transform that is equally valid for its fogless partner,
because the two are pixel-aligned. So for every tile we get both what the
detector can see and what is actually there.

This is the only harness that scores the population the reader is actually
applied to -- tiles the shot itself sees as fog. The older measurements scored
edges whose neighbor was *explored*, which is a different population and is
how a false call once survived every other number recorded for it.

Not shipped: nothing imports it.

    .venv/Scripts/python.exe shoreline/tools/fogpair.py
"""
import os
import sys

import cv2
import numpy as np

# shoreline/, then the repo root: polyshore for the reader, polymerge for
# the anchoring and tile-sampling primitives it is built on.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import polymerge as pm
import polyshore as ps

PAIRS = os.path.join(HERE, "fog_pairs")
DARK = 25

# Each pair's board size. Stated rather than detected, for the reason
# baseline.py states them: a wrong size is the most destructive mistake
# available here. Every pair does detect correctly, so a disagreement would be
# a real signal rather than a nuisance.
PAIR_SIZES = {"bright_monsoon": 20, "living_bay": 16, "epic_blood": 18,
              "ocean_warrior": 18, "spaghetti": 20, "mil_goon": 18}

# The replay view has UI chrome top (the turn timeline) and bottom (the button
# row); neither is board and both would otherwise join the silhouette.
TOP_CROP, BOTTOM_CROP = 0.16, 0.10


def _mask(img, top_crop=TOP_CROP, bottom_crop=BOTTOM_CROP):
    h = img.shape[0]
    m = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > DARK).astype(np.uint8) * 255
    m[:int(h * top_crop)] = 0
    m[int(h * (1 - bottom_crop)):] = 0
    return m


def anchor_pair(tag, size):
    """(warped fog, warped fogless, warped mask, template, origin, u_col,
    u_row, anchor source)."""
    fog = cv2.imread(os.path.join(PAIRS, f"{tag}_fog.png"))
    clr = cv2.imread(os.path.join(PAIRS, f"{tag}_fogless.png"))
    if fog is None or clr is None:
        raise SystemExit("missing one of the pair")
    if fog.shape != clr.shape:
        raise SystemExit(f"pair differs in size: {fog.shape} vs {clr.shape}")

    t, _, edge_t = pm.load_template(pm.template_path_for(size), DARK, 0)
    top, right, bottom, left, _ = pm.detect_corners(edge_t)
    origin, u_col, u_row = pm.build_lattice(top, right, left, size)
    dir_a, dir_b = pm.BOARD_DIR_A, pm.BOARD_DIR_B
    t_off, _ = pm.edge_lines(pm.board_boundary(edge_t))

    mask = _mask(fog)
    M, src, _, _ = pm.anchor_to_template(
        fog, mask, mask, cv2.cvtColor(fog, cv2.COLOR_BGR2HSV),
        cv2.cvtColor(t, cv2.COLOR_BGR2GRAY), t_off, dir_a, dir_b,
        origin, u_col, u_row, size, 150, f"{tag}_fog", refine=True)

    wt, ht = t.shape[1], t.shape[0]
    return (cv2.warpAffine(fog, M[:2], (wt, ht), flags=cv2.INTER_LANCZOS4),
            cv2.warpAffine(clr, M[:2], (wt, ht), flags=cv2.INTER_LANCZOS4),
            cv2.warpAffine(mask, M[:2], (wt, ht), flags=cv2.INTER_NEAREST),
            t, origin, u_col, u_row, src)


def truth_tiles(warped_clear, wmask, origin, u_col, u_row, n):
    """Each tile's real terrain from the fogless view: 'water' | 'land' | None.

    Read on the same dropped rhombus the shoreline reader uses, since the
    lattice marks fog cube tops and real terrain is drawn below them. Tiles
    that are neither clearly water nor clearly land are left unlabeled rather
    than guessed -- an ambiguous truth would score the detector on noise."""
    H, W = wmask.shape
    drop = ps.SHORE_DROP_FRAC * float(np.linalg.norm(u_col))
    water, ocean = ps.water_chroma_masks(warped_clear)
    water &= wmask > 0
    ocean &= wmask > 0
    out = {}
    for i in range(n):
        for j in range(n):
            poly = pm.tile_poly(origin, u_col, u_row, i, j, 0.40) + [0, drop]
            r = pm.poly_mask_bbox(poly, W, H)
            if r is None:
                continue
            m, (x0, y0, x1, y1) = r
            ins = m > 0
            area = int(ins.sum())
            if area < 200:
                continue
            wet = (float((ins & water[y0:y1, x0:x1]).sum()) +
                   float((ins & ocean[y0:y1, x0:x1]).sum())) / area
            if wet >= 0.50:
                out[(i, j)] = "water"
            elif wet <= 0.10:
                out[(i, j)] = "land"
    return out


def score(tag, size, basis_pack=None, method="ratio"):
    """(correct, wrong, resolved, addressable, wrong detail, uncalled truth)."""
    wf, wc, wm, t, o, uc, ur, _ = anchor_pair(tag, size)
    truth = truth_tiles(wc, wm, o, uc, ur, size)
    tg = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    fog, expl = set(), set()
    for i in range(size):
        for j in range(size):
            s = pm.sample_tile(wf, wm, tg, pm.tile_poly(o, uc, ur, i, j, 0.25),
                               0.55, 0.5,
                               wedge_poly=pm.tile_top_wedge(o, uc, ur, i, j))
            if not s or not s.get("witness"):
                continue
            (expl if s["explored"] else fog).add((i, j))

    if basis_pack is None:
        reads, oceans = ps.read_shorelines(wf, wm, o, uc, ur, expl, fog)
    elif method == "hybrid":
        reads, oceans, _ = ps.read_shorelines_hybrid(
            wf, wm, o, uc, ur, expl, fog, basis_pack["templates"])
    else:
        reads, oceans = ps.read_shorelines_joint(wf, wm, o, uc, ur, expl, fog,
                                                basis_pack)
    claims, uncalled = {}, []
    for (i, j, d), (verdict, ratio) in reads.items():
        di, dj = ps.SHORE_NEIGHBOR[d]
        k = (i + di, j + dj)
        if k not in fog:
            continue
        if verdict is None:
            uncalled.append((k, ratio, truth.get(k)))
        else:
            claims.setdefault(k, set()).add(verdict)
    for (i, j) in oceans:
        for d, (di, dj) in ps.SHORE_NEIGHBOR.items():
            k = (i + di, j + dj)
            if k in fog:
                claims.setdefault(k, set()).add("water")

    ok = bad = 0
    detail = []
    for k, verdicts in claims.items():
        if len(verdicts) > 1:            # conflict: marked nothing
            continue
        v = next(iter(verdicts))
        tr = truth.get(k)
        if tr is None:
            continue
        if v == tr:
            ok += 1
        else:
            bad += 1
            detail.append((k, v, tr))
    # Fog tiles that *could* be answered: adjacent to an explored tile that is
    # really water. Ocean counts, since the ocean rule reaches them too --
    # without it the denominator excludes tiles the reader does resolve and
    # coverage comes out above 100%.
    addressable = {k for k in fog for d, (di, dj) in ps.SHORE_NEIGHBOR.items()
                   if (k[0] - di, k[1] - dj) in expl
                   and truth.get((k[0] - di, k[1] - dj)) == "water"}
    addressable |= {k for (i, j) in oceans
                    for (di, dj) in ps.SHORE_NEIGHBOR.values()
                    for k in [(i + di, j + dj)] if k in fog}
    return ok, bad, len(claims), len(addressable), detail, uncalled


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--method",
                    choices=("ratio", "joint", "hybrid", "both"),
                    default="hybrid")
    ap.add_argument("--loo", action="store_true",
                    help="joint only: re-learn the basis with each pair held "
                         "out, so no pair is scored against its own training "
                         "data")
    args = ap.parse_args()
    if args.method == "both":
        for m in ("ratio", "hybrid"):
            print(f"===== {m} =====")
            run(m, args.loo)
            print()
        return
    run(args.method, args.loo)


def _basis_for(tag, loo):
    if not loo:
        return ps.load_shore_basis()
    import subprocess, tempfile
    out = os.path.join(tempfile.gettempdir(), f"basis_wo_{tag}.npz")
    subprocess.run([sys.executable, os.path.join(HERE, "tools",
                                                 "learn_shorelines.py"),
                    "--exclude", tag, "-o", out],
                   capture_output=True, text=True)
    return ps.load_shore_basis(out)


def run(method, loo=False):
    tot_ok = tot_bad = 0
    missed = {"water": 0, "land": 0, None: 0}
    print(f"{'pair':18s} {'size':8s} {'correct':>8s} {'wrong':>6s} "
          f"{'resolved':>9s} {'coverage':>9s}")
    for tag, size in sorted(PAIR_SIZES.items()):
        pack = None
        if method in ("joint", "hybrid"):
            pack = _basis_for(tag, loo)
            if pack is None:
                print(f"{tag:18s} SKIPPED -- no basis; run tools/learn_shorelines.py")
                continue
        try:
            ok, bad, res, addr, detail, uncalled = score(tag, size, pack, method)
        except SystemExit as e:
            print(f"{tag:18s} SKIPPED -- {e}")
            continue
        tot_ok += ok
        tot_bad += bad
        for _, _, tr in uncalled:
            missed[tr] = missed.get(tr, 0) + 1
        print(f"{tag:18s} {str(size) + 'x' + str(size):8s} {ok:8d} {bad:6d} "
              f"{res:9d} {res / max(addr, 1):8.0%}")
        for k, v, tr in detail:
            print(f"    WRONG {k}: said {v}, truth {tr}")
    n = tot_ok + tot_bad
    print(f"\noverall {tot_ok}/{n} = {tot_ok / max(n, 1):.1%} correct on real "
          f"ground truth")
    print(f"uncalled edges facing fog, by what was really there: "
          f"water {missed.get('water', 0)}, land {missed.get('land', 0)}, "
          f"unlabeled {missed.get(None, 0)}")


if __name__ == "__main__":
    main()
