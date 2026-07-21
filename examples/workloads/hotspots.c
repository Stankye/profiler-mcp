/*
 * Deterministic profiling workload with named hotspots.
 *
 * Each hot_* function has a distinct performance signature so a profiler
 * (real or mock) can be validated against known-good attribution:
 *
 *   hot_compute  — FP-heavy, core-bound; should dominate cycles, low CPI
 *   hot_memory   — strided loads over a large buffer; cache-miss heavy, high CPI
 *   hot_branch   — data-dependent unpredictable branches; branch-miss heavy
 *
 * Usage: hotspots [--seconds N] [--only compute|memory|branch]
 * Default runs all three, weighted roughly 50/30/20 in wall time.
 *
 * Build: cc -O2 -g -o hotspots hotspots.c
 * (noinline attributes keep the functions visible to samplers at -O2)
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MEM_BUF_ELEMS (64 * 1024 * 1024 / sizeof(uint64_t)) /* 64 MiB */

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

__attribute__((noinline)) static double hot_compute(uint64_t iters) {
    double acc = 1.0001;
    for (uint64_t i = 0; i < iters; i++) {
        acc = acc * 1.0000001 + 0.0000001;
        acc = acc / 1.0000001;
    }
    return acc;
}

__attribute__((noinline)) static uint64_t hot_memory(uint64_t *buf, uint64_t iters) {
    uint64_t sum = 0, idx = 0;
    for (uint64_t i = 0; i < iters; i++) {
        /* stride of 8193 elements defeats prefetch and thrashes cache */
        idx = (idx + 8193) & (MEM_BUF_ELEMS - 1);
        sum += buf[idx];
        buf[idx] = sum;
    }
    return sum;
}

__attribute__((noinline)) static uint64_t hot_branch(uint64_t iters) {
    uint64_t sum = 0, x = 88172645463325252ULL;
    for (uint64_t i = 0; i < iters; i++) {
        /* xorshift makes the branch condition unpredictable */
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        if (x & 1) sum += x >> 3;
        else if (x & 2) sum -= x >> 5;
        else sum ^= x >> 7;
    }
    return sum;
}

static void run_phase(const char *name, double budget_sec,
                      double (*fc)(uint64_t), uint64_t *(mem_buf),
                      uint64_t (*fm)(uint64_t *, uint64_t), uint64_t (*fb)(uint64_t)) {
    double start = now_sec();
    volatile double dsink = 0;
    volatile uint64_t usink = 0;
    uint64_t chunk = 1 << 22;
    while (now_sec() - start < budget_sec) {
        if (fc) dsink += fc(chunk);
        if (fm) usink += fm(mem_buf, chunk / 4);
        if (fb) usink += fb(chunk);
    }
    fprintf(stderr, "phase %-8s ran %.2fs\n", name, now_sec() - start);
}

int main(int argc, char **argv) {
    double seconds = 10.0;
    const char *only = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--seconds") && i + 1 < argc) seconds = atof(argv[++i]);
        else if (!strcmp(argv[i], "--only") && i + 1 < argc) only = argv[++i];
    }

    uint64_t *buf = malloc(MEM_BUF_ELEMS * sizeof(uint64_t));
    if (!buf) { perror("malloc"); return 1; }
    memset(buf, 1, MEM_BUF_ELEMS * sizeof(uint64_t));

    if (only) {
        if (!strcmp(only, "compute")) run_phase("compute", seconds, hot_compute, NULL, NULL, NULL);
        else if (!strcmp(only, "memory")) run_phase("memory", seconds, NULL, buf, hot_memory, NULL);
        else if (!strcmp(only, "branch")) run_phase("branch", seconds, NULL, NULL, NULL, hot_branch);
        else { fprintf(stderr, "unknown --only %s\n", only); return 2; }
    } else {
        run_phase("compute", seconds * 0.5, hot_compute, NULL, NULL, NULL);
        run_phase("memory", seconds * 0.3, NULL, buf, hot_memory, NULL);
        run_phase("branch", seconds * 0.2, NULL, NULL, NULL, hot_branch);
    }
    free(buf);
    return 0;
}
