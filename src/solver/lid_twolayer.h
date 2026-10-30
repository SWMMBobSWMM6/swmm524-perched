//-----------------------------------------------------------------------------
//   lid_twolayer.h
//
//   Project:  EPA SWMM5
//   Version:  5.2+
//   Date:     02/26/2026
//   Author:   Robert E. Dickinson / SWMM5+ TAC
//
//   Two-Layer Infiltration via LID Control Reuse
//
//   CONCEPT:
//   Instead of defining a whole new infiltration method, this module lets
//   a subcatchment's pervious area use an existing LID control's soil
//   layer definition for infiltration. A single new parameter is added
//   to [LID_USAGE]: UseAsInfil (0 or 1).
//
//   A second soil layer keyword (SOIL2) is added to [LID_CONTROLS] to
//   define the lower soil layer. The existing SOIL line becomes the upper
//   layer. All parameter parsing, validation, and unit conversion for
//   soil properties is already handled by the existing LID parser.
//
//   When UseAsInfil = 1, the pervious area infiltration is computed
//   using the LID's SOIL (upper) and SOIL2 (lower) layers instead of
//   the default [INFILTRATION] method.
//
//-----------------------------------------------------------------------------
#ifndef LID_TWOLAYER_H
#define LID_TWOLAYER_H

//-----------------------------------------------------------------------------
//  Constants
//-----------------------------------------------------------------------------
#define LID_UPPER_SOIL  0
#define LID_LOWER_SOIL  1

//-----------------------------------------------------------------------------
//  Data Structures
//-----------------------------------------------------------------------------

// State variables for the two-layer soil infiltration 
// (per subcatchment LID usage that has UseAsInfil = 1)
typedef struct
{
    // Upper layer (from LID SOIL line)
    double upperMoisture;       // Current upper moisture content (vol fraction)
    double upperFu;             // Green-Ampt cumulative infiltration (ft)
    double upperCumInfil;       // Cumulative infiltration volume (ft)
    
    // Lower layer (from LID SOIL2 line)
    double lowerMoisture;       // Current lower moisture content (vol fraction)
    double lowerCumPerc;        // Cumulative deep percolation (ft)
    
    // Rates (current time step)
    double infiltRate;          // Surface -> upper layer (ft/s)
    double percRate;            // Upper -> lower layer (ft/s)
    double deepPercRate;        // Lower -> deep groundwater (ft/s)
    
    int    isActive;            // 1 if this subcatch uses two-layer infil
}  TLidTwoLayerState;

//-----------------------------------------------------------------------------
//  Exported Functions
//-----------------------------------------------------------------------------

// Initialize module — allocate state arrays after subcatchment count is known
void   lidTwoLayer_initModule(int nSubcatch);

// Free module memory
void   lidTwoLayer_close(void);

// Set a subcatchment's LID usage as the two-layer infiltration source
//   j      = subcatchment index
//   lidIdx = index of the LID control in the LID usage table
void   lidTwoLayer_activate(int j, int lidIdx);

// Initialize state at start of simulation
void   lidTwoLayer_initState(int j);

// Compute two-layer infiltration for a time step
//   j        = subcatchment index
//   tstep    = time step (seconds)
//   rainfall = rainfall rate (ft/s)
//   runon    = runon rate (ft/s)
//   depth    = ponded depth (ft)
//   returns  = infiltration rate (ft/s) from surface into upper layer
double lidTwoLayer_getInfil(int j, double tstep, double rainfall,
                            double runon, double depth);

// Check if subcatchment j uses two-layer infiltration
int    lidTwoLayer_isActive(int j);

// Get deep percolation rate for subcatchment j
double lidTwoLayer_getDeepPerc(int j);

// Get moisture content of upper (layer=0) or lower (layer=1) 
double lidTwoLayer_getMoisture(int j, int layer);

#endif // LID_TWOLAYER_H
