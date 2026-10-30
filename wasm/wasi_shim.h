/* WASI build shim: wasi-libc has no mkstemp; SWMM uses it only for scratch file names. */
#ifndef WASI_SHIM_H
#define WASI_SHIM_H
int mkstemp(char *tmpl);
#endif
