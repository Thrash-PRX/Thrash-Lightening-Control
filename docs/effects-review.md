# Effect review

| Existing mode | Decision | Reason |
| --- | --- | --- |
| Steady | Keep | Stable useful illumination without repeated writes |
| Battery Saver | Keep | Input-based wake and idle sleep |
| Breathe | Keep as Calm Breathe | One slow ambient rhythm |
| Surge Wave | Retire; saved selection migrates to Breathe | Another timing envelope over the same single zone, adds little practical value |
| Reactive | Keep | Typing feedback with physical hold/release tracking |
| Music / Mic | Retire; saved selection migrates to Speaker Beats | Noisy ambient response and microphone access add complexity; output-only mode is more useful |
| Music / Speaker | Keep as Speaker Beats | Entertainment mode driven by actual output peaks |

Earlier flashing modes (Heartbeat, Disco, Pulse, Binary Clock, Blink, Strobe, SOS, Lightning and Candle) stay retired.

New Focus Timer runs 25 minutes of steady light, a six-second double-breathe reminder and the remainder of a five-minute break dark. The next focus interval begins at 30 minutes. It has a visible phase/countdown and resets on reselection. New Night Shift uses local clock boundaries to keep light dim overnight (22:00–07:00). It never requests an unsupported native level.

All effects operate globally on Off/Dim/Bright, or Off/On where appropriate. No RGB or spatial wave is claimed. Hardware acceptance is needed for perceived transitions and bridge latency.
