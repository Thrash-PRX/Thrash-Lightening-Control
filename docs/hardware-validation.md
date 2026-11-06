# Hardware validation — 2026-11-06

Device: Lenovo LOQ 15ARP9 (83JC). Lenovo IdeaNotebookAddin contract: 1.0.13.114. Reported capability: TwoLevels (Off, Dim, Bright). Validation used real hardware and current source, without administrator elevation. No serial numbers, typed characters, network details or audio samples are included.

| Check | Evidence | Result |
| --- | --- | --- |
| Native brightness | Off → Dim → Bright → Dim; all Lenovo readbacks matched; user visually confirmed the repeated four-second sequence | Pass |
| Read latency | Three initial queries: 2.09, 3.34, 2.89 ms | Observed |
| Write latency | Warm native commands approximately 3.5–4.9 ms; first write after initialization approximately 115–157 ms | Observed |
| Calm Breathe | 12 seconds, 10 successful writes using levels 0/1/2, no errors; user confirmed visible breathing | Pass for short run |
| Reactive | Real global hook detected 11 physical keypresses; 22 successful Dim/Bright writes; user confirmed hold/release behavior | Pass for short run |
| Battery Saver idle | Actual 30-second timeout, sleeping at 30.003 seconds, native level 0 | Pass |
| Battery Saver wake | User reported wake but found the upward ramp uncomfortable. Replaced it with direct restoration of selected native brightness. Live revised app recorded only Off → Dim, with native and 3D preview both at level 1 and no Bright request | API/live-preview pass; final comfort feedback pending |
| Focus Timer | Accelerated boundary: steady focus, six-second reminder, dark break. Native readback at break: Off; no errors | Boundary smoke pass; full 25-minute soak not run |
| Night Shift | Local hour 7: daytime status and Bright readback were correct | Daytime smoke pass; overnight boundary not run on hardware |
| Speaker Beats | Real Windows output peak meter ran six seconds, maximum reported envelope about 0.98, no errors | Interface smoke pass; rhythm quality not visually confirmed |
| Owned-helper recovery | Only the test's PowerShell helper was terminated. Replacement connected automatically, reconnect count incremented and a subsequent Dim command succeeded | Recovery pass; pipe-finalization warning found and cleanup guarded |
| Real UI/preview | Current source window connected to Lenovo; live native Dim and 3D-preview Dim matched | Pass for Dim state |

## Hardware-driven changes

Battery Saver now wakes directly to the selected Dim or Bright native level. It does not run an Off → Dim → Bright wake envelope. Fn+Space selection is also checked while asleep so a newly selected Dim level is not overwritten by an older Bright target. Unit regressions cover both direct wake levels and the asleep Fn+Space case.

Helper shutdown explicitly closes owned pipes and guards closed-pipe errors after an unexpected helper exit. This addresses an OSError finalization warning observed during recovery testing.

The live validation window uses an isolated test preference store with Dim selected. It does not overwrite the user's saved settings or install a release.

## Remaining acceptance

- User confirmation that revised direct Dim wake is comfortable.
- Revised app's physical Fn+Space synchronization, including asleep operation.
- Startup/sign-in and upgrade behavior of the packaged build.
- Full Focus Timer cycle, overnight Night Shift transition and sustained audio/lighting soak.
- No merge or release until remaining acceptance is reviewed.
