"""
How often does the 4 in topsoil sit at (near) saturation in each LID setup?
Re-runs the Experiment B seasons for the LID variants with an LID report file and
integrates time with topsoil moisture >= porosity - 0.01 inside the 90-day scoring window.

The LID report writes a row every runoff step while the unit is active and stops while
every LID flux is below MINFLOW. A saturated topsoil always has percolation above MINFLOW,
so saturated time is never hidden in a gap; each row's duration is capped at the dry step.
"""
import os, json, datetime as dt
import swmmlab as S
import run_season as R

OUT = "runs_sat"
THRESH = S.TOP["por"] - 0.01
CAP_S = 300.0

def one(vkey, season):
    v = S.VARIANTS[vkey][1]
    st = R.SEASONS[season]
    end = st + dt.timedelta(days=R.SPIN_D + R.EVAL_D + 2)
    ss = R.storms(st)
    rain = []
    for (t0, P, hrs) in ss:
        rain += [(t0 + dt.timedelta(hours=h), P / hrs) for h in range(hrs)]
    inp = os.path.join(OUT, f"{vkey}_{season}.inp")
    lr = os.path.join(OUT, f"{vkey}_{season}_lid.txt")
    S.write_inp(inp, v, st, end, rain, lid_rpt=lr, title=f"{vkey} {season} saturation time")
    rpt, out, p = S.run(inp, v.get("engine"))
    rows = S.lid_report(lr)
    t = [dt.datetime.strptime(r["date"] + " " + r["time"], "%m/%d/%Y %H:%M:%S") for r in rows]
    e0 = st + dt.timedelta(days=R.SPIN_D)
    e1 = e0 + dt.timedelta(days=R.EVAL_D)
    sat = 0.0
    longest = cur = 0.0
    sf_min, sf_end, th2 = 1.0, 1.0, []
    for i, r in enumerate(rows[:-1]):
        if not (e0 <= t[i] < e1):
            continue
        dur = min((t[i + 1] - t[i]).total_seconds(), CAP_S)
        if v["kind"] == "perched":
            sf_min = min(sf_min, r["v"][10]); sf_end = r["v"][10]; th2.append(r["v"][12])
        if r["v"][11] >= THRESH:
            sat += dur
            cur += dur
            longest = max(longest, cur)
        else:
            cur = 0.0
    os.remove(lr)
    return dict(variant=vkey, season=season,
                sat_hours=round(sat / 3600, 1),
                sat_pct_of_window=round(100 * sat / (R.EVAL_D * 86400), 2),
                longest_sat_hours=round(longest / 3600, 1),
                struct_min=round(sf_min, 3), struct_end=round(sf_end, 3),
                soil2_theta_mean=(round(sum(th2) / len(th2), 3) if th2 else None))

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    res = [one(k, s) for k in ("L0", "L1", "L2", "L2s", "P1", "P1s", "P2", "P2s") for s in ("dormant", "growing")]
    json.dump(res, open("sat_time.json", "w"), indent=1)
    for r in res:
        print(r)
