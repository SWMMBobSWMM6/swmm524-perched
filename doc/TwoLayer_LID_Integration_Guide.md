# Two-Layer Infiltration via LID Control Reuse
## Integration Guide & Documentation Changes

**Author:** Robert E. Dickinson, Autodesk Water Technologist  
**Date:** February 26, 2026  
**Version:** SWMM5.2+ / SWMM5+  
**Status:** Proposed Enhancement  

---

## 1. Design Philosophy

**The problem with the "new infiltration method" approach:** It requires a new keyword in `[OPTIONS]`, a completely new 14-parameter format in `[INFILTRATION]`, new parsing code, new validation code, and new unit conversion code — all of which already exists in the LID parser.

**The elegant solution:** Reuse what SWMM5 already has.

1. The LID control's `SOIL` line already defines: thickness, porosity, field capacity, wilting point, Ksat, suction, and initial moisture deficit — with all parsing, validation, and unit conversion already working.

2. Add **one new keyword** to `[LID_CONTROLS]`: `SOIL2` (identical format to `SOIL`) for the lower layer.

3. Add **one new parameter** to `[LID_USAGE]`: `UseAsInfil` (0 or 1) at the end of the line.

4. When `UseAsInfil = 1`, the subcatchment's pervious area infiltration uses the LID's `SOIL` (upper) and `SOIL2` (lower) layers instead of the default `[INFILTRATION]` method.

### What This Achieves

| Aspect | Old Approach | LID Reuse Approach |
|--------|-------------|-------------------|
| New parameters in INP | 14 per subcatchment | **1** (UseAsInfil flag) |
| New INP section format | Yes — new [INFILTRATION] | **No** — existing LID format |
| New [OPTIONS] keyword | Yes — TWOLAYER | **No** — uses existing infil method |
| New parsing code | ~200 lines | **~20 lines** (SOIL2 + UseAsInfil) |
| Reuses existing validation | No | **Yes** — LID soil parser |
| Backward compatible | New INP format | **100%** — old INPs unchanged |
| Per-subcatchment control | All or nothing | **Per-subcatchment** override |
| Soil parameter library | Must duplicate | **Shared** via LID controls |

### Key Advantage: Soil Profile Reuse

Multiple subcatchments can reference the same LID control, sharing the same soil profile definition. Define it once, use it everywhere:

```
;; One soil profile definition serves many subcatchments
[LID_CONTROLS]
SandyLoamClay  BC
SandyLoamClay  SOIL   12  0.453  0.190  0.085  0.43   4.33  0.30
SandyLoamClay  SOIL2  24  0.464  0.310  0.187  0.04   8.22  0.15

[LID_USAGE]
S1  SandyLoamClay  0  0  0  0  0  0  *  *  0  1
S2  SandyLoamClay  0  0  0  0  0  0  *  *  0  1
S5  SandyLoamClay  0  0  0  0  0  0  *  *  0  1
```

---

## 2. Source Code Changes (Minimal)

### 2.1 New Files

| File | Description |
|------|-------------|
| `lid_twolayer.h` | State structure and function prototypes |
| `lid_twolayer.c` | Two-layer infiltration using LID soil properties |

### 2.2 Changes to `lid.h` — Add SOIL2 to TLidProc

The `TLidProc` structure (which holds a LID control's properties) already has a `soil` member of type `TSoilLayer`. Add a second one:

```c
// In lid.h — TLidProc structure
typedef struct
{
    // ... existing members ...
    TSoilLayer  soil;       // Existing upper soil layer (SOIL line)
    TSoilLayer  soil2;      // NEW: lower soil layer (SOIL2 line)
    int         hasSoil2;   // NEW: flag — 1 if SOIL2 is defined
    // ... rest of existing members ...
}  TLidProc;
```

The `TSoilLayer` structure already has all the fields we need:
```c
// Already in lid.h (no changes needed):
typedef struct
{
    double  thickness;      // layer thickness (ft)
    double  porosity;       // vol. fraction of pore space
    double  fieldCap;       // field capacity (vol. fraction)
    double  wiltPoint;      // wilting point (vol. fraction)
    double  kSat;           // saturated hydraulic conductivity (ft/s)
    double  suction;        // suction head (ft)
    // ...
}  TSoilLayer;
```

### 2.3 Changes to `lid.c` — Parse SOIL2 Keyword

In `lid_readProcParams()`, add a case for the "SOIL2" keyword. It uses the **exact same parsing logic** as "SOIL" but writes to `lidProc->soil2` instead of `lidProc->soil`:

```c
// In lid_readProcParams():
// After the existing "SOIL" case:

else if (match(tok[0], "SOIL2"))
{
    // Parse identically to SOIL — same parameters, same validation
    // but store in lidProc->soil2 instead of lidProc->soil
    lidProc->soil2.thickness = x[0] / UCF(RAINDEPTH);
    lidProc->soil2.porosity  = x[1];
    lidProc->soil2.fieldCap  = x[2];
    lidProc->soil2.wiltPoint = x[3];
    lidProc->soil2.kSat      = x[4] / UCF(RAINFALL);
    lidProc->soil2.suction   = x[5] / UCF(RAINDEPTH);
    // ... same validation as SOIL ...
    lidProc->hasSoil2 = 1;
}
```

**Lines of new parsing code: ~15** (copy-paste of SOIL case, change target member).

### 2.4 Changes to `lid.c` — Parse UseAsInfil in [LID_USAGE]

In `lid_readGroupParams()` (which parses `[LID_USAGE]` lines), read the optional `UseAsInfil` parameter at the end:

```c
// In lid_readGroupParams(), after parsing existing parameters:
int useAsInfil = 0;
if (ntoks > LAST_EXISTING_TOKEN_INDEX + 1)
{
    if (!getInt(tok[LAST_EXISTING_TOKEN_INDEX + 1], &useAsInfil))
        return ERR_NUMBER;
}

if (useAsInfil == 1)
{
    // Verify the LID control has SOIL2 defined
    if (!LidProcs[lidIndex].hasSoil2)
    {
        report_writeErrorMsg(ERR_LID_PARAMS, 
            "UseAsInfil requires SOIL2 layer in LID control");
        return ERR_LID_PARAMS;
    }
    // Activate two-layer infiltration for this subcatchment
    lidTwoLayer_activate(j, lidIndex);
}
```

**Lines of new parsing code: ~12.**

### 2.5 Changes to `subcatch.c` — Override Infiltration

In `subcatch_getRunoff()`, check if two-layer is active before calling the default infiltration:

```c
// In subcatch_getRunoff(), where infil_getInfil() is called:
double infil;
if (lidTwoLayer_isActive(j))
{
    infil = lidTwoLayer_getInfil(j, tstep, rainfall, runon, depth);
}
else
{
    infil = infil_getInfil(j, tstep, rainfall, runon, depth);
}
```

**Lines changed: ~5** (wrap existing call in an if/else).

### 2.6 Changes to `project.c`

```c
// In project_init(), after subcatchment allocation:
lidTwoLayer_initModule(Nobjects[SUBCATCH]);

// In project_close():
lidTwoLayer_close();
```

### 2.7 Summary of All Code Changes

| File | Change | Lines |
|------|--------|-------|
| `lid.h` | Add `soil2` + `hasSoil2` to TLidProc | ~3 |
| `lid.c` | Parse "SOIL2" keyword (copy of SOIL) | ~15 |
| `lid.c` | Parse `UseAsInfil` in [LID_USAGE] | ~12 |
| `subcatch.c` | if/else to call lidTwoLayer_getInfil | ~5 |
| `project.c` | Init and close calls | ~4 |
| **New:** `lid_twolayer.h` | Header file | ~60 |
| **New:** `lid_twolayer.c` | Implementation | ~250 |
| **Total existing code touched** | | **~39 lines** |

---

## 3. INP File Format Changes

### 3.1 [OPTIONS] — No Change

The existing `INFILTRATION` keyword is unchanged. The standard method (Green-Ampt, Horton, etc.) is still the default for subcatchments that don't have `UseAsInfil = 1`.

### 3.2 [LID_CONTROLS] — One New Keyword: SOIL2

```
[LID_CONTROLS]
;;               Type
SandyLoamClay    BC

;;Name           Layer    Thick  Por    FC     WP     Ksat   Suct   IMD
SandyLoamClay    SURFACE  0      0      0      0      0
SandyLoamClay    SOIL     12.0   0.453  0.190  0.085  0.43   4.33   0.30   ;; Upper layer
SandyLoamClay    SOIL2    24.0   0.464  0.310  0.187  0.04   8.22   0.15   ;; Lower layer (NEW)
SandyLoamClay    STORAGE  0      0      0      0
SandyLoamClay    DRAIN    0      0      0      0      0      0
```

`SOIL2` uses the **identical 7 parameters** as `SOIL`:

| Parameter | Units | Description |
|-----------|-------|-------------|
| Thickness | in (mm) | Layer thickness |
| Porosity | fraction | Total porosity |
| FieldCap | fraction | Field capacity |
| WiltPoint | fraction | Wilting point |
| Ksat | in/hr (mm/hr) | Saturated hydraulic conductivity |
| Suction | in (mm) | Capillary suction head |
| IMD | fraction | Initial moisture deficit |

### 3.3 [LID_USAGE] — One New Column: UseAsInfil

```
[LID_USAGE]
;;Subcatch  LID            Num  Area  Width  InitSat  FromImp  ToPerv  Rpt  Drain  FromPerv  UseAsInfil
S1          SandyLoamClay  0    0     0      0        0        0       *    *      0         1
```

| Value | Meaning |
|-------|---------|
| 0 (default) | Normal LID behavior — no effect on pervious area infiltration |
| 1 | Use this LID's SOIL + SOIL2 as the subcatchment's pervious area infiltration model |

When `UseAsInfil = 1`:
- `Number`, `Area`, `Width` can be 0 (the LID is not placed as a physical BMP)
- The LID control must have both `SOIL` and `SOIL2` defined
- The standard `[INFILTRATION]` entry for this subcatchment is **ignored**
- Other subcatchments without `UseAsInfil = 1` continue using the default method

### 3.4 Backward Compatibility

Existing INP files work without any changes because:
- `SOIL2` is optional — LID controls without it behave exactly as before
- `UseAsInfil` is optional — if omitted, defaults to 0 (no override)
- No changes to `[OPTIONS]`, `[INFILTRATION]`, or any other existing section

---

## 4. Theory — The LID Percolation Equation

The core of this enhancement is reusing the percolation equation from `lid_proc.c :: soilFluxRates()`:

```c
percRate = kSat * exp(-15.0 * (1.0 - theta / porosity));
```

This approximates the Brooks-Corey unsaturated hydraulic conductivity:

| Saturation Level | θ/n | Percolation Rate |
|-----------------|-----|-----------------|
| Saturated | 1.0 | Ksat × 1.000 (100%) |
| 90% | 0.9 | Ksat × 0.223 (22.3%) |
| 80% | 0.8 | Ksat × 0.050 (5.0%) |
| 70% | 0.7 | Ksat × 0.011 (1.1%) |
| 50% | 0.5 | Ksat × 0.00055 (0.055%) |
| At wilting point | ~0.2 | ≈ 0 |

The steep exponential decay means percolation drops rapidly below saturation, which realistically captures how water moves through unsaturated soil. The same equation is applied twice: once for upper → lower percolation, and once for lower → deep percolation.

### Moisture Balance

```
Upper layer: dθ_u/dt = (infil - perc_upper - ET_upper) / thickness_upper
Lower layer: dθ_l/dt = (perc_upper - perc_lower - ET_lower) / thickness_lower
```

Where:
- `infil` = Green-Ampt infiltration from surface into upper layer
- `perc_upper` = upper → lower percolation (LID equation)
- `perc_lower` = lower → deep groundwater (LID equation)
- `ET` = evapotranspiration (optional, layer-specific)

---

## 5. Documentation Updates

### 5.1 SWMM5 User's Manual

**Chapter on LID Controls:**

Add description of `SOIL2` keyword:

> **SOIL2** (Optional): Defines a lower soil layer beneath the primary SOIL layer. Uses the same seven parameters as SOIL. When used with `UseAsInfil = 1` in [LID_USAGE], the SOIL and SOIL2 layers together provide a two-layer infiltration model for the subcatchment's pervious area.

**Chapter on LID Usage:**

Add description of `UseAsInfil` parameter:

> **UseAsInfil** (Optional, default = 0): When set to 1, the referenced LID control's SOIL and SOIL2 layers are used as a two-layer infiltration model for the subcatchment's entire pervious area, overriding the default infiltration method set in [OPTIONS]. The LID control must have both SOIL and SOIL2 defined. Other LID_USAGE parameters (Number, Area, Width) can be set to 0 since the LID is serving as a soil profile definition rather than a physical BMP.

### 5.2 SWMM5 Technical Reference

**Add Section: "Two-Layer Infiltration via LID Soil Reuse"**

Document the mathematical formulation, coupling between Green-Ampt surface infiltration and the LID percolation model, and moisture balance equations for both layers.

### 5.3 Appendix D — Input File Format

- Add `SOIL2` to the list of [LID_CONTROLS] keywords with parameter descriptions
- Add `UseAsInfil` to the [LID_USAGE] parameter list

---

## 6. Typical Soil Parameter Values

These values work for both SOIL and SOIL2 lines:

| Soil Type | Porosity | Field Cap | Wilt Point | Ksat (in/hr) | Suction (in) |
|-----------|----------|-----------|------------|-------------|--------------|
| Sand | 0.437 | 0.062 | 0.024 | 4.74 | 1.93 |
| Loamy Sand | 0.437 | 0.105 | 0.047 | 1.18 | 2.40 |
| Sandy Loam | 0.453 | 0.190 | 0.085 | 0.43 | 4.33 |
| Loam | 0.463 | 0.232 | 0.116 | 0.13 | 3.50 |
| Silt Loam | 0.501 | 0.284 | 0.135 | 0.26 | 6.69 |
| Clay Loam | 0.464 | 0.310 | 0.187 | 0.04 | 8.22 |
| Clay | 0.475 | 0.378 | 0.265 | 0.01 | 12.45 |

---

## 7. Testing Recommendations

1. **Backward compatibility:** Existing INP files with no SOIL2 or UseAsInfil must produce identical results
2. **Mass balance:** Rainfall = runoff + Δstorage(upper) + Δstorage(lower) + deep perc + ET
3. **Consistency:** With identical SOIL and SOIL2 properties, compare with standard Green-Ampt
4. **Profile sharing:** Multiple subcatchments using the same LID control must independently track moisture
5. **Mixed models:** Some subcatchments using UseAsInfil, others using default — both should work in the same run

---

## 8. Future Enhancements

- Groundwater coupling: deep percolation → SWMM5 groundwater recharge
- SOIL3, SOIL4... for N-layer profiles
- Temperature-dependent Ksat for frozen ground
- Capillary rise from lower to upper layer
- Layer-specific root zone ET
