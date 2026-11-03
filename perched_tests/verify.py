"""
verify.py -- rerun the study and check every stored number against a fresh run.

    python3 verify.py                    # everything; OpenSWMM group needs OPENSWMM_BIN
    python3 verify.py --skip-openswmm    # leave the OpenSWMM group out on purpose
    python3 verify.py --only season,storm8

Engines come from the environment (see BUILD.md):
    SWMM_ENGINE          EPA SWMM 5.2.4 runswmm
    SWMM_MHFIX_ENGINE    5.2.4 + Modified Horton MaxInfil fix
    SWMM_PERCHED_ENGINE  swmm524-perched (van-genuchten branch)
    OPENSWMM_BIN         folder with openswmm and openswmm-legacy (swmm6_rel @ 13746831)

Every group has an expected case count in tests_manifest.json.  A group passes
only if it executed exactly that many cases and every case passed.  A missing
engine, a missing reference file, an engine that exits non-zero or writes no
output, a count mismatch, or a number that moved all count as failures.
Exit status: 0 when every group required by the arguments passed, 1 otherwise.
All runs go to a fresh folder (default verify_runs/, deleted at start), so a
stale output from an earlier run can never be read as a pass.
"""
import argparse, datetime as dt, filecmp, json, os, shutil, subprocess, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import swmmlab as S
import run_season as R
import run_recovery as RA
import storm8_test as T8
import vg_ablation as AB
import vg_checks as VC

MANIFEST = json.load(open("tests_manifest.json"))
TOL = MANIFEST["tolerance"]

def ablation_variants():
    for k, (d, v) in AB.CASES.items():
        S.VARIANTS.setdefault(k, (d, v))
ablation_variants()            # also runs in spawned workers, which re-import this module

def has_extension(v):
    """True if the variant uses a swmm524-perched feature (SOIL2, VG or STRUCT lines)."""
    return bool(v.get("soil2") or v.get("vg") or v.get("struct"))

def close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol

# ---------------------------------------------------------------- season / ablation
def season_job(args):
    vkey, season, workdir = args
    ablation_variants()
    R.RUNS = workdir
    try:
        r = R.case((vkey, season))
    except Exception as e:                       # engine missing, no .out, unreadable .rpt
        return dict(variant=vkey, season=season, error=f"{type(e).__name__}: {str(e)[:200]}")
    r.pop("storms", None)
    return r

def check_season_row(ref, new):
    if "error" in new:
        return False, new["error"]
    bad = []
    for k in ("eval_capture_pct", "big_capture_pct"):
        if not close(ref[k], new[k], TOL["capture_pct"]):
            bad.append(f"{k} {ref[k]} -> {new[k]}")
    for k in ("eval_runoff", "big_runoff", "rpt_runoff"):
        if not close(ref[k], new[k], TOL["depth_in"]):
            bad.append(f"{k} {ref[k]} -> {new[k]}")
    if not close(new["rpt_runoff"], new["out_runoff"], TOL["rpt_vs_out_in"]):
        bad.append(f".rpt runoff {new['rpt_runoff']} vs .out runoff {new['out_runoff']}")
    if new["cont_err"] is None or abs(new["cont_err"]) > TOL["continuity_pct_max"]:
        bad.append(f"continuity {new['cont_err']} %")
    return not bad, "; ".join(bad) or f"capture {new['eval_capture_pct']} / big {new['big_capture_pct']}"

def group_season(work, pool):
    ref = json.load(open("results_B.json"))
    jobs = [(r["variant"], r["season"], work) for r in ref]
    news = pool.map(season_job, jobs)
    return [(f"{r['variant']} {r['season']}",) + check_season_row(r, n) for r, n in zip(ref, news)]

def group_ablation(work, pool):
    ref = json.load(open("vg_ablation.json"))
    jobs = [(r["key"], s, work) for r in ref for s in R.SEASONS]
    news = {(n["variant"], n["season"]): n for n in pool.map(season_job, jobs)}
    out = []
    for r in ref:
        for s in R.SEASONS:
            n = news[(r["key"], s)]
            name = f"{r['key']} {s}"
            if "error" in n:
                out.append((name, False, n["error"])); continue
            ok = (close(r[s], n["big_capture_pct"], TOL["capture_pct"]) and
                  close(r[s + "_all"], n["eval_capture_pct"], TOL["capture_pct"]) and
                  abs(n["cont_err"]) <= TOL["continuity_pct_max"])
            out.append((name, ok, f"big {r[s]} -> {n['big_capture_pct']}, all {r[s + '_all']} -> {n['eval_capture_pct']}, cont {n['cont_err']} %"))
    return out

# ---------------------------------------------------------------- VG checks
def group_vg(work, pool):
    try:
        res = VC.run_checks(work)
    except Exception as e:
        return [("VG checks", False, f"{type(e).__name__}: {str(e)[:200]}")]
    return VC.assertions(res)

# ---------------------------------------------------------------- eight-inch storm
def group_storm8(work, pool):
    ref = {r["key"]: r for r in json.load(open("storm8_results.json"))}
    out = []
    for key in T8.CASES:
        try:
            n = T8.run_case(key, work)
        except Exception as e:
            out.append((key, False, f"{type(e).__name__}: {str(e)[:200]}")); continue
        r = ref.get(key)
        if r is None:
            out.append((key, False, "no reference row")); continue
        bad = [f"{k} {r[k]} -> {n[k]}" for k in ("infil", "runoff", "kept", "final_storage")
               if not close(r[k], n[k], TOL["depth_in"])]
        if not close(r["peak_cfs"], n["peak_cfs"], TOL["peak_cfs"]):
            bad.append(f"peak {r['peak_cfs']} -> {n['peak_cfs']} cfs")
        out.append((key, not bad, "; ".join(bad) or f"infil {n['infil']} in, runoff {n['runoff']} in"))
    return out

# ---------------------------------------------------------------- parity (null effect)
def parity_inputs(work):
    """Inputs with no SOIL2/VG/STRUCT line: recovery, season and eight-inch-storm sets."""
    files = []
    d = os.path.join(work, "inputs"); os.makedirs(d, exist_ok=True)
    plain = [k for k, (desc, v) in S.VARIANTS.items() if not has_extension(v) and not k.startswith("A_")]
    for k in plain:
        v = S.VARIANTS[k][1]
        for season, st in RA.SEASONS.items():
            for D in RA.DAYS:
                for P, hrs in RA.STORMS.items():
                    t_test = st + dt.timedelta(hours=RA.WETUP_HRS) + dt.timedelta(days=D)
                    end = t_test + dt.timedelta(hours=hrs) + dt.timedelta(days=3)
                    wet = [(st + dt.timedelta(hours=h), RA.WETUP_I) for h in range(RA.WETUP_HRS)]
                    test = [(t_test + dt.timedelta(hours=h), P / hrs) for h in range(hrs)]
                    for which, rain in (("with", wet + test), ("without", wet)):
                        tag = f"A_{k}_{season}_D{D:g}_P{P:g}_{which}"
                        lid = os.path.abspath(os.path.join(d, tag + "_lid.txt")) if v["kind"] == "lid" else None
                        inp = os.path.join(d, tag + ".inp")
                        S.write_inp(inp, v, st, end, rain, lid_rpt=lid, title=tag)
                        files.append((inp, lid))
        for season, st in R.SEASONS.items():
            end = st + dt.timedelta(days=R.SPIN_D + R.EVAL_D + 2)
            rain = []
            for (t0, P, hrs) in R.storms(st):
                rain += [(t0 + dt.timedelta(hours=h), P / hrs) for h in range(hrs)]
            inp = os.path.join(d, f"B_{k}_{season}.inp")
            S.write_inp(inp, v, st, end, rain, title=f"{k} {season}", report_step="00:01:00")
            files.append((inp, None))
    for key, (label, eng, case) in T8.CASES.items():
        if case["model"] == "LID_PERCHED":
            continue
        inp = os.path.join(d, f"D_{key}.inp")
        T8.write(inp, case)
        files.append((inp, None))
    return files

def parity_job(args):
    inp, lid = args
    base = inp[:-4]
    try:
        res = {}
        for tag, eng in (("stock", S.ENGINE), ("perch", S.PERCHED_ENGINE)):
            p = subprocess.run([eng, inp, f"{base}_{tag}.rpt", f"{base}_{tag}.out"], capture_output=True, text=True)
            if p.returncode != 0 or not os.path.exists(f"{base}_{tag}.out") or os.path.getsize(f"{base}_{tag}.out") == 0:
                return (os.path.basename(inp), False, f"{tag} engine exit {p.returncode}, no .out")
            if lid:
                if not os.path.exists(lid):
                    return (os.path.basename(inp), False, f"{tag} wrote no LID report")
                os.replace(lid, f"{base}_{tag}_lid.txt")
        same_out = filecmp.cmp(f"{base}_stock.out", f"{base}_perch.out", shallow=False)
        same_lid = (not lid) or filecmp.cmp(f"{base}_stock_lid.txt", f"{base}_perch_lid.txt", shallow=False)
        for tag in ("stock", "perch"):
            for ext in (".out", ".rpt", "_lid.txt"):
                fp = f"{base}_{tag}{ext}"
                if os.path.exists(fp):
                    os.remove(fp)
        ok = same_out and same_lid
        why = "identical .out" + (" and LID report" if lid else "") if ok else \
              ("" if same_out else ".out differs ") + ("" if same_lid else "LID report differs")
        return (os.path.basename(inp), ok, why)
    except Exception as e:
        return (os.path.basename(inp), False, f"{type(e).__name__}: {str(e)[:200]}")

def group_parity(work, pool):
    try:
        files = parity_inputs(work)
    except Exception as e:
        return [("parity inputs", False, f"{type(e).__name__}: {str(e)[:200]}")]
    return pool.map(parity_job, files, chunksize=8)

# ---------------------------------------------------------------- OpenSWMM engines
OSW_EXPECT_KEYS = ("runoff", "infil", "final_storage", "precip")

def osw_job(args):
    eng, kind, key, inp, work, bin_dir = args
    exe = {"legacy": os.path.join(bin_dir, "openswmm-legacy"), "swmm6": os.path.join(bin_dir, "openswmm"),
           "stock": S.ENGINE, "mhfix": S.MHFIX_ENGINE}[eng]
    base = os.path.join(work, f"{key}__{eng}")
    env = dict(os.environ, LD_LIBRARY_PATH=bin_dir + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""))
    name = f"{eng} {kind} {key}"
    try:
        p = subprocess.run([exe, inp, base + ".rpt", base + ".out"], capture_output=True, text=True, timeout=900, env=env)
        r = dict(rc=p.returncode)
        rc = S.runoff_continuity(base + ".rpt")
        r.update(runoff=rc.get("Surface Runoff"), infil=rc.get("Infiltration Loss"),
                 final_storage=rc.get("Final Storage"), precip=rc.get("Total Precipitation"))
        if kind == "season":
            import compare_engines as C
            r["all"], r["big"] = C.score_season(key.split("_")[1], base + ".out")
        r["version"] = next((l.strip() for l in open(base + ".rpt", errors="replace") if "VERSION" in l), "?")
    except Exception as e:
        return dict(name=name, error=f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        if os.path.exists(base + ".out"):
            os.remove(base + ".out")
    return dict(name=name, **r)

def group_openswmm(work, pool, bin_dir):
    ref = json.load(open("engines_results_a4.json"))
    srcdir = os.path.join(work, "osw_inputs"); os.makedirs(srcdir, exist_ok=True)
    jobs = []
    for r in ref:
        key, kind = r["key"], r["kind"]
        inp = os.path.join(srcdir, key + ".inp")
        if not os.path.exists(inp):
            if kind in ("season", "soil2"):
                vkey, season = key.split("_")
                st = R.SEASONS[season]
                end = st + dt.timedelta(days=R.SPIN_D + R.EVAL_D + 2)
                rain = []
                for (t0, P, hrs) in R.storms(st):
                    rain += [(t0 + dt.timedelta(hours=h), P / hrs) for h in range(hrs)]
                S.write_inp(inp, S.VARIANTS[vkey][1], st, end, rain, title=f"{vkey} {season} synthetic season", report_step="00:01:00")
            else:
                T8.write(inp, T8.CASES[key][2])
        jobs.append((r["engine"], kind, key, inp, work, bin_dir))
    news = pool.map(osw_job, jobs)
    out = []
    for r, n in zip(ref, news):
        if "error" in n:
            out.append((n["name"], False, n["error"])); continue
        bad = []
        if n["rc"] != r["rc"]:
            bad.append(f"exit {r['rc']} -> {n['rc']}")
        if n["version"] != r["version"]:
            bad.append(f"version '{n['version']}'")
        for k in OSW_EXPECT_KEYS:
            if not close(r.get(k), n.get(k), TOL["depth_in"]):
                bad.append(f"{k} {r.get(k)} -> {n.get(k)}")
        for k in ("all", "big"):
            if k in r and not close(r[k], n.get(k), TOL["capture_pct"]):
                bad.append(f"{k} {r[k]} -> {n.get(k)}")
        out.append((n["name"], not bad, "; ".join(bad) or f"runoff {n['runoff']} in"))
    return out

# ---------------------------------------------------------------- driver
GROUPS = ["season", "ablation", "vg_checks", "storm8", "parity", "openswmm"]
FUNCS = {"season": group_season, "ablation": group_ablation, "vg_checks": group_vg,
         "storm8": group_storm8, "parity": group_parity}

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--skip-openswmm", action="store_true", help="leave the OpenSWMM group out on purpose")
    ap.add_argument("--only", help="comma-separated groups: " + ",".join(GROUPS))
    ap.add_argument("--workdir", default="verify_runs")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--keep", action="store_true", help="keep the run folder afterwards")
    ap.add_argument("--report", default="verify_report.json")
    a = ap.parse_args()

    groups = GROUPS if not a.only else [g.strip() for g in a.only.split(",")]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        print("unknown group(s):", unknown); return 1
    if a.skip_openswmm and "openswmm" in groups:
        groups = [g for g in groups if g != "openswmm"]
    if os.path.exists(a.workdir):
        shutil.rmtree(a.workdir)
    os.makedirs(a.workdir)

    print("Engines")
    for label, path in (("SWMM_ENGINE", S.ENGINE), ("SWMM_MHFIX_ENGINE", S.MHFIX_ENGINE),
                        ("SWMM_PERCHED_ENGINE", S.PERCHED_ENGINE), ("OPENSWMM_BIN", os.environ.get("OPENSWMM_BIN", ""))):
        state = "found" if path and os.path.exists(path) else "MISSING" if path else "not set"
        print(f"  {label:20} {path or '-'}  [{state}]")
    print()

    summary, report, t_all = [], {}, time.time()
    with Pool(a.jobs) as pool:
        for g in groups:
            exp = MANIFEST["groups"][g]["expected"]
            t0 = time.time()
            if g == "openswmm":
                bin_dir = os.environ.get("OPENSWMM_BIN")
                if not bin_dir:
                    summary.append((g, exp, 0, 0, 0, "SKIPPED: OPENSWMM_BIN not set (use --skip-openswmm to leave it out on purpose)"))
                    report[g] = dict(expected=exp, executed=0, status="skipped")
                    continue
                rows = group_openswmm(os.path.join(a.workdir, g), pool, bin_dir) if os.path.isdir(bin_dir) else \
                       [("OPENSWMM_BIN", False, f"not a folder: {bin_dir}")]
            else:
                wd = os.path.join(a.workdir, g); os.makedirs(wd, exist_ok=True)
                try:
                    rows = FUNCS[g](wd, pool)
                except Exception as e:
                    rows = [(g, False, f"{type(e).__name__}: {str(e)[:200]}")]
            npass = sum(1 for r in rows if r[1])
            nfail = len(rows) - npass
            note = f"{time.time() - t0:.0f} s"
            if len(rows) != exp:
                note += f"; COUNT MISMATCH: expected {exp}, executed {len(rows)}"
            summary.append((g, exp, len(rows), npass, nfail, note))
            report[g] = dict(expected=exp, executed=len(rows), passed=npass, failed=nfail,
                             failures=[dict(case=r[0], detail=r[2]) for r in rows if not r[1]][:50])
            for r in [r for r in rows if not r[1]][:8]:
                print(f"  FAIL {g}: {r[0]} | {r[2]}")

    print(f"\n{'group':10} {'expected':>8} {'executed':>8} {'passed':>7} {'failed':>7}  note")
    ok_all = True
    for g, exp, ex, p, f, note in summary:
        ok = ex == exp and f == 0 and p == exp
        ok_all &= ok
        print(f"{g:10} {exp:8d} {ex:8d} {p:7d} {f:7d}  {'PASS' if ok else 'FAIL'}  {note}")
    if a.skip_openswmm and "openswmm" not in groups and not a.only:
        print(f"{'openswmm':10} {'-':>8} {'-':>8} {'-':>7} {'-':>7}  left out by --skip-openswmm")
    tot = [sum(x[i] for x in summary) for i in (1, 2, 3, 4)]
    print(f"{'total':10} {tot[0]:8d} {tot[1]:8d} {tot[2]:7d} {tot[3]:7d}  {time.time() - t_all:.0f} s")
    print("\nRESULT:", "PASS" if ok_all else "FAIL")
    report["result"] = "PASS" if ok_all else "FAIL"
    report["engines"] = dict(SWMM_ENGINE=S.ENGINE, SWMM_MHFIX_ENGINE=S.MHFIX_ENGINE, SWMM_PERCHED_ENGINE=S.PERCHED_ENGINE,
                             OPENSWMM_BIN=os.environ.get("OPENSWMM_BIN"))
    report["when"] = dt.datetime.now().isoformat(timespec="seconds")
    json.dump(report, open(a.report, "w"), indent=1)
    if not a.keep:
        shutil.rmtree(a.workdir, ignore_errors=True)
    return 0 if ok_all else 1

if __name__ == "__main__":
    sys.exit(main())
