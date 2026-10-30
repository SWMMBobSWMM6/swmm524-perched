# swmm524-perched

EPA SWMM 5.2.4 with a **perched two-layer soil** option for bio-retention LIDs. A 4 in decompacted topsoil can now sit over a compacted subsoil that admits water only as fast as its own conductivity allows. Water the subsoil refuses stays in the topsoil, the topsoil saturates from the bottom up, and the next storm runs off.

The change is 310 added lines and 2 changed lines in `lid.c`, `lid.h` and `lidproc.c` (see `PERCHED_CHANGES.patch`). With no `SOIL2` line in the input file, the engine writes **the same `.out` bytes as EPA 5.2.4**: 598 of 598 test inputs, including every stock LID case.

## Why

In stock 5.2.4, a bio-retention cell's soil layer percolates into the storage layer at the soil's own unsaturated conductivity. The only cap is the storage layer's unused volume (`lidproc.c`, `biocellFluxRates`):

```c
            //... limit soil perc by unused storage volume
            maxRate = StorageExfil + StorageDrain + StorageEvap +
                      (storageThickness - storageDepth) *
                      storageVoidFrac/Tstep;
            SoilPerc = MIN(SoilPerc, maxRate);
```

That fits engineered media over gravel. Put compacted clay in the storage layer and it becomes a bucket with no lid. Over a synthetic winter it captured **100 %** of every storm, and it did the same with the clay made impermeable. Modified Horton, the other common setup, recovers infiltration capacity on a drying-time clock regardless of ET or drainage. The question came from soil-decompaction credit work in the Chesapeake Bay watershed.

## Input

Two new lines go under a bio-retention cell (`BC`) in `[LID_CONTROLS]`:

```
TOP  BC
TOP  SURFACE  0.05  0.0  0.0  2.0  5
TOP  SOIL     4   0.50  0.30   0.15   1.0   36  3.5      ; decompacted topsoil
TOP  SOIL2    24  0.43  0.321  0.221  0.01  50  9.45     ; compacted sandy clay
TOP  STORAGE  0   0     0.01   0                         ; only the seepage field is used
TOP  DRAIN    0   0.5   0      6
TOP  STRUCT   0.2 0.02  0.1                              ; optional
```

- **`SOIL2`** takes the same fields as `SOIL`: thickness (in), porosity, field capacity, wilting point, Ksat (in/hr), conductivity slope, suction head (in). It replaces the storage layer.
- **`STORAGE`** keeps only its seepage field, which caps drainage from SOIL2 to the native soil below. Seepage 0 makes the bottom impermeable.
- **`STRUCT`** (optional) takes a decay rate (1/day, applied while the topsoil is within 0.01 of saturation), a recovery rate (1/day, applied while it is at or below field capacity) and a floor (0–1]. The resulting structure factor multiplies the topsoil Ksat for both surface entry and percolation.
- The LID report file gains one header line. In perched mode the *Pavement Level* column holds the structure factor and the *Storage Level* column holds SOIL2 moisture content.

## Physics, step by step

1. **Perched head.** The topsoil holds water above field capacity as a saturated zone at its base:
   h = L1·(θ1 − FC1)/(φ1 − FC1).
2. **Interface capacity, computed once per time step.** SWMM's own Green-Ampt routine (`grnampt_getInfil`, the same code the LID surface uses) runs on the SOIL2 parameters, with the perched head added to the suction head:
   cap = GA(K2, ψ2 + h, IMD ≤ φ2 − θ2).
   Supply is the topsoil's K1(θ1) × structure factor, limited to its drainable water. The GA deficit starts at φ2 − FC2 and can never exceed SOIL2's actual free pore space.
3. **Layer fluxes** (`perchedFluxRates`). Topsoil percolation is min(K1(θ1), cap, SOIL2 free volume). SOIL2 drains at min(K2(θ2), seepage) and never below FC2. ET draws from surface water first, then the topsoil down to WP1, then SOIL2 down to WP2.
4. **SOIL2 storage.** SOIL2 is stored in the existing storage slot as an equivalent depth, θ2 = depth·φ2/L2, so the water balance, limits and continuity code run unchanged.
5. **Structure** (optional). After each step: s ← s_min + (s − s_min)·e^(−kd·Δt) while saturated, and s ← 1 − (1 − s)·e^(−kr·Δt) while at or below FC.

## Controls

| Check | Result |
|---|---|
| No `SOIL2` line, against EPA 5.2.4 (598 inputs: Horton, stock LID storage layer, no-storage LID, impermeable cases) | **598 of 598 `.out` files byte-identical** |
| `STRUCT 0 0 1` against no `STRUCT` | byte-identical `.out` |
| Limiting case: K2 = 1000 in/hr, FC2 ≈ WP2 ≈ 0, no suction. The interface no longer limits, so the result should equal the stock storage-layer bucket. | test-storm runoff difference **0.000 in** across all 64 recovery cases. Both seasons capture 100 %, as stock L0 does. |
| Runoff continuity, perched runs | ≤ 0.003 % |
| `.out`-integrated runoff against `.rpt` total | equal to 0.001 in |

## Results

The site is one acre covered by the LID: 4 in of topsoil (φ 0.50, FC 0.30, WP 0.15, Ksat 1.0 in/hr) over 24 in of compacted sandy clay (φ 0.43, FC 0.321, WP 0.221, suction 9.45 in, Ksat 0.01 in/hr). The synthetic seasons have a storm every 6 days at about 4 in/month and a 61-day spin-up. The scoring windows are Jan–Mar (dormant) and Jul–Sep (growing).

**Storms of 0.75 in and larger captured, dormant / growing:**

| Setup | Capture | Hours topsoil saturated (dormant) |
|---|---|---|
| Modified Horton, 7-day drying | 77 / 78 % | (not tracked) |
| Stock LID, clay as storage layer (total or drainable porosity) | 100 / 100 % | 0 |
| Stock LID, no storage layer, seepage = clay Ksat | 79 / 95 % | 47 |
| **Perched, clay Ksat 0.01 in/hr** | **83 / 97 %** | 34 |
| **Perched, clay Ksat 0.002 in/hr** | **54 / 95 %** | 326 (spells up to 40 h) |
| Perched 0.01 + STRUCT (illustrative) | 82 / 97 % | 37; structure factor falls to 0.72 |
| Perched 0.002 + STRUCT (illustrative) | 51 / 95 % | 327; structure factor falls to 0.11 |

In winter, SOIL2 moisture averaged 0.41 against a porosity of 0.43. The compacted layer sits close to saturation all season, so the interface flux runs near K2. That is the perched regime field HYDRUS profiles show.

The single-event recovery test (`perched_tests/run_recovery.py`) starts the subsoil at its wilting point. That flatters the clay's early sorptivity, so its capture numbers run above the season runs for short dry spells.

## What this does not show

- **No observed data and no HYDRUS comparison yet.** The engine is built so a HYDRUS T-level summary can be laid against it month by month. That comparison is the next test.
- **Not a Richards solver.** Each layer is one moisture bucket. The interface flux comes from Green-Ampt with a perched head, not from a resolved pressure profile. There is no water table position within SOIL2 and no lateral interflow.
- **The `STRUCT` rates are illustrative, not calibrated.** Only Ksat degrades; macropore volume (porosity) does not. That understates the storage lost when structure collapses.
- The Green-Ampt object for SOIL2 keeps its own recovery clock between events, as SWMM's surface Green-Ampt does. Its deficit is clamped to SOIL2's actual free pore space but not otherwise tied to θ2.
- Only `BC` cells. There is no hot-start state for SOIL2 or the structure factor.

## Build and run

```
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS="-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0"
cmake --build . -j
./bin/Release/runswmm ../examples/perched_P1_dormant_season.inp out.rpt out.out
```

On Ubuntu 24 with `_FORTIFY_SOURCE` on, the 5.2.4 command-line build aborts at "Retrieving project data", for stock EPA as well as this engine.

`perched_tests/` holds the harness: the `.inp` writer, the recovery, season and saturation runners, the parity check against a stock 5.2.4 binary, and the result files. Set `SWMM_ENGINE` to a stock 5.2.4 `runswmm` and `SWMM_PERCHED_ENGINE` to this one.

## WebAssembly build

`wasm/build_wasm.sh` compiles the engine to a wasm32-wasi module with Zig's C toolchain (`pip install ziglang`), using `-O2`, no fast-math and no FP contraction. `wasm/wasi_shim.c` supplies `mkstemp`, which wasi-libc lacks; no engine source changes. `wasm/runwasi.mjs` runs it under Node with the same `inp rpt out` arguments as `runswmm`. The browser runner in the Topsoil Recovery Check page drives it through a 16-call in-memory WASI layer.

Parity, measured: against the native build, 53 of 59 `.out` files byte-identical, with runoff totals equal on all 59. The other 6 differ only in the last bits of a few values. Two are stock cases (≤ 2×10⁻¹⁸); four are the stiff K2 = 1000 in/hr limiting case (≤ 0.01 on individual reported rates). With no SOIL2 line, this wasm and a wasm build of stock EPA 5.2.4 wrote byte-identical `.out` files on 25 of 25 inputs.

## Credits and license

The base engine is EPA SWMM 5.2.4 (Lewis Rossman, US EPA), which is public domain; see `README-EPA.md`. The perched option was written for the SWMM Enablement work of Robert Dickinson. Its reference points are soil physics from Nimmo (2004) on textural and structural porosity and Leij, Ghezzehei and Or (2002) on pore-size dynamics after tillage.

**AI use.** Claude (Anthropic) wrote the code changes, the test harness and this README at Bob Dickinson's direction. It also built and ran the engine and the controls. Bob set the requirements and reviews the results.
