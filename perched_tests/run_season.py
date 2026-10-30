"""
Experiment B -- a synthetic continuous season (no observed rain in hand).

Storms every 6 days cycling through
  0.30 0.80 0.50 1.50 0.25 1.00 0.40 2.00 0.60 0.75 in   (8.1 in / 60 days ~ 4 in/month)
at roughly 1/6 in/hr.  61-day spin-up, then a 90-day evaluation window:
  dormant : Nov 1 spin-up -> Jan 1 .. Mar 31
  growing : May 1 spin-up -> Jul 1 .. Sep 28
Same storm train both seasons; only the month (ET, RECOVERY) changes.
Per-storm runoff is integrated from the .out file storm-start to next-storm-start
and checked against the .rpt Surface Runoff total.
"""
import os, csv, json, datetime as dt
from multiprocessing import Pool
import swmmlab as S

RUNS = "runs_B"
CYCLE = [0.30, 0.80, 0.50, 1.50, 0.25, 1.00, 0.40, 2.00, 0.60, 0.75]
SPACING_D, SPIN_D, EVAL_D = 6, 61, 90
SEASONS = {"dormant": dt.datetime(2026, 11, 1), "growing": dt.datetime(2027, 5, 1)}

def storms(start):
    out, k, day = [], 0, 0
    while day <= SPIN_D + EVAL_D - 1:
        P = CYCLE[k % len(CYCLE)]
        hrs = max(1, int(P / (1 / 6) + 0.5))
        out.append((start + dt.timedelta(days=day), P, hrs))
        k += 1
        day += SPACING_D
    return out

def case(args):
    vkey, season = args
    v = S.VARIANTS[vkey][1]
    st = SEASONS[season]
    end = st + dt.timedelta(days=SPIN_D + EVAL_D + 2)
    ss = storms(st)
    rain = []
    for (t0, P, hrs) in ss:
        rain += [(t0 + dt.timedelta(hours=h), P / hrs) for h in range(hrs)]
    inp = os.path.join(RUNS, f"{vkey}_{season}.inp")
    S.write_inp(inp, v, st, end, rain, title=f"{vkey} {season} synthetic season", report_step="00:01:00")
    rpt, out, p = S.run(inp, v.get("engine"))
    if p.returncode:
        return dict(variant=vkey, season=season, error=p.stderr[-200:])
    rc = S.runoff_continuity(rpt)
    O = S.Out(out)
    d = S.runoff_depth_series(O)
    step_s = O.step
    t_first = st + dt.timedelta(seconds=step_s)       # period k ends at start + (k+1)*step
    def idx(t):
        return int(round((t - t_first).total_seconds() / step_s))
    eval0 = st + dt.timedelta(days=SPIN_D)
    rows = []
    for i, (t0, P, hrs) in enumerate(ss):
        t1 = ss[i + 1][0] if i + 1 < len(ss) else end
        r = sum(d[max(idx(t0), 0): idx(t1)])
        rows.append(dict(t=t0.isoformat(), P=P, runoff=r, eval=(t0 >= eval0)))
    ev = [r for r in rows if r["eval"]]
    big = [r for r in ev if r["P"] >= 0.75]
    res = dict(variant=vkey, season=season,
               rpt_runoff=rc["Surface Runoff"], out_runoff=round(sum(d), 3),
               cont_err=rc.get("Continuity Error (%)"),
               eval_rain=round(sum(r["P"] for r in ev), 2),
               eval_runoff=round(sum(r["runoff"] for r in ev), 3),
               big_rain=round(sum(r["P"] for r in big), 2),
               big_runoff=round(sum(r["runoff"] for r in big), 3),
               storms=rows)
    res["eval_capture_pct"] = round(100 * (1 - res["eval_runoff"] / res["eval_rain"]), 1)
    res["big_capture_pct"] = round(100 * (1 - res["big_runoff"] / res["big_rain"]), 1)
    by = {}
    for r in ev:
        by.setdefault(r["P"], []).append(r["runoff"])
    res["capture_by_size"] = {P: round(100 * (1 - sum(x) / (P * len(x))), 1) for P, x in sorted(by.items())}
    return res

if __name__ == "__main__":
    os.makedirs(RUNS, exist_ok=True)
    jobs = [(k, s) for k in S.VARIANTS for s in SEASONS]
    with Pool(os.cpu_count()) as pool:
        R = pool.map(case, jobs)
    json.dump(R, open("results_B.json", "w"), indent=1)
    for r in R:
        if "error" in r:
            print("ERR", r); continue
        print(f"{r['variant']:5} {r['season']:8} capture all {r['eval_capture_pct']:5.1f}%  "
              f">=0.75in {r['big_capture_pct']:5.1f}%  rpt/out runoff {r['rpt_runoff']}/{r['out_runoff']}  "
              f"cont {r['cont_err']}  by size {r['capture_by_size']}")
