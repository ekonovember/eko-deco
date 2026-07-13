// SPDX-License-Identifier: GPL-2.0
// Minimal stand-in for Subsurface core/pref.h — only what deco.cpp needs.
#ifndef PREF_H
#define PREF_H

enum deco_mode {
	BUEHLMANN,
	RECREATIONAL,
	VPMB
};

extern enum deco_mode pref_deco_mode(bool in_planner);

#endif // PREF_H
