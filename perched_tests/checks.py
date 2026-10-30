"""
Controls and side calculations.

1. Null-effect control: H0r (RECOVERY pattern of all 1.0) must reproduce H0 byte for byte.
2. Repeat run: the same .inp run twice must give a byte-identical .out.
3. Two descriptions: .out-integrated runoff vs .rpt Surface Runoff (done in run_season.py).
4. Green-Ampt ceiling: how much water a compacted sandy-clay layer at field capacity can
   take in during a storm if its top is ponded the whole time (an upper bound on what the
   LID storage "bucket" is allowed to swallow instantly).
"""
import filecmp, glob, os, shutil, subprocess, math, json
import swmmlab as S

def same(a, b):
    return filecmp.cmp(a, b, shallow=False)

out = {}
# 1. null-effect control, every Experiment A case and both Experiment B seasons
pairs = 0; identical = 0
for f in glob.glob("runs_A/H0_*_with.out") + glob.glob("runs_A/H0_*_without.out") + glob.glob("runs_B/H0_*.out"):
    g = f.replace("/H0_", "/H0r_")
    pairs += 1
    identical += same(f, g)
out["null_effect_H0_vs_H0r"] = f"{identical} of {pairs} .out pairs byte-identical"

# 2. repeat runs
rep = []
for f in ["runs_A/L0_Jan_D3_P1_with.inp", "runs_A/H0_Jul_D2_P2_with.inp", "runs_B/L2_dormant.inp"]:
    g = f.replace(".inp", "_repeat.inp")
    shutil.copy(f, g)
    S.run(g)
    rep.append(same(f.replace(".inp", ".out"), g.replace(".inp", ".out")))
out["repeat_runs_identical"] = rep

# 4. Green-Ampt ceiling into compacted SaCl at field capacity, ponded top
K = S.SUB["ksat"]; psi = S.SUB["suct"]; dth = S.SUB["por"] - S.SUB["fc"]
def ga_F(t_hr):
    a = psi * dth
    F = max(math.sqrt(2 * a * K * t_hr), K * t_hr)
    for _ in range(60):
        g = F - a * math.log(1 + F / a) - K * t_hr
        dg = 1 - a / (a + F)
        F -= g / dg
    return F
out["GA_ceiling_in"] = {f"{h} h": round(ga_F(h), 2) for h in (6, 12, 24, 48, 72)}
out["GA_psi_dtheta_in"] = round(psi * dth, 3)
out["SaCl_unit_gradient_in_per_day"] = round(K * 24, 2)
out["L0_bucket_capacity_in"] = round(S.SUB["thick"] * S.SUB["por"], 2)
out["L1_bucket_capacity_in"] = round(S.SUB["thick"] * (S.SUB["por"] - S.SUB["fc"]), 2)
out["topsoil_drainable_in"] = S.TOP_DRAINABLE
out["topsoil_to_wilting_in"] = S.TOP_TO_WP
out["Horton_kd_per_hr"] = round(S.VARIANTS["H0"][1]["kd"], 4)
out["Horton_recovered_fraction_vs_days"] = {d: round(1 - math.exp(math.log(0.02) / 7 * d), 3) for d in (0.5, 1, 2, 3, 5, 7)}
json.dump(out, open("checks.json", "w"), indent=1)
print(json.dumps(out, indent=1))
