"""
macOS sound + popup notifications for TJR signals.
Uses built-in macOS tools — no extra installs needed.
"""
import subprocess


def _sound(name: str):
    """Play a macOS system sound."""
    try:
        subprocess.run(
            ["afplay", f"/System/Library/Sounds/{name}.aiff"],
            capture_output=True, timeout=3
        )
    except Exception:
        pass


def _popup(title: str, message: str, sound: str = "Hero"):
    """Show macOS notification banner."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "{sound}"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
    except Exception:
        pass


def alert_sweep(direction: str, price: float, level: float):
    """Yellow warning — sweep detected, get ready."""
    label = "SWEEP HIGH" if direction == "bear" else "SWEEP LOW"
    _sound("Ping")
    _popup(
        f"⚠ {label} — GET READY",
        f"Price at {price:.2f} | Asia level was {level:.2f}",
        sound="Ping"
    )


def alert_signal(direction: str, entry: float, stop: float, tp2: float, score: int):
    """Loud alert — signal confirmed, place the trade NOW."""
    side = "LONG 🟢" if direction == "long" else "SHORT 🔴"
    _sound("Hero")
    _sound("Hero")   # play twice — hard to miss
    _popup(
        f"🚨 TJR SIGNAL — {side}",
        f"Entry {entry:.2f} | Stop {stop:.2f} | TP2 {tp2:.2f} | Score {score}/5",
        sound="Hero"
    )
