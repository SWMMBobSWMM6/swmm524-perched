"""
Parity contract: with no SOIL2/STRUCT lines, swmm524-perched must write the
same .out bytes as EPA SWMM 5.2.4 for every input already in this study.
"""
import glob, os, subprocess, filecmp, sys
from multiprocessing import Pool

STOCK = "/root/swmm524/build/bin/Release/runswmm"
PERCH = "/root/swmm524-perched/build/bin/Release/runswmm"
OUT = "runs_parity"

def one(inp):
    base = os.path.join(OUT, os.path.basename(inp)[:-4])
    a = (base + "_stock.rpt", base + "_stock.out")
    b = (base + "_perch.rpt", base + "_perch.out")
    subprocess.run([STOCK, inp, *a], capture_output=True)
    subprocess.run([PERCH, inp, *b], capture_output=True)
    same = os.path.exists(a[1]) and filecmp.cmp(a[1], b[1], shallow=False)
    os.remove(a[1]); os.remove(b[1]); os.remove(a[0]); os.remove(b[0])
    return inp, same

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob("runs_A/*.inp") + glob.glob("runs_B/*.inp"))
    files = [f for f in files if "_repeat" not in f]
    with Pool(os.cpu_count()) as p:
        res = p.map(one, files)
    bad = [f for f, s in res if not s]
    print(f"{len(res) - len(bad)} of {len(res)} .out files byte-identical")
    for f in bad[:10]:
        print("DIFF", f)
