"""Chart colors for the PNGs and the dashboard, in light and dark.

Two categorical series at most, in the first two slots of a palette checked for
color-vision deficiency in both modes, and one blue ramp for magnitude (light to dark on a
light surface, the other way on a dark one).
"""

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "one": "#2a78d6", "two": "#eb6834",
        "neutral": "#c3c2b7",
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "one": "#3987e5", "two": "#d95926",
        "neutral": "#52514e",
    },
}  # fmt: skip

SEQUENTIAL = {"light": ("#cde2fb", "#0d366b"), "dark": ("#104281", "#cde2fb")}
