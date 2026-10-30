"""
Experiment A -- controlled storage-recovery test.

  3.0 in wet-up storm over 24 h (0.125 in/hr)  ->  D dry days  ->  test storm
  test storm = 1.0 in over 6 h or 2.0 in over 12 h (0.167 in/hr)

Each case is run twice, with and without the test storm, to the same end time.
Test-storm runoff = Surface Runoff(with) - Surface Runoff(without), from the
.rpt Runoff Quantity Continuity table (inches over the 1-acre subcatchment).
Season changes only the start month (January vs July) and hence ET / RECOVERY.
"""
import os, sys, csv, json, datetime as dt, filecmp
from multiprocessing import Pool
import swmmlab as S

RUNS = "runs_A"
DAYS = [0.5, 1, 2, 3, 5, 7, 10, 14]
STORMS = {1.0: 6, 2.0: 12}          # depth (in) : hours at 1/6 in/hr
SEASONS = {"Jan": dt.datetime(2027, 1, 1), "Jul": dt.datetime(2027, 7, 1)}
WETUP_HRS, WETUP_I = 24, 0.125

def case(args):
    vkey, season, D, P = args
    v = S.VARIANTS[vkey][1]
    st = SEASONS[season]
    t_test = st + dt.timedelta(hours=WETUP_HRS) + dt.timedelta(days=D)
    hrs = STORMS[P]
    end = t_test + dt.timedelta(hours=hrs) + dt.timedelta(days=3)
    wet = [(st + dt.timedelta(hours=h), WETUP_I) for h in range(WETUP_HRS)]
    test = [(t_test + dt.timedelta(hours=h), P / hrs) for h in range(hrs)]
    tag = f"{vkey}_{season}_D{D:g}_P{P:g}"
    res = dict(variant=vkey, season=season, D=D, P=P)
    for which, rain in (("with", wet + test), ("without", wet)):
        inp = os.path.join(RUNS, f"{tag}_{which}.inp")
        lidrpt = None
        if v["kind"] == "lid" and which == "without":
            lidrpt = os.path.join(RUNS, f"{tag}_lid.txt")
        S.write_inp(inp, v, st, end, rain, lid_rpt=lidrpt, title=tag + " " + which)
        rpt, out, p = S.run(inp, v.get("engine"))
        if p.returncode != 0:
            return dict(res, error=f"rc={p.returncode} {p.stderr[-200:]}")
        rc = S.runoff_continuity(rpt)
        res[f"SR_{which}"] = rc["Surface Runoff"]
        res[f"err_{which}"] = rc.get("Continuity Error (%)")
        if lidrpt:
            rows = S.lid_report(lidrpt)
            # state at the instant the test storm would start
            tstr = t_test.strftime("%m/%d/%Y")
            ttime = t_test.strftime("%H:%M:%S")
            before = [r for r in rows
                      if dt.datetime.strptime(r["date"] + " " + r["time"], "%m/%d/%Y %H:%M:%S") <= t_test]
            last = before[-1]["v"]
            theta, stor = last[11], last[12]
            res["theta_at_test"] = theta
            res["topsoil_free_in"] = (S.TOP["por"] - theta) * S.TOP["thick"]
            res["stor_level_in"] = stor
            vf = v["vr"] / (1 + v["vr"]) if v["vr"] > 0 else 0.0
            res["bucket_free_in"] = (v["stor_thick"] - stor) * vf
            # hours after wet-up end until topsoil first reaches field capacity + 0.01
            t0 = st + dt.timedelta(hours=WETUP_HRS)
            hit = None
            for r in rows:
                tt = dt.datetime.strptime(r["date"] + " " + r["time"], "%m/%d/%Y %H:%M:%S")
                if tt > t0 and r["v"][11] <= S.TOP["fc"] + 0.01:
                    hit = (tt - t0).total_seconds() / 3600.0
                    break
            res["hrs_to_fc"] = hit
            os.remove(lidrpt)          # large; state already extracted
    res["test_runoff_in"] = round(res["SR_with"] - res["SR_without"], 3)
    res["capture_pct"] = round(100.0 * (1.0 - res["test_runoff_in"] / P), 1)
    return res

if __name__ == "__main__":
    os.makedirs(RUNS, exist_ok=True)
    jobs = [(k, s, D, P) for k in S.VARIANTS for s in SEASONS for D in DAYS for P in STORMS]
    with Pool(os.cpu_count()) as pool:
        results = pool.map(case, jobs)
    bad = [r for r in results if "error" in r]
    print("cases", len(results), "errors", len(bad))
    for b in bad[:5]:
        print(b)
    keys = ["variant", "season", "D", "P", "test_runoff_in", "capture_pct", "SR_with",
            "SR_without", "err_with", "err_without", "theta_at_test", "topsoil_free_in",
            "stor_level_in", "bucket_free_in", "hrs_to_fc"]
    with open("results_A.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)
    json.dump(results, open("results_A.json", "w"), indent=1, default=str)
