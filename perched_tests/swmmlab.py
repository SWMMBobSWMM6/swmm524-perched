"""
swmmlab.py -- shared pieces for the topsoil-over-compacted-sandy-clay test.

One 1-acre, 100 % pervious subcatchment draining to one outfall.
Two ways of representing 4 in of decompacted, amended topsoil over a
compacted sandy clay (SaCl) subsoil in EPA SWMM 5.2.4:

  Modified Horton  - topsoil storage = (f0 - fmin)/kd ; fmin = compacted Ksat ;
                     recovery by drying time (and optional monthly RECOVERY pattern)
  LID (Bio-retention cell covering the whole subcatchment)
                   - SOIL layer   = the 4 in topsoil
                   - STORAGE layer = the compacted SaCl (void ratio, seepage = Ksat)

All inputs US customary.  Engine: EPA SWMM 5.2.4 built from the v5.2.4 tag.
"""
import os, struct, subprocess, math, re

ENGINE = os.environ.get("SWMM_ENGINE", "/root/swmm524/build/bin/Release/runswmm")
PERCHED_ENGINE = os.environ.get("SWMM_PERCHED_ENGINE", "/root/swmm524-perched/build/bin/Release/runswmm")
AREA_AC = 1.0
AREA_FT2 = 43560.0
WIDTH = 208.71

# ---- soils (assumptions, stated in the write-up) ---------------------------
TOP = dict(thick=4.0, por=0.50, fc=0.30, wp=0.15, ksat=1.0, hco=36.0, suct=3.5)
SUB = dict(por=0.430, fc=0.321, wp=0.221, ksat=0.01, suct=9.45, thick=24.0)
TOP_DRAINABLE = TOP["thick"] * (TOP["por"] - TOP["fc"])          # 0.80 in
TOP_TO_WP = TOP["thick"] * (TOP["por"] - TOP["wp"])              # 1.40 in

def void_ratio(porosity):
    return porosity / (1.0 - porosity)

# Chesapeake-ish monthly PET, in/day (Jan..Dec)
PET = [0.02, 0.03, 0.06, 0.10, 0.14, 0.17, 0.18, 0.16, 0.12, 0.07, 0.04, 0.02]
PET_RECOVERY = [round(p / max(PET), 3) for p in PET]

# ---- variants ----------------------------------------------------------------
def horton(f0=3.0, fmin=SUB["ksat"], store=TOP_DRAINABLE, dry=7.0, maxinfil=0.0,
           recovery=None):
    kd = (f0 - fmin) / store
    return dict(kind="horton", f0=f0, fmin=fmin, kd=kd, dry=dry,
                maxinfil=maxinfil, recovery=recovery)

def perched(k2=SUB["ksat"], seep=None, struct=None, soil2=None):
    """swmm524-perched: topsoil over SOIL2 with a conductivity-limited interface."""
    s2 = dict(thick=SUB["thick"], por=SUB["por"], fc=SUB["fc"], wp=SUB["wp"],
              ksat=k2, hco=50.0, suct=SUB["suct"])
    if soil2:
        s2.update(soil2)
    return dict(kind="perched", soil2=s2, seep=(k2 if seep is None else seep),
                struct=struct, engine=PERCHED_ENGINE)

ILLUSTRATIVE_STRUCT = (0.2, 0.02, 0.1)   # decay 1/day saturated, recovery 1/day <= FC, floor

def lid(stor_thick=SUB["thick"], stor_por=SUB["por"], seep=SUB["ksat"]):
    return dict(kind="lid", stor_thick=stor_thick,
                vr=(void_ratio(stor_por) if stor_thick > 0 else 0.0), seep=seep)

VARIANTS = {
    # Modified Horton family
    "H0":   ("Mod. Horton, store 0.80 in, fmin = 0.01 in/hr, 7-day drying",
             horton()),
    "H0r":  ("H0 + RECOVERY pattern of all 1.0 (null-effect control)",
             horton(recovery=[1.0] * 12)),
    "H1":   ("H0 + RECOVERY pattern scaled to monthly PET",
             horton(recovery=PET_RECOVERY)),
    "Hz":   ("H0 with an impermeable subsoil (fmin = 0)",
             horton(fmin=0.0)),
    "Hmax": ("H0 with MaxInfil = 0.80 in (5.2.4 defect check)",
             horton(maxinfil=TOP_DRAINABLE)),
    # LID family
    "L0":   ("LID: storage = 24 in SaCl, void ratio from TOTAL porosity 0.43",
             lid()),
    "L1":   ("LID: storage = 24 in SaCl, void ratio from DRAINABLE porosity 0.109",
             lid(stor_por=SUB["por"] - SUB["fc"])),
    "L2":   ("LID: no storage layer, seepage = SaCl Ksat (Ksat-limited drainage)",
             lid(stor_thick=0.0)),
    "Lz":   ("L0 with an impermeable subsoil (seepage = 0)",
             lid(seep=0.0)),
    # sensitivity: subsoil 5x tighter (Ksat 0.002 in/hr)
    "H0s":  ("H0 with fmin = 0.002 in/hr (tighter compacted layer)",
             horton(fmin=0.002)),
    "L2s":  ("L2 with seepage = 0.002 in/hr (tighter compacted layer)",
             lid(stor_thick=0.0, seep=0.002)),
    # swmm524-perched
    "P1":   ("Perched engine: SOIL2 = 24 in SaCl, Ksat 0.01 in/hr, GA-limited interface",
             perched()),
    "P1s":  ("P1 with SOIL2 Ksat and seepage 0.002 in/hr (tighter clay)",
             perched(k2=0.002)),
    "P2":   ("P1 + STRUCT 0.2/day decay, 0.02/day recovery, floor 0.1 (illustrative)",
             perched(struct=ILLUSTRATIVE_STRUCT)),
    "P2s":  ("P1s + the same STRUCT (illustrative)",
             perched(k2=0.002, struct=ILLUSTRATIVE_STRUCT)),
    # controls for the perched engine
    "Pinf": ("Limiting case: SOIL2 Ksat 1000 in/hr, FC~WP~0, no suction, seepage 0.01 (should match L0)",
             perched(k2=1000.0, seep=SUB["ksat"],
                     soil2=dict(fc=0.000002, wp=0.000001, hco=0.0, suct=0.0))),
    "P1k0": ("P1 + STRUCT 0 0 1 (null-effect control, should equal P1)",
             perched(struct=(0.0, 0.0, 1.0))),
}

# ---- .inp writer ----------------------------------------------------------------
def fmt_date(d):           # d = datetime
    return d.strftime("%m/%d/%Y"), d.strftime("%H:%M:%S")

def write_inp(path, variant, start, end, rain, lid_rpt=None, title="", report_step="00:05:00"):
    """rain: list of (datetime, intensity in/hr) at 1-hr spacing (nonzero hours only)."""
    v = variant
    sd, st = fmt_date(start)
    ed, et = fmt_date(end)
    L = []
    L += ["[TITLE]", title or os.path.basename(path), ""]
    L += ["[OPTIONS]",
          "FLOW_UNITS           CFS",
          "INFILTRATION         MODIFIED_HORTON",
          "FLOW_ROUTING         KINWAVE",
          f"START_DATE           {sd}", f"START_TIME           {st}",
          f"REPORT_START_DATE    {sd}", f"REPORT_START_TIME    {st}",
          f"END_DATE             {ed}", f"END_TIME             {et}",
          "DRY_DAYS             0",
          f"REPORT_STEP          {report_step}",
          "WET_STEP             00:01:00",
          "DRY_STEP             00:05:00",
          "ROUTING_STEP         0:00:30",
          "ALLOW_PONDING        NO",
          "SKIP_STEADY_STATE    NO", ""]
    L += ["[EVAPORATION]", "MONTHLY " + " ".join(f"{p:.3f}" for p in PET),
          "DRY_ONLY NO"]
    if v["kind"] == "horton" and v.get("recovery"):
        L += ["RECOVERY REC"]
    L += [""]
    L += ["[RAINGAGES]", "RG1  INTENSITY 1:00 1.0 TIMESERIES RAIN", ""]
    L += ["[SUBCATCHMENTS]",
          f"S1  RG1  OUT1  {AREA_AC}  0  {WIDTH}  2.0  0", ""]
    L += ["[SUBAREAS]", "S1  0.012  0.15  0.05  0.05  0  OUTLET", ""]
    if v["kind"] == "perched":
        t, s2 = TOP, v["soil2"]
        L += ["[INFILTRATION]", "S1  3.0  0.01  3.7375  7  0", ""]
        L += ["[LID_CONTROLS]",
              "TOP  BC",
              "TOP  SURFACE  0.05  0.0  0.0  2.0  5",
              f"TOP  SOIL     {t['thick']}  {t['por']}  {t['fc']}  {t['wp']}  {t['ksat']}  {t['hco']}  {t['suct']}",
              f"TOP  SOIL2    {s2['thick']}  {s2['por']}  {s2['fc']}  {s2['wp']}  {s2['ksat']}  {s2['hco']}  {s2['suct']}",
              f"TOP  STORAGE  0  0  {v['seep']}  0",
              "TOP  DRAIN    0  0.5  0  6"]
        if v.get("struct"):
            kd, kr, smin = v["struct"]
            L += [f"TOP  STRUCT   {kd}  {kr}  {smin}"]
        L += [""]
        rpt = f'"{lid_rpt}"' if lid_rpt else "*"
        L += ["[LID_USAGE]",
              f"S1  TOP  1  {AREA_FT2}  {WIDTH}  0  0  0  {rpt}  *  0", ""]
    elif v["kind"] == "horton":
        h = v
        L += ["[INFILTRATION]",
              f"S1  {h['f0']:.4f}  {h['fmin']:.4f}  {h['kd']:.6f}  {h['dry']:.3f}  {h['maxinfil']:.4f}", ""]
    else:
        # infiltration params irrelevant (LID covers 100 %), but section required
        L += ["[INFILTRATION]", "S1  3.0  0.01  3.7375  7  0", ""]
        t, s = TOP, v
        L += ["[LID_CONTROLS]",
              "TOP  BC",
              "TOP  SURFACE  0.05  0.0  0.0  2.0  5",
              f"TOP  SOIL     {t['thick']}  {t['por']}  {t['fc']}  {t['wp']}  {t['ksat']}  {t['hco']}  {t['suct']}",
              f"TOP  STORAGE  {s['stor_thick']}  {s['vr']:.4f}  {s['seep']}  0",
              "TOP  DRAIN    0  0.5  0  6", ""]
        rpt = f'"{lid_rpt}"' if lid_rpt else "*"
        L += ["[LID_USAGE]",
              f"S1  TOP  1  {AREA_FT2}  {WIDTH}  0  0  0  {rpt}  *  0", ""]
    L += ["[OUTFALLS]", "OUT1  0  FREE  NO", ""]
    L += ["[TIMESERIES]"]
    if not rain:
        L += [f"RAIN  {sd}  00:00  0.0"]
    for (d, r) in rain:
        dd, tt = fmt_date(d)
        L += [f"RAIN  {dd}  {tt[:5]}  {r:.5f}"]
    L += [""]
    if v["kind"] == "horton" and v.get("recovery"):
        L += ["[PATTERNS]", "REC  MONTHLY  " + " ".join(f"{x:.3f}" for x in v["recovery"]), ""]
    L += ["[REPORT]", "INPUT NO", "CONTROLS NO", "SUBCATCHMENTS ALL",
          "NODES ALL", "LINKS ALL", ""]
    L += ["[COORDINATES]", "OUT1  0  0", ""]
    L += ["[Polygons]", "S1  0  0", "S1  208.71  0", "S1  208.71  208.71", "S1  0  208.71", ""]
    with open(path, "w") as f:
        f.write("\n".join(L))

def run(inp, engine=None):
    rpt = inp[:-4] + ".rpt"
    out = inp[:-4] + ".out"
    p = subprocess.run([engine or ENGINE, inp, rpt, out], capture_output=True, text=True)
    return rpt, out, p

# ---- .rpt readers --------------------------------------------------------------
def runoff_continuity(rpt):
    """Return dict of Runoff Quantity Continuity rows -> inches."""
    txt = open(rpt).read()
    m = re.search(r"Runoff Quantity Continuity(.*?)\n\s*\n\s*\*", txt, re.S)
    if not m:
        raise RuntimeError("no runoff continuity in " + rpt)
    rows = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"\s*([A-Za-z %()]+?)\s*\.+\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?", line)
        if mm:
            key = mm.group(1).strip()
            rows[key] = float(mm.group(3)) if mm.group(3) else float(mm.group(2))
    return rows

def has_errors(rpt):
    t = open(rpt).read()
    return ("ERROR" in t), t

# ---- .out reader (minimal, SWMM 5.x binary) ------------------------------------
class Out:
    def __init__(self, path):
        b = open(path, "rb").read()
        self.b = b
        magic, ver, fu, ns, nn, nl, npol = struct.unpack_from("<7i", b, 0)
        assert magic == 516114522, "bad magic"
        id_pos, prop_pos, out_pos, nper, err, magic2 = struct.unpack_from("<6i", b, len(b) - 24)
        assert magic2 == 516114522
        self.ns, self.nn, self.nl, self.npol, self.nper = ns, nn, nl, npol, nper
        self.out_pos, self.err = out_pos, err
        # walk the property / variable section
        p = prop_pos
        k = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * k + 4 * k * ns
        k = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * k + 4 * k * nn
        k = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * k + 4 * k * nl
        self.nsv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * self.nsv
        self.nnv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * self.nnv
        self.nlv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * self.nlv
        self.nyv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * self.nyv
        self.start, self.step = struct.unpack_from("<di", b, p)
        self.bpp = 8 + 4 * (ns * self.nsv + nn * self.nnv + nl * self.nlv + self.nyv)

    def subcatch(self, j, var):
        """time series of subcatchment j variable var (0 rain,2 evap,3 infil,4 runoff)."""
        vals = []
        base = self.out_pos + 8 + 4 * (j * self.nsv + var)
        for t in range(self.nper):
            vals.append(struct.unpack_from("<f", self.b, base + t * self.bpp)[0])
        return vals

def runoff_depth_series(out):
    """runoff depth (in) per reporting period for the single 1-acre subcatchment."""
    q = out.subcatch(0, 4)              # cfs at end of each period
    dt = out.step
    return [qi * dt / AREA_FT2 * 12.0 for qi in q]

# ---- LID report reader -----------------------------------------------------------
def lid_report(path):
    """Return list of dict rows from a SWMM 5.2 LID report file."""
    rows, hdr = [], None
    for line in open(path):
        s = line.strip()
        if not s:
            continue
        if s.startswith("Date") and "Time" in s:
            hdr = "date"
            continue
        if hdr and re.match(r"\d{1,2}/\d{1,2}/\d{4}", s):
            parts = s.split()
            nums = [float(x) for x in parts[2:]]
            rows.append(dict(date=parts[0], time=parts[1], v=nums))
    return rows
