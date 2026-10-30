# twolayer-base branch

The **general-purpose** two-layer subcatchment infiltration, without the
STRUCT decay parameter that the `main` branch adds for construction-site
perched water tables.

## What's here

| File | Purpose |
|------|---------|
| `src/solver/lid_twolayer.c` | Standalone two-layer engine module (465 lines) |
| `src/solver/lid_twolayer.h` | Header — state structures, function prototypes |
| `examples/TwoLayer_LID_Example.inp` | 3-subcatchment working example |
| `doc/BUILD_GUIDE.md` | Line-by-line integration against EPA SWMM 5.2.4 |
| `doc/TwoLayer_LID_Integration_Guide.md` | Pseudo-diffs for each modified file |
| `doc/TwoLayer_Infiltration.docx` | Full technical write-up |

## How it differs from main

| | `twolayer-base` (this branch) | `main` (perched) |
|---|---|---|
| Approach | Standalone `lid_twolayer.c` module | Patches in `lid.c` / `lidproc.c` |
| SOIL2 keyword | Yes | Yes |
| STRUCT keyword | No | Yes — structural porosity decay |
| UseAsInfil flag | Yes — in [LID_USAGE] | No — activates via SOIL2 presence |
| Infiltration method | Green-Ampt surface + LID perc | LID biocell flux rates |
| Lines touching EPA code | ~51 | ~310 (patch) |

Both branches share the SOIL2 keyword and the LID percolation equation
`perc = Ksat × exp(−15 × (1 − θ/n))`.

## Origin

Created February 2026, originally at `dickinsonre/swmm5-dickinson`
(now archived). Moved here October 2026.

## AI Use

Engine code, integration guide, build guide, example INP, and documentation
were written with Claude (Anthropic). The two-layer approach — reusing the
LID soil parser — was Robert Dickinson's idea.
