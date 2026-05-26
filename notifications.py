"""
macOS sound + popup notifications for quant system signals.
Uses built-in macOS tools — no extra installs needed.
"""
import subprocess


def _sound(name: str):
    try:
        subprocess.run(["afplay", f"/System/Library/Sounds/{name}.aiff"],
                       capture_output=True, timeout=3)
    except Exception:
        pass


def _popup(title: str, message: str, sound: str = "Hero"):
    try:
        script = f'display notification "{message}" with title "{title}" sound name "{sound}"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
    except Exception:
        pass


def alert_warning(strategy: str, detail: str):
    """Yellow warning — setup is forming, get ready."""
    _sound("Ping")
    _popup(f"⚠ {strategy.upper()} FORMING", detail, sound="Ping")


def alert_signal(strategy: str, direction: str, entry: float, stop: float, target: float):
    """Loud alert — signal confirmed, place the trade NOW."""
    side = "LONG 🟢" if direction == "long" else "SHORT 🔴"
    _sound("Hero")
    _sound("Hero")
    _popup(
        f"🚨 {strategy.upper()} — {side}",
        f"E:{entry:.1f}  S:{stop:.1f}  T:{target:.1f}",
        sound="Hero"
    )


def alert_session_start():
    _sound("Ping")
    _popup("📈 Market Opens in 5 min", "Check gap size and VIX. Get ready.", sound="Ping")


def alert_session_end():
    _sound("Glass")
    _popup("🏁 Session Over — 12:00 PM", "Stop trading. Review your trades.", sound="Glass")


def alert_risk_warning(msg: str):
    _sound("Basso")
    _popup("⛔ RISK WARNING", msg, sound="Basso")
