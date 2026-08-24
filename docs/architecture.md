# Architecture

## Runtime flow

```text
Qt desktop UI
    │
    ├── EffectEngine worker thread
    │       ├── Timed brightness patterns
    │       ├── Windows keyboard hook + combined input activity (Reactive and Battery Saver)
    │       ├── PortAudio input (Music · Mic only)
    │       └── Windows Core Audio peak meter (Music · Speaker only)
    │
    └── KeyboardBacklightController
            │
            └── Hidden persistent Windows PowerShell process
                    │
                    └── Lenovo Vantage IdeaNotebookAddin .NET assemblies
                            │
                            └── Lenovo hardware driver
```

## Lenovo bridge

The installed Lenovo Vantage add-in exposes a private .NET API rather than a stable public SDK. The controller discovers the newest complete `IdeaNotebookAddin` directory, starts Windows PowerShell from its fixed System32 path, loads the contract assemblies, and obtains the `IdeaNotebookAgent` singleton through reflection.

Brightness changes mutate `KeyboardBacklightStatus`, serialize Lenovo's request object, and call the two-parameter `SetBacklight` method. Keeping the helper process alive avoids the startup cost of loading .NET and Lenovo assemblies for every frame.

The helper is created with `CREATE_NO_WINDOW`, receives only fixed brightness tokens, and merges output streams so a Lenovo error cannot block on an unread pipe. A controller monitor automatically reinitializes the bridge if it exits.

## Effect engine

Effects execute on a daemon worker thread. The controller serializes hardware writes with a lock. Stopping an effect signals an event, joins the worker, closes effect-specific audio resources, and restores the nearest native level for the selected intensity.

Lenovo's white-backlight contract exposes either one or two illuminated levels plus off. The 1–100 control, Breathe, fades, and Wave use 60 Hz pulse-density blending between adjacent native states. This improves perceived smoothness but does not invent additional hardware brightness levels or spatial zones.

## Audio modes

- Music · Mic uses `sounddevice.RawInputStream` with 16-bit mono input. RMS is calculated in memory.
- Music · Speaker uses `IAudioMeterInformation::GetPeakValue` on the current Windows render endpoint through `pycaw`.

Microphone energy uses adaptive floor/peak normalization. Speaker mode compares fast and slow output envelopes to identify sudden beat-like attacks, applies a short adaptive cooldown, and turns each onset into a bright/dim pulse. Core Audio exposes only the endpoint peak here, so no speaker samples are captured or stored.

## Battery saver and startup

Battery Saver combines the global keyboard hook with Windows' `GetLastInputInfo` timestamp. A startup launch begins with the keyboard off. The first keyboard or mouse input performs a sine-eased wake to the remembered intensity; keypresses, mouse movement, clicks, and scrolling reset the timer, and the light fades off after 30 seconds of total input inactivity. The keyboard hook remains active so that, when Space is observed, the worker can poll Lenovo's native state after the firmware shortcut settles and synchronize Fn+Space changes when the contract reports them.

The startup toggle creates or removes two linked per-user entries: a Windows `Run` value visible in Task Manager's Startup apps page, and an on-demand Task Scheduler action with `HighestAvailable` privileges. At sign-in the Run value starts the task, which launches the app hidden in the notification area. No background service is installed.

## Packaging

PyInstaller creates an application folder containing Python, Qt, the application artwork, PortAudio support, and Core Audio bindings. Inno Setup compresses that folder and verification documents into one installer. Lenovo proprietary assemblies are intentionally discovered at runtime and are never included.
