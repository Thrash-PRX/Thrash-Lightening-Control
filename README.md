<p align="center">
  <img src="assets/app-icon.png" width="128" alt="LOQ LIGHTENING CENTRE icon">
</p>

<h1 align="center">LOQ LIGHTENING CENTRE</h1>

<p align="center">A native Windows lighting lab for compatible Lenovo LOQ white-backlit keyboards.</p>

<p align="center">
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-38bdf8">
  <img alt="Release v3.1.2" src="https://img.shields.io/badge/Release-v3.1.2-ef4058">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-22c55e">
</p>

**THRASH · Made by Hanif**

## v3.2.0 development branch

URX Hub-inspired native Qt dashboard with URX Lighting screen proportions: compact top pills, a large live LOQ keyboard stage, icon rail, and three control panels, Dim/Bright shortcuts, themed glass panels, one-click effect selection, tray switching, and remembered preferences. The preview samples cached native brightness at 30 Hz while visible, lights every key as one white zone, and shows unavailable state when the bridge is disconnected. It sends no additional hardware commands. Physical layouts vary by model and region.

The focused mode catalog contains Steady, Battery Saver, Breathe, Surge Wave, Reactive, and the two audio modes. Repetitive Heartbeat, Disco, Pulse, and Binary Clock are retired. Existing saved selections for retired modes fall back to Battery Saver without auto-starting.

The hardware provides Off/Dim/Bright (some models have only one illuminated level). Effect envelopes use native steps with hysteresis, not rapid software PWM. This reduces repeated bridge writes and boundary flicker; it does not provide continuous dimming. Steady keeps a constant native level for focused work.

This is a standalone app using a private Lenovo compatibility bridge, **not a Vantage plugin**. See [integration findings](docs/vantage-integration.md).

CI artifacts for this branch are unsigned development builds. Validate the hardware and installer before release. No new signed release is claimed.

## Requirements

- 64-bit Windows 10 or Windows 11
- A Lenovo laptop with a compatible single-zone white-backlit keyboard
- Lenovo Vantage with the `IdeaNotebookAddin` components installed
- Administrator access for the Lenovo hardware bridge

Compatibility is detected from Lenovo Vantage's backlight capability rather than a hard-coded model number. RGB keyboards and unsupported contracts are rejected safely.

## Download and install

Stable releases remain on the repository [Releases](../../releases) page. For v3.2.0 validation, download the unsigned Windows build artifact from the branch PR checks and compare its installer SHA-256 with the accompanying checksum file. The installer does not install certificates or Lenovo assemblies.

## How to use

1. Open the app and confirm the header says **Lenovo bridge online**.
2. Click a mode under **Lighting** or **Audio Reactive**. It starts immediately, and clicking another mode switches without an off/on cycle.
3. Choose the desired **Intensity** from 1–100. Use the top-right power button to turn the selected mode off or back on.
4. Leave God Mode off for curated automatic timing. Enable it in **Settings** only when you want advanced speed, reactive, or idle-timeout controls.
5. Closing the window keeps the app in the notification area by default. Use the tray menu's **Quit** command to exit fully.

`Fn+Space` is Lenovo's keyboard-backlight shortcut on supported LOQ models. Battery Saver watches the resulting native backlight state and synchronizes its remembered level when possible. `Fn+Q` controls Lenovo operating/thermal modes and is not intercepted by this app.

## Modes

| Mode | Purpose |
| --- | --- |
| Steady | Constant Dim or Bright for work |
| Battery Saver | Wake on input, sleep after inactivity |
| Breathe | Slow symmetric native-step rhythm |
| Surge Wave | Asymmetric crest and trailing ripple |
| Reactive | Brighten on typing, fade on release |
| Music / Mic | Follow microphone energy locally |
| Music / Speaker | Follow Windows output peaks locally |

## Battery Saver, startup, and tray

When launched by Windows startup, the keyboard begins off. Battery Saver runs quietly in the tray and the first keyboard or mouse input breathes the light up to the user's remembered 1–100 intensity. Mouse movement, clicks, scrolling, and keypresses all reset the timer. After 30 seconds without any of those inputs, it fades out again. The timeout can be changed only in God Mode.

**Run at Windows Startup** creates a current-user Startup apps entry and an elevated on-demand scheduled task with the stable identifier `Thrash Lightening Control`. This avoids leaving a visible console window and lets the entry appear in Task Manager. Turning the option off removes both entries. No Windows service is installed.

## Audio privacy

- Music / Mic analyzes short microphone blocks in memory. Nothing is saved or transmitted.
- Music / Speaker reads the Windows Core Audio output peak meter. It does not open the microphone, record speaker samples, or upload audio.

## Why PowerShell appears in Task Manager

Lenovo exposes this backlight interface through private .NET assemblies installed with Lenovo Vantage. The app keeps one hidden, non-interactive Windows PowerShell helper alive to load those assemblies and send low-latency commands. Closing or killing that helper interrupts hardware control; the app attempts to reconnect automatically. See [Architecture](docs/architecture.md).

## Build from source

```powershell
git clone https://github.com/Thrash-PRX/Thrash-Lightening-Control.git
cd Thrash-Lightening-Control
py -m pip install -r requirements-build.txt
py -m PyInstaller --clean --noconfirm keyboard-effects.spec
```

For the compressed installer, install Inno Setup 6 and run `build_installer.bat`. Public certificates may be distributed; never commit a `.pfx`, `.p12`, private key, or password.

## Help and contributing

See [Troubleshooting](docs/troubleshooting.md), [Contributing](CONTRIBUTING.md), and [Security](SECURITY.md). Compatibility reports should include the laptop model, Windows version, Lenovo Vantage version, and copied diagnostics with personal information removed.

Lenovo, LOQ, Legion, IdeaPad, and Lenovo Vantage are trademarks of Lenovo. ASUS, TUF, and Armoury Crate are trademarks of their respective owners. This independent project is not affiliated with or endorsed by those companies, and it does not redistribute Lenovo proprietary DLLs.

Original project code is available under the [MIT License](LICENSE).

Internal executable, preference store, scheduled task and installation directory identifiers remain compatible with previous Thrash installations. Windows product metadata and display names use LOQ LIGHTENING CENTRE.
