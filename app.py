"""
Keyboard Backlight Effects Controller for Lenovo laptops (IdeaPad / LOQ / Legion)
================================================================================
Interfaces with Lenovo Vantage's IdeaNotebookAddin DLLs to control keyboard backlight.
Uses a persistent PowerShell subprocess for low-latency command execution.
Includes a global keyboard hook to react to keystrokes in real-time.
"""

import os
import sys
import time
import threading
import ctypes
from ctypes import wintypes
import subprocess
import glob
import re
import queue
import math
import tempfile
from xml.sax.saxutils import escape as xml_escape
from PySide6.QtCore import (
    Qt, QEvent, QTimer, QRectF, QPointF, QEasingCurve, QPropertyAnimation,
    QSettings, QVariantAnimation,
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPixmap,
    QPainterPath, QPen, QRadialGradient, QImage,
)
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QRadioButton,
    QProgressBar, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget, QGraphicsOpacityEffect,
)

from keyboard_preview_3d import LOQKeyboardPreview

# Define hook-related types and signatures for ctypes
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]


class LASTINPUTINFO(ctypes.Structure):
    """Windows timestamp for the most recent keyboard or mouse input."""
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]

# Declare HHOOK type
if not hasattr(wintypes, 'HHOOK'):
    wintypes.HHOOK = wintypes.HANDLE

# Declare HOOKPROC to return c_void_p (64-bit on x64 systems) to prevent overflow crash!
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

# Set up user32 and kernel32 signatures for pointer safety
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HMODULE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_void_p

user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL

kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []

# ---------------------------------------------------------------------------
#  Admin check & self-elevation
# ---------------------------------------------------------------------------

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


APP_VERSION = "3.2.0"
APP_NAME = "LOQ LIGHTENING CENTRE"
STARTUP_TASK_NAME = "Thrash Lightening Control"
STARTUP_RUN_VALUE = "Thrash Lightening Control"
STARTUP_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _hidden_process_kwargs():
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _startup_task_exists():
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", STARTUP_TASK_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            **_hidden_process_kwargs(),
        )
        return result.returncode == 0
    except OSError:
        return False


def _startup_run_command():
    schtasks = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe"
    )
    return f'"{schtasks}" /Run /TN "{STARTUP_TASK_NAME}"'


def _startup_registry_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_RUN_VALUE)
        return STARTUP_TASK_NAME in str(value)
    except OSError:
        return False


def startup_task_enabled():
    """Return whether the Task Manager-visible startup launcher is complete."""
    return _startup_task_exists() and _startup_registry_enabled()


def _startup_action():
    if getattr(sys, "frozen", False):
        return sys.executable, "--startup", os.path.dirname(sys.executable)
    script = os.path.abspath(__file__)
    return sys.executable, f'"{script}" --startup', os.path.dirname(script)


def _create_startup_task():
    executable, arguments, working_dir = _startup_action()
    domain = os.environ.get("USERDOMAIN", "")
    username = os.environ.get("USERNAME", "")
    user_id = f"{domain}\\{username}" if domain else username
    task_xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts LOQ LIGHTENING CENTRE by THRASH in the notification area.</Description></RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>{xml_escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{xml_escape(executable)}</Command>
      <Arguments>{xml_escape(arguments)}</Arguments>
      <WorkingDirectory>{xml_escape(working_dir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''
    xml_path = None
    try:
        handle, xml_path = tempfile.mkstemp(prefix="loq-startup-", suffix=".xml")
        os.close(handle)
        with open(xml_path, "w", encoding="utf-16") as xml_file:
            xml_file.write(task_xml)
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", STARTUP_TASK_NAME, "/XML", xml_path, "/F"],
            capture_output=True,
            text=True,
            check=False,
            **_hidden_process_kwargs(),
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Task Scheduler rejected the request").strip()
            raise RuntimeError(detail)
    finally:
        if xml_path:
            try:
                os.unlink(xml_path)
            except OSError:
                pass


def _set_startup_registry(enabled):
    import winreg
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_RUN_KEY) as key:
            winreg.SetValueEx(key, STARTUP_RUN_VALUE, 0, winreg.REG_SZ, _startup_run_command())
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, STARTUP_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, STARTUP_RUN_VALUE)
    except FileNotFoundError:
        pass


def set_startup_task(enabled):
    """Register an elevated on-demand task and a Task Manager startup entry."""
    if enabled:
        _create_startup_task()
        try:
            _set_startup_registry(True)
        except Exception:
            subprocess.run(
                ["schtasks", "/Delete", "/TN", STARTUP_TASK_NAME, "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **_hidden_process_kwargs(),
            )
            raise
    else:
        _set_startup_registry(False)
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", STARTUP_TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            check=False,
            **_hidden_process_kwargs(),
        )
        if result.returncode != 0 and result.returncode != 1:
            detail = (result.stderr or result.stdout or "Task Scheduler rejected the request").strip()
            raise RuntimeError(detail)
    return enabled

# ---------------------------------------------------------------------------
#  Dynamic DLL path finder
# ---------------------------------------------------------------------------

def find_lenovo_dlls():
    """Locate the latest version of Lenovo Vantage's IdeaNotebookAddin DLLs."""
    paths = glob.glob(r"C:\ProgramData\Lenovo\Vantage\Addins\IdeaNotebookAddin\*\KeyboardContract.dll")
    def version_key(path):
        folder_name = os.path.basename(os.path.dirname(path))
        return tuple(int(part) for part in re.findall(r"\d+", folder_name))

    # Vantage updates can leave a partially installed newer add-in behind.
    # Prefer the newest COMPLETE folder instead of rejecting every version.
    for contract in sorted(paths, key=version_key, reverse=True):
        folder = os.path.dirname(contract)
        dlls = {
            "contract": contract,
            "addin": os.path.join(folder, "IdeaNotebookAddin.dll"),
            "json": os.path.join(folder, "Newtonsoft.Json.dll"),
        }
        if all(os.path.isfile(path) for path in dlls.values()):
            return dlls
    return None

# ---------------------------------------------------------------------------
#  Keyboard Backlight Controller via Persistent PowerShell
# ---------------------------------------------------------------------------

class KeyboardBacklightController:
    """Controls Lenovo keyboard backlight via IdeaNotebookAddin.dll using persistent PowerShell."""

    def __init__(self):
        self.method = None
        self.current_level = 2  # 0=off, 1=dim, 2=bright
        self.max_level = 2
        self.backlight_level_type = "Unknown"
        self.compatible_white_backlight = False
        self.contract_version = "Unknown"
        self._lock = threading.Lock()
        self.ps_proc = None
        self._ps_output = queue.Queue()
        self._admin = is_admin()
        self.system_model = self._get_system_model()
        self.last_error = None
        self.reconnect_count = 0
        self._shutdown = threading.Event()
        self._monitor_thread = None

        self.detect_method()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _get_system_model(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
                product = str(winreg.QueryValueEx(key, "SystemProductName")[0]).strip()
                try:
                    family = str(winreg.QueryValueEx(key, "SystemFamily")[0]).strip()
                except OSError:
                    family = ""
            if family and family.lower() not in ("to be filled by o.e.m.", "system product name"):
                return f"{family} ({product})" if product and product not in family else family
            return product
        except Exception:
            return "Lenovo Laptop"

    def detect_method(self):
        """Safely initialize or reinitialize the hidden Lenovo bridge."""
        with self._lock:
            return self._detect_method_unlocked()

    def _detect_method_unlocked(self):
        """Initialize the persistent controller. Caller holds _lock."""
        self.close_ps()
        self.method = "connecting"
        self.last_error = None
        dlls = find_lenovo_dlls()
        if dlls:
            try:
                self.contract_version = os.path.basename(os.path.dirname(dlls["contract"]))
                powershell = os.path.join(
                    os.environ.get("SystemRoot", r"C:\Windows"),
                    "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
                )
                self.ps_proc = subprocess.Popen(
                    [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._ps_output = queue.Queue()
                threading.Thread(target=self._read_ps_output, daemon=True).start()

                init_script = f"""
                [System.Reflection.Assembly]::LoadFrom('{dlls["contract"]}') | Out-Null
                [System.Reflection.Assembly]::LoadFrom('{dlls["json"]}') | Out-Null
                $asm = [System.Reflection.Assembly]::LoadFrom('{dlls["addin"]}')
                $agentType = $asm.GetType('IdeaNotebookAddin.IdeaNotebookAgent')
                $agent = $agentType.GetMethod('GetInstance', [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static).Invoke($null, $null)
                $setBacklightMethod = $agentType.GetMethods() | Where-Object {{ $_.Name -eq 'SetBacklight' -and $_.GetParameters().Count -eq 2 }}

                function Set-KbdBacklight([string]$level) {{
                    $status = $agentType.GetMethod('GetBacklightStatus', [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Instance).Invoke($agent, $null)
                    $list = $status.GetType().GetProperty('List').GetValue($status)
                    $items = $list.GetType().GetProperty('Items').GetValue($list)
                    foreach ($item in $items) {{
                        $keyVal = $item.GetType().GetProperty('key').GetValue($item)
                        if ($keyVal -eq 'KeyboardBacklightStatus') {{
                            $item.GetType().GetProperty('value').SetValue($item, $level)
                        }}
                    }}
                    $req = New-Object Lenovo.Modern.Contracts.Keyboard.KeyboardSettingsRequest
                    $req.List = $list
                    $jsonPayload = [Newtonsoft.Json.JsonConvert]::SerializeObject($req)
                    $resp = $setBacklightMethod.Invoke($agent, @($jsonPayload, $null))
                    Write-Output "OK:$level"
                }}

                function Get-KbdBacklight {{
                    $status = $agentType.GetMethod('GetBacklightStatus', [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Instance).Invoke($agent, $null)
                    $list = $status.GetType().GetProperty('List').GetValue($status)
                    $items = $list.GetType().GetProperty('Items').GetValue($list)
                    $level = 'Unknown'
                    $capability = 'Unknown'
                    foreach ($item in $items) {{
                        $keyVal = $item.GetType().GetProperty('key').GetValue($item)
                        $valueVal = $item.GetType().GetProperty('value').GetValue($item)
                        if ($keyVal -eq 'KeyboardBacklightStatus') {{ $level = [string]$valueVal }}
                        if ($keyVal -eq 'KeyboardBacklightLevel') {{ $capability = [string]$valueVal }}
                    }}
                    Write-Output "STATE:$level|$capability"
                }}
                """
                self.ps_proc.stdin.write(init_script + "\n")
                self.ps_proc.stdin.flush()

                state = self._query_backlight_unlocked()
                if state is None:
                    raise RuntimeError("Lenovo Vantage did not report a keyboard backlight state")
                level, capability = state
                if capability not in ("OneLevel", "TwoLevels"):
                    raise RuntimeError(
                        f"This build currently supports white Lenovo backlights only (reported: {capability})"
                    )
                self.current_level = level
                self.backlight_level_type = capability
                self.max_level = 1 if capability == "OneLevel" else 2
                self.compatible_white_backlight = True
                self.method = "lenovo_vantage_dll"
                return True
            except Exception as e:
                self.last_error = str(e)
                print(f"Error initializing Vantage DLL control: {e}")
                self.close_ps()
        else:
            self.last_error = "Lenovo Vantage keyboard DLLs were not found"

        self.method = "unavailable"
        self.compatible_white_backlight = False
        return False

    def _query_backlight_unlocked(self):
        """Return (native level, capability) without changing the keyboard."""
        if not self.ps_proc or self.ps_proc.poll() is not None:
            return None
        while True:
            try:
                self._ps_output.get_nowait()
            except queue.Empty:
                break
        try:
            self.ps_proc.stdin.write("Get-KbdBacklight\n")
            self.ps_proc.stdin.flush()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    response = self._ps_output.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if response.startswith("STATE:"):
                    payload = response[6:]
                    state_text, _, capability = payload.partition("|")
                    level_map = {"Off": 0, "DisabledOff": 0, "Level_1": 1, "Level_2": 2, "Auto": 1}
                    if state_text in level_map:
                        return level_map[state_text], capability or "Unknown"
            return None
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def refresh_native_brightness(self):
        """Poll Fn+Space/Vantage state without mutating it."""
        with self._lock:
            state = self._query_backlight_unlocked()
            if state is None:
                return None
            level, capability = state
            self.current_level = level
            self.backlight_level_type = capability
            return level

    def _send_command(self, level_str):
        """Send command to persistent PowerShell stdin."""
        if not self.ps_proc:
            return False
        try:
            if self.ps_proc.poll() is not None:
                return False
            while True:
                try:
                    self._ps_output.get_nowait()
                except queue.Empty:
                    break
            self.ps_proc.stdin.write(f"Set-KbdBacklight '{level_str}'\n")
            self.ps_proc.stdin.flush()
            deadline = time.monotonic() + 5.0
            expected = f"OK:{level_str}"
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    response = self._ps_output.get(timeout=max(0.01, remaining))
                except queue.Empty:
                    break
                if response == expected:
                    return True
            return False
        except Exception as e:
            self.last_error = str(e)
            print(f"PowerShell communication error: {e}")
            return False

    def _monitor_loop(self):
        """Restore the hidden bridge if it is closed or crashes."""
        while not self._shutdown.wait(2.0):
            proc_dead = self.ps_proc is None or self.ps_proc.poll() is not None
            if self.method != "lenovo_vantage_dll" or proc_dead:
                if self._shutdown.is_set():
                    break
                if self.detect_method():
                    self.reconnect_count += 1
                else:
                    self._shutdown.wait(4.0)

    def _read_ps_output(self):
        """Continuously drain PowerShell output so a DLL error cannot deadlock the UI."""
        proc = self.ps_proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._ps_output.put(line.strip())

    def close_ps(self):
        """Properly close the PowerShell process."""
        if self.ps_proc:
            try:
                self.ps_proc.stdin.write("exit\n")
                self.ps_proc.stdin.flush()
                self.ps_proc.wait(timeout=2)
            except:
                try:
                    self.ps_proc.kill()
                except:
                    pass
            self.ps_proc = None

    def shutdown(self):
        """Permanently stop recovery and close the bridge."""
        self._shutdown.set()
        with self._lock:
            self.close_ps()

    def set_backlight(self, on):
        """Turn backlight fully on or off."""
        if on:
            self.set_brightness(self.max_level)
        else:
            self.set_brightness(0)

    def set_brightness(self, level):
        """Set brightness: 0=off, 1=dim, 2=bright."""
        level = max(0, min(level, self.max_level))
        with self._lock:
            success = False
            try:
                if self.method == "lenovo_vantage_dll":
                    level_map = {0: "Off", 1: "Level_1", 2: "Level_2"}
                    success = self._send_command(level_map[level])
                    if not success:
                        self.method = "unavailable"
            except Exception as e:
                self.last_error = str(e)
                self.method = "unavailable"
                print(f"Set brightness error: {e}")
            if success:
                self.current_level = level
            return success

    def get_status(self):
        names = {
            "lenovo_vantage_dll": "Lenovo bridge online",
            "connecting": "Connecting to Lenovo Vantage…",
            "unavailable": "Compatible Lenovo Vantage interface not found",
        }
        return {
            "method": self.method,
            "method_display": names.get(self.method, self.method),
            "current_level": self.current_level,
            "max_level": self.max_level,
            "backlight_level_type": self.backlight_level_type,
            "compatible_white_backlight": self.compatible_white_backlight,
            "contract_version": self.contract_version,
            "is_admin": self._admin,
            "system_model": self.system_model,
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count,
        }

# ---------------------------------------------------------------------------
#  Effects Engine
# ---------------------------------------------------------------------------

class EffectEngine:
    EFFECTS_META = [
        {"id": "steady", "name": "Steady", "icon": "☀", "desc": "Constant native brightness for focused work"},
        {"id": "battery_saver", "name": "Battery Saver", "icon": "◉",  "desc": "Wakes on input, sleeps after 30 seconds"},
        {"id": "breathe",   "name": "Calm Breathe",        "icon": "◌",     "desc": "Slow, symmetrical soft breathing"},
        {"id": "focus_timer", "name": "Focus Timer", "icon": "◷", "desc": "25-minute focus, gentle reminder, 5-minute dark break"},
        {"id": "night_shift", "name": "Night Shift", "icon": "☾", "desc": "Dim from 10 PM to 7 AM; normal brightness by day"},
        {"id": "reactive",  "name": "Reactive",       "icon": "⌨",     "desc": "Brightens on every keypress"},
        {"id": "music_speaker", "name": "Speaker Beats", "icon": "♫", "desc": "Beat detection from speaker output"},
    ]

    RECOMMENDED_SPEEDS = {
        "battery_saver": 1.0,
        "breathe": 1.0,
        "reactive": 1.0,
        "music_speaker": 1.35,
    }
    SPEED_LIMITS = {
        "breathe": (0.45, 1.65),
        "reactive": (0.55, 2.00),
    }

    @classmethod
    def clamp_speed(cls, effect, speed):
        low, high = cls.SPEED_LIMITS.get(effect, (0.20, 4.00))
        return max(low, min(float(speed), high))

    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.running = False
        self.current_effect = None
        self._focus_started = time.monotonic()
        self.effect_status = ""
        self.speed = 1.0
        self.intensity = 50
        self.mode = 2
        self.hold_behavior = 2
        self.idle_timeout = 30.0
        self.start_asleep = False
        self._rendered_intensity = 0.0
        self._stop = threading.Event()
        self._thread = None

        # Keyboard Hook fields
        self._hook_handle = None
        self._hook_thread = None
        self._hook_thread_id = None
        self._hook_ready_event = threading.Event()
        self._keypress_event = threading.Event()
        self._keyrelease_event = threading.Event()
        self._hook_proc = None
        self._pressed_keys = set()
        self._keypress_counter = 0
        self._keys_lock = threading.Lock()
        self._speaker_meter = None
        self._speaker_device = None
        self._speaker_com_initialized = False
        self._speaker_fast = 0.0
        self._speaker_slow = 0.0
        self._speaker_deviation = 0.01
        self._speaker_last_beat = 0.0
        self._speaker_flash_until = 0.0
        self._speaker_glow_until = 0.0
        self._idle_started = time.monotonic()
        self._last_input_tick = self._get_last_input_tick()
        self._default_level = None
        self._last_key_vk = None
        self.idle_sleeping = False
        self.idle_seconds = 0.0
        self.music_level = 0.0
        self.last_error = None

    def start(self, effect, intensity=50, speed=None, mode=2, hold_behavior=2, start_asleep=False):
        valid_effects = {item["id"] for item in self.EFFECTS_META}
        if effect not in valid_effects:
            raise ValueError(f"Unknown effect: {effect}")
        self.stop(restore=False)
        self.current_effect = effect
        self._focus_started = time.monotonic()
        self.effect_status = ""
        recommended = self.RECOMMENDED_SPEEDS.get(effect, 1.0)
        self.speed = self.clamp_speed(effect, recommended if speed is None else speed)
        self.intensity = max(1, min(int(intensity), 100))
        self.mode = mode
        self.hold_behavior = hold_behavior
        self.start_asleep = bool(start_asleep)
        self.last_error = None
        self._speaker_fast = 0.0
        self._speaker_slow = 0.0
        self._speaker_deviation = 0.01
        self._speaker_last_beat = 0.0
        self._speaker_flash_until = 0.0
        self._speaker_glow_until = 0.0
        self._idle_started = time.monotonic()
        self._last_input_tick = self._get_last_input_tick()
        self._default_level = None
        self.idle_sleeping = self.start_asleep
        self.idle_seconds = 0.0
        self._rendered_intensity = 0.0
        self.music_level = 0.0
        with self._keys_lock:
            self._pressed_keys.clear()
            self._keypress_counter = 0
        self.running = True
        self._stop.clear()

        # Reactive and battery-saving default modes both need global input.
        if self.current_effect in ("reactive", "battery_saver"):
            if not self._start_keyboard_hook():
                self.running = False
                raise RuntimeError(self.last_error or "Could not start the Windows keyboard hook")

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, restore=True):
        self.running = False
        self._stop.set()

        # Terminate keyboard hook if active
        self._stop_keyboard_hook()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._close_audio()
        if restore:
            target = max(1, int(round((self.intensity / 100.0) * self.ctrl.max_level)))
            self.ctrl.set_brightness(min(self.ctrl.max_level, target))
        self.current_effect = None

    def _wait(self, secs):
        self._stop.wait(secs)
        return not self.running

    def _loop(self):
        fns = {
            "steady": self._steady,
            "battery_saver": self._battery_saver,
            "breathe": self._breathe,
            "focus_timer": self._focus_timer,
            "night_shift": self._night_shift,
            "reactive": self._reactive,
            "music_speaker": self._music_speaker,
        }
        fn = fns.get(self.current_effect)
        if not fn:
            return
        try:
            while self.running:
                if fn():
                    break
        except Exception as exc:
            self.last_error = str(exc)
            print(f"Effect error: {exc}")
        finally:
            self._close_audio()
            self.running = False
            if not self._stop.is_set():
                target = max(1, int(round((self.intensity / 100.0) * self.ctrl.max_level)))
                self.ctrl.set_brightness(min(self.ctrl.max_level, target))

    # -- Keyboard Hook Management -------------------------------------------

    def _start_keyboard_hook(self):
        """Starts the low-level global Windows keyboard hook thread."""
        if self._hook_thread and self._hook_thread.is_alive():
            self._stop_keyboard_hook()
            if self._hook_thread and self._hook_thread.is_alive():
                self.last_error = "The previous keyboard hook did not stop cleanly"
                return False
        self._keypress_event.clear()
        self._keyrelease_event.clear()
        self._hook_ready_event.clear()
        self._hook_thread = threading.Thread(target=self._hook_message_loop, daemon=True)
        self._hook_thread.start()
        if not self._hook_ready_event.wait(timeout=0.50):
            self.last_error = "Windows did not initialize the keyboard hook in time"
            self._stop_keyboard_hook()
            return False
        return bool(self._hook_handle)

    def _stop_keyboard_hook(self):
        """Terminates the hook loop and removes the global hook."""
        if self._hook_thread_id:
            for _attempt in range(5):
                if user32.PostThreadMessageW(self._hook_thread_id, 0x0012, 0, 0):
                    break
                time.sleep(0.01)
        if (self._hook_thread and self._hook_thread.is_alive()
                and self._hook_thread is not threading.current_thread()):
            self._hook_thread.join(timeout=1)
        self._keypress_event.clear()
        self._keyrelease_event.clear()
        self._hook_ready_event.clear()
        with self._keys_lock:
            self._pressed_keys.clear()
        if self._hook_thread and not self._hook_thread.is_alive():
            self._hook_thread = None

    def _record_key_down(self, identity, vk_code=None):
        """Record one physical key without treating auto-repeat as another press."""
        self._last_key_vk = identity[0] if vk_code is None and isinstance(identity, tuple) else (
            identity if vk_code is None else vk_code
        )
        with self._keys_lock:
            if identity in self._pressed_keys:
                return False
            self._pressed_keys.add(identity)
            self._keypress_counter += 1
        self._keypress_event.set()
        return True

    def _record_key_up(self, identity):
        """Release one physical key and signal only when every key is released."""
        with self._keys_lock:
            self._pressed_keys.discard(identity)
            all_released = not self._pressed_keys
        if all_released:
            self._keyrelease_event.set()
        return all_released

    def _hook_message_loop(self):
        """Standard Windows message loop that handles keyboard events."""
        self._hook_thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # Force Windows to create this thread's message queue before signalling
        # readiness, so WM_QUIT cannot be lost during a quick effect switch.
        user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0)

        def hook_cb(nCode, wParam, lParam):
            try:
                if nCode >= 0 and self.running:
                    kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    vk = kbd.vkCode
                    identity = (vk, kbd.scanCode, kbd.flags & 0x01)

                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._record_key_down(identity, vk)
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._record_key_up(identity)
            except Exception as e:
                print(f"Keyboard hook exception: {e}")
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        # Keep a reference to prevent GC crash
        self._hook_proc = HOOKPROC(hook_cb)
        hmod = kernel32.GetModuleHandleW(None)

        self._hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            hmod,
            0
        )

        try:
            if not self._hook_handle:
                error = kernel32.GetLastError()
                self.last_error = f"Global keyboard hook failed (Windows error {error})"
                print(self.last_error)
                self._hook_ready_event.set()
                return

            self._hook_ready_event.set()
            while self.running:
                message_result = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if message_result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook_handle:
                user32.UnhookWindowsHookEx(self._hook_handle)
            self._hook_handle = None
            self._hook_thread_id = None
            self._hook_ready_event.set()

    # -- Effects ------------------------------------------------------------

    @staticmethod
    def _get_last_input_tick():
        """Return Windows' latest combined keyboard/mouse activity tick."""
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if user32.GetLastInputInfo(ctypes.byref(info)):
            return int(info.dwTime)
        return None

    def _render_intensity(self, percent):
        """Quantize to native states with hysteresis; never simulate PWM over IPC."""
        percent = max(0.0, min(100.0, float(percent)))
        self._rendered_intensity = percent
        maximum = max(1, int(getattr(self.ctrl, "max_level", 2)))
        target = percent / 100.0 * maximum
        current = max(0, min(maximum, self.ctrl.current_level))
        # A small dead band prevents repeated writes around a level boundary.
        if percent == 0:
            level = 0
        elif percent == 100:
            level = maximum
        elif target > current + 0.58 or target < current - 0.58:
            level = min(maximum, max(0, int(math.floor(target + 0.5))))
        else:
            level = current
        if level != self.ctrl.current_level:
            self.ctrl.set_brightness(level)
        return level

    def _steady(self):
        maximum = max(1, int(getattr(self.ctrl, "max_level", 2)))
        level = max(1, min(maximum, int(math.floor(self.intensity / 100 * maximum + 0.5))))
        if level != self.ctrl.current_level:
            self.ctrl.set_brightness(level)
        self._rendered_intensity = self.intensity
        return self._wait(0.10)

    def _night_shift(self):
        hour = time.localtime().tm_hour
        maximum = max(1,int(self.ctrl.max_level))
        level = 1 if hour >= 22 or hour < 7 else max(1,min(maximum,int(self.intensity/100*maximum+0.5)))
        self.effect_status = "Evening dim · until 7 AM" if hour >= 22 or hour < 7 else "Day brightness · dims at 10 PM"
        if self.ctrl.current_level != level:
            self.ctrl.set_brightness(level)
        return self._wait(1.0)

    def _focus_timer(self):
        elapsed = max(0,time.monotonic()-self._focus_started) % 1800
        if elapsed < 1500:
            remaining = int(math.ceil(1500-elapsed))
            self.effect_status = f"Focus · {remaining//60:02d}:{remaining%60:02d} remaining"
            return self._steady()
        if elapsed < 1506:
            self.effect_status = "Break reminder · gentle double breathe"
            phase = ((elapsed-1500) % 3)/3
            maximum=max(1,int(self.ctrl.max_level))
            peak=max(1,min(maximum,int(self.intensity/100*maximum+0.5)))*100/maximum
            self._render_intensity(peak*self._breathe_envelope(phase))
            return self._wait(1/30)
        remaining = int(math.ceil(1800-elapsed))
        self.effect_status = f"Break · {remaining//60:02d}:{remaining%60:02d} remaining"
        if self.ctrl.current_level != 0:
            self.ctrl.set_brightness(0)
        return self._wait(0.5)

    def _fade_to(self, target, duration=0.55, start=None):
        """Sine-eased envelope rendered as discrete native brightness steps."""
        start = self._rendered_intensity if start is None else float(start)
        target = max(0.0, min(100.0, float(target)))
        started = time.monotonic()
        duration = max(0.05, float(duration))
        while self.running:
            progress = min(1.0, (time.monotonic() - started) / duration)
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            self._render_intensity(start + (target - start) * eased)
            if progress >= 1.0:
                return False
            if self._wait(1.0 / 60.0):
                return True
        return True

    def _battery_saver(self):
        """Wake on keyboard/mouse activity and sleep after the idle timeout."""
        keyboard_activity = self._keypress_event.is_set()
        if keyboard_activity:
            self._keypress_event.clear()

        latest_input_tick = self._get_last_input_tick()
        system_activity = (
            latest_input_tick is not None
            and self._last_input_tick is not None
            and latest_input_tick != self._last_input_tick
        )
        if latest_input_tick is not None:
            self._last_input_tick = latest_input_tick

        if keyboard_activity or system_activity:
            if keyboard_activity and self._last_key_vk == 0x20 and not self.idle_sleeping:
                # Fn itself is firmware-owned, but Space is visible. Give the
                # native Fn+Space cycle time to settle, then synchronize.
                previous_native = self.ctrl.current_level
                if self._wait(0.07):
                    return True
                native = self.ctrl.refresh_native_brightness()
                if native is not None and native != previous_native:
                    self.intensity = max(1, int(round((native / self.ctrl.max_level) * 100)))
            self._idle_started = time.monotonic()
            self.idle_seconds = 0.0
            if self.idle_sleeping:
                self.idle_sleeping = False
                if self._fade_to(self.intensity, 0.68, start=0):
                    return True

        self.idle_seconds = max(0.0, time.monotonic() - self._idle_started)
        if self.idle_seconds >= self.idle_timeout and not self.idle_sleeping:
            self.idle_sleeping = True
            if self._fade_to(0, 0.48):
                return True

        if self.idle_sleeping:
            if self.ctrl.current_level != 0:
                self.ctrl.set_brightness(0)
            return self._wait(0.05)

        self._render_intensity(self.intensity)
        return self._wait(1.0 / 60.0)

    @staticmethod
    def _breathe_envelope(phase):
        """Gentle 0→1→0 curve with soft shoulders and no abrupt level jumps."""
        phase = max(0.0, min(1.0, float(phase)))
        return math.sin(math.pi * phase) ** 1.28

    def _breathe(self):
        """Slow symmetric envelope across native brightness steps."""
        frame = 1.0 / 30.0
        deadline = time.monotonic()
        previous = deadline
        phase = 0.0
        while self.running:
            now = time.monotonic()
            phase = (phase + (now - previous) * self.speed / 5.6) % 1.0
            previous = now
            self._render_intensity(self.intensity * self._breathe_envelope(phase))
            deadline += frame
            delay = deadline - time.monotonic()
            if delay <= 0:
                deadline = time.monotonic() + frame
                delay = frame
            if self._wait(delay):
                return True
        return True

    def _music_speaker(self):
        """Detect beat-like output transients without opening the microphone."""
        if self._speaker_meter is None:
            try:
                from ctypes import POINTER, cast
                import comtypes
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

                comtypes.CoInitialize()
                self._speaker_com_initialized = True
                self._speaker_device = AudioUtilities.GetSpeakers()
                interface = self._speaker_device._dev.Activate(
                    IAudioMeterInformation._iid_, CLSCTX_ALL, None
                )
                self._speaker_meter = cast(interface, POINTER(IAudioMeterInformation))
            except Exception as exc:
                self._close_audio()
                raise RuntimeError(f"Could not monitor Windows speaker output: {exc}") from exc

        peak = float(self._speaker_meter.GetPeakValue())
        self._apply_speaker_beat(peak)
        return self._wait(0.020)

    def _apply_speaker_beat(self, raw_level, now=None):
        """Turn endpoint peaks into adaptive, debounced beat pulses."""
        now = time.monotonic() if now is None else float(now)
        raw_level = max(0.0, min(1.0, float(raw_level)))

        # The fast envelope follows drum attacks; the slow envelope tracks the
        # song's current loudness. Their separation is an onset, not just volume.
        self._speaker_fast = self._speaker_fast * 0.48 + raw_level * 0.52
        self._speaker_slow = self._speaker_slow * 0.94 + raw_level * 0.06
        onset = max(0.0, self._speaker_fast - self._speaker_slow)
        self._speaker_deviation = self._speaker_deviation * 0.94 + onset * 0.06

        sensitivity = max(0.2, min(4.0, self.speed))
        threshold = (
            0.006 + self._speaker_slow * 0.15 + self._speaker_deviation * 1.10
        ) / (0.72 + sensitivity * 0.34)
        refractory = max(0.095, 0.24 - sensitivity * 0.028)
        is_beat = (
            raw_level >= 0.018
            and onset >= threshold
            and now - self._speaker_last_beat >= refractory
        )

        if is_beat:
            self._speaker_last_beat = now
            self._speaker_flash_until = now + 0.075
            self._speaker_glow_until = now + 0.19

        if now < self._speaker_flash_until:
            output_intensity = self.intensity
            target_meter = 1.0
        elif now < self._speaker_glow_until:
            output_intensity = self.intensity * 0.48
            target_meter = 0.48
        else:
            output_intensity = 0
            target_meter = min(0.28, raw_level * 1.8)

        self.music_level = self.music_level * 0.34 + target_meter * 0.66
        self._render_intensity(output_intensity)
        return is_beat

    def _close_audio(self):
        self._speaker_meter = None
        self._speaker_device = None
        if self._speaker_com_initialized:
            try:
                import comtypes
                comtypes.CoUninitialize()
            except Exception:
                pass
            self._speaker_com_initialized = False
        self.music_level = 0.0

    @staticmethod
    def _reactive_levels(mode, intensity):
        m = str(mode)
        if m == "2":
            return intensity * 0.36, intensity
        elif m == "3":
            return intensity, intensity * 0.40
        elif m == "4":
            return 0, intensity * 0.55
        elif m == "5":
            return 0, intensity
        return intensity, 0

    @staticmethod
    def _reactive_timings(speed):
        speed_scale = math.sqrt(max(0.55, float(speed)))
        return {
            "pulse": max(0.14, min(0.32, 0.22 / speed_scale)),
            "hold": max(0.12, min(0.26, 0.18 / speed_scale)),
            "release": max(0.15, min(0.40, 0.30 / speed_scale)),
        }

    def _reactive(self):
        """Continuously render idle/active levels so hold and pulse are distinct."""
        frame = 1.0 / 30.0
        seen_counter = 0

        while self.running:
            base, _active = self._reactive_levels(self.mode, self.intensity)
            with self._keys_lock:
                counter = self._keypress_counter

            if counter == seen_counter:
                self._render_intensity(base)
                if self._wait(frame):
                    return True
                continue

            seen_counter = counter
            timings = self._reactive_timings(self.speed)
            activated_at = time.monotonic()
            visible_until = activated_at + (
                timings["hold"] if str(self.hold_behavior) == "2" else timings["pulse"]
            )

            while self.running:
                _base, active = self._reactive_levels(self.mode, self.intensity)
                self._render_intensity(active)
                with self._keys_lock:
                    keys_held = bool(self._pressed_keys)
                    newest_counter = self._keypress_counter

                if newest_counter != seen_counter:
                    seen_counter = newest_counter
                    extension = timings["hold"] if str(self.hold_behavior) == "2" else timings["pulse"]
                    visible_until = time.monotonic() + extension

                if str(self.hold_behavior) == "2":
                    finished = not keys_held and time.monotonic() >= visible_until
                else:
                    finished = time.monotonic() >= visible_until
                if finished:
                    break
                if self._wait(frame):
                    return True

            self._keypress_event.clear()
            self._keyrelease_event.clear()
            release_started = time.monotonic()
            retrigger = False
            while self.running:
                base, active = self._reactive_levels(self.mode, self.intensity)
                with self._keys_lock:
                    newest_counter = self._keypress_counter
                if newest_counter != seen_counter:
                    seen_counter = newest_counter - 1
                    retrigger = True
                    break
                progress = min(1.0, (time.monotonic() - release_started) / timings["release"])
                eased = 0.5 - 0.5 * math.cos(math.pi * progress)
                self._render_intensity(active + (base - active) * eased)
                if progress >= 1.0:
                    break
                if self._wait(frame):
                    return True
            if retrigger:
                continue

        return True

    def get_status(self):
        return {
            "running": self.running,
            "current_effect": self.current_effect,
            "speed": self.speed,
            "intensity": self.intensity,
            "idle_timeout": self.idle_timeout,
            "music_level": self.music_level,
            "idle_sleeping": self.idle_sleeping,
            "idle_seconds": self.idle_seconds,
            "last_error": self.last_error,
        }

# ---------------------------------------------------------------------------
#  Native Windows desktop interface
# ---------------------------------------------------------------------------

controller = None
engine = None
window = None


def apply_windows_backdrop(widget, dark=True):
    """Request the native Windows 11 backdrop; custom glass remains the fallback."""
    if os.name != "nt":
        return False
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        enabled = ctypes.c_int(1 if dark else 0)
        # DWMWA_USE_IMMERSIVE_DARK_MODE and DWMWA_SYSTEMBACKDROP_TYPE.
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)
        )
        backdrop = ctypes.c_int(2)  # DWMSBT_MAINWINDOW / Mica where supported.
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
        )
        return result == 0
    except Exception:
        return False


class MinimalButton(QPushButton):
    """Short hover feedback, with no perpetual animation or layout movement."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hover_amount = 0.0
        self._hover_motion = QVariantAnimation(self)
        self._hover_motion.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_motion.valueChanged.connect(self._set_hover_amount)

    def _set_hover_amount(self, value):
        self._hover_amount = float(value)
        self.update()

    def _hover_to(self, amount):
        self._hover_motion.stop()
        if not getattr(self.window(), "animations_enabled", True):
            self._set_hover_amount(amount)
            return
        self._hover_motion.setDuration(140 if amount else 100)
        self._hover_motion.setStartValue(self._hover_amount)
        self._hover_motion.setEndValue(amount)
        self._hover_motion.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover_to(1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_to(0.0)

    def hideEvent(self, event):
        self._hover_motion.stop()
        self._hover_amount = 0.0
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hover_amount <= 0 or not self.isEnabled():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255,255,255,int(24*self._hover_amount)),1))
        painter.setBrush(QColor(255,255,255,int(12*self._hover_amount)))
        radius = min(20, self.height()/2-1)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),radius,radius)
        painter.end()


class GlassFrame(QFrame):
    """Layered translucent surface with depth, tint, and specular glass edges."""

    def __init__(self, surface="panel", parent=None):
        super().__init__(parent)
        self.surface = surface
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -2.5)
        light = getattr(self.window(), "appearance_mode", "dark") == "light"
        accent = QColor(getattr(self.window(), "active_accent", "#42c8ff"))
        radius = 19 if self.surface in ("sidebar", "panel") else 16
        if getattr(self.window(), "hub_style", False):
            if self.surface in ("stage", "topbar"):
                painter.end()
                return
            painter.setBrush(QColor("#ffffff" if light else "#101010"))
            painter.setPen(QPen(QColor("#dedede" if light else "#242424"), 1))
            painter.drawRoundedRect(rect, 24, 24)
            painter.end()
            return

        shadow_rect = QRectF(rect).translated(0, 2.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(2, 7, 14, 42 if light else 92))
        painter.drawRoundedRect(shadow_rect, radius, radius)

        background = getattr(self.window(), "background", None)
        blurred = getattr(background, "_blurred_scene", QPixmap())
        if background is not None and not blurred.isNull():
            origin = self.mapTo(background, self.rect().topLeft())
            source = QRectF(origin.x(), origin.y(), self.width(), self.height())
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.save()
            painter.setClipPath(clip)
            painter.setOpacity(0.76 if light else 0.62)
            painter.drawPixmap(rect, blurred, source)
            painter.restore()

        glass = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if light:
            glass.setColorAt(0.0, QColor(255, 255, 255, 155))
            glass.setColorAt(0.42, QColor(242, 250, 255, 100))
            tinted = QColor(accent)
            tinted.setAlpha(34)
            glass.setColorAt(1.0, tinted)
        else:
            glass.setColorAt(0.0, QColor(18, 31, 48, 130))
            glass.setColorAt(0.48, QColor(5, 13, 25, 85))
            tinted = QColor(accent)
            tinted.setAlpha(24)
            glass.setColorAt(1.0, tinted)
        painter.setBrush(glass)
        outer = QColor(accent)
        outer.setAlpha(82 if light else 72)
        painter.setPen(QPen(outer, 1.05))
        painter.drawRoundedRect(rect, radius, radius)

        inner = QRectF(rect).adjusted(1.4, 1.4, -1.4, -1.4)
        highlight = QLinearGradient(inner.topLeft(), inner.topRight())
        highlight.setColorAt(0.0, QColor(255, 255, 255, 178 if light else 92))
        highlight.setColorAt(0.34, QColor(255, 255, 255, 48 if light else 24))
        highlight.setColorAt(0.72, QColor(255, 255, 255, 8))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 94 if light else 36))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QBrush(highlight), 1.15))
        painter.drawRoundedRect(inner, radius - 1.5, radius - 1.5)

        sheen = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + max(18, rect.height() * 0.42))
        sheen.setColorAt(0.0, QColor(255, 255, 255, 40 if light else 20))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(sheen)
        painter.drawRoundedRect(QRectF(rect.left() + 2, rect.top() + 2, rect.width() - 4,
                                       min(rect.height() * 0.46, 62)), radius - 2, radius - 2)

        grain = QColor(255, 255, 255, 14 if light else 9)
        painter.setPen(QPen(grain, 1))
        for index in range(18):
            x = rect.left() + 12 + ((index * 47) % max(13, int(rect.width() - 24)))
            y = rect.top() + 9 + ((index * 29) % max(11, int(rect.height() - 18)))
            painter.drawPoint(QPointF(x, y))
        painter.end()


class ResponsiveTitle(QLabel):
    """Keep the full product name visible by fitting its font to available width."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("headerTitle")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def _fit_font(self):
        available = max(120, self.contentsRect().width() - 2)
        chosen = 24
        while chosen > 15:
            font = QFont("Segoe UI Variable Display", chosen, QFont.Bold)
            if QFontMetrics(font).horizontalAdvance(self.text()) <= available:
                break
            chosen -= 1
        if abs(self.font().pointSizeF() - chosen) > 0.1:
            # A local rule outranks the application-wide QWidget font rule.
            self.setStyleSheet(
                f"font: 700 {chosen}pt 'Segoe UI Variable Display';"
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_font()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_font()


class ElidedLabel(QLabel):
    """Preserve full accessible text while fitting long live status strings."""

    def __init__(self, text="", parent=None, mode=Qt.ElideRight):
        self._full_text = str(text)
        self._elide_mode = mode
        super().__init__("", parent)
        self.setToolTip(self._full_text)
        self._apply_elision()

    def setText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._apply_elision()

    def text(self):
        return self._full_text

    def _apply_elision(self):
        available = max(1, self.contentsRect().width())
        QLabel.setText(
            self,
            self.fontMetrics().elidedText(self._full_text, self._elide_mode, available),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elision()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            QTimer.singleShot(0, self._apply_elision)


class EffectCard(QAbstractButton):
    """A modern two-line lighting-mode card with consistent monochrome icons."""

    def __init__(self, effect, parent=None):
        super().__init__(parent)
        self.effect = effect
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(68)
        self.setToolTip(effect["desc"])
        self.setAccessibleName(effect["name"])
        self.setAccessibleDescription(effect["desc"])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        god_mode = bool(getattr(self.window(), "god_mode", False))
        light_mode = getattr(self.window(), "appearance_mode", "dark") == "light"
        accent = QColor(getattr(self.window(), "active_accent", "#42c8ff"))

        if self.isChecked():
            background = QLinearGradient(rect.topLeft(), rect.bottomRight())
            selected_top = QColor(accent)
            selected_top.setAlpha(92 if light_mode else 88)
            selected_bottom = QColor("#ffffff" if light_mode else "#07131e")
            selected_bottom.setAlpha(156 if light_mode else 168)
            background.setColorAt(0.0, QColor("#4b1018") if god_mode else selected_top)
            background.setColorAt(1.0, QColor("#21090e") if god_mode else selected_bottom)
            border = QColor("#ff4d5f") if god_mode else accent
            name_color = QColor("#132235" if light_mode else "#f5fbff")
            desc_color = QColor("#7e2230" if light_mode and god_mode else "#45647b" if light_mode else "#ffc0c7" if god_mode else "#a9daf2")
            icon_color = QColor("#ff6575") if god_mode else accent
        elif self.underMouse():
            background = QColor(255, 255, 255, 154) if light_mode else QColor(23, 36, 53, 142)
            border = accent
            name_color = QColor("#152438" if light_mode else "#f3f8fc")
            desc_color = QColor("#526b7e" if light_mode else "#aebfd0")
            icon_color = accent
        else:
            background = QColor(250, 253, 255, 128) if light_mode else QColor(8, 17, 29, 105)
            border = QColor(55, 93, 120, 90) if light_mode else QColor(112, 164, 202, 90)
            name_color = QColor("#17283b" if light_mode else "#e8f0f7")
            desc_color = QColor("#5c7183" if light_mode else "#8fa3b8")
            icon_color = accent

        if getattr(self.window(), "hub_style", False):
            background = QColor("#ffffff" if light_mode else "#191919" if self.isChecked() else "#111111")
            border = QColor("#888888" if self.isChecked() else "#292929")
            name_color = QColor("#171717" if light_mode else "#ffffff")
            desc_color = QColor("#666666" if light_mode else "#a1a1aa")
            icon_color = name_color
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 5, 12, 55 if light_mode else 105))
        painter.drawRoundedRect(QRectF(rect).translated(0, 2), 14, 14)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 14, 14)

        rim = QLinearGradient(rect.topLeft(), rect.topRight())
        rim.setColorAt(0.0, QColor(255, 255, 255, 155 if light_mode else 72))
        rim.setColorAt(0.55, QColor(255, 255, 255, 8))
        rim_color = QColor(accent)
        rim_color.setAlpha(96 if self.isChecked() else 30)
        rim.setColorAt(1.0, rim_color)
        painter.setPen(QPen(QBrush(rim), 1.0))
        painter.drawLine(QPointF(rect.left() + 13, rect.top() + 1.4),
                         QPointF(rect.right() - 13, rect.top() + 1.4))

        icon_rect = QRectF(rect.left() + 15, rect.top() + 13, 28, 42)
        painter.setFont(QFont("Segoe UI Symbol", 14, QFont.DemiBold))
        painter.setPen(icon_color)
        painter.drawText(icon_rect, Qt.AlignLeft | Qt.AlignVCenter, self.effect["icon"])

        text_left = rect.left() + 49
        name_rect = QRectF(text_left, rect.top() + 12, rect.width() - 62, 22)
        desc_rect = QRectF(text_left, rect.top() + 34, rect.width() - 62, 21)
        painter.setFont(QFont("Segoe UI Variable Text", 9, QFont.DemiBold))
        painter.setPen(name_color)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, self.effect["name"])
        painter.setFont(QFont("Segoe UI Variable Text", 7.8, QFont.Normal))
        painter.setPen(desc_color)
        painter.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter, self.effect["desc"])
        painter.end()


class AnimatedBrand(QWidget):
    """Original animated T// wordmark with a restrained moving light sweep."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self._started = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        window = self.window()
        light = getattr(window, "appearance_mode", "dark") == "light"
        animated = getattr(window, "animations_enabled", True)
        phase = ((time.monotonic() - self._started) * 0.32) % 1.0 if animated else 0.45
        accent = QColor(getattr(window, "active_accent", "#42c8ff"))

        glow = QColor(accent)
        glow.setAlpha(int(32 + 28 * math.sin(phase * math.tau) ** 2))
        painter.setPen(QPen(glow, 7))
        painter.drawLine(QPointF(12 + phase * 120, 39), QPointF(42 + phase * 120, 39))

        painter.setFont(QFont("Segoe UI Variable Display", 19, QFont.Black))
        painter.setPen(accent)
        painter.drawText(QRectF(0, 2, 52, 37), Qt.AlignLeft | Qt.AlignVCenter, "T//")
        painter.setFont(QFont("Segoe UI Variable Display", 12, QFont.Bold))
        painter.setPen(QColor("#18283b" if light else "#f5f9fc"))
        painter.drawText(QRectF(54, 3, self.width() - 54, 36), Qt.AlignLeft | Qt.AlignVCenter, "THRASH")
        painter.end()


class AmbientBackground(QWidget):
    """Cached animated scene plus a low-resolution frost map for glass panels."""

    def __init__(self):
        super().__init__()
        self.setObjectName("central")
        self.appearance_mode = "dark"
        self.accent = QColor("#42c8ff")
        self._texture = QPixmap(resource_path(os.path.join("assets", "thrash-liquid-glass-v3.png")))
        self._scaled_texture = QPixmap()
        self._scene = QPixmap()
        self._blurred_scene = QPixmap()
        self._frame_index = 0
        self._started = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(66)

    def _tick(self):
        host = self.window()
        if not host.isVisible() or host.isMinimized() or not getattr(host, "animations_enabled", True):
            return
        self.update()
        for panel in self.findChildren(GlassFrame):
            panel.update()

    def _refresh_texture_cache(self):
        if self._texture.isNull() or self.width() <= 0 or self.height() <= 0:
            self._scaled_texture = QPixmap()
            return
        self._scaled_texture = self._texture.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_texture_cache()
        self._blurred_scene = QPixmap()

    def set_appearance(self, mode, accent):
        self.appearance_mode = mode
        self.accent = QColor(accent)
        self._blurred_scene = QPixmap()
        self.update()

    def _paint_scene(self, painter, width, height, phase):
        painter.setRenderHint(QPainter.Antialiasing)
        if getattr(self.window(), "hub_style", False):
            painter.fillRect(QRectF(0, 0, width, height), QColor("#f3f3f3" if self.appearance_mode == "light" else "#0a0a0a"))
            return

        base = QLinearGradient(0, 0, width, height)
        if self.appearance_mode == "light":
            base.setColorAt(0.0, QColor("#e7f2f8"))
            base.setColorAt(0.52, QColor("#f7fbfd"))
            base.setColorAt(1.0, QColor("#e9eef7"))
        else:
            base.setColorAt(0.0, QColor("#05070d"))
            base.setColorAt(0.52, QColor("#0a101b"))
            base.setColorAt(1.0, QColor("#070a11"))
        painter.fillRect(QRectF(0, 0, width, height), base)

        if not self._scaled_texture.isNull():
            source_x = max(0, (self._scaled_texture.width() - width) // 2)
            source_y = max(0, (self._scaled_texture.height() - height) // 2)
            painter.setOpacity(0.20 if self.appearance_mode == "light" else 0.52)
            painter.drawPixmap(0, 0, self._scaled_texture, source_x, source_y, width, height)
            painter.setOpacity(1.0)

        accent_glow = QColor(self.accent)
        accent_glow.setAlpha(42 if self.appearance_mode == "light" else 70)
        for x, y, radius, color in [
            (width * (0.17 + 0.025 * math.sin(phase * 0.45)), height * 0.10,
             width * 0.52, accent_glow),
            (width * 0.92, height * (0.66 + 0.035 * math.cos(phase * 0.38)),
             width * 0.48, QColor(110, 56, 255, 40)),
        ]:
            glow = QRadialGradient(QPointF(x, y), radius)
            glow.setColorAt(0.0, color)
            fade = QColor(color)
            fade.setAlpha(0)
            glow.setColorAt(1.0, fade)
            painter.fillRect(QRectF(0, 0, width, height), glow)

        # A quiet keyboard-grid motif in the lower background.
        grid_color = QColor(self.accent)
        grid_color.setAlpha(18 if self.appearance_mode == "dark" else 25)
        painter.setPen(QPen(grid_color, 1))
        key_w, key_h, gap = 42, 15, 7
        start_x, start_y = width * 0.43, height * 0.78
        for row in range(4):
            offset = (row % 2) * 12
            for col in range(11):
                rect = QRectF(start_x + col * (key_w + gap) + offset,
                              start_y + row * (key_h + gap), key_w, key_h)
                painter.drawRoundedRect(rect, 4, 4)

    def paintEvent(self, event):
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0:
            return
        if self._scaled_texture.isNull():
            self._refresh_texture_cache()
        self._scene = QPixmap(self.size())
        self._scene.fill(Qt.transparent)
        scene_painter = QPainter(self._scene)
        self._paint_scene(scene_painter, width, height, time.monotonic() - self._started)
        scene_painter.end()

        self._frame_index += 1
        if self._blurred_scene.isNull() or self._frame_index % 3 == 0:
            small = self._scene.scaled(
                max(1, width // 9), max(1, height // 9),
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
            )
            self._blurred_scene = small.scaled(
                self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
            )

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._scene)
        painter.end()


class BootSplash(QWidget):
    """Original LOQ-inspired boot sequence with no copied Lenovo assets."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(720, 420)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        elapsed = time.monotonic() - self.started
        progress = min(1.0, elapsed / 2.4)
        eased = 1.0 - (1.0 - progress) ** 3

        panel = QRectF(4, 4, self.width() - 8, self.height() - 8)
        bg = QLinearGradient(panel.topLeft(), panel.bottomRight())
        bg.setColorAt(0, QColor("#04060b"))
        bg.setColorAt(0.55, QColor("#09111e"))
        bg.setColorAt(1, QColor("#04060b"))
        painter.setPen(QPen(QColor(63, 178, 255, int(110 * eased)), 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(panel, 26, 26)

        glow = QRadialGradient(QPointF(self.width() / 2, self.height() * 0.42), 250)
        glow.setColorAt(0, QColor(31, 155, 255, int(105 * eased)))
        glow.setColorAt(1, QColor(31, 155, 255, 0))
        painter.fillRect(panel, glow)

        logo_font = QFont("Segoe UI Variable Display", 58, QFont.Bold)
        logo_font.setLetterSpacing(QFont.AbsoluteSpacing, 7)
        painter.setFont(logo_font)
        painter.setPen(QColor(235, 247, 255, int(255 * eased)))
        painter.drawText(QRectF(0, 105, self.width(), 100), Qt.AlignCenter, "T//")

        slash_x = self.width() / 2 + 86
        painter.setPen(QPen(QColor(56, 189, 248, int(255 * eased)), 5))
        painter.drawLine(int(slash_x - 12), 128, int(slash_x + 12), 184)

        sub_alpha = int(255 * max(0, min(1, (progress - 0.28) / 0.4)))
        painter.setFont(QFont("Segoe UI Variable Text", 10, QFont.Medium))
        painter.setPen(QColor(164, 205, 231, sub_alpha))
        painter.drawText(QRectF(0, 213, self.width(), 34), Qt.AlignCenter,
                         "LOQ LIGHTENING CENTRE  •  THRASH")

        track = QRectF(160, 292, 400, 3)
        painter.fillRect(track, QColor(255, 255, 255, 20))
        painter.fillRect(QRectF(track.left(), track.top(), track.width() * progress, track.height()),
                         QColor("#38bdf8"))
        painter.setFont(QFont("Segoe UI Variable Text", 8))
        painter.setPen(QColor(117, 146, 167, sub_alpha))
        painter.drawText(QRectF(0, 314, self.width(), 28), Qt.AlignCenter,
                         "INITIALIZING LENOVO LIGHTING BRIDGE")
        painter.end()


class GodModeOverlay(QWidget):
    """Short, original red unlock sequence for the advanced-control reveal."""

    def __init__(self, parent):
        super().__init__(parent)
        self.progress = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def play(self, finished):
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(1150)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.valueChanged.connect(self._tick)
        self.animation.finished.connect(lambda: (self.hide(), finished()))
        self.animation.start()

    def _tick(self, value):
        self.progress = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pulse = math.sin(self.progress * math.pi)
        painter.fillRect(self.rect(), QColor(3, 2, 4, int(242 * pulse)))
        scan_x = int(self.width() * self.progress)
        glow = QLinearGradient(scan_x - 130, 0, scan_x + 35, 0)
        glow.setColorAt(0, QColor(255, 30, 55, 0))
        glow.setColorAt(0.72, QColor(255, 30, 55, int(90 * pulse)))
        glow.setColorAt(1, QColor(255, 87, 105, int(225 * pulse)))
        painter.fillRect(QRectF(scan_x - 130, 0, 165, self.height()), glow)
        painter.setPen(QPen(QColor(255, 64, 82, int(230 * pulse)), 2))
        painter.drawLine(scan_x, 0, scan_x, self.height())
        painter.setFont(QFont("Bahnschrift SemiCondensed", 10, QFont.DemiBold))
        painter.setPen(QColor(255, 100, 113, int(255 * pulse)))
        painter.drawText(QRectF(0, self.height() / 2 - 42, self.width(), 25),
                         Qt.AlignCenter, "ADVANCED LIGHTING CORE")
        painter.setFont(QFont("Bahnschrift SemiCondensed", 29, QFont.Bold))
        painter.setPen(QColor(255, 244, 246, int(255 * pulse)))
        message = "GOD MODE // ACTIVE" if self.progress > 0.62 else "UNLOCKING GOD MODE"
        painter.drawText(QRectF(0, self.height() / 2 - 15, self.width(), 62),
                         Qt.AlignCenter, message)
        painter.end()


# this source preserves an easy migration reference while this definition is the
# one instantiated by the entry point.
class DesktopApplication(QMainWindow):
    """Legion-inspired, original desktop shell with progressive disclosure."""

    LIGHTING_IDS = {
        "steady", "battery_saver", "breathe", "focus_timer", "night_shift", "reactive",
    }
    AUDIO_IDS = {"music_speaker"}

    def __init__(self, ctrl, effect_engine, settings=None):
        super().__init__()
        self.hub_style = True
        self.ctrl = ctrl
        self.engine = effect_engine
        self.settings = settings if settings is not None else QSettings("Thrash", "Thrash Lightening Control")
        legacy_settings = QSettings("Thrash", "Lenovo LOQ Backlit Effects")
        if not self.settings.contains("settingsMigrated"):
            for key in ("godMode", "closeToTray", "animations", "intensity", "idleTimeout"):
                if legacy_settings.contains(key):
                    self.settings.setValue(key, legacy_settings.value(key))
            self.settings.setValue("settingsMigrated", True)
        self.god_mode = self.settings.value("godMode", False, type=bool)
        self.close_to_tray = self.settings.value("closeToTray", True, type=bool)
        self.animations_enabled = self.settings.value("animations", True, type=bool)
        self.appearance_mode = self.settings.value("appearanceMode", "dark", type=str)
        self.accent_theme = self.settings.value("accentTheme", "white", type=str)
        self.active_accent = "#42c8ff"
        self.intensity = max(1, min(self.settings.value("intensity", 50, type=int), 100))
        self.engine.idle_timeout = max(10, min(self.settings.value("idleTimeout", 30, type=int), 300))
        self.light_on = False
        self._shown_error = None
        self._quitting = False
        self._tray_notice_shown = False
        self._has_animated = False
        self._ui_ready = False
        self._suppress_effect_start = False
        self.effect_buttons = QButtonGroup(self)
        self.nav_buttons = QButtonGroup(self)
        self.react_buttons = QButtonGroup(self)
        self.hold_buttons = QButtonGroup(self)
        self.appearance_buttons = QButtonGroup(self)
        self.accent_buttons = QButtonGroup(self)
        self.advanced_widgets = []
        self.cards = {}
        self._build_ui()
        self._build_tray()
        self._apply_god_mode(repaint=True)
        remembered_effect = self.settings.value("lastEffect", "battery_saver", type=str)
        remembered_effect = {"wave":"breathe", "music_mic":"music_speaker"}.get(remembered_effect,remembered_effect)
        if remembered_effect not in self.cards:
            remembered_effect = "battery_saver"
        self._select_effect(remembered_effect, activate=False)
        self._ui_ready = True
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start(250)
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._refresh_keyboard_preview)
        self.preview_timer.start(33)
        self._refresh_status()

    def _build_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(resource_path(os.path.join("assets", "app-icon.png"))))
        self.resize(1440, 900)
        self.setMinimumSize(1040, 700)
        self._set_theme()
        self.background = AmbientBackground()
        self.background.set_appearance(self.appearance_mode, self.active_accent)
        self.setCentralWidget(self.background)
        root = QVBoxLayout(self.background)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(16)
        root.addWidget(self._make_header())
        lower = QHBoxLayout()
        sidebar = self._make_sidebar()
        sidebar.setMinimumHeight(300)
        sidebar_scroll = self._scroll_page(sidebar)
        sidebar_scroll.setFixedWidth(280)
        self.sidebar_scroll = sidebar_scroll
        lower.addWidget(sidebar_scroll)

        body = QVBoxLayout()
        body.setSpacing(12)
        old_bar = self._make_action_bar()
        old_bar.hide()
        self.pages = QStackedWidget()
        self.pages.addWidget(self._scroll_page(self._lighting_page()))
        self.pages.addWidget(self._scroll_page(self._audio_page()))
        self.pages.addWidget(self._scroll_page(self._device_page()))
        self.pages.addWidget(self._scroll_page(self._settings_page()))
        self.pages.addWidget(self._scroll_page(self._about_page()))
        body.addWidget(self.pages, 1)

        root.addWidget(self.preview_panel, 1)
        lower.addLayout(body, 1)
        root.addLayout(lower, 1)
        self.god_overlay = GodModeOverlay(self.background)
        self._page_opacity = QGraphicsOpacityEffect(self.pages)
        self._page_opacity.setOpacity(1.0)
        self.pages.setGraphicsEffect(self._page_opacity)
        self._page_fade = QPropertyAnimation(self._page_opacity, b"opacity", self)
        self._page_fade.setDuration(160)
        self._page_fade.setEasingCurve(QEasingCurve.OutCubic)
        self.pages.currentChanged.connect(self._animate_page_change)

    def _animate_page_change(self, index):
        for title,(button,page) in self.rail_buttons.items():
            button.setProperty("selected",page == index and title != "Reactive")
            button.style().unpolish(button)
            button.style().polish(button)
        selected = self.nav_buttons.button(index)
        if selected:
            selected.setChecked(True)
        self._page_fade.stop()
        self._page_opacity.setOpacity(1.0)
        if self.animations_enabled and self.isVisible() and not self.isMinimized():
            self._page_fade.setStartValue(0.86)
            self._page_fade.setEndValue(1.0)
            self._page_fade.start()

    def _set_theme(self):
        accents = {"white": "#ffffff", "cyan": "#42c8ff", "violet": "#a78bfa", "amber": "#f59e0b", "emerald": "#34d399"}
        accent = "#ff4055" if self.god_mode else accents.get(self.accent_theme, "#ffffff")
        self.active_accent = accent
        light = self.appearance_mode == "light"
        text = "#17283b" if light else "#eaf1f7"
        title = "#102035" if light else "#fbfdff"
        muted = "#5b7083" if light else "#a1a1aa"
        group_gradient = (
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,154),stop:1 rgba(226,241,250,82))"
            if light else
            "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(18,31,48,132),stop:1 rgba(3,10,21,76))"
        )
        button = "#ffffff" if light else "#161616"
        hover = "#eeeeee" if light else "#222222"
        border = "#dddddd" if light else "#27272a"
        accent_color = QColor(accent)
        nav_selected = "#ffffff" if not light else "#171717"
        self.setStyleSheet(f"""
            QMainWindow {{ background: {'#e9f1f6' if light else '#05070c'}; }}
            QWidget {{ color: {text}; font: 9.5pt 'Segoe UI Variable Text'; }}
            QLabel {{ background: transparent; }}
            QLabel#devicePill {{ border:1px solid #222; border-radius:24px; padding:12px 18px; font:700 10pt 'Segoe UI'; }}
            QLabel#replicaHeading {{ font:900 26pt 'Segoe UI'; color:{title}; }}
            QLabel#controlHeading {{ font:800 13pt 'Segoe UI'; color:{title}; }}
            QPushButton#readConfig {{ background:#ffffff; color:#111111; border-radius:20px; padding:14px 20px; }}
            QPushButton#railIcon {{ width:44px; height:44px; border:0; border-radius:22px; padding:0; background:transparent; color:#a1a1aa; font:18pt 'Segoe UI Symbol'; }}
            QPushButton#railIcon[selected='true'] {{ background:#ffffff; color:#111111; }}
            QPushButton#segment {{ border-radius:10px; background:#222222; }}
            QFrame#whiteSwatch {{ border-radius:10px; background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ffffff,stop:1 #323232); }}
            QComboBox {{ background:#161616; color:#ffffff; border:1px solid #292929; border-radius:9px; padding:12px; min-width:100px; }}
            QComboBox QAbstractItemView {{ background:#161616; color:#ffffff; selection-background-color:#333333; }}

            QLabel#headerTitle {{ color: {title}; }}
            QLabel#title {{ font: 900 24pt 'Segoe UI'; color: {title}; }}
            QLabel#pageTitle {{ font: 800 20pt 'Segoe UI'; color: {title}; }}
            QLabel#section {{ color: {accent}; font: 650 8pt 'Segoe UI Variable Text'; }}
            QLabel#muted {{ color: {muted}; }}
            QFrame#sidebar, QFrame#glass, QFrame#status {{ background: transparent; border: 0; }}
            QGroupBox {{ background: {group_gradient}; border: 1px solid {border}; border-radius: 18px; }}
            QPushButton {{ background: {button}; border: 1px solid {border};
                border-radius: 20px; padding: 12px 16px; font: 600 9pt 'Segoe UI Variable Text'; }}
            QPushButton:hover {{ border-color: {border}; background: {button}; }}
            QPushButton#nav {{ text-align: left; background: transparent; border: 0; padding: 8px 12px; color: {muted}; }}
            QPushButton#nav:checked {{ color: {"#111111" if not light else "#ffffff"}; background: {nav_selected}; border-radius: 18px; }}
            QPushButton#primary {{ background: {accent}; color: #05080d; border: 0; font-weight: 750; }}
            QPushButton#primary[running='true'] {{ background: #ff5367; color: #160407; }}
            QPushButton#power {{ min-width:44px; max-width:44px; min-height:44px; max-height:44px; padding:0;
                border-radius:22px; font:700 17pt 'Segoe UI Symbol'; color:{muted}; }}
            QPushButton#power[powered='true'] {{ background:{accent}; color:#071018; border-color:{accent}; }}
            QLabel#statusPill {{ background: rgba({accent_color.red()},{accent_color.green()},{accent_color.blue()},30);
                border: 1px solid rgba({accent_color.red()},{accent_color.green()},{accent_color.blue()},72);
                border-radius: 10px; padding: 5px 9px; font: 650 8pt 'Segoe UI Variable Text'; }}
            QCheckBox {{ spacing: 10px; padding: 6px; color: {text}; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid #71869a; border-radius: 6px; background: {button}; }}
            QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
            QRadioButton {{ padding: 6px; color: {text}; }}
            QGroupBox {{ margin-top: 12px; padding: 16px 12px 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 14px; color: {accent}; padding: 0 6px; }}
            QSlider::groove:horizontal {{ height: 18px; background: #27272a; border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ width: 18px; margin: 0px; background: #ffffff; border: 2px solid {accent}; border-radius: 9px; }}
            QProgressBar {{ height: 8px; background: #1e2a3c; border: 0; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
            QScrollBar:vertical {{ background: transparent; width: 7px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: #454545; min-height: 26px; border-radius: 3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollArea {{ border: 0; background: transparent; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
        """)
        if hasattr(self, "background"):
            self.background.set_appearance(self.appearance_mode, self.active_accent)

    def _make_sidebar(self):
        sidebar = GlassFrame("sidebar")
        self.sidebar_panel = sidebar
        sidebar.setFixedWidth(270)
        row = QHBoxLayout(sidebar)
        row.setContentsMargins(12, 28, 12, 22)
        row.setSpacing(14)
        icons = QVBoxLayout()
        self.rail_buttons = {}
        for icon, title, page in [("▤", "Device",2),("ϟ", "Reactive",0),("☼", "Lighting",0),("♫", "Audio",1),("⚙", "Settings",3),("ⓘ", "About",4)]:
            button = MinimalButton(icon)
            button.setObjectName("railIcon")
            button.setFixedSize(44,44)
            button.setAccessibleName(title)
            self.rail_buttons[title] = (button,page)
            button.setToolTip(title)
            button.clicked.connect(lambda checked=False, i=page: self.pages.setCurrentIndex(i))
            if title == "Lighting":
                button.setProperty("selected", True)
            icons.addWidget(button)
        icons.addStretch()
        row.addLayout(icons)
        self.sidebar_features = QWidget(sidebar)
        features = QVBoxLayout(self.sidebar_features)
        features.setContentsMargins(0,0,0,0)
        for index, text in [(0,"Effects"),(1,"Audio Reactive"),(2,"Device"),(3,"Settings"),(4,"About")]:
            button = MinimalButton(text)
            button.setObjectName("nav")
            button.setFixedHeight(42)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.pages.setCurrentIndex(i))
            self.nav_buttons.addButton(button,index)
            features.addWidget(button)
            if index == 0:
                button.setChecked(True)
        features.addStretch()
        self.god_badge = QLabel("ADVANCED")
        features.addWidget(self.god_badge)
        row.addWidget(self.sidebar_features,1)
        return sidebar

    def _make_header(self):
        panel = GlassFrame("topbar")
        self.header_panel = panel
        panel.setFixedHeight(54)
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        back = MinimalButton("‹  Back")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(2))
        row.addWidget(back)
        self.header_title = QLabel("LOQ LIGHTENING CENTRE")
        self.header_title.setObjectName("devicePill")
        row.addWidget(self.header_title)
        row.addStretch()
        self.header_subtitle = QLabel("THRASH")
        self.header_subtitle.setObjectName("muted")
        row.addWidget(self.header_subtitle)
        default = MinimalButton("Default  ⌄")
        default.setToolTip("Open lighting preferences")
        default.clicked.connect(lambda: self.pages.setCurrentIndex(3))
        row.addWidget(default)
        read = MinimalButton("⟳  Read Config")
        read.setObjectName("readConfig")
        read.clicked.connect(self.redetect)
        row.addWidget(read)
        self.header_status_cluster = QWidget(panel)
        self.header_status_cluster.hide()
        self.connection_dot = QLabel("●", self.header_status_cluster)
        self.method_label = QLabel("Detecting…", self.header_status_cluster)
        self.state_label = ElidedLabel("READY", self.header_status_cluster)
        self.power_button = MinimalButton("☼")
        self.power_button.setObjectName("power")
        self.power_button.setProperty("powered", False)
        self.power_button.setAccessibleName("Lighting power")
        self.power_button.clicked.connect(self.toggle_power)
        return panel

    def _scroll_page(self, content):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _page(self, title, subtitle):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        note = QLabel(subtitle)
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(heading)
        layout.addWidget(note)
        return page, layout

    def _card_grid(self, ids, columns=3):
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        effects = [item for item in EffectEngine.EFFECTS_META if item["id"] in ids]
        for index, effect in enumerate(effects):
            card = EffectCard(effect)
            card.setProperty("effect_id", effect["id"])
            self.effect_buttons.addButton(card)
            self.cards[effect["id"]] = card
            card.clicked.connect(self._effect_changed)
            grid.addWidget(card, index // columns, index % columns)
        return host

    def _lighting_page(self):
        legacy = self._legacy_lighting_page()
        legacy.hide()
        # Keep the existing effect actions for tray, settings and engine wiring.
        self.legacy_controls = legacy
        legacy.setParent(self.background)
        legacy.hide()
        self.preview_panel.setParent(None)
        self.preview_panel.surface = "stage"
        self.preview_panel.setFixedHeight(358)
        old = self.preview_panel.layout()
        while old.count():
            item = old.takeAt(0)
            if item.widget():
                item.widget().hide()
        self.keyboard_preview.setParent(self.preview_panel)
        self.keyboard_preview.setMinimumHeight(180)
        self.keyboard_preview.setMaximumHeight(320)
        self.keyboard_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.keyboard_preview.show()
        old.addWidget(self.keyboard_preview,1)
        power_row = QHBoxLayout()
        power_row.addStretch()
        for title,action in [("↶",lambda:self.keyboard_preview.orbit(-15,0)),("Reset view",self.keyboard_preview.reset_view),("↷",lambda:self.keyboard_preview.orbit(15,0))]:
            button = MinimalButton(title)
            button.setAccessibleName({"↶":"Rotate laptop left", "↷":"Rotate laptop right"}.get(title,title))
            button.clicked.connect(action)
            power_row.addWidget(button)
        power_row.addWidget(self.power_button)
        old.addLayout(power_row)
        page = GlassFrame("panel")
        box = QVBoxLayout(page)
        box.setContentsMargins(26, 26, 26, 22)
        box.setSpacing(24)
        heading = QLabel("Lighting Effects")
        heading.setObjectName("replicaHeading")
        box.addWidget(heading)
        columns = QHBoxLayout()
        columns.setSpacing(18)
        def section(title):
            panel = GlassFrame("control")
            column = QVBoxLayout(panel)
            column.setContentsMargins(24,24,24,24)
            column.setSpacing(18)
            label = QLabel(title)
            label.setObjectName("controlHeading")
            column.addWidget(label)
            columns.addWidget(panel,1)
            return column
        effects = section("Effect")
        effects.addWidget(QLabel("ACTIVE EFFECT"))
        self.effect_combo = QComboBox()
        self.effect_combo.setAccessibleName("Active lighting effect")
        for effect in EffectEngine.EFFECTS_META:
            self.effect_combo.addItem(effect["name"],effect["id"])
        self.effect_combo.activated.connect(lambda index: self._select_effect(self.effect_combo.itemData(index),activate=True))
        effects.addWidget(self.effect_combo)
        self.effect_detail = QLabel()
        self.effect_detail.setWordWrap(True)
        self.effect_detail.setObjectName("muted")
        effects.addWidget(self.effect_detail)
        effects.addStretch()
        controls = section("Effect Controls")
        controls.addWidget(QLabel("EFFECT SPEED"))
        controls.addWidget(self.speed_label)
        controls.addWidget(self.speed_slider)
        self.speed_slider.setToolTip("Enable Advanced controls in Settings to adjust effect speed")
        controls.addWidget(QLabel("BRIGHTNESS"))
        controls.addWidget(self.intensity_value)
        controls.addWidget(self.intensity_slider)
        controls.addStretch()
        custom = section("Effect Customization")
        segment = QHBoxLayout()
        for title, value in [("Dim",50),("Bright",100)]:
            button = MinimalButton(title)
            button.setObjectName("segment")
            button.clicked.connect(lambda checked=False,v=value:self._native_preset(v))
            segment.addWidget(button)
        custom.addLayout(segment)
        custom.addWidget(QLabel("WHITE BACKLIGHT"))
        swatch = QFrame()
        swatch.setObjectName("whiteSwatch")
        swatch.setFixedSize(138,110)
        custom.addWidget(swatch)
        zone = QLabel("Single zone")
        zone.setObjectName("muted")
        custom.addWidget(zone)
        custom.addStretch()
        box.addLayout(columns,1)
        box.addWidget(self.advanced_panel)
        return page

    def _legacy_lighting_page(self):
        page, layout = self._page("LIGHTING", "Your keyboard, your workspace. Choose a steady glow or a purposeful rhythm.")
        summary = GlassFrame("panel")
        self.preview_panel = summary
        summary_layout = QVBoxLayout(summary)
        summary_title = QLabel("SINGLE ZONE  /  WHITE BACKLIGHT")
        summary_title.setObjectName("section")
        summary_layout.addWidget(summary_title)
        self.lighting_summary = QLabel("Choose a mode to begin")
        self.lighting_summary.setObjectName("pageTitle")
        summary_layout.addWidget(self.lighting_summary)
        native_note = QLabel("Off · Dim · Bright   /   Effects use the brightness steps available on your keyboard.")
        native_note.setObjectName("muted")
        native_note.setWordWrap(True)
        native_note.hide()
        self.keyboard_preview = LOQKeyboardPreview()
        summary_layout.addWidget(self.keyboard_preview)
        presets = QHBoxLayout()
        for label, intensity in [("DIM", 50), ("BRIGHT", 100)]:
            button = MinimalButton(label)
            button.setAccessibleName(f"Steady {label.lower()} lighting")
            button.clicked.connect(lambda checked=False, value=intensity: self._native_preset(value))
            presets.addWidget(button)
        presets.addStretch()
        summary_layout.addLayout(presets)
        layout.addWidget(self._card_grid(self.LIGHTING_IDS, 3))
        self.battery_note = QLabel("BATTERY SAVER  •  wakes on keyboard or mouse input  •  sleeps after 30 seconds")
        self.battery_note.setObjectName("muted")
        self.battery_note.setWordWrap(True)
        self.battery_note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.battery_note)
        self.advanced_panel = QGroupBox("GOD MODE  /  ADVANCED TIMING")
        advanced = QVBoxLayout(self.advanced_panel)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("EFFECT SPEED"))
        speed_row.addStretch()
        self.speed_label = QLabel("1.0×")
        speed_row.addWidget(self.speed_label)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(2, 40)
        self.speed_slider.setValue(10)
        self.speed_slider.valueChanged.connect(self._speed_changed)
        advanced.addLayout(speed_row)
        advanced.addWidget(self.speed_slider)
        self.reactive_options = QGroupBox("REACTIVE LAB")
        react_layout = QVBoxLayout(self.reactive_options)
        reaction_row = QGridLayout()
        for index, (value, text_value) in enumerate([(1, "On → Off"), (2, "Dim → Bright"), (3, "Bright → Dim"), (4, "Off → Dim"), (5, "Off → Bright")]):
            option = QRadioButton(text_value)
            self.react_buttons.addButton(option, value)
            option.clicked.connect(self._reactive_options_changed)
            reaction_row.addWidget(option, index // 3, index % 3)
            if value == 2:
                option.setChecked(True)
        react_layout.addLayout(reaction_row)
        hold_row = QHBoxLayout()
        for value, text_value in [(1, "Single timed pulse"), (2, "Hold until every key is released")]:
            option = QRadioButton(text_value)
            self.hold_buttons.addButton(option, value)
            option.clicked.connect(self._reactive_options_changed)
            hold_row.addWidget(option)
            if value == 2:
                option.setChecked(True)
        hold_row.addStretch()
        react_layout.addLayout(hold_row)
        advanced.addWidget(self.reactive_options)
        layout.addWidget(self.advanced_panel)
        self.advanced_widgets.extend([self.advanced_panel])
        layout.addStretch()
        return page

    def _native_preset(self, intensity):
        self.intensity_slider.setValue(intensity)
        self._select_effect("steady", activate=True)

    def _audio_page(self):
        page, layout = self._page("AUDIO REACTIVE", "Speaker Beats uses Windows output peaks, without opening the microphone.")
        layout.addWidget(self._card_grid(self.AUDIO_IDS, 1))
        audio = GlassFrame("panel")
        audio.setObjectName("glass")
        audio_layout = QVBoxLayout(audio)
        self.audio_source_label = QLabel("SPEAKER MODE listens to Windows output—not the microphone.")
        self.audio_source_label.setObjectName("muted")
        self.audio_source_label.setWordWrap(True)
        self.audio_source_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.music_meter = QProgressBar()
        self.music_meter.setRange(0, 100)
        self.music_meter.setTextVisible(False)
        audio_layout.addWidget(self.audio_source_label)
        audio_layout.addWidget(self.music_meter)
        layout.addWidget(audio)
        layout.addStretch()
        return page

    def _device_page(self):
        page, layout = self._page("DEVICE", "Capability-first detection for Lenovo LOQ white-backlit keyboards.")
        panel = GlassFrame("panel")
        panel.setObjectName("glass")
        info = QGridLayout(panel)
        self.device_values = {}
        for row, (key, title) in enumerate([("model", "SYSTEM"), ("capability", "BACKLIGHT"), ("native", "NATIVE LEVEL"), ("contract", "VANTAGE CONTRACT")]):
            label = QLabel(title)
            label.setObjectName("section")
            value = QLabel("Detecting…")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.device_values[key] = value
            info.addWidget(label, row, 0)
            info.addWidget(value, row, 1)
        layout.addWidget(panel)
        buttons = QHBoxLayout()
        redetect = MinimalButton("RE-DETECT HARDWARE")
        redetect.clicked.connect(self.redetect)
        copy = MinimalButton("COPY DIAGNOSTICS")
        copy.clicked.connect(self._copy_diagnostics)
        buttons.addWidget(redetect)
        buttons.addWidget(copy)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        return page

    def _settings_page(self):
        page, layout = self._page("SETTINGS", "Simple by default. Experimental controls unlock only when requested.")
        appearance = QGroupBox("APPEARANCE  /  GLASS THEMES")
        appearance_layout = QVBoxLayout(appearance)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("MODE"))
        for value, label in [("dark", "Dark"), ("light", "Light")]:
            option = QRadioButton(label.upper())
            option.setProperty("appearance_value", value)
            option.setChecked(self.appearance_mode == value)
            option.toggled.connect(self._appearance_changed)
            self.appearance_buttons.addButton(option)
            mode_row.addWidget(option)
        mode_row.addStretch()
        appearance_layout.addLayout(mode_row)
        accent_row = QHBoxLayout()
        accent_row.addWidget(QLabel("ACCENT"))
        for value, label in [("white", "Mono"), ("cyan", "Ion"), ("violet", "Nova"), ("amber", "Solar"), ("emerald", "Matrix")]:
            option = QRadioButton(label.upper())
            option.setProperty("accent_value", value)
            option.setChecked(self.accent_theme == value)
            option.toggled.connect(self._accent_changed)
            self.accent_buttons.addButton(option)
            accent_row.addWidget(option)
        accent_row.addStretch()
        appearance_layout.addLayout(accent_row)
        layout.addWidget(appearance)
        panel = GlassFrame("panel")
        panel.setObjectName("glass")
        settings_layout = QVBoxLayout(panel)
        self.startup_checkbox = QCheckBox("RUN AT WINDOWS STARTUP (VISIBLE IN TASK MANAGER)")
        self.startup_checkbox.setChecked(startup_task_enabled())
        self.startup_checkbox.toggled.connect(self._set_startup)
        self.tray_checkbox = QCheckBox("KEEP RUNNING IN THE SYSTEM TRAY WHEN CLOSED")
        self.tray_checkbox.setChecked(self.close_to_tray)
        self.tray_checkbox.toggled.connect(self._set_close_to_tray)
        self.animation_checkbox = QCheckBox("ENABLE INTERFACE ANIMATIONS")
        self.animation_checkbox.setChecked(self.animations_enabled)
        self.animation_checkbox.toggled.connect(self._set_animations)
        self.god_checkbox = QCheckBox("ENABLE GOD MODE — ADVANCED LIGHTING CONTROLS")
        self.god_checkbox.setChecked(self.god_mode)
        self.god_checkbox.toggled.connect(self._toggle_god_mode)
        for widget in [self.startup_checkbox, self.tray_checkbox, self.animation_checkbox, self.god_checkbox]:
            settings_layout.addWidget(widget)
        warning = QLabel("God Mode changes lighting timing only. It does not overclock the CPU, GPU, or keyboard hardware.")
        warning.setObjectName("muted")
        warning.setWordWrap(True)
        warning.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        settings_layout.addWidget(warning)
        layout.addWidget(panel)
        self.god_settings = QGroupBox("GOD MODE  /  BATTERY SAVER LAB")
        god_layout = QVBoxLayout(self.god_settings)
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("IDLE TIMEOUT"))
        timeout_row.addStretch()
        self.timeout_label = QLabel(f"{int(self.engine.idle_timeout)} SEC")
        timeout_row.addWidget(self.timeout_label)
        self.timeout_slider = QSlider(Qt.Horizontal)
        self.timeout_slider.setRange(10, 300)
        self.timeout_slider.setValue(int(self.engine.idle_timeout))
        self.timeout_slider.valueChanged.connect(self._timeout_changed)
        god_layout.addLayout(timeout_row)
        god_layout.addWidget(self.timeout_slider)
        layout.addWidget(self.god_settings)
        self.advanced_widgets.append(self.god_settings)
        reset = MinimalButton("RESET INTERFACE DEFAULTS")
        reset.clicked.connect(self._reset_defaults)
        layout.addWidget(reset, 0, Qt.AlignLeft)
        layout.addStretch()
        return page

    def _about_page(self):
        page, layout = self._page("ABOUT", f"{APP_NAME}  •  Version {APP_VERSION}")
        panel = GlassFrame("panel")
        panel.setObjectName("glass")
        box = QVBoxLayout(panel)
        title = QLabel("LOQ LIGHTENING CENTRE")
        title.setObjectName("title")
        body = QLabel(
            "A community-built controller for compatible Lenovo LOQ white-backlit keyboards.\n\n"
            "Privacy: lighting, keyboard activity, and audio analysis remain on this PC. No recordings or telemetry are uploaded.\n\n"
            "Compatibility: uses private Lenovo assemblies that may change after Vantage updates. This is a standalone app, not a Vantage plugin. RGB models are excluded.\n\n"
            "Lenovo, LOQ, Legion, ASUS, TUF, and Armoury Crate are trademarks of their respective owners. This project is independent and unaffiliated."
        )
        body.setWordWrap(True)
        body.setObjectName("muted")
        body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        credits = QLabel("THRASH · Made by Hanif · © 2026")
        credits.setObjectName("section")
        box.addWidget(title)
        box.addWidget(body)
        box.addSpacing(12)
        box.addWidget(credits)
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def _make_action_bar(self):
        panel = GlassFrame("bar")
        panel.setObjectName("glass")
        self.action_panel = panel
        row = QHBoxLayout(panel)
        row.setContentsMargins(15, 11, 15, 11)
        row.addWidget(QLabel("INTENSITY"))
        self.intensity_slider = QSlider(Qt.Horizontal)
        self.intensity_slider.setRange(1, 100)
        self.intensity_slider.setValue(self.intensity)
        self.intensity_slider.valueChanged.connect(self._intensity_changed)
        self.intensity_value = QLabel(f"{self.intensity}%")
        self.intensity_value.setFixedWidth(45)
        row.addWidget(self.intensity_slider, 1)
        row.addWidget(self.intensity_value)
        hint = QLabel("SELECT AN EFFECT TO APPLY IT INSTANTLY")
        hint.setObjectName("muted")
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addSpacing(16)
        row.addWidget(hint)
        return panel

    def _build_tray(self):
        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_icon.setToolTip(APP_NAME)
        menu = QMenu()
        open_action = QAction(f"Open {APP_NAME}", self)
        open_action.triggered.connect(self._restore_from_tray)
        power_action = QAction("Toggle Lighting Power", self)
        power_action.triggered.connect(self.toggle_power)
        battery_action = QAction("Arm Battery Saver", self)
        battery_action.triggered.connect(self.arm_startup_battery_saver)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_application)
        menu.addAction(open_action)
        menu.addAction(power_action)
        menu.addAction(battery_action)
        effect_menu = menu.addMenu("Switch Lighting Effect")
        self.tray_effect_actions = {}
        self.tray_power_action = power_action
        for effect in EffectEngine.EFFECTS_META:
            action = QAction(effect["name"], self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, effect_id=effect["id"]: self._activate_tray_effect(effect_id)
            )
            effect_menu.addAction(action)
            self.tray_effect_actions[effect["id"]] = action
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()
        self._sync_tray_effect_actions()

    def _activate_tray_effect(self, effect_id):
        """Switch to any supported effect without reopening the main window."""
        if effect_id in self.cards:
            self._select_effect(effect_id, activate=True)
        self._sync_tray_effect_actions()

    def _sync_tray_effect_actions(self):
        if not hasattr(self, "tray_effect_actions"):
            return
        active = self.engine.running and bool(self.power_button.property("powered"))
        selected = self.selected_effect() if active else None
        for effect_id, action in self.tray_effect_actions.items():
            action.setChecked(effect_id == selected)
        self.tray_power_action.setText("Turn Lighting Off" if active else "Turn Lighting On")

    def _select_effect(self, effect_id, activate=False):
        card = self.cards.get(effect_id)
        if card:
            self._suppress_effect_start = not activate
            card.setChecked(True)
            self._effect_changed()
            self._suppress_effect_start = False

    def selected_effect(self):
        button = self.effect_buttons.checkedButton()
        return button.property("effect_id") if button else "battery_saver"

    def _effect_changed(self, _checked=False):
        effect = self.selected_effect()
        if hasattr(self,"effect_combo"):
            self.effect_combo.setCurrentIndex(self.effect_combo.findData(effect))
        self.speed_slider.setEnabled(self.god_mode and effect in ("breathe","reactive","music_speaker"))
        low, high = EffectEngine.SPEED_LIMITS.get(effect, (0.20, 4.00))
        effective = EffectEngine.clamp_speed(effect, self.speed_slider.value() / 10.0)
        self.speed_slider.blockSignals(True)
        self.speed_slider.setRange(int(round(low * 10)), int(round(high * 10)))
        self.speed_slider.setValue(int(round(effective * 10)))
        self.speed_slider.blockSignals(False)
        self.speed_label.setText(f"{effective:.1f}×")
        self.reactive_options.setVisible(self.god_mode and effect == "reactive")
        self.advanced_panel.setVisible(self.god_mode)
        self.audio_source_label.setText(
            "SPEAKER MODE uses Windows loopback output and adaptive beat transients—not the microphone."
        )
        if self._ui_ready and not self._suppress_effect_start:
            self.settings.setValue("lastEffect", effect)
            self.start_effect()
        self._sync_tray_effect_actions()

    def _speed_changed(self, value):
        effective = EffectEngine.clamp_speed(self.selected_effect(), value / 10.0)
        self.speed_label.setText(f"{effective:.1f}×")
        if self.god_mode and self.engine.running:
            self.engine.speed = effective

    def _reactive_options_changed(self):
        """Apply God Mode reaction choices immediately without restarting power."""
        if self.engine.running and self.engine.current_effect == "reactive":
            self.engine.mode = self.react_buttons.checkedId()
            self.engine.hold_behavior = self.hold_buttons.checkedId()

    def _intensity_changed(self, value):
        self.intensity = value
        self.intensity_value.setText(f"{value}%")
        self.settings.setValue("intensity", value)
        if self.engine.running:
            self.engine.intensity = value

    def _timeout_changed(self, value):
        self.engine.idle_timeout = float(value)
        self.timeout_label.setText(f"{value} SEC")
        self.battery_note.setText(f"BATTERY SAVER  •  wakes on keyboard or mouse input  •  sleeps after {value} seconds")
        self.settings.setValue("idleTimeout", value)

    def _toggle_god_mode(self, enabled):
        self.god_mode = bool(enabled)
        self.settings.setValue("godMode", self.god_mode)
        self._apply_god_mode(repaint=True)
        self._animate_page_change(self.pages.currentIndex())

    def _apply_god_mode(self, repaint=False):
        for widget in self.advanced_widgets:
            widget.setVisible(self.god_mode)
        self.god_badge.setVisible(self.god_mode)
        self.speed_slider.setEnabled(self.god_mode and self.selected_effect() in ("breathe","reactive","music_speaker"))
        if hasattr(self, "reactive_options"):
            self.reactive_options.setVisible(self.god_mode and self.selected_effect() == "reactive")
        if not self.god_mode and hasattr(self, "speed_slider"):
            effect = self.selected_effect()
            recommended = EffectEngine.RECOMMENDED_SPEEDS.get(effect, 1.0)
            effective = EffectEngine.clamp_speed(effect, recommended)
            self.speed_slider.blockSignals(True)
            self.speed_slider.setValue(int(round(effective * 10)))
            self.speed_slider.blockSignals(False)
            self.speed_label.setText(f"{effective:.1f}×")
            if self.engine.running:
                self.engine.speed = effective
        if repaint:
            self._set_theme()
            for card in self.cards.values():
                card.update()

    def _set_close_to_tray(self, enabled):
        self.close_to_tray = bool(enabled)
        self.settings.setValue("closeToTray", self.close_to_tray)

    def _set_animations(self, enabled):
        self.animations_enabled = bool(enabled)
        self.settings.setValue("animations", self.animations_enabled)
        if not enabled:
            if hasattr(self,"_page_fade"):
                self._page_fade.stop()
                self._page_opacity.setOpacity(1.0)
            for button in self.findChildren(MinimalButton):
                button._hover_motion.stop()
                button._set_hover_amount(0.0)
            if hasattr(self,"_entrance_animation"):
                self._entrance_animation.stop()
                self.setWindowOpacity(1.0)
        self._sync_animation_timers()
        if hasattr(self, "animated_brand"):
            self.animated_brand.update()
        if hasattr(self, "background"):
            self.background.update()

    def _sync_animation_timers(self):
        visible = self.isVisible() and not self.isMinimized()
        active = self.animations_enabled and visible and not self.hub_style
        if hasattr(self, "preview_timer"):
            if visible:
                self.preview_timer.start(33)
            else:
                self.preview_timer.stop()
        if hasattr(self, "animated_brand"):
            if active:
                self.animated_brand._timer.start(33)
            else:
                self.animated_brand._timer.stop()
        if hasattr(self, "background"):
            if active:
                self.background._timer.start(66)
            else:
                self.background._timer.stop()

    def _appearance_changed(self, checked):
        if not checked:
            return
        sender = self.sender()
        self.appearance_mode = sender.property("appearance_value")
        self.settings.setValue("appearanceMode", self.appearance_mode)
        self._refresh_appearance()

    def _accent_changed(self, checked):
        if not checked:
            return
        sender = self.sender()
        self.accent_theme = sender.property("accent_value")
        self.settings.setValue("accentTheme", self.accent_theme)
        self._refresh_appearance()

    def _refresh_appearance(self):
        self._set_theme()
        for card in self.cards.values():
            card.update()
        for panel in self.findChildren(GlassFrame):
            panel.update()
        if hasattr(self, "animated_brand"):
            self.animated_brand.update()
        if self.isVisible():
            apply_windows_backdrop(self, self.appearance_mode == "dark")

    def _reset_defaults(self):
        self.god_checkbox.setChecked(False)
        self.tray_checkbox.setChecked(True)
        self.animation_checkbox.setChecked(True)
        self.intensity_slider.setValue(50)
        self.timeout_slider.setValue(30)
        self.speed_slider.setValue(10)
        self.react_buttons.button(2).setChecked(True)
        self.hold_buttons.button(2).setChecked(True)
        for button in self.appearance_buttons.buttons():
            if button.property("appearance_value") == "dark":
                button.setChecked(True)
        for button in self.accent_buttons.buttons():
            if button.property("accent_value") == "cyan":
                button.setChecked(True)
        self.state_label.setText("DEFAULTS RESTORED")

    def start_effect(self, start_asleep=False):
        if self.ctrl.method != "lenovo_vantage_dll":
            QMessageBox.warning(self, "Controller unavailable", "A compatible Lenovo white-backlight interface was not found.")
            return False
        effect = self.selected_effect()
        try:
            speed = self.speed_slider.value() / 10 if self.god_mode else None
            mode = self.react_buttons.checkedId() if self.god_mode else 2
            hold = self.hold_buttons.checkedId() if self.god_mode else 2
            self.engine.start(effect, intensity=self.intensity, speed=speed, mode=mode,
                              hold_behavior=hold, start_asleep=start_asleep)
            name = next(item["name"] for item in EffectEngine.EFFECTS_META if item["id"] == effect)
            self.state_label.setText(f"ACTIVE  /  {name.upper()}")
            self.light_on = True
            self._set_power_visual(True)
            return True
        except Exception as exc:
            self._set_power_visual(False)
            QMessageBox.critical(self, "Could not start effect", str(exc))
            return False

    def arm_startup_battery_saver(self):
        self._select_effect("battery_saver", activate=False)
        self.ctrl.set_brightness(0)
        self.light_on = False
        self.start_effect(start_asleep=True)

    def _set_power_visual(self, powered):
        if not hasattr(self, "power_button"):
            return
        self.power_button.setProperty("powered", bool(powered))
        self.power_button.style().unpolish(self.power_button)
        self.power_button.style().polish(self.power_button)
        self._sync_tray_effect_actions()

    def stop_effect(self, power_off=True):
        self.engine.stop(restore=not power_off)
        if power_off:
            self.ctrl.set_brightness(0)
            self.light_on = False
            self.state_label.setText("POWER  /  OFF")
        else:
            self.state_label.setText("READY")
        self._set_power_visual(False)

    def toggle_effect(self):
        self.toggle_power()

    def toggle_power(self):
        if self.engine.running or self.light_on:
            self.stop_effect(power_off=True)
        else:
            self.start_effect()

    def toggle_light(self):
        self.toggle_power()

    def redetect(self):
        if self.engine.running:
            self.stop_effect()
        self.ctrl.detect_method()
        self._refresh_status()

    def _copy_diagnostics(self):
        status = self.ctrl.get_status()
        lines = [
            f"{APP_NAME} {APP_VERSION}",
            f"System: {status.get('system_model', 'Unknown')}",
            f"Bridge: {status.get('method_display', 'Unknown')}",
            f"Capability: {status.get('backlight_level_type', 'Unknown')}",
            f"Native level: {status.get('current_level', 'Unknown')} / {status.get('max_level', 'Unknown')}",
            f"Contract: {status.get('contract_version', 'Unknown')}",
            f"Administrator: {status.get('is_admin', False)}",
            f"Last error: {status.get('last_error') or 'None'}",
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.state_label.setText("DIAGNOSTICS COPIED")

    def _set_startup(self, enabled):
        try:
            set_startup_task(enabled)
            self.state_label.setText("STARTUP  /  ENABLED" if enabled else "STARTUP  /  DISABLED")
        except Exception as exc:
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(not enabled)
            self.startup_checkbox.blockSignals(False)
            QMessageBox.warning(self, "Startup setting failed", str(exc))

    def _refresh_keyboard_preview(self):
        # Only sample cached state. Never poll the private hardware bridge per frame.
        if self.isVisible() and not self.isMinimized() and self.keyboard_preview.isVisible():
            self.keyboard_preview.set_native_state(
                self.ctrl.current_level, self.ctrl.max_level,
                self.ctrl.method == "lenovo_vantage_dll",
            )

    def _refresh_status(self):
        effect = next((item["name"] for item in EffectEngine.EFFECTS_META if item["id"] == self.selected_effect()), "Ready")
        self.lighting_summary.setText(f"{effect}  ·  {'On' if self.light_on else 'Off'}")
        detail = next((item["desc"] for item in EffectEngine.EFFECTS_META if item["id"] == self.selected_effect()), "")
        if self.engine.running and self.selected_effect() in ("focus_timer","night_shift"):
            detail = getattr(self.engine,"effect_status","") or detail
        self.effect_detail.setText(detail)
        status = self.ctrl.get_status()
        self.method_label.setText(f"{status.get('system_model', 'Lenovo LOQ')}  •  {status.get('method_display', 'Unknown')}")
        method = status.get("method")
        self.connection_dot.setStyleSheet(
            "color:#2dd4bf; font-size:15px;" if method == "lenovo_vantage_dll" else
            "color:#fbbf24; font-size:15px;" if method == "connecting" else
            "color:#fb7185; font-size:15px;"
        )
        self.music_meter.setValue(int(self.engine.music_level * 100))
        self.device_values["model"].setText(status.get("system_model", "Unknown"))
        capability = status.get("backlight_level_type", "Unknown")
        if status.get("compatible_white_backlight"):
            capability += "  •  compatible white backlight"
        self.device_values["capability"].setText(capability)
        self.device_values["native"].setText(f"{status.get('current_level', 0)} of {status.get('max_level', 2)}")
        self.device_values["contract"].setText(status.get("contract_version", "Unknown"))
        if self.engine.running and self.engine.current_effect == "battery_saver":
            if self.intensity != self.engine.intensity:
                self.intensity = self.engine.intensity
                self.intensity_slider.blockSignals(True)
                self.intensity_slider.setValue(self.intensity)
                self.intensity_slider.blockSignals(False)
                self.intensity_value.setText(f"{self.intensity}%")
                self.settings.setValue("intensity", self.intensity)
            if self.engine.idle_sleeping:
                self.state_label.setText("BATTERY SAVER  /  SLEEPING")
            else:
                remaining = max(0, int(math.ceil(self.engine.idle_timeout - self.engine.idle_seconds)))
                self.state_label.setText(f"BATTERY SAVER  /  SLEEP IN {remaining}s")
        if self.engine.last_error and self.engine.last_error != self._shown_error:
            self._shown_error = self.engine.last_error
            self.light_on = False
            self._set_power_visual(False)
            QMessageBox.warning(self, "Effect stopped", self.engine.last_error)
        if not self.engine.running and self.power_button.property("powered") and not self.light_on:
            self._set_power_visual(False)

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_backdrop(self, self.appearance_mode == "dark")
        self._sync_animation_timers()
        if not self._has_animated and self.animations_enabled:
            self._has_animated = True
            self.setWindowOpacity(0.0)
            self._entrance_animation = QPropertyAnimation(self, b"windowOpacity", self)
            self._entrance_animation.setDuration(180)
            self._entrance_animation.setStartValue(0.0)
            self._entrance_animation.setEndValue(1.0)
            self._entrance_animation.setEasingCurve(QEasingCurve.OutCubic)
            self._entrance_animation.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self,"sidebar_features"):
            compact = self.width() < 1350
            self.sidebar_features.setVisible(not compact)
            self.sidebar_panel.setFixedWidth(76 if compact else 270)
            self.sidebar_scroll.setFixedWidth(86 if compact else 280)
        if hasattr(self, "preview_panel"):
            self.preview_panel.setFixedHeight(max(250, int(self.height() * 0.42) - 20))
        if hasattr(self, "god_overlay"):
            self.god_overlay.setGeometry(self.centralWidget().rect())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            QTimer.singleShot(0, self._sync_animation_timers)

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self._sync_animation_timers()
        self.raise_()
        self.activateWindow()

    def _quit_application(self):
        self._quitting = True
        self.status_timer.stop()
        self.preview_timer.stop()
        self.engine.stop()
        self.ctrl.shutdown()
        self.tray_icon.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if not self._quitting and self.close_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            self._sync_animation_timers()
            if not self._tray_notice_shown:
                self._tray_notice_shown = True
                self.tray_icon.showMessage("Still running", "Lighting control continues in the system tray.", QSystemTrayIcon.Information, 3200)
            return
        self._quit_application()
        event.accept()

# ---------------------------------------------------------------------------
#  Shutdown Hook
# ---------------------------------------------------------------------------

import atexit
@atexit.register
def cleanup():
    if engine is not None:
        engine.stop()
    if controller is not None:
        controller.shutdown()

# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    startup_launch = "--startup" in sys.argv

    # The packaged EXE is built with a requireAdministrator manifest. When
    # running from source, still provide a friendly UAC elevation fallback.
    if not is_admin():
        try:
            args = list(sys.argv[1:])
            if not getattr(sys, "frozen", False):
                args.insert(0, os.path.abspath(sys.argv[0]))
            params = " ".join(f'"{arg}"' for arg in args)
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
            if result <= 32:
                raise RuntimeError(f"ShellExecuteW failed with code {result}")
            sys.exit(0)
        except Exception as exc:
            print(f"Administrator privileges are required: {exc}")
            sys.exit(1)

    if startup_launch:
        sys.argv.remove("--startup")

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setApplicationDisplayName(APP_NAME)
    qt_app.setApplicationVersion(APP_VERSION)
    qt_app.setOrganizationName("Thrash")
    qt_app.setWindowIcon(QIcon(resource_path(os.path.join("assets", "app-icon.png"))))
    qt_app.setFont(QFont("Segoe UI Variable Text", 10))
    qt_app.setQuitOnLastWindowClosed(False)

    splash = BootSplash()
    if startup_launch:
        splash.started -= 2.4
    else:
        splash.show()
    bootstrap = {}

    def initialize_hardware():
        try:
            bootstrap["controller"] = KeyboardBacklightController()
            bootstrap["engine"] = EffectEngine(bootstrap["controller"])
        except Exception as exc:
            bootstrap["error"] = exc

    threading.Thread(target=initialize_hardware, daemon=True).start()
    boot_timer = QTimer()

    def finish_boot():
        global controller, engine, window
        if time.monotonic() - splash.started < 2.4:
            return
        if "error" in bootstrap:
            boot_timer.stop()
            splash.close()
            QMessageBox.critical(None, "Startup failed", str(bootstrap["error"]))
            qt_app.quit()
            return
        if "controller" not in bootstrap:
            return
        boot_timer.stop()
        controller = bootstrap["controller"]
        engine = bootstrap["engine"]
        window = DesktopApplication(controller, engine)
        if startup_launch:
            window.arm_startup_battery_saver()
        else:
            window.show()
        splash.close()

    boot_timer.timeout.connect(finish_boot)
    boot_timer.start(45)
    sys.exit(qt_app.exec())
