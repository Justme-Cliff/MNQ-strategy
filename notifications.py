"""
Cross-platform sound + popup notifications for the IDK Quant system.

macOS  : osascript (built-in) + afplay system sounds
Windows: winsound (built-in) + PowerShell BalloonTip toast
Linux  : notify-send (standard on GNOME/KDE) + paplay/aplay sounds

No extra packages required on any platform — all tools are either
built into Python or ship with the OS.

Optional on Windows: pip install win10toast
  If win10toast is installed, it is used instead of PowerShell for cleaner toasts.
"""
from __future__ import annotations
import platform
import subprocess
import sys

_OS = platform.system()   # "Darwin" | "Windows" | "Linux"

# ── Optional Windows toast library ──────────────────────────────────────────
_WIN_TOASTER = None
if _OS == "Windows":
    try:
        from win10toast import ToastNotifier   # type: ignore
        _WIN_TOASTER = ToastNotifier()
    except ImportError:
        pass

# ── Windows CREATE_NO_WINDOW flag (suppresses extra console windows) ─────────
_NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── macOS sound names → Windows winsound constants ───────────────────────────
# winsound.MB_* values (integers) so we can import lazily on non-Windows
_WIN_SOUNDS = {
    "Hero":  0x00000030,   # MB_ICONEXCLAMATION — urgent
    "Ping":  0x00000040,   # MB_ICONASTERISK    — info
    "Glass": 0x00000000,   # MB_OK              — default beep
    "Pop":   0x00000040,   # MB_ICONASTERISK    — info
    "Basso": 0x00000010,   # MB_ICONHAND        — critical/error
}

# Linux sound files (freedesktop standard paths)
_LINUX_SOUNDS = {
    "Hero":  "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "Ping":  "/usr/share/sounds/freedesktop/stereo/bell.oga",
    "Glass": "/usr/share/sounds/freedesktop/stereo/service-login.oga",
    "Pop":   "/usr/share/sounds/freedesktop/stereo/dialog-information.oga",
    "Basso": "/usr/share/sounds/freedesktop/stereo/dialog-error.oga",
}


def _sound(name: str) -> None:
    """Play a system sound by its macOS name (mapped to other platforms)."""
    try:
        if _OS == "Darwin":
            subprocess.run(
                ["afplay", f"/System/Library/Sounds/{name}.aiff"],
                capture_output=True, timeout=3,
            )

        elif _OS == "Windows":
            import winsound
            winsound.MessageBeep(_WIN_SOUNDS.get(name, 0x00000040))

        else:
            path = _LINUX_SOUNDS.get(name)
            if path:
                # Try paplay (PulseAudio), then aplay (ALSA), then beep
                for cmd in (["paplay", path], ["aplay", path]):
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=3)
                        break
                    except FileNotFoundError:
                        continue

    except Exception:
        pass


def _popup(title: str, message: str, sound: str = "Hero") -> None:
    """Display an OS notification popup (non-blocking where possible)."""
    # Strip characters that break script embedding
    def _clean(s: str) -> str:
        return (s.replace("\\", "\\\\")
                 .replace('"',  '\\"')
                 .replace("'",  "\\'")
                 .replace("\n", " "))

    safe_title = _clean(title)
    safe_msg   = _clean(message)

    try:
        if _OS == "Darwin":
            script = (
                f'display notification "{safe_msg}" '
                f'with title "{safe_title}" '
                f'sound name "{sound}"'
            )
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=0.5,
            )

        elif _OS == "Windows":
            if _WIN_TOASTER is not None:
                # win10toast — clean modern toast, non-blocking
                _WIN_TOASTER.show_toast(
                    title,
                    message,
                    duration=5,
                    threaded=True,
                )
            else:
                # Fallback: PowerShell BalloonTip (no extra packages needed)
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "Add-Type -AssemblyName System.Drawing; "
                    "$n = New-Object System.Windows.Forms.NotifyIcon; "
                    "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                    "$n.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info; "
                    f"$n.BalloonTipTitle = '{safe_title}'; "
                    f"$n.BalloonTipText  = '{safe_msg}'; "
                    "$n.Visible = $true; "
                    "$n.ShowBalloonTip(5000); "
                    "Start-Sleep -Seconds 6; "
                    "$n.Dispose()"
                )
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                    creationflags=_NO_WIN,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        else:
            # Linux: notify-send (ships with libnotify on GNOME/KDE/XFCE)
            subprocess.run(
                ["notify-send", "--urgency=normal", "--expire-time=5000",
                 title, message],
                capture_output=True, timeout=2,
            )

    except Exception:
        # Absolute fallback: terminal output so no notification is ever silently lost
        print(f"\n{'='*60}")
        print(f"  NOTIFICATION | {title}")
        print(f"  {message}")
        print(f"{'='*60}\n")


# ── Public API ────────────────────────────────────────────────────────────────

def alert_warning(strategy: str, detail: str) -> None:
    """Setup forming — get ready."""
    _sound("Ping")
    _popup(f"SETUP FORMING — {strategy.upper()}", detail, sound="Ping")


def alert_signal(
    strategy: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> None:
    """Signal confirmed — place the trade NOW."""
    side = "LONG" if direction == "long" else "SHORT"
    _sound("Hero")
    _sound("Hero")
    _popup(
        f"{strategy.upper()} {side} — SIGNAL",
        f"E: {entry:.1f}   S: {stop:.1f}   T: {target:.1f}",
        sound="Hero",
    )


def alert_session_start() -> None:
    """Market opens in 5 minutes."""
    _sound("Ping")
    _popup(
        "Market Opens in 5 min",
        "Check gap size and VIX. Get ready.",
        sound="Ping",
    )


def alert_session_end() -> None:
    """Session over — noon ET."""
    _sound("Glass")
    _popup(
        "Session Over — 12:00 PM",
        "Stop trading. Close all positions.",
        sound="Glass",
    )


def alert_breakeven(strategy: str, direction: str, entry: float) -> None:
    """T1 hit — move stop to entry (breakeven)."""
    side = "LONG" if direction == "long" else "SHORT"
    _sound("Pop")
    _sound("Pop")
    _popup(
        f"T1 HIT — MOVE STOP TO ENTRY",
        f"{strategy.upper()} {side} | Move SL to {entry:.1f} (your entry price)",
        sound="Pop",
    )


def alert_risk_warning(msg: str) -> None:
    """Buffer / risk warning."""
    _sound("Basso")
    _popup("RISK WARNING", msg, sound="Basso")
