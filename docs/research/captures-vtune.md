# vtune verbatim output captures

Confidence: verbatim-verified

## Synthesis (what the mock must emit)

MOCK VTUNE EMISSION SPEC (byte-realistic, derived from verbatim captures above)

1. STREAMS. All 'vtune:'-prefixed status/progress/warning/error lines go to stderr; the application's own output and the report/summary body go to stdout. The wanggan768q MCP server reads stdout only and treats nonzero exit as error, so reports MUST be clean on stdout and exit 0.

2. 'vtune -collect hotspots -r <dir> -- <app>' stderr sequence (each line exactly):
   [optional] vtune: Warning: Microarchitecture performance insights will not be available. Make sure the sampling driver is installed and enabled on your system.
   vtune: Collection started. To stop the collection, either press CTRL-C or enter from another console window: vtune -r <ABSOLUTE result dir> -command stop.
   <app stdout passes through>
   vtune: Collection stopped.
   vtune: Using result path `<ABSOLUTE result dir>'      <- backquote+quote pattern `...'
   Then finalization progress lines, format: "vtune: Executing actions %2d %% %s" — literally 'vtune: Executing actions  0 % Finalizing results' (two spaces before single-digit percent, one space before ' % '). Real vtune pads each to ~79 cols with trailing spaces and terminates with \r (same line overwritten); milestone sequence 0,0,0,7,7,12,12,14,19,...,50 (Saving the result),50 Generating a report,75 Setting data model parameters,75 Generating a report,100 Generating a report,100 done. Action strings seen: Finalizing results / Finalizing the result / Clearing the database / Loading raw data to the database / Loading '<file>' file / Updating precomputed scalar metrics / Processing profile metrics and debug information / Setting data model parameters / Resolving module symbols / Resolving information for `<module>' / Resolving bottom user stack information / Resolving thread name information / Resolving call target names for dynamic code / Resolving interrupt name information / Preparing output tree / Parsing columns in input tree / Creating top-level columns / Creating top-level rows / Precomputing frequently used data / Discarding redundant overtime data / Saving the result / Generating a report.
   Interleaved warnings: "vtune: Warning: Cannot locate debugging information for file `<abs path>'."
   After collect, vtune auto-prints the summary report (stdout), then final stderr lines '...100 % Generating a report' and '...100 % done'.

3. SUMMARY report body (stdout), sw-sampling hotspots — exact skeleton:
   Elapsed Time: 1.307s\n    CPU Time: 16.663s\n        Effective Time: 16.663s\n        Spin Time: 0s\n        Overhead Time: 0s\n    Total Thread Count: 16\n    Paused Time: 0s\n\nTop Hotspots\n then a space-aligned table with header 'Function  Module  CPU Time  % of CPU Time(%)' (col widths fit data; dashes row of '-' matching each column width; CPU Time right-aligned like '6.021s'; percent right-aligned like '36.1%'; last row '[Others]  N/A  ...'), then WITHOUT blank line 'Collection and Platform Info' with 4-space-indented 'Application Command Line: ./app "arg1" "arg2" ' (args individually double-quoted, trailing space), Operating System:, Computer Name:, Result Size: 4.0 MB , Collection start time: HH:MM:SS DD/MM/YYYY UTC, Collection stop time:, Collector Type: User-mode sampling and tracing (or 'Event-based sampling driver' / 'Driverless Perf per-process sampling'), CPU block (Name:, Frequency:, Logical CPU Count:, optional Cache Allocation Technology sub-block). End with blank line + fixed hint block: 'If you want to skip descriptions of detected performance issues in the report,\nenter: vtune -report summary -report-knob show-issues=false -r <my_result_dir>.\nAlternatively, you may view the report in the csv format: vtune -report\n<report_name> -format=csv.' Issue descriptions are ' | '-prefixed wrapped lines directly under a metric line.

4. 'vtune -report hotspots' DEFAULT (text): two-space separated aligned columns 'Function  CPU Time  CPU Time:Effective Time  CPU Time:Spin Time  CPU Time:Overhead Time  Module  Function (Full)  Source File  Start Address', dash row per column, times with 's' suffix ('0.560s', '0s') right-aligned, Source File '[Unknown]' when no symbols, Start Address hex '0x401176' left-aligned.

5. 'vtune -report hotspots -format csv' (no -csv-delimiter): DELIMITER IS TAB. Evidence: the vtune-mcp-server issues exactly this command and splits on '\\t' (its tests hardcode tab fixtures), and independent user-committed CSVs from plain '-format csv' are tab-delimited. Intel's docs never state a default — they say csv 'must' be combined with -csv-delimiter (comma|tab|semicolon|colon) — so the default is undocumented but empirically tab; flag this if exactness matters. Header (sw-sampling, group-by function): 'Function\\tCPU Time\\tCPU Time:Effective Time\\tCPU Time:Spin Time\\tCPU Time:Overhead Time\\tModule\\tFunction (Full)\\tSource File\\tStart Address'. There is NO '% of CPU Time' column in the CSV report (that exists only in the summary Top Hotspots table). Values: seconds as bare floats with 6 decimals ('47.479808'), zero as '0.0', integer counters bare ('20662505000'). With -csv-delimiter comma, fields containing commas get double-quoted. Threaded runs may expand Spin/Overhead into ':Imbalance or Serial Spinning/:Lock Contention/:Other' and ':Creation/:Scheduling/:Reduction/:Atomics/:Other' sub-columns; hw-sampling adds 'Instructions Retired', 'Microarchitecture Usage(%)', 'Microarchitecture Usage:Microarchitecture Usage(%)', 'Microarchitecture Usage:CPI Rate'. Top-down CSV: first column 'Function Stack', metrics 'CPU Time:Total'/'CPU Time:Self', first row 'Total', depth = leading spaces in field 1.

6. ERRORS (stderr, nonzero exit): use the verbatim lines captured — 'This analysis type is not applicable to the system because VTune Profiler cannot recognize the processor. ...', 'This analysis type is not applicable to the current machine microarchitecture.', 'Cannot enable event-based sampling collection: Architectural Performance Monitoring version is 0. ...', 'This analysis requires one of these actions: a) Install Intel Sampling Drivers. b) Configure driverless collection with Perf system-wide profiling. ...'. For a bad analysis type ('vtune -collect nonsense'), output verifiably CONTAINS the substring 'Cannot find analysis type' (Galois scripts grep for exactly that), but I could not capture the full sentence verbatim; emit e.g. "vtune: Error: Cannot find analysis type `nonsense'." and treat the wording after the substring as reconstructed.

## Collection-phase stdout/stderr transcript of 'vtune -collect hotspots' (VTune 2025.0, sw sampling / user-mode sampling and tracing), including start/stop lines, warnings, and 'Executing actions' progress lines. NOTE: progress lines are emitted with trailing-space padding and carriage returns; in this captured log they appear concatenated/one-per-line.

Source: https://github.com/vaishnavirathi456-coder/eece5640-final-project/blob/main/heat_flow/vtune_results.txt

~~~
vtune: Warning: Microarchitecture performance insights will not be available. Make sure the sampling driver is installed and enabled on your system.
vtune: Collection started. To stop the collection, either press CTRL-C or enter from another console window: vtune -r /home/rathi.va/final_project/heat_flow/vtune_heat -command stop.
Grid: 2048x2048 | Threads: 16 | Time: 1.2802 seconds
vtune: Collection stopped.
vtune: Using result path `/home/rathi.va/final_project/heat_flow/vtune_heat'
vtune: Executing actions  0 %
vtune: Executing actions  0 % Finalizing results
vtune: Executing actions  0 % Finalizing the result
vtune: Executing actions  0 % Clearing the database
vtune: Executing actions  7 % Clearing the database
vtune: Executing actions  7 % Loading raw data to the database
vtune: Executing actions  7 % Loading 'systemcollector-3629064-d0143.sc' file
vtune: Executing actions 12 % Loading 'systemcollector-3629064-d0143.sc' file
vtune: Executing actions 12 % Loading '3629064-3629139.0.trace' file
vtune: Executing actions 12 % Updating precomputed scalar metrics
vtune: Executing actions 14 % Updating precomputed scalar metrics
vtune: Executing actions 14 % Processing profile metrics and debug information
vtune: Executing actions 19 % Processing profile metrics and debug information
vtune: Executing actions 19 % Setting data model parameters
vtune: Executing actions 19 % Resolving module symbols
vtune: Executing actions 19 % Resolving information for `heat_flow'
vtune: Executing actions 19 % Resolving information for `libgomp.so.1'
vtune: Warning: Cannot locate debugging information for file `/home/rathi.va/final_project/heat_flow/heat_flow'.
vtune: Warning: Cannot locate debugging information for file `/lib64/libgomp.so.1'.
vtune: Executing actions 19 % Resolving information for `libc.so.6'
vtune: Warning: Cannot locate debugging information for file `/lib64/libc.so.6'.
vtune: Executing actions 22 % Resolving bottom user stack information
vtune: Executing actions 23 % Resolving thread name information
vtune: Executing actions 24 % Resolving call target names for dynamic code
vtune: Executing actions 25 % Resolving interrupt name information
vtune: Executing actions 26 % Processing profile metrics and debug information
vtune: Executing actions 30 % Setting data model parameters
vtune: Executing actions 30 % Precomputing frequently used data
vtune: Executing actions 36 % Updating precomputed scalar metrics
vtune: Executing actions 37 % Discarding redundant overtime data
vtune: Executing actions 39 % Saving the result
vtune: Executing actions 50 % Saving the result
vtune: Executing actions 50 % Generating a report
vtune: Executing actions 50 % Setting data model parameters
vtune: Executing actions 75 % Setting data model parameters
vtune: Executing actions 75 % Generating a report
[... summary report text here, see next sample ...]
vtune: Executing actions 100 % Generating a report
vtune: Executing actions 100 % done
~~~

## Complete 'vtune -report summary' text for a hotspots (sw-sampling) result, printed after collection: Elapsed Time block, Top Hotspots table (4 columns incl. '% of CPU Time(%)'), Collection and Platform Info, and the closing hint block. VTune 2025.0. Spacing is verbatim (4-space indents, aligned columns).

Source: https://github.com/vaishnavirathi456-coder/eece5640-final-project/blob/main/heat_flow/vtune_results.txt

~~~
Elapsed Time: 1.307s
    CPU Time: 16.663s
        Effective Time: 16.663s
        Spin Time: 0s
        Overhead Time: 0s
    Total Thread Count: 16
    Paused Time: 0s

Top Hotspots
Function             Module        CPU Time  % of CPU Time(%)
-------------------  ------------  --------  ----------------
func@0x1fe10         libgomp.so.1    6.021s             36.1%
func@0x1fc70         libgomp.so.1    5.452s             32.7%
heat_flow._omp_fn.0  heat_flow       4.460s             26.8%
func@0x1e860         libgomp.so.1    0.360s              2.2%
GOMP_parallel        libgomp.so.1    0.350s              2.1%
[Others]             N/A             0.020s              0.1%
Collection and Platform Info
    Application Command Line: ./heat_flow "2048" "16" 
    Operating System: 5.14.0-362.13.1.el9_3.x86_64 \S Kernel \r on an \m 
    Computer Name: d0143
    Result Size: 4.0 MB 
    Collection start time: 03:04:15 09/04/2026 UTC
    Collection stop time: 03:04:17 09/04/2026 UTC
    Collector Type: User-mode sampling and tracing
    CPU
        Name: Unknown
        Frequency: 1.996 GHz
        Logical CPU Count: 128
        Cache Allocation Technology
            Level 2 capability: not detected
            Level 3 capability: available

If you want to skip descriptions of detected performance issues in the report,
enter: vtune -report summary -report-knob show-issues=false -r <my_result_dir>.
Alternatively, you may view the report in the csv format: vtune -report
<report_name> -format=csv.
~~~

## Older-version summary variant (VTune 2021.1.1, hotspots): CPU Time block with Idle/Poor/Ok/Ideal/Over sub-lines, 3-column Top Hotspots (no % column), and a performance-issue description block prefixed with ' | '.

Source: https://github.com/thgdsg/perf-analysis/blob/main/stage2/logs/web-BerkStan/hotspots/threads-4/ht-true/bind-spread/run-5/pr_web-BerkStan_t4_5_20251004-180639.log

~~~
    CPU Time: 7.410s
        Effective Time: 7.410s
            Idle: 0s
            Poor: 7.410s
            Ok: 0s
            Ideal: 0s
            Over: 0s
        Spin Time: 0s
        Overhead Time: 0s
    Total Thread Count: 4
    Paused Time: 0s

Top Hotspots
Function                                                                       Module          CPU Time
-----------------------------------------------------------------------------  --------------  --------
PageRankPullGS._omp_fn.1                                                       pr                5.678s
std::istream::operator>>                                                       libstdc++.so.6    0.912s
func@0x18e20                                                                   libgomp.so.1      0.210s
BuilderBase<int, int, int, (bool)1>::MakeCSR._omp_fn.14                        pr                0.158s
std::__introsort_loop<int*, long, __gnu_cxx::__ops::_Iter_less_iter>.isra.236  pr                0.116s
[Others]                                                                       N/A               0.337s
Effective Physical Core Utilization: 6.3% (2.755 out of 44)
 | The metric value is low, which may signal a poor physical CPU cores
 | utilization caused by:
 |     - load imbalance
 |     - threading runtime overhead
 |     - contended synchronization
 |     - thread/process underutilization
 |     - incorrect affinity that utilizes logical cores instead of physical
 |       cores
 | Explore sub-metrics to estimate the efficiency of MPI and OpenMP parallelism
 | or run the Locks and Waits analysis to identify parallel bottlenecks for
 | other parallel runtimes.
~~~

## Default-delimiter CSV output of 'vtune -report hotspots ... -format csv' (no -csv-delimiter): TAB-delimited (tabs shown as \t). This is the exact sw-sampling hotspots header + data rows. CPU Time is raw seconds with 6 decimals, zero is '0.0', no 's' suffix, no '% of CPU Time' column.

Source: https://github.com/YYYusei/llm-hpc-project/blob/main/results/vtune/hpcg_vtune_hotspots_new.csv

~~~
Function\tCPU Time\tCPU Time:Effective Time\tCPU Time:Spin Time\tCPU Time:Overhead Time\tModule\tFunction (Full)\tSource File\tStart Address
ComputeSYMGS_ref\t47.479808\t47.479808\t0.0\t0.0\txhpcg\tComputeSYMGS_ref(SparseMatrix_STRUCT const&, Vector_STRUCT const&, Vector_STRUCT&)\t[Unknown]\t0x27180
ComputeSPMV_ref\t19.070656\t19.070656\t0.0\t0.0\txhpcg\tComputeSPMV_ref(SparseMatrix_STRUCT const&, Vector_STRUCT&, Vector_STRUCT&)\t[Unknown]\t0x26f90
ComputeDotProduct_ref\t1.391727\t1.391727\t0.0\t0.0\txhpcg\tComputeDotProduct_ref(int, Vector_STRUCT const&, Vector_STRUCT const&, double&, double&)\t[Unknown]\t0x25900
~~~

## Extended tab-delimited hotspots CSV header (threading-aware run): Spin Time and Overhead Time expand into sub-columns. Tabs shown as \t.

Source: https://github.com/kyc001/parallel/blob/main/ann-mpi/results/vtune_exports/hotspots_functions.csv

~~~
Function\tCPU Time\tCPU Time:Effective Time\tCPU Time:Spin Time\tCPU Time:Spin Time:Imbalance or Serial Spinning\tCPU Time:Spin Time:Lock Contention\tCPU Time:Spin Time:Other\tCPU Time:Overhead Time\tCPU Time:Overhead Time:Creation\tCPU Time:Overhead Time:Scheduling\tCPU Time:Overhead Time:Reduction\tCPU Time:Overhead Time:Atomics\tCPU Time:Overhead Time:Other\tModule\tFunction (Full)\tSource File\tStart Address
pthread_mutex_lock\t3.675855\t0.0\t3.675855\t0.0\t0.0\t3.675855\t0.0\t0.0\t0.0\t0.0\t0.0\t0.0\tlibwinpthread-1.dll\tpthread_mutex_lock\t[Unknown]\t0x2e3652ef0
~~~

## Comma-delimited hotspots CSV (generated with -csv-delimiter comma), hw event-based sampling variant: extra columns Instructions Retired / Microarchitecture Usage / CPI Rate; fields containing commas are double-quoted.

Source: https://github.com/frankkopp/FrankyCPP/blob/master/results/vtune/2026-03-06_01-54-49/hotspots.csv

~~~
Function,CPU Time,CPU Time:Effective Time,CPU Time:Spin Time,CPU Time:Overhead Time,Instructions Retired,Microarchitecture Usage(%),Microarchitecture Usage:Microarchitecture Usage(%),Microarchitecture Usage:CPI Rate,Module,Function (Full),Source File,Start Address
engine::TT::put,17.611828,17.611828,0.0,0.0,20662505000,4.3,4.3,4.495869,frankycpp_v1.5.exe,"engine::TT::put(unsigned __int64,enum chess::Depth,class chess::Move,class chess::Value,enum chess::ValueType,class chess::Value)",TT.cpp,0x14024a990
engine::TT::probe,17.298849,17.298849,0.0,0.0,21240540000,4.4,4.4,4.250564,frankycpp_v1.5.exe,engine::TT::probe(unsigned __int64 const &),TT.cpp,0x14024abd0
~~~

## Text-format (default, no -format) 'vtune -report hotspots' output: two-space-aligned columns, dashed underline row, times with 's' suffix right-aligned, Start Address left-aligned with trailing spaces.

Source: https://github.com/michael7198/tachep2024finalproject/blob/main/VTune%20files/hotspots.txt

~~~
Function  CPU Time  CPU Time:Effective Time  CPU Time:Spin Time  CPU Time:Overhead Time  Module  Function (Full)                      Source File  Start Address
--------  --------  -----------------------  ------------------  ----------------------  ------  -----------------------------------  -----------  -------------
dotprod     0.560s                   0.560s                  0s                      0s  cproj   dotprod(int*, int*, int)             [Unknown]    0x401176     
matmult     0.370s                   0.370s                  0s                      0s  cproj   matmult(int*, int*, int*, int, int)  [Unknown]    0x4011ef     
stencil     0.023s                   0.023s                  0s                      0s  cproj   stencil(int*, int*, int, int)        [Unknown]    0x40141e     
main        0.003s                   0.003s                  0s                      0s  cproj   main                                 [Unknown]    0x4015b2     
~~~

## Top-down report CSV (comma variant, generated per inferno docs with '-report top-down ... -format csv -csv-delimiter comma'): first column 'Function Stack', depth encoded as leading spaces, first data row 'Total'.

Source: https://github.com/jonhoo/inferno/blob/main/tests/data/collapse-vtune/vtune.csv

~~~
Function Stack,CPU Time:Self,Module
Total,0.0,[Unknown]
 RtlUserThreadStart,0.0,ntdll.dll
  BaseThreadInitThunk,0.0,KERNEL32.DLL
   _scrt_common_main_seh,0.0,inferno-collapse-dtrace.exe
    main,0.0,inferno-collapse-dtrace.exe
     "std::rt::lang_start<core::result::Result<(), std::io::error::Error>>",0.0,inferno-collapse-dtrace.exe
~~~

## Verbatim vtune error lines for unsupported hardware / EBS not possible (from a SLURM CI log; each line goes to stderr and collection aborts).

Source: https://github.com/xbx18502/hpc-test/blob/main/matmul_practice/performance_compare/slurm-5415.out

~~~
vtune: Error: This analysis type is not applicable to the system because VTune Profiler cannot recognize the processor. If this is an old Intel processor, please refer to the minimum hardware requirements in the release note. If this is a new Intel processor, please check for an updated version of VTune Profiler. If this is an unreleased Intel processor, please contact Online Service Center for an NDA product package.
vtune: Error: This analysis type is not applicable to the current machine microarchitecture.
vtune: Error: Cannot enable event-based sampling collection: Architectural Performance Monitoring version is 0. Make sure the vPMU feature is enabled in your hypervisor.
vtune: Error: Cannot collect memory bandwidth data. Make sure the sampling driver is installed and enabled on your system. See the Sampling Drivers help topic for more details. Note that memory bandwidth collection is not possible if you are profiling inside a virtualized environment.
~~~

## Verbatim vtune error/warning for missing sampling drivers / perf paranoid setting (stderr of a hw-sampling collect attempt).

Source: https://github.com/titansarus/umd-714-project/blob/main/SPEChpc/benchspec/HPC/621.miniswp_s/run/run_base_ref_gnu_mpi.0011/sweep_vtune.err

~~~
vtune: Error: This analysis requires one of these actions: a) Install Intel Sampling Drivers. b) Configure driverless collection with Perf system-wide profiling. To enable Perf system-wide profiling, set /proc/sys/kernel/perf_event_paranoid to 1 or set up Perf tool capabilities.
vtune: Warning: Access to /proc/kallsyms file is limited. Consider changing /proc/sys/kernel/kptr_restrict to 0 to enable resolution of OS kernel and kernel module symbols.
~~~

## Common warnings and hw-summary Collection and Platform Info variants: kernel-symbols warning, 'Event-based sampling driver' and 'Driverless Perf per-process sampling' collector types, CPU Name strings.

Source: https://github.com/SlugLab/CXLMemSim/blob/master/artifact/gapbs/tc/vtune.txt and https://github.com/kerszamaral/pdp_jacobi/blob/main/vtune_results/laplace_mp_1024_15000_39.txt

~~~
vtune: Warning: Cannot locate debugging information for the Linux kernel. Source-level analysis will not be possible. Function-level analysis will be limited to kernel symbol tables. See the Enabling Linux Kernel Analysis topic in the product online help for instructions.
---
Collection and Platform Info
    Application Command Line: ./laplace_mp "1024" "15000" 
    Operating System: 6.1.0-28-amd64 12.10
    Computer Name: hype2
    Result Size: 45.6 MB 
    Collection start time: 20:05:47 04/04/2025 UTC
    Collection stop time: 20:05:52 04/04/2025 UTC
    Collector Type: Driverless Perf per-process sampling
    CPU
        Name: Intel(R) Xeon(R) E5/E7 v3 Processor code named Haswell
        Frequency: 2.295 GHz 
        Logical CPU Count: 40
        Max DRAM Single-Package Bandwidth: 59.000 GB/s
---
    Collector Type: Event-based sampling driver
    CPU
        Name: Intel(R) Xeon(R) Processor code named Sapphirerapids
        Frequency: 3.000 GHz
        Logical CPU Count: 12
---(hw run start)
vtune: Peak bandwidth measurement started.
vtune: Peak bandwidth measurement finished.
vtune: Collection started. To stop the collection, either press CTRL-C or enter from another console window: vtune -r /home/steve/CXLMemSim-dev/build/r012macc -command stop.
~~~

## What the target consumer (wanggan768q/vtune-mcp-server server.py + tests) expects: commands issued with '-format csv' and NO -csv-delimiter; parser splits lines on '\t'; skips lines starting with 'vtune:' or 'Elapsed Time'; top-down header's first field must be exactly 'Function Stack'; columns read by name: 'CPU Time:Total', 'CPU Time:Self'. Test fixtures encode tab-delimited output.

Source: https://github.com/wanggan768q/vtune-mcp-server/blob/main/server.py

~~~
Commands: ["-report", "hotspots", "-result-dir", result_dir, "-format", "csv", "-group-by", group_by] (+ optional ["-report-knob", "show-issues=false"]); ["-report", "summary", "-result-dir", result_dir, "-format", "text"]; ["-report", "top-down", "-result-dir", dir, "-format", "csv"] with knobs ["-report-knob", "show-issues=false", "-report-knob", "hide-recursive-entries=true"].
Parser (_parse_topdown): skips `if not line.strip() or line.startswith("vtune:") or line.startswith("Elapsed Time")`; requires `'\t' in line`; `parts = line.split('\t')`; header detected when `parts[0].strip() == "Function Stack"`; depth = count of leading spaces in parts[0].
Runner: uses subprocess result.stdout only when returncode==0; on nonzero returns '[VTune Error (exit N)]\n' + stderr.
Test fixture: "Function Stack\tCPU Time:Total\tCPU Time:Self\nTotal\t100.0\t0.0\n _start\t99.9\t0.0\n  main\t95.5\t5.0\n   foo\t50.0\t3.0\n"
~~~
