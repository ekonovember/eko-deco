// SPDX-License-Identifier: GPL-2.0
// Minimal stand-in for Subsurface core/dive.h — only what deco.cpp calls.
// The three methods reproduce dive.cpp verbatim (get_surface_pressure,
// rel_mbar_to_depth, depth_to_bar via salinity_to_specific_weight), with the
// salinity/surface-pressure lookup collapsed to plain members.
#ifndef DIVE_H
#define DIVE_H

#include "units.h"

struct dive {
	pressure_t surface_pressure = 1_atm;   // mbar; 1_atm == 1013
	int salinity = SEAWATER_SALINITY;      // g/10l; sea water == 10300

	// dive.cpp: salinity_to_specific_weight()
	double specific_weight() const
	{
		return salinity * 0.981 / 100000.0; // mbar per mm
	}

	pressure_t get_surface_pressure() const
	{
		return surface_pressure.mbar > 0 ? surface_pressure : 1_atm;
	}

	// dive.cpp: rel_mbar_to_depth()
	depth_t rel_mbar_to_depth(int mbar) const
	{
		return depth_t { {}, int_cast<int>(mbar / specific_weight()) };
	}

	// dive.cpp: depth_to_mbar(f) + depth_to_bar(), lrint as upstream
	double depth_to_bar(depth_t depth) const
	{
		double mbarf = get_surface_pressure().mbar + depth.mm * specific_weight();
		return lrint(mbarf) / 1000.0;
	}
};

#endif // DIVE_H
