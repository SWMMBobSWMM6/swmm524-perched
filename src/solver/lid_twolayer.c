//-----------------------------------------------------------------------------
//   lid_twolayer.c
//
//   Project:  EPA SWMM5
//   Version:  5.2+
//   Date:     02/26/2026
//   Author:   Robert E. Dickinson / SWMM5+ TAC
//
//   Two-Layer Infiltration via LID Control Reuse
//
//   PURPOSE:
//   When a subcatchment's [LID_USAGE] entry has UseAsInfil = 1, this module
//   replaces the default infiltration computation for the pervious area
//   with a two-layer soil model. The soil properties come directly from the
//   referenced LID control:
//
//     SOIL  line → upper layer properties
//     SOIL2 line → lower layer properties (new keyword)
//
//   No new infiltration method keyword is needed in [OPTIONS]. No new
//   [INFILTRATION] format is needed. Only ONE parameter is added to the
//   [LID_USAGE] table.
//
//   PERCOLATION MODEL (from lid_proc.c):
//     perc = kSat * exp(-15.0 * (1.0 - theta / porosity))
//
//   This is the same proven equation already used in the LID soil layer.
//   We simply apply it twice — once for upper-to-lower percolation and
//   once for lower-to-deep percolation.
//
//   MOISTURE BALANCE:
//     Upper: d(theta_u)/dt = (infil - perc_upper - ET_u) / thickness_u
//     Lower: d(theta_l)/dt = (perc_upper - perc_lower - ET_l) / thickness_l
//
//-----------------------------------------------------------------------------

#include <math.h>
#include <string.h>
#include <stdlib.h>
#include "headers.h"
#include "lid.h"
#include "lid_twolayer.h"

//-----------------------------------------------------------------------------
//  Local Constants
//-----------------------------------------------------------------------------
#define DEPTH_TOL       0.00001     // Minimum depth tolerance (ft)
#define PERC_EXP        15.0        // LID percolation exponent
#define MIN_KSAT        1.0e-12     // Minimum Ksat (ft/s)
#define MAX_GA_ITER     20          // Green-Ampt max iterations
#define GA_TOL          0.0001      // Green-Ampt convergence tolerance (ft)

//-----------------------------------------------------------------------------
//  Module-level Variables
//-----------------------------------------------------------------------------
static TLidTwoLayerState* TLState = NULL;  // Array [nSubcatch]
static int*    LidControlIdx = NULL;        // Which LID control to use per subcatch
static int     NsubcatchAlloc = 0;

//-----------------------------------------------------------------------------
//  Local Function Prototypes
//-----------------------------------------------------------------------------
static double  computeGreenAmpt(double Ks, double psi, double IMD,
                   double* Fu, double tstep, double iRate, double depth);
static double  computePercolation(double kSat, double porosity,
                   double wiltPoint, double moisture);
static void    updateLayerMoisture(double* moisture, double porosity,
                   double wiltPoint, double fluxIn, double fluxOut,
                   double thickness, double tstep);

//=============================================================================
//  MODULE INIT / CLOSE
//=============================================================================

void lidTwoLayer_initModule(int nSubcatch)
//
//  Purpose: Allocates memory for two-layer state tracking.
//  Called:  During project initialization, after subcatchment count is known.
//
{
    int j;
    
    lidTwoLayer_close();  // Free any previous allocation
    
    if (nSubcatch <= 0) return;
    
    TLState = (TLidTwoLayerState*)calloc(nSubcatch, sizeof(TLidTwoLayerState));
    LidControlIdx = (int*)calloc(nSubcatch, sizeof(int));
    
    if (!TLState || !LidControlIdx) {
        report_writeErrorMsg(ERR_MEMORY, "lid_twolayer");
        return;
    }
    
    NsubcatchAlloc = nSubcatch;
    
    for (j = 0; j < nSubcatch; j++) {
        TLState[j].isActive = 0;
        LidControlIdx[j] = -1;
    }
}

void lidTwoLayer_close(void)
{
    if (TLState)       { free(TLState);       TLState = NULL; }
    if (LidControlIdx) { free(LidControlIdx); LidControlIdx = NULL; }
    NsubcatchAlloc = 0;
}

//=============================================================================
//  ACTIVATION — Called when parsing [LID_USAGE] with UseAsInfil = 1
//=============================================================================

void lidTwoLayer_activate(int j, int lidIdx)
//
//  Purpose: Marks subcatchment j as using LID control lidIdx for two-layer
//           infiltration on its pervious area.
//
//  Input:   j      = subcatchment index
//           lidIdx = index of the LID control that has SOIL + SOIL2 layers
//
//  Notes:   This is called from the [LID_USAGE] parser when UseAsInfil = 1.
//           The LID control at lidIdx must have both SOIL and SOIL2 defined.
//           If SOIL2 is not defined, only single-layer LID infiltration is used.
//
{
    if (j < 0 || j >= NsubcatchAlloc) return;
    
    TLState[j].isActive = 1;
    LidControlIdx[j] = lidIdx;
}

//=============================================================================
//  STATE INITIALIZATION
//=============================================================================

void lidTwoLayer_initState(int j)
//
//  Purpose: Initializes two-layer state variables from the LID control's
//           soil layer properties at the start of simulation.
//
//  Input:   j = subcatchment index
//
//  Notes:   Reads soil properties from the LID control referenced by
//           LidControlIdx[j]. The LID's SOIL parameters are the upper
//           layer; SOIL2 parameters are the lower layer.
//
//           All soil properties (thickness, porosity, fieldCap, wiltPoint,
//           kSat, suction) are already in internal units (ft, ft/s) because
//           they were converted by the LID parser.
//
{
    TLidTwoLayerState* state;
    TLidProc*          lidProc;  // The LID control's process data
    
    if (!TLState || j < 0 || j >= NsubcatchAlloc) return;
    if (!TLState[j].isActive) return;
    
    state = &TLState[j];
    
    // Get the LID control — this provides soil layer properties
    // lidProc = &LidProcs[LidControlIdx[j]];  // (actual accessor depends on SWMM5 version)
    
    // Initialize upper layer at field capacity
    // (actual init reads from lidProc->soil.porosity - lidProc->soil.fieldCap)
    // For now, set defaults — real implementation reads from the LID control:
    state->upperMoisture = 0.0;    // Will be set from LID soil.fieldCap
    state->upperFu       = 0.0;
    state->upperCumInfil = 0.0;
    
    state->lowerMoisture = 0.0;    // Will be set from LID soil2.fieldCap
    state->lowerCumPerc  = 0.0;
    
    state->infiltRate    = 0.0;
    state->percRate      = 0.0;
    state->deepPercRate  = 0.0;
    
    //------------------------------------------------------------------
    //  INTEGRATION POINT: In the actual SWMM5 code, read initial
    //  moisture from the LID control's soil layers:
    //
    //  TLidProc* lp = &LidProcs[LidControlIdx[j]];
    //  state->upperMoisture = lp->soil.porosity - lp->soil.initMoisture;
    //  state->lowerMoisture = lp->soil2.porosity - lp->soil2.initMoisture;
    //
    //  where soil2 is the new SOIL2 layer added to the LID control.
    //------------------------------------------------------------------
}

//=============================================================================
//  MAIN INFILTRATION COMPUTATION
//=============================================================================

double lidTwoLayer_getInfil(int j, double tstep, double rainfall,
                            double runon, double depth)
//
//  Purpose: Computes the two-layer infiltration rate using the LID control's
//           soil layer properties.
//
//  Input:   j        = subcatchment index
//           tstep    = time step (seconds)
//           rainfall = rainfall rate on pervious area (ft/s)
//           runon    = runon rate from other areas (ft/s)
//           depth    = current surface ponding depth (ft)
//
//  Returns: infiltration rate from surface into upper layer (ft/s)
//
//  Theory:
//  -------
//  1. Green-Ampt infiltration from surface into upper layer
//     (uses upper layer Ksat, suction, and current moisture deficit)
//
//  2. Percolation from upper layer to lower layer:
//     perc_u = Ksat_u * exp(-15 * (1 - theta_u / porosity_u))
//     This is the SAME equation from lid_proc.c :: soilFluxRates()
//
//  3. Deep percolation from lower layer:
//     perc_l = Ksat_l * exp(-15 * (1 - theta_l / porosity_l))
//
//  4. Update moisture in both layers
//
{
    TLidTwoLayerState* state;
    double  availWater, infil, percUpper, percLower;
    
    //------------------------------------------------------------------
    //  INTEGRATION POINT: In actual code, get soil properties from:
    //  TLidProc* lp = &LidProcs[LidControlIdx[j]];
    //  Upper layer: lp->soil.thickness, .porosity, .fieldCap, .wiltPoint, .kSat, .suction
    //  Lower layer: lp->soil2.thickness, .porosity, .fieldCap, .wiltPoint, .kSat, .suction
    //
    //  For this reference implementation, we use placeholder variables.
    //  Replace these with actual LID control accessors.
    //------------------------------------------------------------------
    
    // === PLACEHOLDER soil properties (replace with LID control reads) ===
    // Upper layer (from LID SOIL line)
    double uThick   = 1.0;     // lp->soil.thickness (ft)
    double uPor     = 0.453;   // lp->soil.porosity
    double uFC      = 0.190;   // lp->soil.fieldCap
    double uWP      = 0.085;   // lp->soil.wiltPoint
    double uKsat    = 0.000012; // lp->soil.kSat (ft/s)
    double uSuction = 0.361;   // lp->soil.suction (ft)
    
    // Lower layer (from LID SOIL2 line)
    double lThick   = 2.0;     // lp->soil2.thickness (ft)
    double lPor     = 0.464;   // lp->soil2.porosity
    double lFC      = 0.310;   // lp->soil2.fieldCap
    double lWP      = 0.187;   // lp->soil2.wiltPoint
    double lKsat    = 0.0000011; // lp->soil2.kSat (ft/s)
    // ===================================================================
    
    if (!TLState || j < 0 || j >= NsubcatchAlloc) return 0.0;
    state = &TLState[j];
    if (!state->isActive) return 0.0;
    
    //--- Step 1: Green-Ampt infiltration into upper layer ---------------
    availWater = rainfall + runon;
    {
        double IMD = uPor - state->upperMoisture;
        if (IMD < DEPTH_TOL) IMD = DEPTH_TOL;
        double iRate = availWater + depth / tstep;
        
        infil = computeGreenAmpt(uKsat, uSuction, IMD,
                                 &state->upperFu, tstep, iRate, depth);
        
        // Limit to available water
        if (infil > iRate) infil = iRate;
        
        // Limit to upper layer capacity
        double maxVol = (uPor - state->upperMoisture) * uThick;
        if (infil * tstep > maxVol) infil = maxVol / tstep;
        if (infil < 0.0) infil = 0.0;
    }
    
    //--- Step 2: Percolation upper → lower (LID equation) ---------------
    //
    //  THIS IS THE KEY EQUATION from lid_proc.c :: soilFluxRates():
    //
    //    percRate = kSat * exp(-15.0 * (1.0 - theta / porosity))
    //
    percUpper = computePercolation(uKsat, uPor, uWP, state->upperMoisture);
    
    // Limit to available moisture above wilting point
    {
        double maxPerc = (state->upperMoisture - uWP) * uThick / tstep;
        if (maxPerc < 0.0) maxPerc = 0.0;
        if (percUpper > maxPerc) percUpper = maxPerc;
    }
    
    // Limit to what lower layer can accept
    {
        double lowerCap = (lPor - state->lowerMoisture) * lThick / tstep;
        if (lowerCap < 0.0) lowerCap = 0.0;
        if (percUpper > lowerCap) percUpper = lowerCap;
    }
    
    //--- Step 3: Deep percolation from lower layer (same LID equation) ---
    percLower = computePercolation(lKsat, lPor, lWP, state->lowerMoisture);
    
    {
        double maxPerc = (state->lowerMoisture - lWP) * lThick / tstep;
        if (maxPerc < 0.0) maxPerc = 0.0;
        if (percLower > maxPerc) percLower = maxPerc;
    }
    
    //--- Step 4: Update moisture in both layers -------------------------
    updateLayerMoisture(&state->upperMoisture, uPor, uWP,
                        infil, percUpper, uThick, tstep);
    
    updateLayerMoisture(&state->lowerMoisture, lPor, lWP,
                        percUpper, percLower, lThick, tstep);
    
    //--- Store rates ----------------------------------------------------
    state->infiltRate   = infil;
    state->percRate     = percUpper;
    state->deepPercRate = percLower;
    state->upperCumInfil += infil * tstep;
    state->lowerCumPerc  += percLower * tstep;
    
    return infil;
}

//=============================================================================
//  ACCESSOR FUNCTIONS
//=============================================================================

int lidTwoLayer_isActive(int j)
{
    if (!TLState || j < 0 || j >= NsubcatchAlloc) return 0;
    return TLState[j].isActive;
}

double lidTwoLayer_getDeepPerc(int j)
{
    if (!TLState || j < 0 || j >= NsubcatchAlloc) return 0.0;
    return TLState[j].deepPercRate;
}

double lidTwoLayer_getMoisture(int j, int layer)
{
    if (!TLState || j < 0 || j >= NsubcatchAlloc) return 0.0;
    if (layer == LID_UPPER_SOIL) return TLState[j].upperMoisture;
    if (layer == LID_LOWER_SOIL) return TLState[j].lowerMoisture;
    return 0.0;
}

//=============================================================================
//  LOCAL (STATIC) FUNCTIONS
//=============================================================================

static double computeGreenAmpt(double Ks, double psi, double IMD,
                               double* Fu, double tstep,
                               double iRate, double depth)
//
//  Purpose: Green-Ampt infiltration solver.
//
//  Input:   Ks    = saturated hydraulic conductivity (ft/s)
//           psi   = capillary suction head (ft)
//           IMD   = initial moisture deficit (fraction)
//           Fu    = pointer to cumulative infiltration (ft) — updated
//           tstep = time step (seconds)
//           iRate = available water rate (ft/s)
//           depth = ponded surface depth (ft)
//
//  Returns: infiltration rate (ft/s)
//
{
    double c1, Fnew, Fold, Fprev;
    int    iter;
    
    if (Ks < MIN_KSAT) return 0.0;
    if (IMD < DEPTH_TOL) IMD = DEPTH_TOL;
    
    c1 = psi * IMD;
    Fprev = *Fu;
    
    // Pre-ponding check
    if (Fprev == 0.0 && iRate <= Ks) {
        *Fu += iRate * tstep;
        return iRate;
    }
    
    if (Fprev == 0.0) {
        double Fp = c1 * Ks / (iRate - Ks);
        if (Fp < 0.0) Fp = 0.0;
        if (iRate * tstep < Fp) {
            *Fu += iRate * tstep;
            return iRate;
        }
        Fprev = Fp;
    }
    
    // Newton-Raphson iteration for Green-Ampt
    Fnew = Fprev + Ks * tstep;
    for (iter = 0; iter < MAX_GA_ITER; iter++) {
        Fold = Fnew;
        if (c1 + Fnew > 0.0) {
            Fnew = Ks * tstep + Fprev + c1 * log((c1 + Fnew) / (c1 + Fprev));
        }
        if (fabs(Fnew - Fold) < GA_TOL) break;
    }
    
    double infil = (Fnew - *Fu) / tstep;
    *Fu = Fnew;
    
    if (depth > DEPTH_TOL) {
        infil += Ks * depth / (c1 + Fnew);
    }
    
    return infil;
}

//-----------------------------------------------------------------------------

static double computePercolation(double kSat, double porosity,
                                 double wiltPoint, double moisture)
//
//  Purpose: Computes percolation rate using the LID exponential model.
//
//  Input:   kSat     = saturated hydraulic conductivity (ft/s)
//           porosity = total porosity (vol fraction)
//           wiltPoint= wilting point (vol fraction)
//           moisture = current moisture content (vol fraction)
//
//  Returns: percolation rate (ft/s)
//
//  =====================================================================
//  THIS IS THE KEY LID EQUATION from lid_proc.c :: soilFluxRates():
//
//     perc = kSat * exp(-15.0 * (1.0 - theta / porosity))
//
//  At full saturation:  perc = kSat
//  At 50% saturation:   perc ≈ 0.055% of kSat
//  At wilting point:     perc → 0
//  =====================================================================
//
{
    double ratio;
    
    if (kSat < MIN_KSAT) return 0.0;
    if (moisture <= wiltPoint) return 0.0;
    
    ratio = moisture / porosity;
    if (ratio > 1.0) ratio = 1.0;
    if (ratio < 0.0) ratio = 0.0;
    
    return kSat * exp(-PERC_EXP * (1.0 - ratio));
}

//-----------------------------------------------------------------------------

static void updateLayerMoisture(double* moisture, double porosity,
                                double wiltPoint, double fluxIn,
                                double fluxOut, double thickness,
                                double tstep)
//
//  Purpose: Updates a soil layer's moisture content.
//
{
    *moisture += (fluxIn - fluxOut) * tstep / thickness;
    
    if (*moisture > porosity)  *moisture = porosity;
    if (*moisture < wiltPoint) *moisture = wiltPoint;
}
