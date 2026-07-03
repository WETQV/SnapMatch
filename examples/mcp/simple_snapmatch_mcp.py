from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("snapmatch-simple-example")


@mcp.tool()
def ping() -> str:
    """Return a short health check message."""
    return "SnapMatch example MCP is running."


@mcp.tool()
def current_time(timezone: str = "Europe/Moscow") -> str:
    """Return current time for an IANA timezone, for example Europe/Moscow."""
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        return f"Unknown timezone: {timezone}"
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


@mcp.tool()
def format_note(title: str, body: str = "") -> str:
    """Format a small note as Markdown."""
    title = (title or "Note").strip()
    body = (body or "").strip()
    if body:
        return f"## {title}\n\n{body}"
    return f"## {title}"


@mcp.tool()
def summarize_numbers(numbers: list[float]) -> dict:
    """Return count, sum, min, max and average for a list of numbers."""
    if not numbers:
        return {"count": 0, "sum": 0, "min": None, "max": None, "average": None}
    total = sum(numbers)
    return {
        "count": len(numbers),
        "sum": total,
        "min": min(numbers),
        "max": max(numbers),
        "average": total / len(numbers),
    }


if __name__ == "__main__":
    mcp.run("stdio")
