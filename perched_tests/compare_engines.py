"""
Experiment F -- the same inputs on five engines.

  stock   EPA SWMM 5.2.4 (v5.2.4 tag)
  mhfix   5.2.4 + OpenSWMM Build 5.3.0 Modified Horton MaxInfil fix
  legacy  OpenSWMM legacy engine 5.3.0 (HydroCouple/openswmm.engine, develop, src/legacy)
  swmm6   OpenSWMM 6.0.0-alpha.3 new engine (same commit, src/engine)
  perched swmm524-perched (only for SOIL2 inputs; identical to stock otherwise)

Season inputs from runs_B (non-perched variants) and the eight-inch storm inputs from runs_D.
Scoring is the same code as run_season.py / storm8_test.py.
"""
import os, json, glob, subprocess, shutil, datetime as dt, time
from multiprocessing import Pool
import swmmlab as S
import run_season as R

# Engine paths come from the environment (see BUILD.md); defaults are the build machine's.
OSW = os.environ.get("OPENSWMM_ALPHA3_BIN", "/home/claude/openswmm_engine/build-native/bin/Release")
ENGINES = {
    "stock":  S.ENGINE,
    "mhfix":  S.MHFIX_ENGINE,
    "legacy": f"{OSW}/openswmm-legacy",
    "swmm6":  f"{OSW}/openswmm",
}
OUT = "runs_F"
SEASON_VARIANTS = ["H0", "H1", "Hz", "H0s", "HS", "HSz", "Hmax", "L0", "L1", "L2", "L2s", "Lz"]
STORM8 = ["horton_cap3", "mh_cap3_stock", "mh_nocap", "horton_nocap", "lid_bucket"]

def version(rpt):
    for line in open(rpt, errors="replace"):
        if "VERSION" in line:
            return line.strip()
    return "?"

def score_season(season, out):
    O = S.Out(out)
    d = S.runoff_depth_series(O)
    st = R.SEASONS[season]
    end = st + dt.timedelta(days=R.SPIN_D + R.EVAL_D + 2)
    ss = R.storms(st)
    t_first = st + dt.timedelta(seconds=O.step)
    idx = lambda t: int(round((t - t_first).total_seconds() / O.step))
    ev0 = st + dt.timedelta(days=R.SPIN_D)
    rows = []
    for i, (t0, P, hrs) in enumerate(ss):
        t1 = ss[i + 1][0] if i + 1 < len(ss) else end
        rows.append((P, sum(d[max(idx(t0), 0): idx(t1)]), t0 >= ev0))
    ev = [r for r in rows if r[2]]
    big = [r for r in ev if r[0] >= 0.75]
    cap = lambda a: round(100 * (1 - sum(x[1] for x in a) / sum(x[0] for x in a)), 1)
    return cap(ev), cap(big)

def job(args):
    eng, kind, key, inp = args
    base = os.path.join(OUT, f"{key}__{eng}")
    t0 = time.time()
    p = subprocess.run([ENGINES[eng], inp, base + ".rpt", base + ".out"], capture_output=True, text=True, timeout=900)
    secs = round(time.time() - t0, 2)
    r = dict(engine=eng, kind=kind, key=key, rc=p.returncode, secs=secs)
    try:
        rc = S.runoff_continuity(base + ".rpt")
        r.update(version=version(base + ".rpt"), runoff=rc.get("Surface Runoff"), infil=rc.get("Infiltration Loss"),
                 final_storage=rc.get("Final Storage"), cont=rc.get("Continuity Error (%)"),
                 precip=rc.get("Total Precipitation"))
        if kind == "season":
            r["all"], r["big"] = score_season(key.split("_")[1], base + ".out")
    except Exception as e:
        r["error"] = str(e)[:200]
    if os.path.exists(base + ".out"):
        os.remove(base + ".out")
    return r

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    jobs = []
    for v in SEASON_VARIANTS:
        for season in ("dormant", "growing"):
            for eng in ENGINES:
                jobs.append((eng, "season", f"{v}_{season}", f"runs_B/{v}_{season}.inp"))
    for k in STORM8:
        for eng in ENGINES:
            jobs.append((eng, "storm8", k, f"runs_D/{k}.inp"))
    with Pool(os.cpu_count()) as pool:
        res = pool.map(job, jobs)
    json.dump(res, open("engines_results.json", "w"), indent=1)
    bad = [r for r in res if r.get("error") or r["rc"]]
    print("runs", len(res), "problems", len(bad))
    for b in bad[:6]:
        print("  ", b)
    print(f"\n{'season setup':16}" + "".join(f"{e:>16}" for e in ENGINES))
    for v in SEASON_VARIANTS:
        cells = []
        for eng in ENGINES:
            dd = next(r for r in res if r["key"] == f"{v}_dormant" and r["engine"] == eng)
            gg = next(r for r in res if r["key"] == f"{v}_growing" and r["engine"] == eng)
            cells.append(f"{dd.get('big', float('nan')):6.1f}/{gg.get('big', float('nan')):<6.1f}")
        print(f"{v:16}" + "".join(f"{c:>16}" for c in cells))
    print(f"\n{'8-in storm':16}" + "".join(f"{e:>16}" for e in ENGINES))
    for k in STORM8:
        cells = []
        for eng in ENGINES:
            r = next(x for x in res if x["key"] == k and x["engine"] == eng)
            cells.append(f"inf {r.get('infil', 0):.2f} ro {r.get('runoff', 0):.2f}")
        print(f"{k:16}" + "".join(f"{c:>16}" for c in cells))
    print("\nversions:", sorted({r.get("version", "?") for r in res}))
    print("mean secs per season run:", {e: round(sum(r["secs"] for r in res if r["engine"] == e and r["kind"] == "season") /
                                          len([r for r in res if r["engine"] == e and r["kind"] == "season"]), 2) for e in ENGINES})
