// SPDX-License-Identifier: GPL-2.0
// Shim that makes upstream deco.cpp compile standalone and exposes a small
// extern "C" surface for the Python ctypes wrapper (subsurface_deco.py).
//
// fill_pressures() is copied verbatim from upstream core/gas.cpp (same pinned
// commit as deco.cpp, see upstream/UPSTREAM.txt), minus the PSCR branch which
// needs the prefs machinery — the oracle only ever runs OC segments.

#include <cstdarg>
#include <cstdio>
#include <cstdlib>

#include "deco.h"
#include "dive.h"
#include "gas.h"
#include "errorhelper.h"
#include "pref.h"

enum deco_mode pref_deco_mode(bool /*in_planner*/)
{
	return BUEHLMANN;
}

int report_error(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	fputc('\n', stderr);
	va_end(ap);
	return -1;
}

// upstream core/gas.cpp fill_pressures(), OC + CCR branches verbatim
gas_pressures fill_pressures(const double amb_pressure, struct gasmix mix, double po2, enum divemode_t divemode)
{
	struct gas_pressures pressures;
	if ((divemode != OC) && po2) {	// This is a rebreather dive where pressures.o2 is defined
		if (po2 >= amb_pressure) {
			pressures.o2 = amb_pressure;
			pressures.n2 = pressures.he = 0.0;
		} else {
			pressures.o2 = po2;
			if (get_o2(mix) == 1000) {
				pressures.he = pressures.n2 = 0;
			} else {
				pressures.he = (amb_pressure - pressures.o2) * (double)get_he(mix) / (1000 - get_o2(mix));
				pressures.n2 = amb_pressure - pressures.o2 - pressures.he;
			}
		}
	} else {
		if (divemode == PSCR) {
			fprintf(stderr, "PSCR not supported by the deco oracle shim\n");
			abort();
		} else {
			// Open circuit dives: no gas pressure values available, they need to be calculated
			pressures.o2 = get_o2(mix) / 1000.0 * amb_pressure;
			pressures.he = get_he(mix) / 1000.0 * amb_pressure;
			pressures.n2 = get_n2(mix) / 1000.0 * amb_pressure;
		}
	}
	return pressures;
}

// ---------------------------------------------------------------------------
// ctypes API. One global stub dive carries surface pressure + salinity.
// ---------------------------------------------------------------------------

static struct dive g_dive;

extern "C" {

deco_state *srf_new(void)
{
	return new deco_state();
}

void srf_free(deco_state *ds)
{
	delete ds;
}

// percent, like upstream set_gf(); -1 leaves a value unchanged
void srf_set_gf(short gflow, short gfhigh)
{
	set_gf(gflow, gfhigh);
}

void srf_set_dive(int surface_mbar, int salinity)
{
	g_dive.surface_pressure = pressure_t { {}, surface_mbar };
	g_dive.salinity = salinity;
}

void srf_clear_deco(deco_state *ds, double surface_pressure_bar)
{
	clear_deco(ds, surface_pressure_bar, true);
}

void srf_add_segment(deco_state *ds, double pressure_bar,
		     int o2_permille, int he_permille, int seconds)
{
	gasmix mix = { fraction_t{ {}, o2_permille }, fraction_t{ {}, he_permille } };
	add_segment(ds, pressure_bar, mix, seconds, 0, OC, 0, true);
}

double srf_tissue_tolerance(deco_state *ds, double pressure_bar)
{
	return tissue_tolerance_calc(ds, &g_dive, pressure_bar, true);
}

// ceiling in mm; smooth=0 rounds up to 3 m stop multiples like the planner
int srf_ceiling_mm(deco_state *ds, double surface_pressure_bar, int smooth)
{
	double tol = tissue_tolerance_calc(ds, &g_dive, g_dive.depth_to_bar(depth_t()), true);
	return deco_allowed_depth(tol, surface_pressure_bar, &g_dive, smooth != 0).mm;
}

int srf_allowed_depth_mm(double tissues_tolerance_bar, double surface_pressure_bar, int smooth)
{
	return deco_allowed_depth(tissues_tolerance_bar, surface_pressure_bar, &g_dive, smooth != 0).mm;
}

double srf_get_gf(deco_state *ds, double ambpressure_bar)
{
	return get_gf(ds, ambpressure_bar, &g_dive);
}

void srf_tissues(const deco_state *ds, double *n2, double *he)
{
	for (int i = 0; i < 16; i++) {
		n2[i] = ds->tissue_n2_sat[i];
		he[i] = ds->tissue_he_sat[i];
	}
}

double srf_gf_low_pressure_this_dive(const deco_state *ds)
{
	return ds->gf_low_pressure_this_dive;
}

void srf_set_gf_low_pressure_this_dive(deco_state *ds, double bar)
{
	ds->gf_low_pressure_this_dive = bar;
}

void srf_set_tissues(deco_state *ds, const double *n2, const double *he)
{
	for (int i = 0; i < 16; i++) {
		ds->tissue_n2_sat[i] = n2[i];
		ds->tissue_he_sat[i] = he[i];
		ds->tissue_inertgas_saturation[i] = n2[i] + he[i];
	}
}

// snapshot/restore for trial ascents, like the planner's deco_state_cache
void srf_copy(deco_state *dst, const deco_state *src)
{
	*dst = *src;
}

int srf_guiding_tissue(const deco_state *ds)
{
	return ds->ci_pointing_to_guiding_tissue;
}

} // extern "C"
