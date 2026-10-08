from __future__ import annotations

PORTFOLIO_EXAMPLES = (
    {
        "id": "capital_preservation",
        "name": "Capital preservation",
        "description": "Illustrative lower-volatility mix; cash and bonds can still lose value, and principal is not guaranteed.",
        "allocation": (
            ("Cash / cash equivalents", 50),
            ("Short-duration bonds", 30),
            ("Broad-market funds", 15),
            ("Event-linked research sleeve", 5),
        ),
    },
    {
        "id": "balanced",
        "name": "Balanced",
        "description": "Illustrative middle path with defensive assets, diversified funds, and a limited event-linked sleeve.",
        "allocation": (
            ("Cash / cash equivalents", 10),
            ("Bonds", 20),
            ("Broad-market funds", 40),
            ("Technology / growth funds", 15),
            ("Event-linked research sleeve", 15),
        ),
    },
    {
        "id": "growth",
        "name": "Growth-oriented",
        "description": "Illustrative higher-volatility mix; a larger equity share can result in substantial losses.",
        "allocation": (
            ("Cash / cash equivalents", 5),
            ("Bonds", 5),
            ("Broad-market funds", 30),
            ("Technology / growth funds", 30),
            ("Event-linked research sleeve", 30),
        ),
    },
)


def allocation_total(profile: dict) -> int:
    return sum(weight for _, weight in profile["allocation"])
