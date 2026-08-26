#!/usr/bin/env python
"""Learn the shoreline basis images from the fog/fogless pairs.

The model, in canonical tile space (a K x K resample of one tile's water
surface, normalised by that tile's own core brightness):

    predicted(h) = W0 + sum_{d in h} B_d + sum_{corners with both edges in h} C_x

for a hypothesis h, a subset of {NW, NE, SE, SW} naming which edges carry a
shoreline. Nine images in all: one water base, four edge contributions, four
corner interaction terms.

Why this shape rather than 16 templates per configuration: a neighbour is not
binary. It can be fog, explored land, explored water or the board rim, and each
occludes differently -- so the configuration space the detector actually meets
is 6^4, and measured over the fog pairs it is dozens of distinct patterns among
about as many tiles. Learning templates for that is hopeless. Learning five, and then four
corner terms, is not: measured, additive-plus-corner explains 92.7% of the
configuration variance where additive alone explains 79.2%.

The bases are learned from tiles whose neighbours are *explored*, because that
population is rich (hundreds of labelled tiles, all 15 configurations) and
the thing being learned transfers: a shoreline looks the same whether the
neighbour is fog or land, to within 0.001-0.007 against a signal of 0.03-0.09.
The one exception is a genuine fog shading effect, carried as four scalars --
see FOG_DELTA below.

Writes shoreline_basis.npz beside polyshore.py. This is an *optional* asset:
the shipped reader (--shoreline-method ratio) does not use it. It is needed only
by the hybrid and joint methods, which are currently measured inert and behind
respectively -- see the shoreline section of CLAUDE.md.

    .venv/Scripts/python.exe shoreline/tools/learn_shorelines.py
    .venv/Scripts/python.exe shoreline/tools/learn_shorelines.py --exclude epic_blood
"""
import argparse
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
sys.path.insert(0, os.path.join(HERE, "tools"))
from fogpair import PAIR_SIZES, anchor_pair, truth_tiles

K = ps.SHORE_BASIS_K          # canonical grid, shared with the runtime
ORDER = ps.SHORE_BASIS_EDGES  # ("NW", "NE", "SE", "SW")
CORNERS = ps.SHORE_BASIS_CORNERS   # the adjacent edge pairs, N/W/E/S
CORE = slice(14 * K // 40, 26 * K // 40)


def gather(tags):
    """Per-tile (normalised patch, visibility, configuration, fog-facing dirs).

    Read off the *fogless* image so every tile on the board contributes, not
    only the explored ones -- an unexplored tile renders identically there.
    """
    out = []
    fogfacing = []
    for tag in tags:
        size = PAIR_SIZES[tag]
        wf, wc, wm, t, o, uc, ur, _ = anchor_pair(tag, size)
        truth = truth_tiles(wc, wm, o, uc, ur, size)
        drop = ps.SHORE_DROP_FRAC * float(np.linalg.norm(uc))
        H, W = wm.shape
        for img, want_fog in ((wc, False), (wf, True)):
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
            water, ocean = ps.water_chroma_masks(img)
            water &= wm > 0
            ocean &= wm > 0
            fogset = None
            if want_fog:
                tg = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
                fogset = set()
                for i in range(size):
                    for j in range(size):
                        s = pm.sample_tile(
                            wf, wm, tg, pm.tile_poly(o, uc, ur, i, j, 0.25),
                            0.55, 0.5,
                            wedge_poly=pm.tile_top_wedge(o, uc, ur, i, j))
                        if s and s.get("witness") and not s["explored"]:
                            fogset.add((i, j))
            for (i, j), tr in truth.items():
                if tr != "water":
                    continue
                got = ps.shore_canon_patch(gray, water, o, uc, ur, i, j, drop)
                if got is None:
                    continue
                patch, vis = got
                if ocean is not None:
                    og = ps.shore_canon_patch(gray, ocean, o, uc, ur, i, j, drop)
                    if og is not None and og[1].mean() > 0.5:
                        continue          # ocean: handled by chroma, not here
                core = patch[CORE, CORE][vis[CORE, CORE]]
                if core.size < 40:
                    continue
                cfg, ok = [], True
                for d in ORDER:
                    di, dj = ps.SHORE_NEIGHBOUR[d]
                    k = (i + di, j + dj)
                    if not (0 <= k[0] < size and 0 <= k[1] < size):
                        continue          # board rim: no land out there
                    t2 = truth.get(k)
                    if t2 is None:
                        ok = False
                        break
                    if t2 == "land":
                        cfg.append(d)
                if not ok:
                    continue
                rec = (patch / float(np.median(core)), vis, tuple(cfg))
                if want_fog:
                    ff = [d for d in ORDER
                          if (i + ps.SHORE_NEIGHBOUR[d][0],
                              j + ps.SHORE_NEIGHBOUR[d][1]) in fogset]
                    if ff:
                        fogfacing.append(rec + (tuple(ff),))
                else:
                    out.append(rec)
    return out, fogfacing


def gather_colour(tags):
    """Per-tile (normalised BGR patch, visibility, configuration).

    Colour, not gray, and that is load-bearing rather than a refinement: the
    same template scheme scores 112 in gray and 116 in colour under
    leave-one-out, and gray makes two false *land* calls where colour makes
    none. A shoreline is a sandy shift, so its evidence is partly chromatic,
    and collapsing three channels to luminance throws that half away.

    Each channel is normalised by that channel's own median over the tile's
    core, so a shot's exposure and white balance divide out and what remains is
    the tile's own colour structure."""
    out = []
    for tag in tags:
        size = PAIR_SIZES[tag]
        wf, wc, wm, t, o, uc, ur, _ = anchor_pair(tag, size)
        truth = truth_tiles(wc, wm, o, uc, ur, size)
        drop = ps.SHORE_DROP_FRAC * float(np.linalg.norm(uc))
        water, ocean = ps.water_chroma_masks(wc)
        water &= wm > 0
        ocean &= wm > 0
        for (i, j), tr in truth.items():
            if tr != "water":
                continue
            got = ps.shore_canon_patch3(wc, water, o, uc, ur, i, j, drop)
            if got is None:
                continue
            patch, vis = got
            og = ps.shore_canon_patch3(wc, ocean, o, uc, ur, i, j, drop)
            if og is not None and og[1].mean() > 0.5:
                continue                  # ocean: recognised by colour, not here
            core = patch[CORE, CORE][vis[CORE, CORE]]
            if core.shape[0] < 40:
                continue
            med = np.median(core, axis=0)
            if np.any(med < 1):
                continue
            cfg, ok = [], True
            for d in ORDER:
                di, dj = ps.SHORE_NEIGHBOUR[d]
                k = (i + di, j + dj)
                if not (0 <= k[0] < size and 0 <= k[1] < size):
                    continue              # board rim: no land out there
                t2 = truth.get(k)
                if t2 is None:
                    ok = False
                    break
                if t2 == "land":
                    cfg.append(d)
            if ok:
                out.append((patch / med, vis, tuple(cfg)))
    return out


def fit_templates(samples):
    """One colour template per configuration: the masked mean of the tiles that
    actually have it.

    Direct means rather than an additive basis, because measured they are the
    better of the two -- 111 correct against the basis's 98 under leave-one-out.
    Additivity buys lower variance on the thin three-edge configurations and
    pays for it in bias: even with corner terms it leaves 7.3% of the
    configuration variance unexplained, and a direct mean has none of that."""
    per = {}
    for patch, vis, cfg in samples:
        key = tuple(d for d in ORDER if d in cfg)
        per.setdefault(key, [[], []])
        per[key][0].append(patch)
        per[key][1].append(vis)
    keys, mats, counts = [], [], []
    for h in sorted(per):
        ps, vs = per[h]
        acc = np.zeros((K, K, 3))
        cnt = np.zeros((K, K, 1))
        for p_, m_ in zip(ps, vs):
            acc += np.where(m_[:, :, None], p_, 0)
            cnt += m_[:, :, None]
        keys.append("-".join(h) if h else "none")
        mats.append(np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan))
        counts.append(len(ps))
    return keys, np.stack(mats).astype(np.float32), np.array(counts)


def design_row(cfg):
    row = [1.0] + [1.0 if d in cfg else 0.0 for d in ORDER]
    return row + [1.0 if (a in cfg and b in cfg) else 0.0 for a, b in CORNERS]


def fit_basis(samples):
    """Per-pixel least squares over the nine terms, using only visible pixels."""
    n_term = 1 + len(ORDER) + len(CORNERS)
    A = np.array([design_row(c) for _, _, c in samples])       # (n, 9)
    P = np.stack([p for p, _, _ in samples])                   # (n, K, K)
    V = np.stack([v for _, v, _ in samples])                   # (n, K, K)
    basis = np.zeros((n_term, K, K), np.float32)
    used = np.zeros((K, K), np.int32)
    for y in range(K):
        for x in range(K):
            m = V[:, y, x]
            used[y, x] = int(m.sum())
            if m.sum() < n_term * 3:
                continue
            sol, *_ = np.linalg.lstsq(A[m], P[m, y, x], rcond=None)
            basis[:, y, x] = sol
    return basis, used


def fit_fog_delta(fogfacing, basis):
    """One scalar per direction: how much a *fog* neighbour darkens or brightens
    that edge's band when there is no shoreline on it.

    Measured to matter on exactly one direction (NE, -0.040 against a signal of
    0.03-0.09) and to be negligible on the other three, but all four are fitted
    so the asymmetry is carried by data rather than by a special case."""
    delta = np.zeros(len(ORDER), np.float32)
    for di, d in enumerate(ORDER):
        num = []
        for patch, vis, cfg, ff in fogfacing:
            if d in cfg or d not in ff:
                continue                  # want: no shoreline, fog neighbour
            pred = basis[0] + sum(basis[1 + k] for k, dd in enumerate(ORDER)
                                  if dd in cfg)
            for ci, (a, b) in enumerate(CORNERS):
                if a in cfg and b in cfg:
                    pred = pred + basis[1 + len(ORDER) + ci]
            band = ps.shore_band_region(d, K) & vis
            if band.sum() < 25:
                continue
            num.append(float((patch[band] - pred[band]).mean()))
        if num:
            delta[di] = float(np.median(num))
    return delta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", default=None,
                    help="hold this pair out, for leave-one-out scoring")
    ap.add_argument("-o", default=os.path.join(HERE, "shoreline_basis.npz"))
    args = ap.parse_args()

    tags = [t for t in sorted(PAIR_SIZES) if t != args.exclude]
    print(f"learning from: {', '.join(tags)}"
          + (f"   (holding out {args.exclude})" if args.exclude else ""))
    samples, fogfacing = gather(tags)
    from collections import Counter
    cnt = Counter(c for _, _, c in samples)
    print(f"{len(samples)} labelled water tiles, {len(cnt)} configurations, "
          f"{len(fogfacing)} fog-facing tiles")
    basis, used = fit_basis(samples)
    tkeys, tmats, tcounts = fit_templates(gather_colour(tags))
    print(f"{len(tkeys)} direct templates, "
          f"{tcounts.min()}-{tcounts.max()} samples each")
    delta = fit_fog_delta(fogfacing, basis)
    print("fog-neighbour offsets (no shoreline on that edge): "
          + "  ".join(f"{d}={v:+.4f}" for d, v in zip(ORDER, delta)))
    np.savez_compressed(args.o, basis=basis, used=used, delta=delta,
                        tpl_keys=np.array(tkeys), tpl=tmats, tpl_n=tcounts,
                        K=np.int32(K), edges=np.array(ORDER),
                        corners=np.array([f"{a}-{b}" for a, b in CORNERS]),
                        trained_on=np.array(tags))
    print(f"wrote {args.o}  ({os.path.getsize(args.o) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
