#!/usr/bin/env python
"""Run polymerge over every set in tests/ and print one table of the numbers
CLAUDE.md tracks as baselines.

This is the project's stand-in for a test suite. It is not part of the shipped
program -- polymerge.py and polybot.py never import it.

Two runs per set, because they answer different questions and --cross-check
returns before the merge path:

  merge run   -> explored union, conflicts, city bars, per-shot fog lock
  cross-check -> worst disagreement between independently anchored shots

Usage:
    .venv/Scripts/python.exe tools/baseline.py                 # all sets
    .venv/Scripts/python.exe tools/baseline.py --only star_change goon_test2
    .venv/Scripts/python.exe tools/baseline.py -o before.json
    .venv/Scripts/python.exe tools/baseline.py --compare before.json

Compare mode is the point of the JSON: it diffs a stored table against a fresh
run and prints only what moved, so an "expected to be inert" refactor can be
proved inert rather than eyeballed.
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLYMERGE = os.path.join(ROOT, "polymerge.py")
TESTS = os.path.join(ROOT, "tests")

# Each set's board size. These are facts about the screenshots, not defaults --
# getting one wrong is the single most destructive mistake available here (see
# CLAUDE.md), so they are stated rather than detected. The detected size is
# checked against this as a side benefit of every run.
SETS = {
    "test_screenshots": 20,
    "test_ss_2": 20,
    "test_ss_3": 20,
    "goon_test2": 18,
    "test_ss_5": 20,
    "test_ss_fruit": 20,
    "archers_test2": 20,
    "beautiful_test3": 20,
    "goon_test": 18,
    "test_ss_elyruins": 20,
    "badland_test": 20,
    "badland_test3": 20,
    "pol_archi_test": 18,
    "star_change": 18,
    "badland_test2": 20,
    "perilous_test": 18,
    "missized_test": 18,
    "basin_treaties": 18,
    "xizauh": 20,
    "u_forest": 18,
    "u_forest2": 18,
    "fogless": 16,
    "replay_ss2": 16,
    "vengir_cultist": 18,
    "scorched_earth": 18,
}

# Sets that cannot run on the default flags. Empty, and kept for the next set
# that needs one: a set needing a flag is a fact about the screenshots, the same
# way SETS records their board size, and burying it in the runner would make the
# table look like a like-for-like comparison when it is not.
#
# fogless needed --min-fog-lock 0 until polymerge learned to merge a board it
# cannot verify the size of, warning instead of refusing whenever the size was
# stated rather than detected. Since SETS states every size, it now runs clean.
# Its 16 was measured off the terrain lattice, not the fog -- both shots span
# 1330.6px with an 80px repeat (harmonics at 160/240/320), giving
# 1330.6/80 - 0.78 = 15.85 -- and confirmed by --overlays grid landing on the
# terrain tile borders at 16 and cutting through them at 20.
SET_FLAGS = {}

# Sets whose cross-check number does not measure what it looks like, for two
# different reasons. Flagged rather than hidden, and never silently excluded.
#
#   fog-repeat: test_ss_fruit, test_ss_elyruins, u_forest2 -- SIFT matching fog
#     against the wrong repeat of itself, on boards that are mostly fog with
#     little shared terrain. See the cross-check caveat in CLAUDE.md.
#     u_forest was on this list and is not any more: its 18.5 turned out to be
#     chrome matching chrome, not fog matching fog, and it reads 0.016 once SIFT
#     is confined to the board (see sift_mask_for in polymerge).
#   not-the-merge's-anchor: fogless, replay_ss2 -- --cross-check returns before the merge
#     path, so it reports the *refined* anchors, and on a board with no fog the
#     merge discards those in favor of each shot's own unrefined edge anchor
#     (see the zero-lock block in polymerge's main). Its 16.6 is the quality of
#     an anchor nothing uses; the anchors the merge does use agree to 0.023
#     tiles. Same shape as star_change's documented case.
CROSS_CHECK_UNRELIABLE = {"test_ss_fruit", "test_ss_elyruins", "u_forest2",
                          "fogless", "replay_ss2"}

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


# Everything in a set directory is treated as an input screenshot unless it is
# named here, so a stray image dropped in silently joins the merge and moves
# that set's numbers with no indication why. Two kinds are excluded by prefix
# rather than by exact name, because both have grown extra files already:
# "merged*" is this program's own regenerable output, and "fogless*" is a
# post-game render of the finished map, kept as a reference alongside the
# shots and emphatically not one to merge.
NOT_A_SHOT = ("merged", "fogless")


def shots_for(set_name):
    """The set's input screenshots -- everything but its own regenerable
    output and any reference image kept alongside it."""
    d = os.path.join(TESTS, set_name)
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith(IMAGE_EXT)
        and not f.lower().startswith(NOT_A_SHOT)
    )


def _run(args, cwd):
    p = subprocess.run([sys.executable, POLYMERGE] + args, cwd=cwd,
                       capture_output=True, text=True, errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _int(pattern, text, default=None):
    m = re.search(pattern, text)
    return int(m.group(1)) if m else default


def _float(pattern, text, default=None):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else default


def measure(set_name, size, outdir, extra=(), in_place=False):
    """Both runs for one set, parsed into a plain dict.

    With `in_place`, the composite and the debug overlays are written back into
    tests/<set>/ as merged.png and debug/ -- the per-set layout CLAUDE.md
    describes, and what the PyCharm run configurations produce. Both are
    regenerable program output, so overwriting them is the intent rather than a
    side effect; the point of doing it here is that a stale debug/ from an
    earlier template is worse than none, since provenance.png and the explored
    masks would show a geometry the current code no longer produces."""
    shots = shots_for(set_name)
    dest = os.path.join(TESTS, set_name)
    out = (os.path.join(dest, "merged.png") if in_place
           else os.path.join(outdir, f"{set_name}.png"))
    common = shots + ["--map-size", str(size)] + SET_FLAGS.get(set_name, [])
    debug = ["--debug-dir", os.path.join(dest, "debug")] if in_place else []

    t0 = time.time()
    rc, merge_log = _run(common + ["--city-bars", "--ruin-vision", "-o", out]
                         + debug + list(extra), ROOT)
    merge_s = time.time() - t0

    xc_rc, xc_log = _run(common + ["--cross-check"] + list(extra), ROOT)

    rec = {
        "size": size,
        "shots": len(shots),
        "ok": rc == 0,
        "cross_check_ok": xc_rc == 0,
        "seconds": round(merge_s, 1),
        "union": _int(r"explored \(union\): (\d+)/", merge_log),
        "tiles": _int(r"explored \(union\): \d+/(\d+)", merge_log),
        "conflicts": _int(r"conflicts: (\d+) tile", merge_log, 0),
        "bars": _int(r"city population bars: (\d+) found", merge_log, 0),
        "worst_cross_check": _float(r"worst disagreement: ([\d.]+) tiles", xc_log),
        "fog_lock": dict(re.findall(r"([\w.\-]+)=(\d+)(?=\s|$)",
                                    _fog_line(merge_log))),
        "dropped": _int(r"DROPPED (\d+)/", merge_log, 0),
        "ruins": _int(r"(\d+) ruin", merge_log, 0),
    }
    if not rec["ok"]:
        rec["error"] = _tail(merge_log)
    if not rec["cross_check_ok"]:
        rec["cross_check_error"] = _tail(xc_log)
    return rec


def _fog_line(log):
    m = re.search(r"^fog lock \(.*?\): (.*)$", log, re.M)
    return m.group(1) if m else ""


def _tail(log, n=3):
    lines = [l for l in log.strip().splitlines() if l.strip()]
    return " | ".join(lines[-n:])[:300]


HEADERS = ("set", "N", "shots", "union", "confl", "bars", "ruins",
           "x-check", "fog lock", "s")


def render(table):
    rows = []
    for name in SETS:
        r = table.get(name)
        if r is None:
            continue
        if not r["ok"]:
            rows.append((name, str(r["size"]), "", "FAILED: " + r.get("error", ""),
                         "", "", "", "", "", str(r["seconds"])))
            continue
        xc = r["worst_cross_check"]
        xc_s = "n/a" if xc is None else f"{xc:.3f}"
        if name in CROSS_CHECK_UNRELIABLE:
            xc_s += "*"
        locks = "/".join(str(v) for _, v in sorted(r["fog_lock"].items()))
        rows.append((name, str(r["size"]), str(r["shots"]),
                     f"{r['union']}/{r['tiles']}", str(r["conflicts"]),
                     str(r["bars"]), str(r.get("ruins", 0)), xc_s, locks,
                     str(r["seconds"])))

    widths = [max(len(HEADERS[i]), max((len(row[i]) for row in rows), default=0))
              for i in range(len(HEADERS))]
    line = "  ".join(h.ljust(w) for h, w in zip(HEADERS, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    print("\n* cross-check does not measure what it looks like on this set "
          "-- see CROSS_CHECK_UNRELIABLE above and CLAUDE.md")


# Fields worth diffing, and how much movement is worth printing. Union,
# conflicts, bars and ruins are exact counts: any change is real. Cross-check is
# a float, but it is deterministic (verified), so the tolerance is for float
# formatting only, not for noise.
#
# `ruins` is the count *after* adjacency clustering -- one entry per actual
# ruin, not per detected diamond cluster -- and it counts what the detector
# found, not what got marked, so it does not move when another player happens to
# explore a ruin tile. It was recorded in the JSON but diffed by nothing for a
# long time, which let two separate ruin-detection regressions sit in the corpus
# unnoticed: every other tracked number here is invariant under ruin detection
# by construction, so nothing else can see one. Both were eventually found by
# eye, on a set whose ruin count was non-zero and therefore looked fine -- so
# read this per set, not as a corpus total.
COMPARE = {"union": 0, "conflicts": 0, "bars": 0, "dropped": 0, "ruins": 0,
           "worst_cross_check": 0.0005}


def compare(old, new):
    moved = False
    for name in SETS:
        a, b = old.get(name), new.get(name)
        if a is None or b is None:
            continue
        diffs = []
        if a.get("ok") != b.get("ok"):
            diffs.append(f"ok {a.get('ok')} -> {b.get('ok')}")
        for field, tol in COMPARE.items():
            x, y = a.get(field), b.get(field)
            if x is None and y is None:
                continue
            if x is None or y is None or abs(x - y) > tol:
                diffs.append(f"{field} {x} -> {y}")
        if a.get("fog_lock") != b.get("fog_lock"):
            diffs.append(f"fog_lock {a.get('fog_lock')} -> {b.get('fog_lock')}")
        if diffs:
            moved = True
            print(f"{name}: " + "; ".join(diffs))
    if not moved:
        print("identical on every set and every tracked field")
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="+", help="run just these sets")
    ap.add_argument("-o", "--out", help="write the table to this JSON file")
    ap.add_argument("--compare", help="diff against a JSON table from an "
                                      "earlier run and print only what moved")
    ap.add_argument("--in-place", action="store_true",
                    help="write each set's composite and debug overlays back "
                         "into tests/<set>/ as merged.png and debug/, instead "
                         "of to a temp dir. Both are regenerable output.")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--extra", nargs="*", default=[],
                    help="extra args passed to every polymerge invocation")
    args = ap.parse_args()

    names = args.only or list(SETS)
    unknown = [n for n in names if n not in SETS]
    if unknown:
        sys.exit(f"unknown set(s): {', '.join(unknown)}")

    table = {}
    with tempfile.TemporaryDirectory() as outdir:
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            futures = {pool.submit(measure, n, SETS[n], outdir, args.extra,
                                   args.in_place): n
                       for n in names}
            for f in concurrent.futures.as_completed(futures):
                n = futures[f]
                table[n] = f.result()
                print(f"  done {n}", file=sys.stderr)

    print()
    render(table)

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(table, fh, indent=1, sort_keys=True)
        print(f"\nwrote {args.out}")

    if args.compare:
        with open(args.compare) as fh:
            old = json.load(fh)
        print(f"\n=== vs {args.compare} ===")
        if compare(old, table):
            sys.exit(1)


if __name__ == "__main__":
    main()
