# uprof verbatim output captures

Confidence: verbatim-verified

## Synthesis (what the mock must emit)

MOCK GENERATOR SPEC (byte-realistic AMDuProfCLI, target version 5.x — modeled on 5.0.1479/5.1.701)

A) 'AMDuProfCLI profile --config hotspots --output-dir <D> --log-path <D> <exe> [args]' stdout (this is what intellikit runs; both regexes 'Generated data files path: (.*)' and 'Generated report file: (.*)' must match this ONE stdout). Emit, in order:
  1. '<resolved-absolute-path-to>/AMDuProfCLI' (the binary echoes its own path as the very first line — verified in 4.0, 4.1 and 5.0 captures)
  2. 'Profiling started'            (NO trailing dots in 5.x; 4.1 printed 'Profiling started...')
  3. <application stdout passthrough>
  4. 'Profiling (data collection) completed ' (EXACT casing, ONE TRAILING SPACE — byte-verified in 5.0)
  5. 'Generated data files path: <D>/AMDuProf-<name>-Hotspots_<Mon>-<DD>-<YYYY>_<HH-MM-SS>'
  6. report phase (verbatim-verified on 4.0.341; carried into 5.x profile — the only reconstructed part of this spec is that these exact lines follow within 'profile'):
     'Translation started ...'  /  'Translation finished'  /  'Generated database file : cpu' (space before colon)  /  'Report generation started...'  /  'Generating report file...'  /  ''  /  'Report generation completed...'  /  ''  /  'Generated report file: <session-dir>/report.csv'
  Session dir name: 'AMDuProf-' + exe basename with extension stripped ('argonmd_o2_gcc.x'→'argonmd_o2_gcc', 'stream.22gb'→'stream') + '-' + session type + '_' + strftime('%b-%d-%Y_%H-%M-%S'). Session type by config: hotspots→Hotspots, tbp→TBP, assess/branch/data_access→EBP, ibs→IBS, overview→Overview, threading→Threading, timechart→Timechart. 'collect' alone stops after line 5; 'report -i <dir>' alone prints line 1 then the report phase.

B) report.csv (hotspots) — exact layout, LF endings, file BEGINS with one empty line, NO trailing newline at EOF:
  line1: ''  |  line2: '"AMD uProf (Version:5.1.701.0)"' (pattern "AMD uProf (Version:<maj.min.build.0>)")  |  line3: 'PERFORMANCE ANALYSIS REPORT'  |  blank
  'EXECUTION' section — rows are 'Key:,"value"' (key unquoted incl. trailing colon, comma, value double-quoted; empty values render as bare 'Command Line Arguments:' / 'Environment Variables:'): Target Path / Command Line Arguments / Working Directory / Environment Variables / CPU Details ("Family(0x19), Model(0x44), Number of Cores(12)") / Operating System / Collect Command (full argv as typed) / Report Command. blank
  'PROFILE DETAILS': Profile Session Type:,"Hotspots" / Profile Scope:,"Single Application" / CPU Mask / CPU Affinity Mask / Profile Start Time:,"Mon Jun  9 15:35:29 2025" (asctime, 2-space day pad) / Profile End Time / Profile Duration:,"5.960 seconds" (3 decimals — intellikit-adjacent parsers read field[1].split()[0]) / Data Folder / Virtual Machine:,"No" / Timer Interval:,"10ms" / Profiling Signal:,"27" / Call Stack Sampling:,"True" / Call Stack Overcome frame-pointer omission:,"False" / Call Stack Unwind Depth:,"32" / Selected View:,"Time based hotspots". blank
  'MONITORED EVENTS': header ',...' shape: 'TBP Events:,Name,Interval,Description' then ',"CPU_TIME","10.000 milliseconds","CPU Time is the time in which the CPU core is executing the code."' TWO blank lines.
  'APPLICATION PERFORMANCE SNAPSHOT': 'Number Of Threads,"1"' (no colon). TWO blank lines.
  '"10 HOTTEST FUNCTIONS (Sort Event - CPU_TIME)"' (WHOLE header line double-quoted) then column row EXACTLY 'FUNCTION,"CPU_TIME" (seconds),Inclusive Time (seconds),Module' (hotspots; tbp omits the Inclusive column). Data rows: '"<demangled signature>",4.3600,4.3600,"/abs/path/to/module"' — names/paths quoted, numbers unquoted %.4f. ONE blank line between remaining sections:
  '"10 HOTTEST PROCESSES (Sort Event - CPU_TIME)"' + 'PROCESS,"CPU_TIME" (seconds)' + '"<comm-15-char-truncated> (PID:666509)",5.4000' (process name is Linux comm, truncated to 15 chars — 'argonmd_o2_gcc.');
  '"10 HOTTEST MODULES (Sort Event - CPU_TIME)"' + 'MODULE,"CPU_TIME" (seconds)' + '"/abs/module/path",5.4000';
  '"10 HOTTEST THREADS (Sort Event - CPU_TIME)"' + 'THREAD,THREAD ID,"CPU_TIME" (seconds)' + '"<comm> (PID:666509)","666509",5.4000' (TID quoted). End file WITHOUT newline. Fewer than 10 rows appear if fewer symbols have samples. For EBP configs substitute sort event CYCLES_NOT_IN_HALT and the PMC multi-metric column row captured above.
  Parser contracts observed in the wild: astroCAMP matches the literal line '"10 HOTTEST FUNCTIONS (Sort Event - CPU_TIME)"' and a line starting 'Profile Duration:'; tables terminate at the first empty line.

C) timechart: stdout = binary path, 'Profiling started...' , repeated '\\rProfile Elapse Time in ms: <n>' progress, 'Profile finished', 'Generated data files path: <session-dir>', 'Live Profile Output file : <session-dir>/timechart.csv' (space BEFORE colon). CSV file: 'AMDPROFILER POWER PROFILE REPORT' / blank / 'AMDuProfCLI Version 5.0.1479.0,' (trailing comma) / blank / 'LAUNCHED APPLICATION DETAILS' (rows with trailing commas: 'Target Path:,./app,') / 'PROFILE DETAILS' ('CPU Details:,Family(0x19) Model(0x44)', 'Sampling Interval:,100 milli-seconds', 'Profile Start Time:,Jun-23-2025_12-07-50,') / 'PROFILED COUNTERS' with 'COUNTER ID,NAME,CATEGORY,UNIT,DESCRIPTION' and rows '38.,core0-power,Power,W,Core0-Average Power reported in Watts.' / blank / 'PROFILE RECORDS' with 'RecordId,Timestamp,core0-power,...' and rows '1,12:7:50:283,    2.10,    0.15,...' (H:M:S:ms unpadded, values %8.2f space-padded).

D) 4.2→5.x CLI deltas (for flag validation): 5.0 ADDED one-shot 'profile' (collect+process+report) and 'diff'; 4.2 surface was collect/translate/report/timechart/info. Flags stable across both: --config, -o|--output-dir, -i|--input-dir, -g (callstack), -e|--event, -a (system-wide), -d (duration), --trace, --interval, --duration, --affinity, report's -g/--detail/--inline/--export-session/--view; info --system/--list {collect-configs,predefined-events,pmu-events,cacheline-events,view-configs}/--collect-config/--view-config/--pmu-event; 'hotspots' config exists in 5.x (verified 5.0; 4.x walkthroughs use tbp/assess instead). 5.x also accepts long form '--log-path' (used by intellikit). 5.3 switched report DB backend SQLite→DuckDB and added session-name options (no observed stdout change). Older 4.1-era reports used column row 'FUNCTION,"CPU_TIME",Module' WITHOUT the ' (seconds)' suffix — emit the 5.x form above. No verbatim 'info --system' output could be found in public sources (doc examples are screenshots); mock output for it is unconstrained beyond plausibility.

## COMPLETE real report.csv from 'AMDuProfCLI collect --config hotspots' + 'report', AMD uProf 5.0.1479, Linux (Ryzen 5 7535HS). Byte-verified: file STARTS with a lone LF (empty line 1), LF line endings throughout, NO trailing newline at EOF. Extracted from session tarball committed in repo.

Source: https://github.com/marcodelapierre/hpc-perf/blob/master/amdtools_argonmd/Examples/dir_amduprof_o2_gcc_ALL.tgz (path inside: dir_amduprof_o2_gcc_hotspots/AMDuProf-argonmd_o2_gcc-Hotspots_Jun-09-2025_15-35-29/report.csv)

~~~

"AMD uProf (Version:5.0.1479.0)"
PERFORMANCE ANALYSIS REPORT

EXECUTION
Target Path:,"./argonmd_o2_gcc.x"
Command Line Arguments:
Working Directory:,"/home/mdelapierre/proj/bmkg/amd-profiling"
Environment Variables:
CPU Details:,"Family(0x19), Model(0x44), Number of Cores(12)"
Operating System:,"Linux Ubuntu 24.04.1 LTS-64 Kernel:6.11.0-25-generic"
Collect Command:,"./AMDuProfCLI collect --config hotspots -g -o dir_amduprof_o2_gcc_hotspots ./argonmd_o2_gcc.x"
Report Command:,"./AMDuProfCLI report -i dir_amduprof_o2_gcc_hotspots/AMDuProf-argonmd_o2_gcc-Hotspots_Jun-09-2025_15-35-29"

PROFILE DETAILS
Profile Session Type:,"Hotspots"
Profile Scope:,"Single Application"
CPU Mask:,"0-11"
CPU Affinity Mask:,"0-11"
Profile Start Time:,"Mon Jun  9 15:35:29 2025"
Profile End Time:,"Mon Jun  9 15:35:35 2025"
Profile Duration:,"5.960 seconds"
Data Folder:,"/home/mdelapierre/proj/bmkg/amd-profiling/dir_amduprof_o2_gcc_hotspots/AMDuProf-argonmd_o2_gcc-Hotspots_Jun-09-2025_15-35-29"
Virtual Machine:,"No"
Timer Interval:,"10ms"
Profiling Signal:,"27"
Call Stack Sampling:,"True"
Call Stack Overcome frame-pointer omission:,"False"
Call Stack Unwind Depth:,"32"
Selected View:,"Time based hotspots"

MONITORED EVENTS
TBP Events:,Name,Interval,Description
,"CPU_TIME","10.000 milliseconds","CPU Time is the time in which the CPU core is executing the code."


APPLICATION PERFORMANCE SNAPSHOT
Number Of Threads,"1"


"10 HOTTEST FUNCTIONS (Sort Event - CPU_TIME)"
FUNCTION,"CPU_TIME" (seconds),Inclusive Time (seconds),Module
"compute_forc_epot(double const*, int, int, int const*, int const*, double const*, double const*, double, double, double, double*, double&)",4.3600,4.3600,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"compute_neigh(double const*, int, double const*, double const*, double, int, int*, int*)",1.0300,1.0300,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"update_pos_pbc(double*, double*, double const*, double const*, int, double, double, double, double const*)",0.0100,0.0100,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"

"10 HOTTEST PROCESSES (Sort Event - CPU_TIME)"
PROCESS,"CPU_TIME" (seconds)
"argonmd_o2_gcc. (PID:666509)",5.4000

"10 HOTTEST MODULES (Sort Event - CPU_TIME)"
MODULE,"CPU_TIME" (seconds)
"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x",5.4000

"10 HOTTEST THREADS (Sort Event - CPU_TIME)"
THREAD,THREAD ID,"CPU_TIME" (seconds)
"argonmd_o2_gcc. (PID:666509)","666509",5.4000
~~~

## Real report.csv from '--config tbp' (same tool/version). Differences vs hotspots: Profile Session Type "Time-based Sampling"; PROFILE DETAILS has 'Call Stack Size(Bytes):,"1024"' instead of Timer Interval/Profiling Signal/Call Stack Unwind Depth; TBP event interval "1.000 milliseconds"; hottest-functions header has NO 'Inclusive Time' column. Same leading-blank-line/LF/no-trailing-newline byte layout.

Source: https://github.com/marcodelapierre/hpc-perf/blob/master/amdtools_argonmd/Examples/dir_amduprof_o2_gcc_ALL.tgz (dir_amduprof_o2_gcc_tbp/AMDuProf-argonmd_o2_gcc-TBP_Jun-09-2025_15-35-35/report.csv)

~~~

"AMD uProf (Version:5.0.1479.0)"
PERFORMANCE ANALYSIS REPORT

EXECUTION
Target Path:,"./argonmd_o2_gcc.x"
Command Line Arguments:
Working Directory:,"/home/mdelapierre/proj/bmkg/amd-profiling"
Environment Variables:
CPU Details:,"Family(0x19), Model(0x44), Number of Cores(12)"
Operating System:,"Linux Ubuntu 24.04.1 LTS-64 Kernel:6.11.0-25-generic"
Collect Command:,"./AMDuProfCLI collect --config tbp -g -o dir_amduprof_o2_gcc_tbp ./argonmd_o2_gcc.x"
Report Command:,"./AMDuProfCLI report -i dir_amduprof_o2_gcc_tbp/AMDuProf-argonmd_o2_gcc-TBP_Jun-09-2025_15-35-35"

PROFILE DETAILS
Profile Session Type:,"Time-based Sampling"
Profile Scope:,"Single Application"
CPU Mask:,"0-11"
CPU Affinity Mask:,"0-11"
Profile Start Time:,"Mon Jun  9 15:35:35 2025"
Profile End Time:,"Mon Jun  9 15:35:40 2025"
Profile Duration:,"5.708 seconds"
Data Folder:,"/home/mdelapierre/proj/bmkg/amd-profiling/dir_amduprof_o2_gcc_tbp/AMDuProf-argonmd_o2_gcc-TBP_Jun-09-2025_15-35-35"
Virtual Machine:,"No"
Call Stack Sampling:,"True"
Call Stack Overcome frame-pointer omission:,"False"
Call Stack Size(Bytes):,"1024"
Selected View:,"Time based hotspots"

MONITORED EVENTS
TBP Events:,Name,Interval,Description
,"CPU_TIME","1.000 milliseconds","CPU Time is the time in which the CPU core is executing the code."


APPLICATION PERFORMANCE SNAPSHOT
Number Of Threads,"1"


"10 HOTTEST FUNCTIONS (Sort Event - CPU_TIME)"
FUNCTION,"CPU_TIME" (seconds),Module
"compute_forc_epot(double const*, int, int, int const*, int const*, double const*, double const*, double, double, double, double*, double&)",4.2450,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"compute_neigh(double const*, int, double const*, double const*, double, int, int*, int*)",0.9000,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"update_pos_pbc(double*, double*, double const*, double const*, int, double, double, double, double const*)",0.0340,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"update_vel(double*, double const*, double const*, int, double, double)",0.0030,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"do_lookup_x",0.0010,"/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"

"10 HOTTEST PROCESSES (Sort Event - CPU_TIME)"
PROCESS,"CPU_TIME" (seconds)
"argonmd_o2_gcc. (PID:666766)",5.1830

"10 HOTTEST MODULES (Sort Event - CPU_TIME)"
MODULE,"CPU_TIME" (seconds)
"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x",5.1820
"/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",0.0010

"10 HOTTEST THREADS (Sort Event - CPU_TIME)"
THREAD,THREAD ID,"CPU_TIME" (seconds)
"argonmd_o2_gcc. (PID:666766)","666766",5.1830
~~~

## Real report.csv from '--config assess' (EBP session type) — shows the PMC-events variant of MONITORED EVENTS and a multi-metric hottest-functions header. Section headers at lines: 3 PERFORMANCE ANALYSIS REPORT, 5 EXECUTION, 15 PROFILE DETAILS, 30 MONITORED EVENTS, 44 APPLICATION PERFORMANCE SNAPSHOT, 48/61/65/71 the four HOTTEST sections. Excerpt (middle PMC rows elided with [...]):

Source: https://github.com/marcodelapierre/hpc-perf/blob/master/amdtools_argonmd/Examples/dir_amduprof_o2_gcc_ALL.tgz (dir_amduprof_o2_gcc_assess/AMDuProf-argonmd_o2_gcc-EBP_Jun-09-2025_15-35-41/report.csv)

~~~
Profile Session Type:,"Assess Performance"
[...]
Selected View:,"Overall Assessment"

MONITORED EVENTS
PMC Events:,Name,Interval,Unitmask,Countmask,Invert Countmask,User,OS,Description
,"CYCLES_NOT_IN_HALT (PMCx076)",250000,0x00,0x00,False,True,True,"The number of cpu cycles when the thread is not in halt state."
,"RETIRED_INST (PMCx0C0)",250000,0x00,0x00,False,True,True,"The number of instructions retired from execution. This count includes exceptions and interrupts. Each exception or interrupt is counted as one instruction."
[... 6 more PMC event rows: RETIRED_BR_INST (PMCx0C2), RETIRED_BR_INST_MISP (PMCx0C3), MISALIGNED_LOADS (PMCx047), L1_DC_ACCESSES_ALL (PMCx029), L1_DEMAND_DC_REFILLS_LOCAL (PMCx043), L2_CACHE_ACCESS_FROM_L1_DC_MISS (PMCx060) ...]


APPLICATION PERFORMANCE SNAPSHOT
Number Of Threads,"1"


"10 HOTTEST FUNCTIONS (Sort Event - CYCLES_NOT_IN_HALT)"
FUNCTION,"CYCLES_NOT_IN_HALT","RETIRED_INST","IPC","CPI","RETIRED_BR_INST_MISP (PTI)","%RETIRED_BR_INST_MISP","L1_DC_ACCESSES (PTI)","L1_DC_MISSES (PTI)","%L1_DC_MISSES","L1_DEMAND_DC_REFILLS_LOCAL (PTI)","MISALIGNED_LOADS (PTI)",Module
"compute_forc_epot(double const*, int, int, int const*, int const*, double const*, double const*, double, double, double, double*, double&)",41066.0000,74449.0000,1.8129,0.5516,1.7206,3.1077,170.4388,1.7623,1.0340,0.1827,0.0228,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"
"main",4.0000,3.0000,0.7500,1.3333,0.0000,0.0000,666.6667,166.6667,25.0000,0.0000,0.0000,"/home/mdelapierre/proj/bmkg/linux-profiling/argonmd_o2.x"

"10 HOTTEST PROCESSES (Sort Event - CYCLES_NOT_IN_HALT)"
[...]
~~~

## COMPLETE stdout of 'AMDuProfCLI collect --config hotspots -g -o ... ./argonmd_o2_gcc.x' (AMD uProf 5.0.1479, Linux). Byte-verified with cat -e: line 1 is the resolved CLI binary path; 'Profiling started' has NO ellipsis in 5.0; 'Profiling (data collection) completed ' HAS ONE TRAILING SPACE; final line 'Generated data files path: ...' ends with newline. Application stdout appears in between, unmodified. (App output elided here with [...].)

Source: https://raw.githubusercontent.com/marcodelapierre/hpc-perf/master/amdtools_argonmd/Examples/out_amduprof_o2_gcc_hotspots

~~~
/opt/amd/software/amduprof/5.0.1479/bin/AMDuProfCLI
Profiling started

** ArgonMD **

 Box Units : 5    5    5  
 No. Time Steps : 10000
[... application stdout ...]
 Loop Clock Time [s] :      7.211
Profiling (data collection) completed 
Generated data files path: /home/mdelapierre/proj/bmkg/amd-profiling/dir_amduprof_o2_gcc_hotspots/AMDuProf-argonmd_o2_gcc-Hotspots_Jun-09-2025_15-35-29
~~~

## COMPLETE stdout of 'AMDuProfCLI report -i <session-dir>' (AMD uProf 4.0.341, NCSA Delta, real captured transcript incl. shell prompt). Note: line 1 again the CLI binary path; 'Translation started ...' (space before dots); 'Generated database file : cpu' (spaces around colon); blank line before 'Report generation completed...' and before 'Generated report file:'.

Source: https://docs.ncsa.illinois.edu/systems/delta/en/latest/user_guide/debug_perf.html (verbatim rst mirror: https://github.com/minump/HandsOn-RAG/blob/main/delta_docs/debug_perf.rst)

~~~
[arnoldg@dt-login03 uprof_tbp]$ export PATH=/sw/external/amd/AMDuProf_Linux_x64_4.0.341/bin:$PATH
[arnoldg@dt-login03 uprof_tbp]$ AMDuProfCLI report -i AMDuProf-stream-TBP_Dec-19-2022_09-40-27/
/sw/external/amd/AMDuProf_Linux_x64_4.0.341/bin/AMDuProfCLI
Translation started ...
Translation finished
Generated database file : cpu
Report generation started...
Generating report file...

Report generation completed...

Generated report file: /projects/bbka/slurm_test_scripts/cpu/stream/uprof_tbp/AMDuProf-stream-TBP_Dec-19-2022_09-40-27/report.csv
~~~

## Official AMD uProf User Guide 5.1 (doc 57368, docs.amd.com) collect example transcript — confirms the 5.x collect output shape and shows the in-progress ellipsis placeholder line.

Source: https://docs.amd.com/r/en-US/57368-uProf-user-guide/Data-Collection-With-CLI

~~~
[amd@uprof-ethanolx5 bin]$ ./AMDuProfCLI collect --config ibs -g -o /tmp/ /tmp/ScimarkStable
Profiling started
………
Profiling (data collection) completed
Generated data files path: /tmp/AMDuProf-ScimarkStable-IBS_Sep-05-2024_21-43-08
~~~

## AMDResearch/intellikit uprof_mcp source (MIT, (c) 2025-2026 AMD) — the EXACT command it runs and the EXACT regexes the mock must satisfy from the stdout of the 'profile' subcommand alone. Default CLI path /opt/AMDuProf_5.1-701/bin/AMDuProfCLI (docs also reference /opt/AMDuProf_5.3-521/bin/AMDuProfCLI); env var INTELLIKIT_UPROF_CLI; timeout 180 s.

Source: https://github.com/AMDResearch/intellikit/blob/main/uprof_mcp/src/uprof_mcp/uprof_profiler.py

~~~
cmd = [
    self.profiler_exe,
    "profile",
    "--config",
    "hotspots",
    "--output-dir",
    str(output_dir),
    "--log-path",
    str(output_dir),
    str(executable),
    *executable_args,
]
...
results_path = re.search("Generated data files path: (.*)", result.stdout)
...
report_path = re.search("Generated report file: (.*)", result.stdout)
~~~

## Third-party parser (belt, Factorio benchmark tool) — exact breadcrumb prefixes it strips, and its test fixture modeling real combined collect+report stdout; independent confirmation of the two load-bearing lines.

Source: https://github.com/florishafkenscheid/belt/blob/main/src/benchmark/parser.rs

~~~
const SESSION_PREFIX: &str = "Generated data files path:";
const REPORT_PREFIX: &str = "Generated report file:";
...
const FACTORIO_OUTPUT: &str = r#"Performed 10 updates in 100.000 ms
avg: 10.000 ms, min: 10.000 ms, max: 10.000 ms
Profiling (data collection) completed
Generated data files path: /tmp/belt-amduprof-run/session
Generated report file: /tmp/belt-amduprof-run/session/report.csv"#;
~~~

## Real 'AMDuProfCLI timechart' stdout (AMD uProf 4.1.424, Argonne Swing slurm log). Line 1 = CLI binary path; 'Profiling started...' WITH ellipsis in 4.1; then repeated carriage-return progress 'Profile Elapse Time in ms: <n>' (concatenates in captured logs); ends 'Profile finished' then the two path lines. Note 'Live Profile Output file : ' has a SPACE BEFORE the colon.

Source: https://github.com/grantwilkins/energy-inference/blob/main/job-scripts/argonne-swing/slurm-96150.out

~~~
/gpfs/fs1/soft/swing/manual/amd-uprof/4.1.424/bin/AMDuProfCLI
Profiling started...
Profile Elapse Time in ms: 0Profile Elapse Time in ms: 100Profile Elapse Time in ms: 201Profile Elapse Time in ms: 301[... repeats every ~100 ms ...]
Profile finished
Generated data files path: /gpfs/fs1/home/ac.gwilkins/energy-inference/cuda/llama2-70b/2024-05-08/07-41-31/AMDuProf-python3-Timechart_May-08-2024_07-41-31
Live Profile Output file : /gpfs/fs1/home/ac.gwilkins/energy-inference/cuda/llama2-70b/2024-05-08/07-41-31/AMDuProf-python3-Timechart_May-08-2024_07-41-31/timechart.csv
~~~

## Real timechart CSV output file (AMDuProfCLI Version 5.0.1479.0, core power counters). Note trailing commas on several metadata rows, 'RecordId,Timestamp,...' header inside PROFILE RECORDS, timestamp format H:M:S:ms without zero padding, and right-aligned space-padded numeric fields.

Source: https://raw.githubusercontent.com/marcodelapierre/hpc-perf/master/amdtools_argonmd/Examples/timechart_o2_power_cores.csv

~~~
AMDPROFILER POWER PROFILE REPORT

AMDuProfCLI Version 5.0.1479.0,

LAUNCHED APPLICATION DETAILS
Target Path:,./argonmd_o2.x,
Command Line Arguments:,,
Working Directory:,/home/mdelapierre/proj/bmkg/amd-profiling,
CPU Core Affinity Mask:,,

PROFILE DETAILS
CPU Details:,Family(0x19) Model(0x44)
Sampling Interval:,100 milli-seconds
Profile Start Time:,Jun-23-2025_12-07-50,

PROFILED COUNTERS
COUNTER ID,NAME,CATEGORY,UNIT,DESCRIPTION
38.,core0-power,Power,W,Core0-Average Power reported in Watts.
40.,core1-power,Power,W,Core1-Average Power reported in Watts.
42.,core2-power,Power,W,Core2-Average Power reported in Watts.
44.,core3-power,Power,W,Core3-Average Power reported in Watts.
46.,core4-power,Power,W,Core4-Average Power reported in Watts.
48.,core5-power,Power,W,Core5-Average Power reported in Watts.

PROFILE RECORDS
RecordId,Timestamp,core0-power,core1-power,core2-power,core3-power,core4-power,core5-power
1,12:7:50:283,    2.10,    0.15,    0.34,    0.02,    0.36,    0.03
2,12:7:50:383,    2.16,    0.08,    0.30,    0.19,    0.34,    0.06
3,12:7:50:483,    5.57,    0.07,    0.59,    0.11,    0.30,    0.07
~~~

## SURF (Snellius) uProf walkthrough — CLI command inventory as used with AMD-uProf 4.1.424 / 5.1.701 modules, a report fragment in the OLDER (pre-5.0) hottest-functions column format (no ' (seconds)' suffix), and the 'profile' one-shot output line. Useful for the info/timechart subcommand surface.

Source: https://servicedesk.surf.nl/wiki/spaces/WIKI/pages/74227822/AMD+uProf

~~~
AMDuProfCLI info --system
AMDuProfCLI info --list predefined-events
AMDuProfCLI info --list collect-configs
AMDuProfCLI timechart --list
AMDuProfCLI profile --config tbp -o AMD_profile_output --affinity 1 ./AMDTClassicMatMul
AMDuProfCLI profile --config assess -o AMD_profile_output --affinity 1 ./AMDTClassicMatMul
AMDuProfCLI profile --config memory -o AMD_profile_output --affinity 1 ./AMDTClassicMatMul
AMDuProfCLI timechart --event core=0-3,power -o AMD_profile_output --interval 10 --affinity 1 ./AMDTClassicMatMul
---
"10 HOTTEST FUNCTIONS (Sort Event - CPU_TIME)"
FUNCTION,"CPU_TIME",Module
"classic_multiply_matrices()",1607.0000,"/gpfs/home3/user/AMDTClassicMatMul"
"random_r",3.0000,"/usr/lib64/libc-2.28.so"
"initialize_matrices()",2.0000,"/gpfs/home3/user/AMDTClassicMatMul"
"rand",1.0000,"/usr/lib64/libc-2.28.so"
---
Generated report file: /home/user/AMD_profile_output/AMDuProf-AMDTClassicMatMul-TBP_Aug-11-2023_10-45-11/report.csv
~~~

## uProf User Guide 5.2/5.3 (docs.amd.com 57368) 'profile' command: per the guide it collects, processes and generates the report in one step — "an alternative to the combination of collect and report command" (sec. 9.9). Representative Linux example invocations from sec. 9.9.4.2 (selection).

Source: https://docs.amd.com/r/en-US/57368-uProf-user-guide/9.9.-Profile-Command and https://docs.amd.com/r/en-US/57368-uProf-user-guide/9.9.4.2.-Linux

~~~
$ ./AMDuProfCLI profile --config tbp -g -o /tmp/cpuprof-tbp AMDTClassicMatMul-bin
$ ./AMDuProfCLI profile --config assess -o /tmp/cpuprof-assess -d 10 AMDTClassicMatMul-bin
$ ./AMDuProfCLI profile --config ibs -a -s event=ibs_op -o /tmp/cpuprof-ibs-swp AMDTClassicMatMul-bin
$ ./AMDuProfCLI profile -a -o /tmp/cpuprof-tbp-swp -d 10
$ ./AMDuProfCLI profile -e event=pmcx76,interval=250000 -e event=pmcxc0,user=1,os=0,interval=250000 -o /tmp/cpuprof-tbp AMDTClassicMatMul-bin
$ AMDuProfCLI profile --config tbp -o /tmp/cpuprof-tbp-attach -d 10 --tid <TID>
$ AMDuProfCLI profile --trace osrt --osrt-event syscall --osrt-threshold syscall:1000000 -o /tmp/cpuprof-os AMDTClassicMatMul-bin
~~~

## uProf User Guide 4.2 (pub 57368 Rev 4.2, Jan 2024) — 4.x CLI surface for comparison: subcommands are collect / translate / report / timechart / info (no 'profile'); report.csv section inventory (EXECUTION, PROFILE DETAILS, MONITORED EVENTS, 10 HOTTEST FUNCTIONS, TAKEN BRANCH ANALYSIS SUMMARY, 10 HOTTEST PROCESSES/MODULES/THREADS, PROFILE REPORT FOR PROCESS when --detail); threading collect/report transcript excerpt below. info --list types: collect-configs, predefined-events, pmu-events, cacheline-events, view-configs.

Source: https://www.amd.com/content/dam/amd/en/documents/developer/version-4-2-documents/uprof/uprof-user-guide-v4.2.pdf

~~~
$ AMDuProfCLI collect --config threading -o /tmp/threading-analysis/ /home/app/classic_lock
...
Generated data files path: /tmp/threading-analysis/AMDuProf-classic_lock-Threading_Jun-13-2023_06-00-23
---
$ sudo AMDuProfCLI report -i /tmp/threading-analysis/AMDuProf-classic_lock-Threading_Jun-13-2023_06-00-23
...
Generated report file: /tmp/threading-analysis/AMDuProf-classic_lock-Threading_Jun-13-2023_06-00-23/report.csv
---
$ ./AMDuProfCLI translate -i /tmp/blockio-analysis/AMDuProf-classic-OsTrace_Dec-09-2021_12-19-27
...
Translation finished
---
AMDuProfCLI info [--help] [<options>]
$ AMDuProfCLI info --system
~~~
