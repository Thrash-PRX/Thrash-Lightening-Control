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

Lenovo's white-backlight contract exposes either one or two illuminated levels plus off. The 1–100 control sets an effect envelope, quantized to native states with hysteresis. Breathe and the Focus Timer reminder sample at 30 Hz and send only changes. Steady holds the nearest illuminated state. No software PWM is sent over IPC; fades remain discrete hardware steps.

## Audio and preview

Speaker Beats uses Core Audio endpoint peak metering only. No microphone path or sounddevice dependency remains.

The 3D preview is a procedural LOQ-inspired mesh drawn through Qt's existing painter: chassis, lid, screen and raised keycaps have actual 3D coordinates, camera projection and depth ordering. Orbit, zoom and reset are available through pointer, keyboard and buttons. It is an illustrative model, not official CAD. Its white key surface uses cached native controller state and adds no hardware calls. No webview, external 3D engine or continuous auto-rotation is used.

Focus Timer uses a monotonic 30-minute cycle to avoid wall-clock adjustments altering intervals. Night Shift uses local wall-clock hour for its 22:00–07:00 brightness schedule. New selections reset focus timing.

## Battery saver and startup

Battery Saver combines the global keyboard hook with Windows' `GetLastInputInfo` timestamp. A startup launch begins with the keyboard off. The first keyboard or mouse input restores the user-selected native Dim or Bright level directly, without an upward brightness ramp; keypresses, mouse movement, clicks, and scrolling reset the timer, and the light fades off after 30 seconds of total input inactivity. The keyboard hook remains active so that, when Space is observed, the worker can poll Lenovo's native state after the firmware shortcut settles and synchronize Fn+Space changes when the contract reports them.

The startup toggle creates or removes two linked per-user entries: a Windows `Run` value visible in Task Manager's Startup apps page, and an on-demand Task Scheduler action with `HighestAvailable` privileges. At sign-in the Run value starts the task, which launches the app hidden in the notification area. No background service is installed.

## Packaging

PyInstaller creates an application folder containing Python, Qt, the application artwork, PortAudio support, and Core Audio bindings. Inno Setup compresses that folder and verification documents into one installer. Lenovo proprietary assemblies are intentionally discovered at runtime and are never included.
