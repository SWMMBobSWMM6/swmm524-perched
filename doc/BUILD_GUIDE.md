# Building a Custom SWMM5 Engine with Two-Layer Infiltration

**A step-by-step guide for Robert E. Dickinson**
**Tested against EPA SWMM 5.2.4 source (Feb 2026)**

---

## What You Need

- **EPA SWMM5 source code**: https://github.com/USEPA/Stormwater-Management-Model
- **Your two-layer files**: `lid_twolayer.c` and `lid_twolayer.h` from `TwoLayer_LID_Subcatchments/`
- **A C compiler**: Visual Studio on Windows, or gcc on Linux/Mac

## The Big Picture

The EPA source tree looks like this:

```
Stormwater-Management-Model/
├── CMakeLists.txt              ← top-level build
├── src/
│   ├── solver/                 ← ALL the engine C code lives here
│   │   ├── CMakeLists.txt      ← uses GLOB *.c *.h (auto-picks up new files!)
│   │   ├── lid.c               ← LID controls (we modify this)
│   │   ├── lid.h               ← LID structures (we modify this)
│   │   ├── lidproc.c           ← LID process calculations
│   │   ├── subcatch.c          ← subcatchment runoff (we modify this)
│   │   ├── project.c           ← project init/close (we modify this)
│   │   ├── infil.c             ← existing infiltration methods
│   │   └── ... (60+ other .c and .h files)
│   ├── run/
│   │   └── main.c              ← CLI executable (calls swmm5 library)
│   └── outfile/                ← binary output reader
└── tests/
```

**Key fact**: The CMakeLists.txt uses `file(GLOB SWMM_SOURCES *.c *.h)` — meaning any `.c` or `.h` file you drop into `src/solver/` is automatically compiled. No build file edits needed.

---

## Step 1: Get the EPA Source

```bash
git clone https://github.com/USEPA/Stormwater-Management-Model.git
cd Stormwater-Management-Model
```

## Step 2: Copy Your Two Files In

```bash
cp TwoLayer_LID_Subcatchments/lid_twolayer.c  src/solver/
cp TwoLayer_LID_Subcatchments/lid_twolayer.h  src/solver/
```

That's it for new files. The CMake glob picks them up automatically.

## Step 3: Modify `src/solver/lid.h` (3 lines)

Open `lid.h` and find the `TLidProc` structure (around line 135):

```c
// LID Process - generic LID design per unit of area
typedef struct
{
    char*          ID;            // identifying name
    int            lidType;       // type of LID
    TSurfaceLayer  surface;       // surface layer parameters
    TPavementLayer pavement;      // pavement layer parameters
    TSoilLayer     soil;          // soil layer parameters    ← find this line
    TStorageLayer  storage;       // storage layer parameters
    TDrainLayer    drain;         // underdrain system parameters
    TDrainMatLayer drainMat;      // drainage mat layer
    double*        drainRmvl;     // underdrain pollutant removals
}  TLidProc;
```

**Add two lines** right after the `soil` member:

```c
    TSoilLayer     soil;          // soil layer parameters
    TSoilLayer     soil2;         // lower soil layer (SOIL2 keyword)    // NEW
    int            hasSoil2;      // 1 if SOIL2 defined for this LID    // NEW
    TStorageLayer  storage;       // storage layer parameters
```

## Step 4: Modify `src/solver/lid.c` (three changes)

### 4A: Add SOIL2 to the layer keywords (around line 93)

Find the `LidLayerTypes` enum and `LidLayerWords` array:

```c
enum LidLayerTypes {
    SURF, SOIL, STOR, PAVE, DRAINMAT, DRAIN, REMOVALS};
```

Change to:

```c
enum LidLayerTypes {
    SURF, SOIL, SOIL2, STOR, PAVE, DRAINMAT, DRAIN, REMOVALS};    // added SOIL2
```

Find the `LidLayerWords` array:

```c
char* LidLayerWords[] =
    {"SURFACE", "SOIL", "STORAGE", "PAVEMENT", "DRAINMAT", "DRAIN",
     "REMOVALS", NULL};
```

Change to:

```c
char* LidLayerWords[] =
    {"SURFACE", "SOIL", "SOIL2", "STORAGE", "PAVEMENT", "DRAINMAT", "DRAIN",
     "REMOVALS", NULL};
```

### 4B: Add SOIL2 case to the parsing switch (around line 400)

Find the switch statement in `lid_readProcParams`:

```c
    switch (m)
    {
    case SURF:  return readSurfaceData(j, toks, ntoks);
    case SOIL:  return readSoilData(j, toks, ntoks);
    case STOR:  return readStorageData(j, toks, ntoks);
```

Add a SOIL2 case:

```c
    switch (m)
    {
    case SURF:  return readSurfaceData(j, toks, ntoks);
    case SOIL:  return readSoilData(j, toks, ntoks);
    case SOIL2: return readSoil2Data(j, toks, ntoks);              // NEW
    case STOR:  return readStorageData(j, toks, ntoks);
```

Then add the `readSoil2Data` function itself — put it right after the existing `readSoilData` function (after line ~700):

```c
//=============================================================================

int readSoil2Data(int j, char* toks[], int ntoks)
//
//  Purpose: reads lower soil layer data for a LID process.
//  Format:  LID_ID  SOIL2  Thickness Porosity FieldCap WiltPt Ksat Kslope Suction
//
{
    int    i;
    double x[7];

    if ( ntoks < 9 ) return error_setInpError(ERR_ITEMS, "");
    for (i = 2; i < 9; i++)
    {
        if ( ! getDouble(toks[i], &x[i-2]) || x[i-2] < 0.0 )
            return error_setInpError(ERR_NUMBER, toks[i]);
    }
    LidProcs[j].soil2.thickness = x[0] / UCF(RAINDEPTH);
    LidProcs[j].soil2.porosity  = x[1];
    LidProcs[j].soil2.fieldCap  = x[2];
    LidProcs[j].soil2.wiltPoint = x[3];
    LidProcs[j].soil2.kSat      = x[4] / UCF(RAINFALL);
    LidProcs[j].soil2.kSlope    = x[5];
    LidProcs[j].soil2.suction   = x[6] / UCF(RAINDEPTH);
    LidProcs[j].hasSoil2 = 1;
    return 0;
}
```

Also add the forward declaration near line 209 with the other static declarations:

```c
static int    readSoilData(int j, char* tok[], int ntoks);
static int    readSoil2Data(int j, char* tok[], int ntoks);        // NEW
static int    readStorageData(int j, char* tok[], int ntoks);
```

### 4C: Read UseAsInfil flag in `lid_readGroupParams` (around line 490)

Find the end of `lid_readGroupParams`, right before the `addLidUnit` call:

```c
    //... read percent of pervious area treated by LID unit
    x[5] = 0.0;
    if (ntoks >= 11)
    {
        if (!getDouble(toks[10], &x[5]) || x[5] < 0.0 || x[5] > 100.0)
            return error_setInpError(ERR_NUMBER, toks[10]);
    }

    //... create a new LID unit and add it to the subcatchment's LID group
    return addLidUnit(j, k, n, x, fname, drainSubcatch, drainNode);
```

Add UseAsInfil reading just before `addLidUnit`:

```c
    //... read percent of pervious area treated by LID unit
    x[5] = 0.0;
    if (ntoks >= 11)
    {
        if (!getDouble(toks[10], &x[5]) || x[5] < 0.0 || x[5] > 100.0)
            return error_setInpError(ERR_NUMBER, toks[10]);
    }

    //... read optional UseAsInfil flag (token index 11)                // NEW
    if (ntoks >= 12)                                                     // NEW
    {                                                                    // NEW
        int useAsInfil = atoi(toks[11]);                                 // NEW
        if (useAsInfil == 1 && LidProcs[k].hasSoil2)                    // NEW
            lidTwoLayer_activate(j, k);                                  // NEW
    }                                                                    // NEW

    //... create a new LID unit and add it to the subcatchment's LID group
    return addLidUnit(j, k, n, x, fname, drainSubcatch, drainNode);
```

Add this `#include` at the top of `lid.c`:

```c
#include "lid_twolayer.h"                                                // NEW
```

## Step 5: Modify `src/solver/subcatch.c` (3 lines)

Find the `getSubareaInfil` function (around line 985). It currently reads:

```c
    // --- compute infiltration rate 
    infil = infil_getInfil(j, tStep, precip,
                           subarea->inflow, subarea->depth);
```

Change to:

```c
    // --- compute infiltration rate 
    if ( lidTwoLayer_isActive(j) )                                       // NEW
        infil = lidTwoLayer_getInfil(j, tStep, precip,                   // NEW
                                     subarea->inflow, subarea->depth);   // NEW
    else                                                                 // NEW
        infil = infil_getInfil(j, tStep, precip,
                               subarea->inflow, subarea->depth);
```

Add this `#include` at the top of `subcatch.c`:

```c
#include "lid_twolayer.h"                                                // NEW
```

## Step 6: Modify `src/solver/project.c` (4 lines)

Add `#include` at the top:

```c
#include "lid_twolayer.h"                                                // NEW
```

Find `project_open` (around line 113). After the line that calls `lid_create`:

```c
    lid_create(Nobjects[LID], Nobjects[SUBCATCH]);
```

Add:

```c
    lid_create(Nobjects[LID], Nobjects[SUBCATCH]);
    lidTwoLayer_create(Nobjects[SUBCATCH]);                              // NEW
```

Find `project_close` (around line 274). Add cleanup:

```c
    lidTwoLayer_close();                                                 // NEW
```

## Step 7: Initialize hasSoil2 to 0

In `lid.c`, find where `LidProcs` members are initialized (around line 280, inside `lid_create`). After:

```c
    LidProcs[j].soil.thickness = 0.0;
```

Add:

```c
    LidProcs[j].soil2.thickness = 0.0;                                   // NEW
    LidProcs[j].hasSoil2 = 0;                                            // NEW
```

---

## Step 8: Build

### Option A: CMake (Windows with Visual Studio)

```bash
mkdir build && cd build
cmake ..
cmake --build . --config Release
```

The executable will be in `build/bin/Release/runswmm.exe`.

### Option B: CMake (Linux/Mac)

```bash
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j4
```

### Option C: Direct gcc (Linux — no CMake needed)

```bash
cd src/solver
gcc -O2 -fPIC -fopenmp -c *.c -I include
cd ../run
gcc -O2 -c main.c -I ../solver/include
gcc -o runswmm main.o ../solver/*.o -lm -fopenmp
```

This produces `runswmm` — your custom SWMM5 engine.

### Option D: WebAssembly (for browser apps)

```bash
cd src/solver
emcc -O2 *.c -I include -o swmm5.js \
  -s MODULARIZE=1 \
  -s EXPORTED_FUNCTIONS='["_swmm_run","_swmm_open","_swmm_start","_swmm_step","_swmm_end","_swmm_close"]' \
  -s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","FS"]'
```

---

## Step 9: Test

### Test backward compatibility:

```bash
./runswmm Example1.inp Example1.rpt Example1.out
```

Any existing INP file must produce identical results. The two-layer code is never called unless `UseAsInfil = 1` is in the INP.

### Test two-layer:

```bash
./runswmm TwoLayer_LID_Example.inp TwoLayer.rpt TwoLayer.out
```

Check the status report for subcatchment continuity errors. They should be < 0.1%.

---

## Summary of All Changes

| File | What to Change | Lines |
|------|---------------|-------|
| Copy `lid_twolayer.c` → `src/solver/` | New file | 0 (auto-compiled) |
| Copy `lid_twolayer.h` → `src/solver/` | New file | 0 (auto-compiled) |
| `lid.h` | Add `soil2` + `hasSoil2` to TLidProc | +2 |
| `lid.c` | Add `#include`, SOIL2 enum/keyword, `readSoil2Data` function, UseAsInfil parsing | ~40 |
| `subcatch.c` | Add `#include`, if/else around `infil_getInfil` | +5 |
| `project.c` | Add `#include`, `lidTwoLayer_create`, `lidTwoLayer_close` | +4 |
| **Total touches to existing EPA code** | | **~51 lines** |

The rest is in `lid_twolayer.c` and `lid_twolayer.h` — your new files that never touch existing logic.

---

## Future Enhancements

Once you've got this building, the same pattern works for any SWMM5 engine mod:

1. Write your new `.c` and `.h` files
2. Drop them in `src/solver/`
3. Add a few dispatch lines in the existing code
4. Build

Same approach works for the improved hydraulics (Preissmann slot, crown transition) and any other engine patches you want to collect in the `swmm5-dickinson` repo.

---

*Robert E. Dickinson — swmm5.org*
*Tested against EPA SWMM 5.2.4 source, February 2026*
