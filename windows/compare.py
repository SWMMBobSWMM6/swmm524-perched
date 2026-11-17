"""
compare.py -- run one SWMM input through EPA SWMM 5.2.4 and through swmm524-perched,
and put the answers side by side.

    python compare.py model.inp [more.inp ...]
    python compare.py model.inp --same-file      # give 5.2.4 the input exactly as written

The two engines sit next to this script: runswmm-524(.exe) and runswmm-perched(.exe).
Results go to a folder compare_out beside each input: both .rpt files, both .out files,
the input 5.2.4 actually ran, and compare_<model>.txt with the table printed here.

Inputs with SOIL2, VG or STRUCT lines.  EPA 5.2.4 does not know these lines, and it does
not reject a SOIL2 line: its keyword match accepts any word that starts with SOIL, so a
SOIL2 line silently replaces the SOIL layer with the clay.  A VG line is ERROR 205.  So by
default 5.2.4 gets a copy with those lines removed: the bio-retention cell keeps its
topsoil, and whatever STORAGE line it has stays as written.  With a zero-thickness storage
layer whose seepage equals the clay's Ksat, that copy is the "no storage layer, seepage =
clay Ksat" setup of the Topsoil Recovery Check.  The script prints the lines it removed and
the seepage 5.2.4 will use.  --same-file skips the copy.

Standard library only; Python 3.8 or later.
Written by Claude (Anthropic) for Robert Dickinson, November 2026.
"""
import argparse, glob, os, re, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = ".exe" if os.name == "nt" else ""
PERCHED_ONLY = ("SOIL2", "VG", "STRUCT")

# ------------------------------------------------------------------ input handling
def perched_lines(text):
    """[LID_CONTROLS] lines that only swmm524-perched understands."""
    out, sect = [], None
    for i, line in enumerate(text.splitlines()):
        s = line.split(";")[0].strip()
        if s.startswith("["):
            sect = s.upper(); continue
        if sect == "[LID_CONTROLS]" and s:
            tok = s.split()
            if len(tok) > 1 and tok[1].upper() in PERCHED_ONLY:
                out.append((i, line))
    return out

def storage_and_soil2(text):
    """Per LID: STORAGE seepage and SOIL2 Ksat, as written."""
    info, sect = {}, None
    for line in text.splitlines():
        s = line.split(";")[0].strip()
        if s.startswith("["):
            sect = s.upper(); continue
        if sect != "[LID_CONTROLS]" or not s:
            continue
        tok = s.split()
        if len(tok) > 1 and tok[1].upper() == "STORAGE" and len(tok) >= 5:
            info.setdefault(tok[0], {})["storage"] = (tok[2], tok[4])          # thickness, seepage
        if len(tok) > 1 and tok[1].upper() == "SOIL2" and len(tok) >= 7:
            info.setdefault(tok[0], {})["soil2_ksat"] = tok[6]
    return info

# ------------------------------------------------------------------ report parsing
NUM = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"

def after_title(txt, title):
    """Lines after the line that carries a report section title."""
    lines = txt.splitlines()
    for i, l in enumerate(lines):
        if l.strip().startswith(title):
            return lines[i + 1:]
    return []

def continuity(txt, title):
    rows = {}
    for line in after_title(txt, title):
        if not line.strip():
            if rows:
                break
            continue
        m = re.match(r"\s*([A-Za-z][A-Za-z %()/]*?)\s*\.{2,}\s*(" + NUM + r")(?:\s+(" + NUM + r"))?", line)
        if m:
            rows[m.group(1).strip()] = [float(m.group(2))] + ([float(m.group(3))] if m.group(3) else [])
    return rows

def rows_after_dashes(txt, title, nnum, nname):
    """Data rows of a dashed SWMM table: nname name columns then nnum numbers."""
    lines = after_title(txt, title)
    dashes = [i for i, l in enumerate(lines[:40]) if re.match(r"\s*-{10,}\s*$", l)]
    if len(dashes) < 2:
        return {}
    out = {}
    for l in lines[dashes[1] + 1:]:
        if re.match(r"\s*-{10,}\s*$", l) or not l.strip():
            break
        tok = l.split()
        if len(tok) >= nname + nnum:
            try:
                out[" ".join(tok[:nname])] = [float(x) for x in tok[nname:nname + nnum]]
            except ValueError:
                pass
    return out

def read_report(path):
    if not os.path.exists(path):
        return dict(missing=True)
    txt = open(path, errors="replace").read()
    ver = next((l.strip() for l in txt.splitlines() if "VERSION" in l or "Build" in l), "?")
    msgs = [l.strip() for l in txt.splitlines() if re.match(r"\s*(ERROR|WARNING)\b", l)]
    return dict(missing=False, version=ver, messages=msgs,
                runoff=continuity(txt, "Runoff Quantity Continuity"),
                routing=continuity(txt, "Flow Routing Continuity"),
                lid=rows_after_dashes(txt, "LID Performance Summary", 8, 2),
                subcatch=rows_after_dashes(txt, "Subcatchment Runoff Summary", 10, 1))

# ------------------------------------------------------------------ .out reading
def read_out(path):
    """Subcatchment runoff (cfs) series from a SWMM 5 binary output file."""
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        return None
    b = open(path, "rb").read()
    magic, ver, fu, ns, nn, nl, npol = struct.unpack_from("<7i", b, 0)
    id_pos, prop_pos, out_pos, nper, err, magic2 = struct.unpack_from("<6i", b, len(b) - 24)
    if magic != 516114522 or magic2 != 516114522:
        return None
    p = prop_pos
    for n in (ns, nn, nl):
        k = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * k + 4 * k * n
    nsv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * nsv
    nnv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * nnv
    nlv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * nlv
    nyv = struct.unpack_from("<i", b, p)[0]; p += 4 + 4 * nyv
    start, step = struct.unpack_from("<di", b, p)
    bpp = 8 + 4 * (ns * nsv + nn * nnv + nl * nlv + nyv)
    series = []
    for j in range(ns):
        base = out_pos + 8 + 4 * (j * nsv + 4)              # variable 4 = runoff
        series.append([struct.unpack_from("<f", b, base + t * bpp)[0] for t in range(nper)])
    return dict(step=step, nper=nper, runoff=series, bytes=b)

# ------------------------------------------------------------------ running
def run(engine, inp, rpt, out):
    for f in (rpt, out):
        if os.path.exists(f):
            os.remove(f)
    p = subprocess.run([engine, inp, rpt, out], capture_output=True, text=True)
    return p.returncode

def fmt(v):
    return "-" if v is None else (f"{v:,.3f}" if abs(v) < 1e6 else f"{v:,.0f}")

def compare(inp, args):
    inp = os.path.abspath(inp)
    stem = os.path.splitext(os.path.basename(inp))[0]
    od = os.path.join(os.path.dirname(inp), "compare_out")
    os.makedirs(od, exist_ok=True)
    text = open(inp, errors="replace").read()
    lines_out = []
    say = lambda s="": (print(s), lines_out.append(s))

    say(f"== {os.path.basename(inp)}")
    pl = perched_lines(text)
    stock_inp = inp
    if pl and not args.same_file:
        keep = text.splitlines()
        drop = {i for i, _ in pl}
        stock_inp = os.path.join(od, stem + ".for-5.2.4.inp")
        open(stock_inp, "w").write("\n".join(l for i, l in enumerate(keep) if i not in drop) + "\n")
        say(f"   5.2.4 runs a copy without {len(pl)} perched-only line(s):")
        for _, l in pl:
            say("     - " + l.strip())
        for lid, d in storage_and_soil2(text).items():
            if "storage" in d:
                th, sp = d["storage"]
                say(f"   LID {lid}: 5.2.4 storage layer thickness {th} in, seepage {sp} in/hr"
                    + (f"; SOIL2 Ksat in the perched run {d['soil2_ksat']} in/hr" if "soil2_ksat" in d else ""))
    elif pl:
        say(f"   --same-file: 5.2.4 gets the input as written, with {len(pl)} perched-only line(s).")
        say("   A SOIL2 line will replace its SOIL layer; a VG line is ERROR 205.")
    else:
        say("   No SOIL2, VG or STRUCT line: both engines run the same file and should agree byte for byte.")

    res = {}
    for tag, eng in (("5.2.4", args.stock), ("perched", args.perched)):
        src = stock_inp if tag == "5.2.4" else inp
        rpt, out = os.path.join(od, f"{stem}.{tag}.rpt"), os.path.join(od, f"{stem}.{tag}.out")
        rc = run(eng, src, rpt, out)
        res[tag] = dict(rc=rc, rpt=read_report(rpt), out=read_out(out), rpt_path=rpt)

    for tag in res:
        r = res[tag]
        state = "no report" if r["rpt"]["missing"] else (f"{len(r['rpt']['messages'])} error/warning line(s)" if r["rpt"]["messages"] else "ran clean")
        say(f"   {tag:8} exit {r['rc']}, {state}")
        for m in (r["rpt"].get("messages") or [])[:5]:
            say("            " + m)

    a, b = res["5.2.4"], res["perched"]
    if a["out"] and b["out"]:
        same = a["out"]["bytes"] == b["out"]["bytes"]
        say(f"   .out files: {'byte-identical' if same else 'differ'}")
    say()
    say(f"   {'Quantity':46} {'EPA 5.2.4':>12} {'perched':>12} {'perched - 5.2.4':>16}")
    def row(label, x, y):
        d = None if (x is None or y is None) else y - x
        say(f"   {label:46} {fmt(x):>12} {fmt(y):>12} {fmt(d):>16}")
    ra, rb = a["rpt"].get("runoff", {}), b["rpt"].get("runoff", {})
    for k in list(dict.fromkeys(list(ra) + list(rb))):
        x, y = ra.get(k), rb.get(k)
        row(f"Runoff continuity: {k}" + (" (in)" if (x or y) and len(x or y) > 1 else ""),
            (x[-1] if x else None), (y[-1] if y else None))
    la, lb = a["rpt"].get("lid", {}), b["rpt"].get("lid", {})
    names = ["Total inflow", "Evap loss", "Infil loss", "Surface outflow", "Drain outflow", "Initial storage", "Final storage", "Continuity error %"]
    for k in list(dict.fromkeys(list(la) + list(lb))):
        for n, nm in enumerate(names):
            x = la[k][n] if k in la else None; y = lb[k][n] if k in lb else None
            unit = "" if nm.endswith("%") else " (in)"
            row(f"LID {k}: {nm}{unit}", x, y)
    sa, sb = a["rpt"].get("subcatch", {}), b["rpt"].get("subcatch", {})
    for k in list(dict.fromkeys(list(sa) + list(sb))):
        x, y = sa.get(k), sb.get(k)
        row(f"Subcatchment {k}: total runoff (in)", x[6] if x else None, y[6] if y else None)
        row(f"Subcatchment {k}: peak runoff (cfs)", x[8] if x else None, y[8] if y else None)
        row(f"Subcatchment {k}: runoff coefficient", x[9] if x else None, y[9] if y else None)
    if a["out"] and b["out"] and a["out"]["nper"] == b["out"]["nper"]:
        for j, (qa, qb) in enumerate(zip(a["out"]["runoff"], b["out"]["runoff"])):
            dmax = max((abs(x - y) for x, y in zip(qa, qb)), default=0.0)
            say(f"   {'Subcatchment #%d: largest runoff difference' % (j + 1):46} {'':>12} {'':>12} {dmax:>12,.4f} cfs")
            say(f"   {'  (any report step, from the .out files)':46}")
    rta, rtb = a["rpt"].get("routing", {}), b["rpt"].get("routing", {})
    for k in ("External Outflow", "Continuity Error (%)"):
        if k in rta or k in rtb:
            x, y = rta.get(k), rtb.get(k)
            row(f"Flow routing: {k}" + (" (ac-ft)" if "%" not in k else ""), x[0] if x else None, y[0] if y else None)
    say()
    open(os.path.join(od, f"compare_{stem}.txt"), "w").write("\n".join(lines_out) + "\n")
    return 0 if (a["rc"] == 0 and b["rc"] == 0) else 1

def main():
    ap = argparse.ArgumentParser(description="Run SWMM inputs through EPA 5.2.4 and swmm524-perched and compare the answers.")
    ap.add_argument("inp", nargs="+", help="SWMM .inp file(s)")
    ap.add_argument("--same-file", action="store_true", help="give 5.2.4 the input exactly as written")
    ap.add_argument("--stock", default=os.path.join(HERE, "runswmm-524" + EXE), help="EPA SWMM 5.2.4 command-line engine")
    ap.add_argument("--perched", default=os.path.join(HERE, "runswmm-perched" + EXE), help="swmm524-perched command-line engine")
    args = ap.parse_args()
    for e in (args.stock, args.perched):
        if not os.path.exists(e):
            print("engine not found:", e); return 2
    files = []
    for f in args.inp:                       # Windows cmd does not expand *.inp itself
        files += sorted(glob.glob(f)) if any(c in f for c in "*?") else [f]
    if not files:
        print("no input files"); return 2
    rc = 0
    for f in files:
        rc |= compare(f, args)
    return rc

if __name__ == "__main__":
    sys.exit(main())
