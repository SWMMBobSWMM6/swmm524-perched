"""
Experiment D -- the eight-inch storm test sent in by the second reviewer, rebuilt.

  10 acres, 100 % pervious, 8.0 in in 24 h, Horton parameters for NRCS soil group B
  from the Denver (UDFCD/MHFD) manual: f0 4.5 in/hr, fmin 0.6 in/hr, decay 6.48 /hr
  (0.0018 /s), drying time 7 days, max infiltration volume 3.0 in.

  Her storm used the NRCS NOAA C 24-hour distribution. Its ordinates are not published
  in any form I could retrieve, so this rebuild uses the SCS Type II 24-hour distribution
  (TR-55) as a stand-in. Every capped result is set by the 3-in cap, not by the storm shape.

Engines: EPA 5.2.4 as released; the same with OpenSWMM's Build 5.3.0 Modified Horton
fix ported in (swmm524-mhfix); swmm524-perched for the perched case.
"""
import os, json, subprocess, datetime as dt
import swmmlab as S

STOCK, MHFIX, PERCH = S.ENGINE, S.MHFIX_ENGINE, S.PERCHED_ENGINE   # set with SWMM_ENGINE etc. (BUILD.md)
OUT = "runs_D"
AREA_AC = 10.0
P_TOTAL = 8.0
# SCS Type II (TR-55) cumulative fraction vs hour -- stand-in for NOAA C
TYPE2 = [(0, 0.000), (2, 0.022), (4, 0.048), (6, 0.080), (7, 0.098), (8, 0.120), (8.5, 0.133),
         (9, 0.147), (9.5, 0.163), (9.75, 0.172), (10, 0.181), (10.5, 0.204), (11, 0.235),
         (11.5, 0.283), (11.75, 0.357), (12, 0.663), (12.5, 0.735), (13, 0.772), (13.5, 0.799),
         (14, 0.820), (16, 0.880), (20, 0.952), (24, 1.000)]
DENVER_B = dict(f0=4.5, fmin=0.6, decay=6.48, dry=7.0)

def cum(t):
    for (t0, c0), (t1, c1) in zip(TYPE2, TYPE2[1:]):
        if t0 <= t <= t1:
            return c0 + (c1 - c0) * (t - t0) / (t1 - t0)
    return 1.0

def hyetograph(step_h=0.1):
    n = int(round(24 / step_h))
    return [(i * step_h, P_TOTAL * (cum((i + 1) * step_h) - cum(i * step_h)) / step_h) for i in range(n)]

CASES = {
    "horton_cap3":   ("Horton, MaxInfil 3 in", STOCK, dict(model="HORTON", fmax=3.0)),
    "mh_cap3_stock": ("Modified Horton, MaxInfil 3 in, EPA 5.2.4 as released", STOCK, dict(model="MODIFIED_HORTON", fmax=3.0)),
    "mh_cap3_fixed": ("Modified Horton, MaxInfil 3 in, with OpenSWMM 5.3.0 fix", MHFIX, dict(model="MODIFIED_HORTON", fmax=3.0)),
    "mh_nocap":      ("Modified Horton, no MaxInfil", STOCK, dict(model="MODIFIED_HORTON", fmax=0.0)),
    "horton_nocap":  ("Horton, no MaxInfil", STOCK, dict(model="HORTON", fmax=0.0)),
    "perched":       ("Perched engine: 7.5 in topsoil (3 in of room from dry) over compacted clay", PERCH, dict(model="LID_PERCHED")),
    "lid_bucket":    ("Stock LID: same topsoil, 24 in clay as storage layer", STOCK, dict(model="LID_BUCKET")),
}

TOP75 = dict(thick=7.5, por=0.50, fc=0.20, wp=0.10, ksat=1.0, hco=36.0, suct=3.5)   # (por - wp) * 7.5 = 3.0 in
CLAY = S.SUB

def write(path, case):
    model = case["model"]
    start = dt.datetime(2027, 6, 1)
    end = start + dt.timedelta(days=2)
    rain = hyetograph()
    L = ["[TITLE]", "Eight-inch storm test " + os.path.basename(path), "",
         "[OPTIONS]", "FLOW_UNITS           CFS",
         "INFILTRATION         " + ("HORTON" if model == "HORTON" else "MODIFIED_HORTON"),
         "FLOW_ROUTING         KINWAVE",
         "START_DATE           06/01/2027", "START_TIME           00:00:00",
         "REPORT_START_DATE    06/01/2027", "REPORT_START_TIME    00:00:00",
         "END_DATE             06/03/2027", "END_TIME             00:00:00",
         "DRY_DAYS             0", "REPORT_STEP          00:05:00", "WET_STEP             00:01:00",
         "DRY_STEP             00:05:00", "ROUTING_STEP         0:00:30", "ALLOW_PONDING        NO", "",
         "[EVAPORATION]", "CONSTANT 0.0", "",
         "[RAINGAGES]", "RG1  INTENSITY 0:06 1.0 TIMESERIES RAIN", "",
         "[SUBCATCHMENTS]", f"S1  RG1  OUT1  {AREA_AC}  0  500  0.5  0", "",
         "[SUBAREAS]", "S1  0.01  0.1  0.05  0.05  0  OUTLET", ""]
    b = DENVER_B
    if model in ("HORTON", "MODIFIED_HORTON"):
        L += ["[INFILTRATION]", f"S1  {b['f0']}  {b['fmin']}  {b['decay']}  {b['dry']}  {case['fmax']}", ""]
    else:
        t = TOP75
        L += ["[INFILTRATION]", f"S1  {b['f0']}  {b['fmin']}  {b['decay']}  {b['dry']}  0", ""]
        L += ["[LID_CONTROLS]", "TOP  BC", "TOP  SURFACE  0.05  0.0  0.0  0.5  5",
              f"TOP  SOIL     {t['thick']}  {t['por']}  {t['fc']}  {t['wp']}  {t['ksat']}  {t['hco']}  {t['suct']}"]
        if model == "LID_PERCHED":
            L += [f"TOP  SOIL2    {CLAY['thick']}  {CLAY['por']}  {CLAY['fc']}  {CLAY['wp']}  {CLAY['ksat']}  50  {CLAY['suct']}",
                  f"TOP  STORAGE  0  0  {CLAY['ksat']}  0"]
        else:
            vr = CLAY["por"] / (1 - CLAY["por"])
            L += [f"TOP  STORAGE  {CLAY['thick']}  {vr:.4f}  {CLAY['ksat']}  0"]
        L += ["TOP  DRAIN    0  0.5  0  6", ""]
        L += ["[LID_USAGE]", f"S1  TOP  1  {AREA_AC * 43560}  500  0  0  0  *  *  0", ""]
    L += ["[OUTFALLS]", "OUT1  0  FREE  NO", "", "[TIMESERIES]"]
    for (h, i) in rain:
        tt = start + dt.timedelta(hours=h)
        L.append(f"RAIN  {tt:%m/%d/%Y}  {tt:%H:%M}  {i:.5f}")
    L += ["", "[REPORT]", "INPUT NO", "SUBCATCHMENTS ALL", "NODES ALL", "LINKS ALL", "",
          "[COORDINATES]", "OUT1  0  0", ""]
    open(path, "w").write("\n".join(L))

def peak_cfs(rpt):
    t = open(rpt).read()
    import re
    m = re.search(r"Subcatchment Runoff Summary.*?\n\s*S1\s+([\d.\s]+)", t, re.S)
    if not m:
        return None
    vals = m.group(1).split()
    return float(vals[-2])          # Peak Runoff CFS

ENGINE_NAME = {STOCK: "stock", MHFIX: "mhfix", PERCH: "perched"}

def run_case(key, outdir=OUT):
    """Write and run one case; raises if the engine fails or writes no report."""
    label, eng, case = CASES[key]
    inp = os.path.join(outdir, key + ".inp")
    write(inp, case)
    rpt, out = inp[:-4] + ".rpt", inp[:-4] + ".out"
    p = subprocess.run([eng, inp, rpt, out], capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(rpt):
        raise RuntimeError(f"{key}: engine {eng} exit {p.returncode}: {p.stderr.strip()[:200]}")
    rc = S.runoff_continuity(rpt)
    kept = rc["Total Precipitation"] - rc["Surface Runoff"] - rc.get("Evaporation Loss", 0.0)
    r = dict(key=key, label=label, engine=ENGINE_NAME.get(eng, os.path.basename(eng)),
             precip=rc["Total Precipitation"], infil=rc["Infiltration Loss"], runoff=rc["Surface Runoff"],
             final_storage=rc.get("Final Storage", 0.0) - rc.get("Initial LID Storage", 0.0),
             kept=round(kept, 3), peak_cfs=peak_cfs(rpt), cont_err=rc.get("Continuity Error (%)"))
    if os.path.exists(out):
        os.remove(out)
    return r

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    res = [run_case(k) for k in CASES]
    json.dump(res, open("storm8_results.json", "w"), indent=1)
    print(f"{'case':16} {'infil':>6} {'runoff':>7} {'stored':>7} {'kept':>6} {'peak':>7} {'cont%':>6}")
    for r in res:
        print(f"{r['key']:16} {r['infil']:6.2f} {r['runoff']:7.2f} {r['final_storage']:7.2f} {r['kept']:6.2f} {r['peak_cfs'] or 0:7.2f} {r['cont_err']:6.3f}")
