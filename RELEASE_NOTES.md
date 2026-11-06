# LOQ LIGHTENING CENTRE v3.1.2

This patch adds full keyboard-and-mouse activity tracking to the rebuilt lighting engine and liquid-glass Windows interface.

## Highlights

- Stable 96 Hz Breathe renderer with a slower symmetric curve and hardware-safe speed ceiling
- Visibly distinct Wave with a sharp crest, long tail, secondary ripple, and dark reset
- Reactive now distinguishes a timed pulse from true hold-until-last-key-release behavior
- Physical multi-key tracking prevents auto-repeat and early-release glitches
- One-click effect switching and persistent top-right master power
- Animated Thrash wordmark, live background-blurred glass surfaces, Light/Dark modes, and four accent themes
- Battery Saver starts dark at boot, wakes on keyboard or mouse input, and sleeps after 30 seconds of total input inactivity
- Mouse movement, clicks, and scrolling all wake the light and reset the Battery Saver timer
- Clean normal mode with automatically tuned speeds and one recommended Reactive behavior
- God Mode reveals advanced timing, alternate Reactive behavior, and adjustable idle timeout
- Red scan-line God Mode unlock sequence
- Dedicated Lighting, Audio Reactive, Device, Settings, and About sections
- Speaker-output beat transients remain separate from microphone response
- Capability-first detection for compatible Lenovo LOQ white-backlit keyboards
- Tray persistence and Task Manager-visible Windows startup behavior
- Responsive title, cards, descriptions, and status layout down to the 1040 px minimum width

## Release assets

- `LOQLighteningCentre-Setup-v3.1.2.exe` — signed compressed Windows installer
- `SHA256SUMS.txt` — installer integrity checksum

## Hardware reality

Compatible keyboards expose only Off, Dim, and Bright. The app approximates intermediate-looking intensity and smoother transitions by rapidly blending those native states. This is still constrained by Lenovo's three-level interface and cannot equal a hardware-native PWM animation. A single-zone keyboard also cannot produce a spatial left-to-right wave, so this release's Wave is intentionally a temporal surge-and-ripple pattern.

Fn+Space is the Lenovo keyboard-light shortcut. Fn+Q controls performance/thermal mode and is left untouched.

## Security and privacy

Administrator access and Lenovo Vantage are required. Audio analysis stays local. Speaker mode uses the Windows output peak meter and does not record microphone or speaker samples.

The installer is signed using a self-signed `CN=Thrash` certificate. Browsers or Windows may warn because the certificate has no public reputation. Verify `SHA256SUMS.txt` before running the installer.
