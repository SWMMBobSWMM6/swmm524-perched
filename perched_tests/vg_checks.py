"""
Experiment G (part 1) -- checks of the van Genuchten option in swmm524-perched.

  G1 closed column: no rain, no ET, seepage 0.  The heads must come to rest with
     drive = (h1 - h2)/dz + 1 = 0 (computed here in Python from the same vG
     formulas), and theta1*L1 + theta2*L2 must not change.  The topsoil HCO is
     set to 10 for this test only, so K near field capacity is large enough for
     the flow to stay above SWMM's MINFLOW (0.001 in/hr) while the heads close;
     the LID report stops writing rows below MINFLOW.
  G2 drying column: both layers start saturated, no rain, no seepage, ET on.
     SOIL2 has no ET of its own in VG mode, so any loss from it is upward flow.
  G3 the same with GMAX tiny: SOIL2 must keep its water.
"""
import datetime as dt, json, math, os, re
import swmmlab as S

OUT = "runs_G"
L1, L2 = S.TOP["thick"], S.SUB["thick"]

def h(theta, thr, ths, a_in, n):
    m = 1 - 1 / n
    se = (theta - thr) / (ths - thr)
    if se >= 1: return 0.0
    se = max(se, 1e-6)
    return -((se ** (-1 / m) - 1) ** (1 / n)) / a_in            # inches

def drive(t1, t2):
    h1 = h(t1, S.VG_TOP[0], S.TOP["por"], S.VG_TOP[1], S.VG_TOP[2])
    h2 = h(t2, S.VG_SACL[0], S.SUB["por"], S.VG_SACL[1], S.VG_SACL[2])
    return (h1 - h2) / (0.5 * (L1 + L2)) + 1.0, h1, h2

def lid_rows(path):
    rows = []
    for line in open(path):
        p = line.rstrip("\n").split("\t")
        if len(p) < 13 or not re.match(r"\s*\d\d/\d\d/\d{4}", p[0]): continue
        v = [float(x) for x in p[1:]]
        rows.append(dict(hours=v[0], evap=v[2], soilperc=v[5], exfil=v[6], theta1=v[11], theta2=v[12]))
    return rows

def column(name, initsat, evap, km="EXP", gmax=None, days=60, top_hco=None):
    vg = dict(soil=S.VG_TOP + (km,), soil2=S.VG_SACL + (km,))
    if gmax is not None: vg["gmax"] = gmax
    top = dict(S.TOP, hco=top_hco) if top_hco is not None else None
    v = S.perched(seep=0.0, soil2=dict(suct=10.08), vg=vg, top=top)
    inp = f"{OUT}/{name}.inp"; lr = os.path.abspath(f"{OUT}/{name}_lid.txt")
    start = dt.datetime(2026, 6, 1)
    S.write_inp(inp, v, start, start + dt.timedelta(days=days), [], lid_rpt=lr, title=name)
    t = open(inp).read()
    t = t.replace(f"S1  TOP  1  {S.AREA_FT2}  {S.WIDTH}  0  0  0", f"S1  TOP  1  {S.AREA_FT2}  {S.WIDTH}  {initsat}  0  0")
    t = re.sub(r"\[EVAPORATION\]\nMONTHLY [^\n]*", f"[EVAPORATION]\nCONSTANT {evap}", t)
    open(inp, "w").write(t)
    rpt, out, p = S.run(inp, S.PERCHED_ENGINE)
    err = re.findall(r"ERROR[^\n]*", open(rpt).read())
    rows = lid_rows(lr)
    rc = S.runoff_continuity(rpt)
    m = re.search(r"S1\s+TOP\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", open(rpt).read())
    lid = dict(zip(["inflow", "evap", "infil", "surf_out", "drain", "init_stor", "final_stor", "cont"], map(float, m.groups()))) if m else {}
    return dict(rows=rows, cont=rc.get("Continuity Error (%)"), evap=rc.get("Evaporation Loss"), errors=err, inp=inp, lid=lid)

def run_checks(outdir=None):
    """Run G1-G3 and return the results dict (written to vg_checks.json by __main__)."""
    global OUT
    if outdir:
        OUT = outdir
    os.makedirs(OUT, exist_ok=True)
    res = {}
    # G1 closed column, EXP and MUALEM K
    for km in ("EXP", "MUALEM"):
        r = column(f"G1_closed_{km}", 50, 0.0, km, top_hco=10.0)
        if not r["rows"]:
            # MUALEM K at this state is below MINFLOW from the first step, so the LID
            # report has no rows; only the mass check from the LID summary applies.
            res[f"G1_{km}"] = dict(note="no LID report rows: every flow below MINFLOW", lid_summary=r["lid"], cont=r["cont"], errors=r["errors"])
            continue
        a, b = r["rows"][0], r["rows"][-1]
        th1_0 = S.TOP["wp"] + 0.5 * (S.TOP["por"] - S.TOP["wp"]); th2_0 = S.SUB["wp"] + 0.5 * (S.SUB["por"] - S.SUB["wp"])
        d0, h10, h20 = drive(th1_0, th2_0); d1, h11, h21 = drive(b["theta1"], b["theta2"])
        res[f"G1_{km}"] = dict(start=dict(theta1=th1_0, theta2=th2_0, drive=round(d0, 3), h1=round(h10, 1), h2=round(h20, 1)),
                               end=dict(theta1=b["theta1"], theta2=b["theta2"], drive=round(d1, 4), h1=round(h11, 2), h2=round(h21, 2)),
                               water_in_start=round(th1_0 * L1 + th2_0 * L2, 4), water_in_end=round(b["theta1"] * L1 + b["theta2"] * L2, 4),
                               cont=r["cont"], errors=r["errors"], last_row_hours=b["hours"], lid_summary=r["lid"])
    # G2 drying column, ET 0.2 in/day; G3 same with GMAX tiny
    for name, gmax in (("G2_drying", None), ("G3_no_upward", 1e-9)):
        r = column(name, 100, 0.2, "EXP", gmax)
        rows = r["rows"]; a, b = rows[0], rows[-1]
        up = [x for x in rows if x["soilperc"] < 0]
        res[name] = dict(theta1_start=a["theta1"], theta1_end=b["theta1"], theta2_start=a["theta2"], theta2_end=b["theta2"],
                         soil2_loss_in=round((a["theta2"] - b["theta2"]) * L2, 3), lid_evap_in=r["evap"],
                         rows_with_upward_flow=len(up), max_upward_in_hr=round(-min([x["soilperc"] for x in rows] + [0]), 5),
                         cont=r["cont"], errors=r["errors"], lid_summary=r["lid"])
    return res

def assertions(res):
    """The four pass/fail statements verify.py checks. Returns [(name, ok, detail)]."""
    out = []
    g = res.get("G1_EXP", {})
    ok = bool(g.get("end")) and abs(g["end"]["drive"]) < 0.05 and abs(g["water_in_end"] - g["water_in_start"]) < 0.02 and not g["errors"]
    out.append(("G1 closed column (EXP): heads come to rest, water kept", ok,
                f"end drive {g.get('end', {}).get('drive')}, water {g.get('water_in_start')} -> {g.get('water_in_end')} in"))
    g = res.get("G1_MUALEM", {}); s = g.get("lid_summary", {})
    ok = bool(s) and abs(s["init_stor"] - s["final_stor"]) < 0.02 and not g.get("errors")
    out.append(("G1 closed column (Mualem): storage unchanged", ok, f"{s.get('init_stor')} -> {s.get('final_stor')} in"))
    g = res.get("G2_drying", {})
    ok = bool(g) and g["rows_with_upward_flow"] > 0 and g["soil2_loss_in"] > 0 and abs(g["cont"] or 0) < 0.01 and not g["errors"]
    out.append(("G2 drying column: SOIL2 loses water only by upward flow", ok,
                f"{g.get('rows_with_upward_flow')} upward rows, SOIL2 loss {g.get('soil2_loss_in')} in, continuity {g.get('cont')} %"))
    g = res.get("G3_no_upward", {})
    ok = bool(g) and g["soil2_loss_in"] == 0 and g["rows_with_upward_flow"] == 0 and not g["errors"]
    out.append(("G3 GMAX ~ 0: SOIL2 keeps its water", ok, f"SOIL2 loss {g.get('soil2_loss_in')} in"))
    return out

if __name__ == "__main__":
    res = run_checks()
    json.dump(res, open("vg_checks.json", "w"), indent=1)
    for name, ok, detail in assertions(res):
        print("PASS" if ok else "FAIL", name, "|", detail)
