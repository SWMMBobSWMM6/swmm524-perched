#include <fcntl.h>
#include <string.h>
#include <errno.h>
static unsigned wasi_shim_counter = 0;
int mkstemp(char *tmpl)
{
    size_t n = strlen(tmpl);
    if (n < 6 || strcmp(tmpl + n - 6, "XXXXXX") != 0) { errno = EINVAL; return -1; }
    for (int tries = 0; tries < 1000; tries++) {
        unsigned v = ++wasi_shim_counter;
        for (int i = 0; i < 6; i++) { tmpl[n - 1 - i] = "0123456789abcdef"[v & 15]; v >>= 4; }
        int fd = open(tmpl, O_RDWR | O_CREAT | O_EXCL, 0600);
        if (fd >= 0 || errno != EEXIST) return fd;
    }
    errno = EEXIST; return -1;
}
