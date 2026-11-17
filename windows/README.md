# Two engines: EPA SWMM 5.2.4 and swmm524-perched (Windows x64)

Two command-line engines, built the same way from pinned sources, plus a script that runs an input through both and puts the answers side by side.

- Robert Dickinson on GitHub: https://github.com/dickinsonre and https://github.com/SWMMBobSWMM6
- The topsoil engine's source, tests and examples: https://github.com/SWMMBobSWMM6/swmm524-perched/tree/van-genuchten
- This folder on GitHub: https://github.com/SWMMBobSWMM6/swmm524-perched/tree/van-genuchten/windows
- EPA SWMM 5.2.4: https://github.com/USEPA/Stormwater-Management-Model/tree/v5.2.4

| File | Engine | Source |
|---|---|---|
| `runswmm-524.exe` | EPA SWMM 5.2.4 | USEPA/Stormwater-Management-Model, tag v5.2.4, commit 7952ca837988b1c32f791812eccc9fd64547e093, unchanged |
| `runswmm-perched.exe` | swmm524-perched (5.2.4 + SOIL2, VG, STRUCT lines) | SWMMBobSWMM6/swmm524-perched, branch van-genuchten, commit 548e5fbf8763cc856bfe947b2aa51fa926afde36 |

Both: Zig 0.17.0 (clang), target x86_64-windows-gnu, `-O2 -fno-fast-math -ffp-contract=off`, all solver files and `src/run/main.c` linked into one executable, no DLL. Hashes in `SHA256SUMS`. The executables are not code-signed, so Windows SmartScreen may ask before the first run.

## Run one engine

```
runswmm-524.exe     model.inp model.rpt model.out
runswmm-perched.exe model.inp model.rpt model.out
```

## Compare the two (Python 3.8 or later, standard library only)

```
python compare.py examples\*.inp
python compare.py C:\models\mysite.inp
python compare.py C:\models\mysite.inp --same-file
```

For each input it writes a `compare_out` folder beside the input with both `.rpt` and `.out` files and `compare_<model>.txt`, and prints:

- whether each engine ran clean, with any ERROR or WARNING lines;
- whether the two `.out` files are byte-identical;
- runoff continuity, the LID Performance Summary, each subcatchment's total runoff, peak and runoff coefficient, and flow routing outflow, for both engines and the difference;
- the largest difference in subcatchment runoff at any report step, read from the `.out` files.

## Inputs with SOIL2, VG or STRUCT lines

EPA 5.2.4 does not reject a `SOIL2` line. Its keyword match accepts any word that starts with a known keyword (`match()` in `input.c`), so `SOIL2` matches `SOIL`, and the clay line silently replaces the topsoil:

```c
char* LidLayerWords[] =
    {"SURFACE", "SOIL", "STORAGE", "PAVEMENT", "DRAINMAT", "DRAIN",
     "REMOVALS", NULL};
...
    else m = findmatch(toks[1], LidLayerWords);        // lid.c line 397
```

A `VG` line is ERROR 205. So `compare.py` gives 5.2.4 a copy without those lines (`compare_out\<model>.for-5.2.4.inp`) and prints what it removed and the storage-layer seepage 5.2.4 will use. With a zero-thickness storage layer and seepage equal to the clay's Ksat, that copy is the "LID, no storage layer, seepage = clay Ksat" setup of the Topsoil Recovery Check. `--same-file` turns the copy off, to see the misread.

## The examples (winter season, Nov to Mar, 15-minute report step)

| Example | What it shows | Surface runoff, 5.2.4 / perched |
|---|---|---|
| `topsoil_no_soil2.inp` | No perched-only line: the engines agree byte for byte | 3.400 / 3.400 in |
| `topsoil_soil2.inp` | 4 in topsoil over 24 in compacted sandy clay, SOIL2 line | 3.400 / 2.869 in |
| `topsoil_soil2.inp --same-file` | 5.2.4 reads SOIL2 as SOIL: the clay becomes the topsoil, no error | 13.521 / 2.869 in |
| `topsoil_soil2_vg.inp` | The same with the van Genuchten lines | 3.400 / 4.324 in |
| `drain_no_storage_layer.inp` | Defect D2: a DRAIN line with no storage layer makes water in both engines. With no SOIL2 line the perched engine runs 5.2.4's own bio-retention routine; it ignores DRAIN lines only when the model has a SOIL2 line | 3.400 / 3.400 in; drain 232.848 in from 20.550 in of rain, continuity -1,100.919 % |

Rain over the season is 20.550 in in every example.

## Checks done on these builds (17 Nov 2026)

- The Windows executables, run under Wine 9.0, wrote `.out` files byte-identical to Linux builds made the same way, on all eight example runs.
- The Linux builds reproduced every stored number in the Topsoil Recovery Check's `verify.py` (season 46, ablation 18, VG checks 4, 8 in storm 7, Experiment H 54) and the parity check: with no SOIL2, VG or STRUCT line, the two engines wrote byte-identical `.out` files and LID reports on 930 of 930 inputs. 1,059 of 1,059 cases passed.
- Not yet run on a Windows machine itself.

## AI use

Claude (Anthropic) built these executables, wrote `compare.py` and this README, and ran the checks above, at Robert Dickinson's request. The swmm524-perched engine change was also written by Claude for him.
