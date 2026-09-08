#!/usr/bin/env python
"""Measure Assets/Rainbowflame.png -- the game's own Elyrion ruin-vision sprite
-- against the corpus, so the ruin detector's constants can be derived from the
sprite instead of fitted to screenshots.

Like tools/baseline.py this is not shipped: polymerge.py and polybot.py never
import it. Unlike baseline.py it asserts nothing and gates nothing -- it prints
measurements, and those measurements are what the detector's thresholds get set
from.

Why this exists
---------------
**The rewrite argued for below has shipped.** detect_ruin_vision matches the
sprite now: RUIN_FLAME_TILE_FRAC, RUIN_MATCH_MIN_CORR, RUIN_MATCH_MIN_SUPPORT
and RUIN_MATCH_MIN_FADE are the constants this measures, and ruin_match_maps is
the fit. So read this as the instrument those constants were set with and are
re-derived on, not as a proposal.

What it replaced: the detector decided what a marker was from HSV statistics
fitted to the corpus, on an unsound basis -- mean saturation was a mean over
pixels *already* above a saturation floor, so it described how crisply a marker
was captured rather than what the marker is. That cost u_forest 6 of 8 ruins
and basin_treaties 4 of 5 while both sets still reported a non-zero count and
looked healthy. (The floor was called RUIN_MIN_SAT and no longer exists;
RUIN_NOMINATE_SAT in polymerge is a different thing -- it nominates *where to
search*, and never classifies anything.)

The sprite settles it, because the compositing is exact and invertible:

    C = f*a*S + (1 - f*a)*F

S and a are the sprite's color and alpha, known per pixel from the PNG. F is
the fog behind it, known per pixel because fog is one deterministic render and
the shot is anchored to it -- polymerge fits the shot's illumination onto the
template (fog_illumination) and now writes that gain into anchor.json. So at a
candidate location the single unknown is f, this frame's fade, and it drops out
of a one-parameter least squares fit. What is left is a residual in gray
levels, and a residual does not care how crisply the marker was captured, which
is the entire point.

The project owner confirms the flames move and fade over time but are always
drawn at the same size relative to the tile. Fixed size is what makes this a
matched filter rather than a scale search: in template space there is one
kernel. Movement is absorbed by a small positional search; fade is the fitted
parameter itself.

Usage:
    .venv/Scripts/python.exe tools/ruinsprite.py
    .venv/Scripts/python.exe tools/ruinsprite.py --only u_forest basin_treaties
    .venv/Scripts/python.exe tools/ruinsprite.py --scale-sweep
    .venv/Scripts/python.exe tools/ruinsprite.py --sheet sheet/
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLYMERGE = os.path.join(ROOT, "polymerge.py")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import baseline as bl                                     # noqa: E402
SPRITE = os.path.join(ROOT, "Assets", "Rainbowflame.png")

# The seven sets with an Elyrion player, and their board sizes. Membership is a
# fact about the screenshots, read off the corpus's own ruin counts.
ELYRION = {
    "test_screenshots": 20,
    "test_ss_2": 20,
    "beautiful_test3": 20,
    "test_ss_elyruins": 20,
    "basin_treaties": 18,
    "u_forest": 18,
    "u_forest2": 18,
}

# Sets with no Elyrion player. Every flame-shaped response here is a false
# positive by definition, which is what makes them the negative control.
CONTROLS = {"goon_test": 18, "star_change": 18, "xizauh": 20, "archers_test2": 20}

# A flame's width as a fraction of the tile step -- the one number the matched
# filter rests on. Kept in step with polymerge's RUIN_FLAME_TILE_FRAC, which
# --scale-sweep is what set: median correlation runs 0.689 at 0.16, 0.894 at
# 0.26 and 0.480 at 0.44, a clean single peak, and one scale fits every flame
# across both board sizes. Re-run the sweep before changing it.
FLAME_TILE_FRAC = 0.26


def load_sprite():
    """The sprite as (bgr float, alpha 0..1), cropped to its own alpha extent."""
    im = cv2.imread(SPRITE, cv2.IMREAD_UNCHANGED)
    if im is None or im.shape[2] != 4:
        raise SystemExit("cannot read a 4-channel sprite at %s" % SPRITE)
    a = im[:, :, 3].astype(np.float64) / 255.0
    ys, xs = np.nonzero(a > 0)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return im[y0:y1, x0:x1, :3].astype(np.float64), a[y0:y1, x0:x1]


def kernel_at(sprite_bgr, sprite_a, width_px):
    """The sprite resampled to a given on-board width, as (bgr, alpha)."""
    h, w = sprite_a.shape
    tw = max(3, int(round(width_px)))
    th = max(3, int(round(width_px * h / float(w))))
    return (cv2.resize(sprite_bgr, (tw, th), interpolation=cv2.INTER_AREA),
            cv2.resize(sprite_a, (tw, th), interpolation=cv2.INTER_AREA))


def fit_fade(obs, fog, spr_bgr, spr_a):
    """Least-squares fade f for one placement, and the residual it leaves.

    Per pixel and channel the model is C = F + f * a * (S - F), so with
    D = C - F and K = a * (S - F) this is a one-parameter projection:
    f = <D,K> / <K,K>, residual = RMS(D - f*K) in gray levels.

    Returns (f, residual, corr). f is left unconstrained deliberately: a
    negative f is not noise to be clipped away, it means whatever is there is
    *brighter* than the fog rather than a tint on it, which no flame ever is,
    so it is evidence.
    """
    K = spr_a[:, :, None] * (spr_bgr - fog)
    D = obs - fog
    kk = float((K * K).sum())
    if kk <= 1e-9:
        return 0.0, float("inf"), 0.0
    f = float((D * K).sum() / kk)
    resid = float(np.sqrt(((D - f * K) ** 2).mean()))
    # The scale-free half of the answer, and the one that actually separates.
    # A raw residual cannot: blank fog scores a *better* residual than a real
    # flame, because there is nothing there to model and D is already ~0. corr
    # asks the different question -- of whatever departure from fog is here,
    # how much of it is shaped like this sprite? Fog has no departure (corr ~ 0
    # on noise), an impostor has a large one that is not flame-shaped.
    dn = float(np.sqrt((D * D).sum()))
    corr = 0.0 if dn <= 1e-9 else float((D * K).sum() / (dn * np.sqrt(kk)))
    return f, resid, corr


def predicted_fog(template, gain):
    """The fog this shot would show, per pixel: the template under this shot's
    own illumination.

    Note the slope/offset split in `gain` is not interpretable on its own. The
    template's fog is nearly constant within a channel, so the regression is
    ill-conditioned and returns things like slope 2.11 / offset -287. The
    *prediction* at the operating point is still right, and prediction is the
    only thing this is used for.
    """
    g = np.asarray(gain, np.float64)
    return np.clip(template.astype(np.float64) * g[:, 0] + g[:, 1], 0, 255)


def run_merge(name, size, out_dir):
    """Merge one set into out_dir and return (debug dir, stdout).

    Runs the real CLI rather than importing, for the reason polybot does the
    same: polymerge reads sys.argv and reports every failure via SystemExit.
    """
    # baseline.shots_for, not a local filter: this one excluded "merged.png"
    # alone, so tests/goon_test/fogless.png and tests/archers_test2/fogless.png
    # -- post-game renders of the finished map, kept as references -- were being
    # merged as input shots on two of the four control sets, which baseline
    # explicitly refuses to do. It also missed ".jpeg".
    shots = bl.shots_for(name)
    dbg = os.path.join(out_dir, name)
    os.makedirs(dbg, exist_ok=True)
    cmd = [sys.executable, POLYMERGE] + shots + [
        "--map-size", str(size), "--ruin-vision",
        "-o", os.path.join(dbg, "merged.png"), "--debug-dir", dbg]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("  %s: merge failed\n%s%s" % (name, p.stdout[-600:], p.stderr[-600:]))
        return None, ""
    return dbg, p.stdout


def flame_sites(ruins_vis, warped):
    """Where the shipped detector accepted pixels, from ruins_<name>.png.

    That overlay paints accepted pixels pure red *over* the warped image, which
    is why the warped image had to be written separately -- the overlay has
    destroyed the very colors anything downstream wants to measure. The
    accepted set is still recoverable as "red here, not red in the source". The
    tile outlines the same overlay draws are excluded by shape: those are thin
    and tile-sized, a flame is a compact blob around 20x32.
    """
    red = ((ruins_vis[:, :, 2] > 200) & (ruins_vis[:, :, 1] < 60)
           & (ruins_vis[:, :, 0] < 60))
    red &= ~((warped[:, :, 2] > 200) & (warped[:, :, 1] < 60)
             & (warped[:, :, 0] < 60))
    n, lab, st, cent = cv2.connectedComponentsWithStats(red.astype(np.uint8), 8)
    out = []
    for c in range(1, n):
        w, h = st[c, cv2.CC_STAT_WIDTH], st[c, cv2.CC_STAT_HEIGHT]
        if st[c, cv2.CC_STAT_AREA] < 25 or w > 120 or h > 120:
            continue
        out.append((w, h, int(st[c, cv2.CC_STAT_AREA]),
                    float(cent[c][0]), float(cent[c][1])))
    return out


def corr_map(obs, fog, spr, fog_mean, valid):
    """Per-pixel match of the flame sprite against the departure-from-fog.

    The same statistic best_fit_at computes at one placement, evaluated
    everywhere at once and exactly:

        D = C - F                      what is here that fog does not explain
        K = a * (S - F)                what one flame at full opacity would add
        corr = <D,K> / (|D| |K|)       how much of D is flame-shaped

    <D,K> is a correlation and |D|^2 a box sum, so both are convolutions and
    the whole map costs two passes per channel rather than a fit per position.
    Note this is scale-free in the fade by construction: f cancels out of the
    ratio, which is exactly the property the shipped HSV thresholds lack. The
    fitted fade is recovered separately where it is wanted, as <D,K>/<K,K>.

    Returned maps are indexed by the *center* of the kernel window.
    """
    spr_bgr, spr_a = spr
    kh, kw = spr_a.shape
    # K needs one fog color rather than the per-pixel field, or it stops being
    # a fixed kernel and the whole thing stops being a convolution. The shot's
    # own mean fog is the right constant and costs almost nothing in accuracy:
    # these renders' fog is uniform tile to tile (per-tile mean spans 228.6-230.2
    # at 20x20, std 0.39), so K varies far less across the board than D does.
    # D itself is still computed against the exact per-pixel fog.
    K = spr_a[:, :, None] * (spr_bgr - np.asarray(fog_mean, np.float64))
    # Out-of-frame pixels must be *excluded*, not treated as zero. A warped
    # shot is black beyond its own frame, so D there is -F: an enormous
    # departure from fog that no kernel explains, which drags the correlation
    # down for any flame near the edge of the photo. Measured on
    # basin_treaties (0,9) -- a genuine ruin only 68% in frame -- that alone
    # was the difference between 0.463 and a detection. So every sum below is
    # taken over valid pixels only, including the kernel's own energy, which is
    # what keeps the ratio a correlation rather than a fraction of one.
    v = valid.astype(np.float64)
    D = (obs - fog) * v[:, :, None]
    num = np.zeros(obs.shape[:2], np.float64)
    dsq = np.zeros(obs.shape[:2], np.float64)
    kk = np.zeros(obs.shape[:2], np.float64)
    for c in range(3):
        # filter2D correlates rather than convolves, which is what is wanted
        # here -- do not "fix" it by flipping the kernel.
        num += cv2.filter2D(D[:, :, c], cv2.CV_64F, K[:, :, c],
                            borderType=cv2.BORDER_CONSTANT)
        dsq += cv2.filter2D(D[:, :, c] ** 2, cv2.CV_64F,
                            np.ones((kh, kw), np.float64),
                            borderType=cv2.BORDER_CONSTANT)
        kk += cv2.filter2D(v, cv2.CV_64F, K[:, :, c] ** 2,
                           borderType=cv2.BORDER_CONSTANT)
    # Support: how much of the kernel's own energy actually landed on valid
    # pixels. Masking without this trades one failure for another -- a window
    # with a handful of valid pixels can correlate near-perfectly with whatever
    # those few happen to be, and it does: masking alone put a false peak at
    # 0.931 on goon_test, higher-scoring than most genuine flames. A
    # correlation computed over a sliver is not a weaker measurement, it is a
    # different one, so gate on support rather than trying to discount it.
    kk_full = float((K * K).sum())
    den = np.sqrt(np.maximum(dsq, 1e-9) * np.maximum(kk, 1e-9))
    return num / den, num / np.maximum(kk, 1e-9), kk / max(kk_full, 1e-9)


# What the shipped detector reports per set, as tools/baseline.py tracks it.
# A count going *down* on a set is the regression this whole exercise is about.
#
# These seven numbers happen to be unchanged across the sprite rewrite -- the
# matched filter reproduced the old detector's per-set counts exactly -- so they
# are the current figures as well as the historical ones. Re-read them off
# baseline.py rather than trusting this copy if anything here moves.
KNOWN_RUINS = {
    "test_screenshots": 3, "test_ss_2": 3, "beautiful_test3": 3,
    "test_ss_elyruins": 11, "basin_treaties": 5, "u_forest": 9, "u_forest2": 3,
}


def cluster(tiles):
    """Merge tiles touching in the 8-neighborhood, as cluster_ruin_tiles does.

    Ruins are never adjacent (a placement guarantee), so two detections on
    neighboring tiles are one diamond cluster straddling a tile border rather
    than two ruins. Only after this does a count mean anything.
    """
    todo, out = set(tiles), []
    while todo:
        seed = todo.pop()
        group, stack = {seed}, [seed]
        while stack:
            i, j = stack.pop()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (i + di, j + dj)
                    if n in todo:
                        todo.discard(n)
                        group.add(n)
                        stack.append(n)
        out.append(group)
    return out


def local_maxima(score, allowed, radius):
    """Peaks of `score` inside `allowed`, no two within `radius`.

    A dilation compares each pixel against the best in its neighborhood, so a
    plateau's whole top would qualify; the >= then ties are broken by taking
    the strongest first and suppressing the rest, which is what keeps one flame
    from being reported several times.
    """
    k = 2 * radius + 1
    peak = (score >= cv2.dilate(score, np.ones((k, k), np.uint8))) & allowed
    ys, xs = np.nonzero(peak)
    order = np.argsort(-score[ys, xs])
    out, taken = [], []
    for i in order:
        y, x = int(ys[i]), int(xs[i])
        if any((y - ty) ** 2 + (x - tx) ** 2 < radius * radius for ty, tx in taken):
            continue
        taken.append((y, x))
        out.append((y, x, float(score[y, x])))
    return out


def candidate_sites(warped, fog_mask, min_sat, tile_px):
    """Every saturated blob sitting on this shot's own fog.

    This is the nomination stage a rewritten detector would run: cheap, and
    deliberately far looser than the shipped RUIN_MIN_SAT of 100, because it no
    longer has to discriminate -- it only has to avoid missing a faint flame.
    Everything that separates a flame from a fire sprite happens downstream in
    the fit.

    The blobs found here on a set with no Elyrion player are, by definition,
    false positives, which is what makes them the negative control worth
    measuring against. Random fog is a floor, not an adversary.
    """
    hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
    cand = (hsv[:, :, 1] >= min_sat) & (hsv[:, :, 2] >= 120) & fog_mask
    k = max(3, int(round(tile_px * 0.06)) | 1)
    closed = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_CLOSE,
                              np.ones((k, k), np.uint8))
    n, lab, st, cent = cv2.connectedComponentsWithStats(closed, 8)
    out = []
    for c in range(1, n):
        w, h = st[c, cv2.CC_STAT_WIDTH], st[c, cv2.CC_STAT_HEIGHT]
        area = int(st[c, cv2.CC_STAT_AREA])
        if area < max(12, int(0.004 * tile_px * tile_px)):
            continue
        if w > 2.5 * tile_px or h > 2.5 * tile_px:
            continue
        out.append((w, h, area, float(cent[c][0]), float(cent[c][1])))
    return out


def best_fit_at(obs_img, fog_img, spr, cx, cy, search=6):
    """Best (f, residual, corr, dx, dy) for a flame centered near (cx, cy).

    The flames move, so a thresholded blob's centroid is not the sprite's
    position to the pixel. A small search absorbs that; kept small on purpose,
    so the match cannot wander onto a neighboring flame in the same cluster.
    """
    spr_bgr, spr_a = spr
    kh, kw = spr_a.shape
    H, W = obs_img.shape[:2]
    best = (0.0, float("inf"), -1.0, 0, 0)
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            x0 = int(round(cx - kw / 2.0)) + dx
            y0 = int(round(cy - kh / 2.0)) + dy
            if x0 < 0 or y0 < 0 or x0 + kw > W or y0 + kh > H:
                continue
            f, r, c = fit_fade(obs_img[y0:y0 + kh, x0:x0 + kw],
                               fog_img[y0:y0 + kh, x0:x0 + kw], spr_bgr, spr_a)
            # ranked by corr, not residual: the search is looking for where the
            # sprite *is*, and residual is minimized by finding less of it
            if c > best[2]:
                best = (f, r, c, dx, dy)
    return best


def tile_mask(shape, origin, u_col, u_row, tiles, inset):
    m = np.zeros(shape[:2], np.uint8)
    for i, j in tiles:
        pts = [origin + (i + a) * u_col + (j + b) * u_row
               for a, b in ((inset, inset), (1 - inset, inset),
                            (1 - inset, 1 - inset), (inset, 1 - inset))]
        cv2.fillConvexPoly(m, np.round(np.array(pts)).astype(np.int32), 1)
    return m > 0


def load_template(dbg_template):
    t = cv2.imread(os.path.join(ROOT, "Overlays", dbg_template),
                   cv2.IMREAD_UNCHANGED)
    if t is None:
        return None
    if t.dtype == np.uint16:
        t = (t / 257.0).astype(np.uint8)
    if t.ndim == 3 and t.shape[2] == 4:
        t = t[:, :, :3]
    return t


def measure(name, size, tmp, args, sprite, rows, sheet):
    dbg, log = run_merge(name, size, tmp)
    if dbg is None:
        return
    with open(os.path.join(dbg, "anchor.json")) as fh:
        anc = json.load(fh)
    origin = np.array(anc["origin"])
    u_col = np.array(anc["u_col"])
    u_row = np.array(anc["u_row"])
    tile_px = float(np.linalg.norm(u_col))
    tmpl = load_template(anc["template"])
    if tmpl is None:
        print("  %s: no template %s" % (name, anc["template"]))
        return
    rng = np.random.default_rng(0)
    for shot, meta in sorted(anc["shots"].items()):
        warped = cv2.imread(os.path.join(dbg, "warped_%s.png" % shot))
        vis = cv2.imread(os.path.join(dbg, "ruins_%s.png" % shot))
        if warped is None or vis is None or meta["fog_gain"] is None:
            continue
        fog_img = predicted_fog(tmpl, meta["fog_gain"])
        obs = warped.astype(np.float64)
        accepted = flame_sites(vis, warped)
        fog_tiles = [tuple(t) for t in meta["fog_tiles"]]
        if not fog_tiles:
            continue
        fm = tile_mask(warped.shape, origin, u_col, u_row, fog_tiles, 0.0)

        if args.map:
            spr = kernel_at(sprite[0], sprite[1], args.frac * tile_px)
            fog_mean = fog_img[fm].reshape(-1, 3).mean(0)
            # in-frame: a warped shot is black outside its own photo
            valid = warped.sum(2) > 0
            cmap, fmap, sup = corr_map(obs, fog_img, spr, fog_mean, valid)
            # Peaks only where this shot has fog to draw a marker on, and only
            # where the fit says a *tint* was added (a real flame darkens fog;
            # f <= 0 means whatever is there is brighter, which no flame is).
            ok = (fm & (fmap > 0.05) & (cmap > args.peak_floor)
                  & (sup >= args.min_support))
            peaks = local_maxima(cmap, ok, int(round(0.18 * tile_px)))
            basis_inv = np.linalg.inv(np.stack([u_col, u_row], axis=1))
            for (py, px, c) in peaks:
                ij = basis_inv @ (np.array([px, py]) - origin)
                rows.append(dict(set=name, shot=shot, frac=args.frac,
                                 kind=("peak-ely" if name in ELYRION
                                       else "peak-ctl"),
                                 f=float(fmap[py, px]), resid=0.0, corr=float(c),
                                 w=0, h=0, area=0, cx=float(px), cy=float(py),
                                 sup=float(sup[py, px]),
                                 tile=(int(np.floor(ij[0])), int(np.floor(ij[1]))),
                                 near=bool(any((px - ax) ** 2 + (py - ay) ** 2
                                               < (0.5 * tile_px) ** 2
                                               for (_, _, _, ax, ay) in accepted))))
                if sheet is not None:
                    sheet.append((name, "peak", float(px), float(py),
                                  float(fmap[py, px]), float(c), warped))
            continue
        cands = candidate_sites(warped, fm, args.min_sat, tile_px)

        def was_accepted(cx, cy):
            """Did the shipped detector accept a flame at this candidate?"""
            return any((cx - ax) ** 2 + (cy - ay) ** 2 < (0.35 * tile_px) ** 2
                       for (_, _, _, ax, ay) in accepted)

        fracs = ([args.frac] if not args.scale_sweep
                 else [round(f, 3) for f in np.arange(0.16, 0.44, 0.02)])
        for frac in fracs:
            spr = kernel_at(sprite[0], sprite[1], frac * tile_px)
            src = accepted if args.scale_sweep else cands
            for (w, h, area, cx, cy) in src:
                f, r, c, dx, dy = best_fit_at(obs, fog_img, spr, cx, cy)
                if args.scale_sweep:
                    kind = "flame"
                elif name in ELYRION:
                    kind = "accepted" if was_accepted(cx, cy) else "ely-other"
                else:
                    kind = "impostor"
                rows.append(dict(set=name, shot=shot, frac=frac, kind=kind,
                                 f=f, resid=r, corr=c, w=w, h=h, area=area,
                                 cx=cx, cy=cy))
                if sheet is not None and not args.scale_sweep:
                    sheet.append((name, kind, cx, cy, f, c, warped))

        if args.scale_sweep or not args.controls:
            continue
        spr = kernel_at(sprite[0], sprite[1], args.frac * tile_px)
        kh, kw = spr[1].shape
        ys, xs = np.nonzero(fm)
        if not len(ys):
            continue
        for k in rng.choice(len(ys), min(args.controls, len(ys)), replace=False):
            y0, x0 = int(ys[k]) - kh // 2, int(xs[k]) - kw // 2
            if y0 < 0 or x0 < 0 or y0 + kh > warped.shape[0] or x0 + kw > warped.shape[1]:
                continue
            f, r, c = fit_fade(obs[y0:y0 + kh, x0:x0 + kw],
                               fog_img[y0:y0 + kh, x0:x0 + kw], *spr)
            if np.isfinite(r):
                rows.append(dict(set=name, shot=shot, frac=args.frac, kind="fog",
                                 f=f, resid=r, corr=c, w=0, h=0, area=0,
                                 cx=float(xs[k]), cy=float(ys[k])))

    print("  measured %s" % name)


def q(vals, p):
    return float(np.percentile(vals, p)) if len(vals) else float("nan")


def report_map(rows, args):
    """What the matched filter would actually detect, swept over its threshold.

    The question a detector has to answer is not "do genuine flames score well"
    -- they do -- but "is there a bar that keeps every impostor out while
    keeping the genuine ones in". A set with no Elyrion player cannot contain a
    ruin marker, so every peak on one is a false positive, and the highest of
    them *is* the bar the threshold has to clear.
    """
    ely = [r for r in rows if r["kind"] == "peak-ely"]
    ctl = [r for r in rows if r["kind"] == "peak-ctl"]
    print("\npeaks found: %d on Elyrion sets, %d on sets with no Elyrion player"
          % (len(ely), len(ctl)))
    if ctl:
        top = sorted(ctl, key=lambda r: -r["corr"])[:8]
        print("\nhighest false peaks (these set the bar):")
        for r in top:
            print("  %-17s %-14s corr %.3f  fade %.3f  support %.2f  tile %s"
                  % (r["set"], r["shot"], r["corr"], r["f"], r.get("sup", 1.0),
                     r["tile"]))
    print("\n%8s  %9s  %9s  %11s  %s"
          % ("corr >=", "ely peaks", "ely tiles", "false peaks", "verdict"))
    for thr in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90):
        e = [r for r in ely if r["corr"] >= thr]
        c = [r for r in ctl if r["corr"] >= thr]
        tiles = {(r["set"], r["tile"]) for r in e}
        mark = "clean" if not c else ""
        print("%8.2f  %9d  %9d  %11d  %s" % (thr, len(e), len(tiles), len(c), mark))

    # Per *cluster*, not per peak. A ruin's marker is several diamonds (a game
    # fact, and the one cluster_ruin_tiles already rests on), so the number of
    # flames backing a detection is evidence in its own right -- and it is
    # evidence a lone impostor cannot manufacture, because whatever it is, there
    # is only one of it. This converts a thin per-peak margin into a per-ruin
    # one without lowering the bar on either.
    print("\ncluster rule -- a detection needs `peaks` flames at corr >= thr:")
    print("%8s %6s   %-28s %s" % ("thr", "peaks", "ruins on Elyrion sets",
                                  "false ruins"))
    for thr in (0.50, 0.55, 0.60, 0.65, 0.70):
        for need in (1, 2, 3):
            g = collections.defaultdict(list)
            for r in ely + ctl:
                if r["corr"] >= thr:
                    g[(r["set"], r["kind"])].append(r)
            ng = nb = 0
            for (st, kind), rs in g.items():
                for cl in cluster({r["tile"] for r in rs}):
                    npk = sum(1 for r in rs if r["tile"] in cl)
                    if npk >= need:
                        if kind == "peak-ely":
                            ng += 1
                        else:
                            nb += 1
            print("%8.2f %6d   %-28d %d%s"
                  % (thr, need, ng, nb, "   clean" if nb == 0 else ""))

    by = collections.defaultdict(set)
    for r in ely:
        if r["corr"] >= args.peak_report:
            by[r["set"]].add(r["tile"])
    print("\nat corr >= %.2f, per Elyrion set -- tiles, then ruins after the "
          "never-adjacent merge:" % args.peak_report)
    print("(the shipped detector's count is what tools/baseline.py tracks)")
    total = 0
    for s in sorted(by):
        cl = cluster(by[s])
        total += len(cl)
        known = KNOWN_RUINS.get(s)
        mark = "" if known is None else (
            "  == shipped" if len(cl) == known else "  vs %d shipped" % known)
        print("  %-18s %2d tiles -> %2d ruins%s" % (s, len(by[s]), len(cl), mark))
        print("       %s" % sorted(by[s]))
    print("  %-18s %14d ruins   vs %d shipped"
          % ("TOTAL", total, sum(KNOWN_RUINS.values())))


def report(rows, args):
    if args.map:
        return report_map(rows, args)
    if args.scale_sweep:
        by = collections.defaultdict(list)
        for r in rows:
            if r["kind"] == "flame":
                by[r["frac"]].append(r["corr"])
        # Ranked on corr, not residual. Residual is minimized by explaining
        # *less* of the flame, so it would prefer a kernel too small to be the
        # sprite -- it gets the size wrong in a specific, confident direction.
        print("\nscale sweep -- match quality over genuine flames, by flame "
              "width")
        print("  %6s  %4s  %11s  %8s  %8s"
              % ("frac", "n", "median corr", "p25", "p75"))
        best = None
        for frac in sorted(by):
            med = q(by[frac], 50)
            print("  %6.3f  %4d  %11.3f  %8.3f  %8.3f"
                  % (frac, len(by[frac]), med, q(by[frac], 25), q(by[frac], 75)))
            if best is None or med > best[1]:
                best = (frac, med)
        print("\n  best: frac=%.3f at median corr %.3f" % best)
        return

    pops = collections.OrderedDict((
        ("accepted flames (Elyrion)", [r for r in rows if r["kind"] == "accepted"]),
        ("other candidates (Elyrion)", [r for r in rows if r["kind"] == "ely-other"]),
        ("candidates, no Elyrion", [r for r in rows if r["kind"] == "impostor"]),
        ("random fog", [r for r in rows if r["kind"] == "fog"]),
    ))
    print("\nflame width = %.3f tile steps, nomination S >= %d\n"
          % (args.frac, args.min_sat))
    print("%-27s %5s  %8s %7s %7s  %8s %7s %7s"
          % ("population", "n", "corr p50", "p10", "max", "fade p50", "p10", "p90"))
    for label, pop in pops.items():
        if not pop:
            continue
        cs = [r["corr"] for r in pop]
        fs = [r["f"] for r in pop]
        print("%-27s %5d  %8.3f %7.3f %7.3f  %8.3f %7.3f %7.3f"
              % (label, len(pop), q(cs, 50), q(cs, 10), max(cs),
                 q(fs, 50), q(fs, 10), q(fs, 90)))

    good = pops["accepted flames (Elyrion)"]
    bad = pops["candidates, no Elyrion"]
    if good and bad:
        print("\nseparation on corr (the scale-free score):")
        print("  worst genuine       %.3f" % min(r["corr"] for r in good))
        print("  best impostor       %.3f" % max(r["corr"] for r in bad))
        print("  genuine p10 / impostor p90   %.3f / %.3f"
              % (q([r["corr"] for r in good], 10), q([r["corr"] for r in bad], 90)))
        margin = min(r["corr"] for r in good) - max(r["corr"] for r in bad)
        print("  margin              %+.3f%s"
              % (margin, "   <- categorical" if margin > 0 else "   <- OVERLAP"))

    print("\nper set, accepted flames:")
    by = collections.defaultdict(list)
    for r in rows:
        if r["kind"] in ("accepted", "impostor", "ely-other"):
            by[(r["set"], r["kind"])].append(r)
    for (name, kind) in sorted(by):
        pop = by[(name, kind)]
        cs = [r["corr"] for r in pop]
        fs = [r["f"] for r in pop]
        print("  %-18s %-10s %3d  corr %6.3f [%6.3f-%6.3f]  fade %5.2f"
              % (name, kind, len(pop), q(cs, 50), min(cs), max(cs), q(fs, 50)))

    # The impostors CLAUDE.md names by tile, so they can be found in the noise.
    worst = sorted(bad, key=lambda r: -r["corr"])[:5] if bad else []
    if worst:
        print("\nhighest-scoring impostors (set, shot, corr, fade, size):")
        for r in worst:
            print("  %-16s %-14s corr %.3f  fade %6.3f  %dx%d"
                  % (r["set"], r["shot"], r["corr"], r["f"], r["w"], r["h"]))


def write_sheet(sheet, path):
    """A contact sheet of every measured flame, at 4x with its numbers.

    Both past ruin regressions were found by eye and by nothing else, so a
    count is not evidence the detector works. This is the artifact to actually
    look at.
    """
    os.makedirs(path, exist_ok=True)
    per = collections.defaultdict(list)
    for (name, kind, cx, cy, f, c, warped) in sheet:
        per["%s_%s" % (name, kind)].append((kind, cx, cy, f, c, warped))
    for name, items in sorted(per.items()):
        tiles = []
        for (kind, cx, cy, f, c, warped) in items:
            x0, y0 = int(cx) - 28, int(cy) - 34
            x1, y1 = x0 + 56, y0 + 68
            if x0 < 0 or y0 < 0 or x1 > warped.shape[1] or y1 > warped.shape[0]:
                continue
            crop = cv2.resize(warped[y0:y1, x0:x1], None, fx=4, fy=4,
                              interpolation=cv2.INTER_NEAREST)
            cv2.putText(crop, "f=%.2f c=%.2f" % (f, c), (4, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
            tiles.append(crop)
        if not tiles:
            continue
        cols = 6
        rows_ = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
        h, w = tiles[0].shape[:2]
        sheet_img = np.zeros((len(rows_) * h, cols * w, 3), np.uint8)
        for ri, row in enumerate(rows_):
            for ci, t in enumerate(row):
                sheet_img[ri * h:(ri + 1) * h, ci * w:(ci + 1) * w] = t
        cv2.imwrite(os.path.join(path, "%s.png" % name), sheet_img)
        print("  sheet %s: %d flames" % (name, len(tiles)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--scale-sweep", action="store_true",
                    help="measure the flame's tile fraction instead of assuming it")
    ap.add_argument("--frac", type=float, default=FLAME_TILE_FRAC)
    ap.add_argument("--map", action="store_true",
                    help="score the whole fog region as a matched filter and "
                         "report what a detector built on it would find")
    ap.add_argument("--min-support", type=float, default=0.75,
                    help="fraction of the sprite that must land on in-frame "
                         "pixels for a match to count as measured at all")
    ap.add_argument("--peak-floor", type=float, default=0.45,
                    help="lowest corr worth recording a peak for")
    ap.add_argument("--peak-report", type=float, default=0.70,
                    help="threshold the per-set tile listing is read at")
    ap.add_argument("--min-sat", type=int, default=60,
                    help="nomination saturation floor; the shipped detector "
                         "uses 100 and has to discriminate with it")
    ap.add_argument("--controls", type=int, default=300,
                    help="random fog locations per shot, as negative controls")
    ap.add_argument("--sheet", help="write a visual contact sheet here")
    ap.add_argument("--keep", help="keep merge output in this directory")
    args = ap.parse_args()

    sprite = load_sprite()
    print("sprite %s: %dx%d, alpha %.2f-%.2f"
          % (os.path.relpath(SPRITE, ROOT), sprite[1].shape[1],
             sprite[1].shape[0], sprite[1].min(), sprite[1].max()))

    sets = dict(ELYRION)
    sets.update(CONTROLS)
    if args.only:
        sets = {k: v for k, v in sets.items() if k in args.only}
    if not sets:
        raise SystemExit("no sets selected")

    tmp = args.keep or tempfile.mkdtemp(prefix="ruinsprite_")
    os.makedirs(tmp, exist_ok=True)
    rows = []
    sheet = [] if args.sheet else None
    for name in sorted(sets):
        measure(name, sets[name], tmp, args, sprite, rows, sheet)
    if not rows:
        raise SystemExit("no measurements -- did any merge succeed?")
    report(rows, args)
    if sheet:
        write_sheet(sheet, args.sheet)


if __name__ == "__main__":
    main()
