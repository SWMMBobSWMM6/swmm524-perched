"""
Experiment G (part 2) -- SWMM runoff coefficients (Rv) in the ten storm-size bins
of the reviewer's HYDRUS table, for three sandy clay profiles.

STAND-IN INPUTS.  The HYDRUS runs use a West Allis rain record and HYDRUS
profile definitions we do not have yet.  Until they arrive this script uses:

  rain     a seeded synthetic record: three Mar 15 - Nov 30 seasons, about 63
           events a season spread across all ten bins (counts chosen so each
           bin holds roughly 3 in of rain a season, like equal-cumulative bins),
           depth uniform within each bin, 15-minute intensities, exponential
           gaps, no snow.  Two shapes with the same events and dates:
             smooth: duration 2 + 6 P^0.65 hours, triangular, peak at 1/3
             burst : duration 0.75 + 2 P^0.6 hours, triangular, peak at 1/4
           Year 1 is spin-up; years 2 and 3 are scored.
  profiles the study's soils (see the site's Limits tab):
           NBD  undisturbed : 4 in SaCl (Ksat 0.02 in/hr) over 24 in SaCl (0.02)
           TOP  compacted   : 4 in compacted SaCl (0.01) over 24 in SaCl (0.02)
           SUB6 decompacted : 4 in amended topsoil (1.0) over 24 in compacted SaCl (0.01)
           Seepage below = the lower layer's Ksat.  vG curves VG_TOP and VG_SACL
           (swmmlab.py) pass through each layer's FC and WP and give its
           Green-Ampt suction.
  PET      the study's monthly PET (Chesapeake values).

Engines/variants per profile:
  stock    EPA SWMM 5.2.4, bio-retention cell, SOIL = upper layer, no storage
           layer, seepage = lower layer Ksat (the "throttle" setup, L2)
  perched  swmm524-perched, SOIL2 = lower layer, Green-Ampt interface
  vg       swmm524-perched + VG lines, exponential K(theta)
  vgm      swmm524-perched + VG lines, vG-Mualem K(theta)

Event runoff = runoff from the event's start to the next event's start.
Rv per bin = sum(runoff) / sum(rain) over scored events in the bin.
"""
import datetime as dt, json, math, os, random
from multiprocessing import Pool
import swmmlab as S

OUT = "runs_G"
BIN_UP = [0.22, 0.33, 0.48, 0.65, 0.80, 0.98, 1.33, 1.70, 2.32, 6.54]
BIN_LO = [0.03] + BIN_UP[:-1]
BIN_N = [25, 11, 7, 5, 4, 3, 3, 2, 2, 1]          # events per season, per bin
BIN10_RANGE = (2.4, 4.0)
YEARS = (2026, 2027, 2028)

# reviewer's HYDRUS table, sandy clay (Rv by bin)
HYDRUS_SACL = {"NBD":  [0.00, 0.01, 0.01, 0.04, 0.07, 0.09, 0.12, 0.20, 0.22, 0.31],
               "TOP":  [0.13, 0.26, 0.37, 0.42, 0.50, 0.56, 0.61, 0.72, 0.72, 0.79],
               "SUB6": [0.01, 0.04, 0.04, 0.07, 0.11, 0.13, 0.19, 0.29, 0.32, 0.52]}

RAIN_SHAPES = {"smooth": (2.0, 6.0, 0.65, 1 / 3), "burst": (0.75, 2.0, 0.60, 1 / 4)}

def rain_record(shape="smooth", seed=20261102):
    a0, a1, ex, fpk = RAIN_SHAPES[shape]
    rnd = random.Random(seed)
    events, series = [], []
    for y in YEARS:
        sizes = []
        for b, n in enumerate(BIN_N):
            lo, hi = (BIN10_RANGE if b == 9 else (BIN_LO[b], BIN_UP[b]))
            for _ in range(n):
                sizes.append(round(rnd.uniform(lo + 0.005, hi - 0.005), 3))
        rnd.shuffle(sizes)
        start, end = dt.datetime(y, 3, 15), dt.datetime(y, 11, 30)
        durs = [2.0 + 6.0 * P ** 0.65 for P in sizes]          # gaps use the smooth durations, so dates match
        durs_shape = [a0 + a1 * P ** ex for P in sizes]
        gaps = [rnd.expovariate(1.0) for _ in sizes]
        free = (end - start).total_seconds() / 3600.0 - sum(durs) - 6.0 * len(sizes)
        scale = free / sum(gaps)
        t = start
        for P, D0, D, g in zip(sizes, durs, durs_shape, gaps):
            t += dt.timedelta(hours=6.0 + g * scale)
            t = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)
            nstep = max(1, int(round(D * 4)))
            tp = nstep * fpk
            w = [(k + 0.5) / tp if k + 0.5 <= tp else (nstep - k - 0.5) / (nstep - tp) for k in range(nstep)]
            w = [max(x, 0.0) for x in w]
            sw = sum(w)
            for k in range(nstep):
                series.append((t + dt.timedelta(minutes=15 * k), P * w[k] / sw * 4.0))   # in/hr
            events.append(dict(t=t, P=P, D=nstep / 4.0, year=t.year))
            t += dt.timedelta(minutes=15 * max(nstep, int(round(D0 * 4))))
    return events, series

SACL = dict(por=S.SUB["por"], fc=S.SUB["fc"], wp=S.SUB["wp"], hco=50.0, suct=10.08)
def layer(thick, ksat, top=False):
    if top:
        return dict(S.TOP, thick=thick)
    return dict(SACL, thick=thick, ksat=ksat)

PROFILES = {
    "NBD":  dict(upper=layer(4.0, 0.02),  lower=layer(24.0, 0.02), vg_up=S.VG_SACL),
    "TOP":  dict(upper=layer(4.0, 0.01),  lower=layer(24.0, 0.02), vg_up=S.VG_SACL),
    "SUB6": dict(upper=layer(4.0, None, top=True), lower=layer(24.0, 0.01), vg_up=S.VG_TOP),
}

def variant(prof, kind):
    pr = PROFILES[prof]
    up, lo = pr["upper"], pr["lower"]
    if kind == "stock":
        v = S.lid(stor_thick=0.0, seep=lo["ksat"])
        v["top"] = up
        return v
    vg = None
    if kind in ("vg", "vgm"):
        km = "MUALEM" if kind == "vgm" else "EXP"
        vg = dict(soil=tuple(pr["vg_up"]) + (km,), soil2=tuple(S.VG_SACL) + (km,))
    return S.perched(k2=lo["ksat"], seep=lo["ksat"], top=up,
                     soil2=dict(thick=lo["thick"], por=lo["por"], fc=lo["fc"], wp=lo["wp"], hco=lo["hco"], suct=lo["suct"]),
                     vg=vg)

def write(prof, kind, series, shape):
    v = variant(prof, kind)
    inp = f"{OUT}/rv_{shape}_{prof}_{kind}.inp"
    S.write_inp(inp, v, dt.datetime(YEARS[0], 3, 1), dt.datetime(YEARS[-1], 12, 15), series,
                title=f"Rv bins stand-in ({shape} rain): {prof} {kind}", report_step="00:15:00", rain_interval="0:15")
    if kind == "stock":
        # the stock writer always uses the study topsoil; put this profile's upper layer in
        t = PROFILES[prof]["upper"]
        txt = open(inp).read()
        old = f"TOP  SOIL     {S.TOP['thick']}  {S.TOP['por']}  {S.TOP['fc']}  {S.TOP['wp']}  {S.TOP['ksat']}  {S.TOP['hco']}  {S.TOP['suct']}"
        new = f"TOP  SOIL     {t['thick']}  {t['por']}  {t['fc']}  {t['wp']}  {t['ksat']}  {t['hco']}  {t['suct']}"
        assert old in txt
        open(inp, "w").write(txt.replace(old, new))
    return inp

def job(args):
    prof, kind, events, shape = args
    inp = f"{OUT}/rv_{shape}_{prof}_{kind}.inp"
    eng = S.ENGINE if kind == "stock" else S.PERCHED_ENGINE
    rpt, out, p = S.run(inp, eng)
    rc = S.runoff_continuity(rpt)
    O = S.Out(out)
    d = S.runoff_depth_series(O)
    t_first = dt.datetime(YEARS[0], 3, 1) + dt.timedelta(seconds=O.step)
    idx = lambda t: int(round((t - t_first).total_seconds() / O.step))
    ev = []
    for i, e in enumerate(events):
        t1 = events[i + 1]["t"] if i + 1 < len(events) else dt.datetime(YEARS[-1], 12, 15)
        ev.append((e["P"], sum(d[max(idx(e["t"]), 0): idx(t1)]), e["year"]))
    os.remove(out)
    scored = [x for x in ev if x[2] != YEARS[0]]
    rv = []
    for b in range(10):
        inb = [x for x in scored if BIN_LO[b] < x[0] <= BIN_UP[b]] if b < 9 else [x for x in scored if x[0] > BIN_UP[8]]
        P = sum(x[0] for x in inb); R = sum(x[1] for x in inb)
        rv.append(dict(n=len(inb), rain=round(P, 3), runoff=round(R, 4), rv=round(R / P, 3) if P else None))
    total = sum(x[0] for x in scored); tot_ro = sum(x[1] for x in scored)
    return dict(rain=shape, profile=prof, kind=kind, cont=rc.get("Continuity Error (%)"), rv=rv,
                rv_all=round(tot_ro / total, 3), rain_scored=round(total, 2))

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    jobs, ev_out = [], {}
    for shape in RAIN_SHAPES:
        events, series = rain_record(shape)
        ev_out[shape] = [dict(t=e["t"].isoformat(), P=e["P"], D=e["D"], year=e["year"]) for e in events]
        for prof in PROFILES:
            for kind in ("stock", "perched", "vg", "vgm"):
                write(prof, kind, series, shape)
                jobs.append((prof, kind, events, shape))
    with Pool(2) as pool:
        res = pool.map(job, jobs)
    json.dump(dict(results=res, events=ev_out, hydrus=HYDRUS_SACL, bins_up=BIN_UP), open("rv_bins.json", "w"), indent=1)
    print(f"{'rain':6} {'prof':5} {'kind':8} {'cont%':>7} " + " ".join(f"{u:>5}" for u in BIN_UP) + "   all")
    for r in res:
        print(f"{r['rain']:6} {r['profile']:5} {r['kind']:8} {r['cont']:7.3f} " + " ".join(f"{x['rv']:5.2f}" for x in r["rv"]) + f"  {r['rv_all']:.3f}")
    for prof, row in HYDRUS_SACL.items():
        print(f"{prof:5} {'HYDRUS':8} {'':7} " + " ".join(f"{x:5.2f}" for x in row))
    yrs = {}
    for e in rain_record()[0]: yrs.setdefault(e["year"], [0, 0.0]); yrs[e["year"]][0] += 1; yrs[e["year"]][1] += e["P"]
    print("events per year / rain:", {y: (n, round(p, 2)) for y, (n, p) in yrs.items()})
    print("events per bin (scored):", [r["n"] for r in res[0]["rv"]])
