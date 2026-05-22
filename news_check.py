"""
Economic calendar warning.
Checks for high-impact US events during your 9:30-11:30 AM trading window.
Uses a hardcoded schedule of the most market-moving events in 2026.
"""
from __future__ import annotations
from datetime import date

# High-impact events that move NQ hard — avoid trading around these
# Format: {date_str: [list of events]}
HIGH_IMPACT_EVENTS_2026 = {
    # FOMC decisions (most market-moving)
    "2026-01-29": ["FOMC Rate Decision 2:00 PM"],
    "2026-03-19": ["FOMC Rate Decision 2:00 PM"],
    "2026-05-07": ["FOMC Rate Decision 2:00 PM"],
    "2026-06-18": ["FOMC Rate Decision 2:00 PM"],
    "2026-07-30": ["FOMC Rate Decision 2:00 PM"],
    "2026-09-17": ["FOMC Rate Decision 2:00 PM"],
    "2026-11-05": ["FOMC Rate Decision 2:00 PM"],
    "2026-12-17": ["FOMC Rate Decision 2:00 PM"],

    # CPI (morning release — can spike NQ at 8:30 AM, affects opening)
    "2026-01-14": ["CPI 8:30 AM — markets volatile at open"],
    "2026-02-11": ["CPI 8:30 AM — markets volatile at open"],
    "2026-03-11": ["CPI 8:30 AM — markets volatile at open"],
    "2026-04-10": ["CPI 8:30 AM — markets volatile at open"],
    "2026-05-13": ["CPI 8:30 AM — markets volatile at open"],
    "2026-06-10": ["CPI 8:30 AM — markets volatile at open"],
    "2026-07-14": ["CPI 8:30 AM — markets volatile at open"],
    "2026-08-12": ["CPI 8:30 AM — markets volatile at open"],
    "2026-09-09": ["CPI 8:30 AM — markets volatile at open"],
    "2026-10-14": ["CPI 8:30 AM — markets volatile at open"],
    "2026-11-12": ["CPI 8:30 AM — markets volatile at open"],
    "2026-12-10": ["CPI 8:30 AM — markets volatile at open"],

    # Non-Farm Payrolls (first Friday of each month, 8:30 AM)
    "2026-01-09": ["NFP 8:30 AM — skip this day"],
    "2026-02-06": ["NFP 8:30 AM — skip this day"],
    "2026-03-06": ["NFP 8:30 AM — skip this day"],
    "2026-04-03": ["NFP 8:30 AM — skip this day"],
    "2026-05-01": ["NFP 8:30 AM — skip this day"],
    "2026-06-05": ["NFP 8:30 AM — skip this day"],
    "2026-07-02": ["NFP 8:30 AM — skip this day"],
    "2026-08-07": ["NFP 8:30 AM — skip this day"],
    "2026-09-04": ["NFP 8:30 AM — skip this day"],
    "2026-10-02": ["NFP 8:30 AM — skip this day"],
    "2026-11-06": ["NFP 8:30 AM — skip this day"],
    "2026-12-04": ["NFP 8:30 AM — skip this day"],

    # GDP (quarterly, 8:30 AM)
    "2026-01-30": ["GDP Advance Q4 8:30 AM"],
    "2026-04-29": ["GDP Advance Q1 8:30 AM"],
    "2026-07-29": ["GDP Advance Q2 8:30 AM"],
    "2026-10-28": ["GDP Advance Q3 8:30 AM"],
}


def check_today() -> list[str]:
    """Return list of event warnings for today. Empty list = clean day."""
    today_str = date.today().isoformat()
    return HIGH_IMPACT_EVENTS_2026.get(today_str, [])


def print_news_warning():
    """Print a warning if today has high-impact events."""
    from rich.console import Console
    from rich.panel import Panel
    console = Console()

    events = check_today()

    if events:
        body = "\n".join(f"  ⚠  {e}" for e in events)
        body += "\n\n  [dim]High-impact news = unpredictable spikes.\n  Consider skipping today or reducing to 1 trade max.[/dim]"
        console.print(Panel(
            body,
            title="[bold red] ⚠  NEWS WARNING TODAY [/bold red]",
            border_style="red", padding=(1, 2)
        ))
    else:
        console.print("[dim]  ✓ No high-impact news events today — clean trading day[/dim]")
