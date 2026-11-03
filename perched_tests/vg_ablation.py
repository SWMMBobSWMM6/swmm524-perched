"""
Experiment G (part 3) -- what in the van Genuchten option moves the season result?

The VG option changes several things at once compared with the perched engine.
Each VG OPTION line puts one perched-engine assumption back, so each run below
differs from full VG (P1vg) in exactly one respect:

  TOPFC    topsoil drains only above field capacity (perched rule)
  FCDRAIN  SOIL2 drains only above field capacity (perched rule)
  SOIL2ET  SOIL2 loses water to ET directly (perched rule)
  GMAX 0   no upward flow (perched has none)
  FCHEAD   Green-Ampt perched head from field capacity (perched rule)
  STEP     downward flux = K1 for any positive drive (the outline's rule)

"all perched rules" applies TOPFC + FCDRAIN + SOIL2ET + no upward + FCHEAD:
what is left is the head-driven downward rule and the vG retention itself.
Same synthetic seasons and scoring as run_season.py.
"""
import json, os
from multiprocessing import Pool
import swmmlab as S
import run_season as R

VG = dict(soil=S.VG_TOP + ("EXP",), soil2=S.VG_SACL + ("EXP",))
def vg(**kw):
    d = dict(VG); d.update(kw); return d
CASES = {
    "A_P1":      ("Perched engine (no VG)", S.perched()),
    "A_VG":      ("Full VG", S.perched(vg=vg())),
    "A_TOPFC":   ("VG + topsoil FC floor", S.perched(vg=vg(options=["TOPFC"]))),
    "A_FCDRAIN": ("VG + SOIL2 FC floor", S.perched(vg=vg(options=["FCDRAIN"]))),
    "A_SOIL2ET": ("VG + direct SOIL2 ET", S.perched(vg=vg(options=["SOIL2ET"]))),
    "A_NOUP":    ("VG + no upward flow", S.perched(vg=vg(gmax=1e-09))),
    "A_FCHEAD":  ("VG + FC-based perched head", S.perched(vg=vg(options=["FCHEAD"]))),
    "A_STEP":    ("VG with the outline's step rule", S.perched(vg=vg(options=["STEP"]))),
    "A_ALLP":    ("VG + all perched rules", S.perched(vg=vg(gmax=1e-09, options=["TOPFC", "FCDRAIN", "SOIL2ET", "FCHEAD"]))),
}

if __name__ == "__main__":
    for k, (d, v) in CASES.items():
        S.VARIANTS[k] = (d, v)
    os.makedirs(R.RUNS, exist_ok=True)
    jobs = [(k, s) for k in CASES for s in R.SEASONS]
    with Pool(2) as pool:
        res = pool.map(R.case, jobs)
    bad = [r for r in res if "error" in r]
    if bad:
        print("ERRORS", bad); raise SystemExit(1)
    out = []
    for k, (d, v) in CASES.items():
        dd = next(r for r in res if r["variant"] == k and r["season"] == "dormant")
        gg = next(r for r in res if r["variant"] == k and r["season"] == "growing")
        out.append(dict(key=k, desc=d, dormant=dd["big_capture_pct"], growing=gg["big_capture_pct"],
                        dormant_all=dd["eval_capture_pct"], growing_all=gg["eval_capture_pct"],
                        cont=max(abs(dd["cont_err"]), abs(gg["cont_err"]))))
    json.dump(out, open("vg_ablation.json", "w"), indent=1)
    full = next(o for o in out if o["key"] == "A_VG")
    print(f"{'case':34} {'dormant':>8} {'vs VG':>7} {'growing':>8} {'vs VG':>7} {'cont%':>6}")
    for o in out:
        print(f"{o['desc']:34} {o['dormant']:8.1f} {o['dormant']-full['dormant']:+7.1f} {o['growing']:8.1f} {o['growing']-full['growing']:+7.1f} {o['cont']:6.3f}")
