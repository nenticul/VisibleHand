"""Shared risk-band labelling, used by the API and the dashboard."""


def risk_level(score: float) -> str:
    if score < 25:
        return "Very Low"
    if score < 45:
        return "Low"
    if score < 60:
        return "Moderate"
    if score < 75:
        return "High"
    if score < 88:
        return "Very High"
    return "Critical"


# (threshold-exclusive-upper, background hex, foreground hex)
RISK_COLORS: list[tuple[int, str, str]] = [
    (25,  "#22c55e", "#04210f"),
    (45,  "#86efac", "#04210f"),
    (60,  "#fde68a", "#241a00"),
    (75,  "#f97316", "#1a0a00"),
    (88,  "#ef4444", "#ffffff"),
    (101, "#7f1d1d", "#ffffff"),
]


def risk_color(score: float) -> tuple[str, str]:
    for threshold, bg, fg in RISK_COLORS:
        if score < threshold:
            return bg, fg
    return "#7f1d1d", "#ffffff"
