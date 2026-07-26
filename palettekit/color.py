"""Color parsing and conversion. Standard library only.

Everything downstream depends on this being right, so the conversions are the
published matrices rather than approximations, and parsing refuses to guess:
a value it doesn't understand returns None instead of a plausible-looking color.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ---------------------------------------------------------------- named colors

NAMED = {
    "aliceblue": "f0f8ff", "antiquewhite": "faebd7", "aqua": "00ffff",
    "aquamarine": "7fffd4", "azure": "f0ffff", "beige": "f5f5dc",
    "bisque": "ffe4c4", "black": "000000", "blanchedalmond": "ffebcd",
    "blue": "0000ff", "blueviolet": "8a2be2", "brown": "a52a2a",
    "burlywood": "deb887", "cadetblue": "5f9ea0", "chartreuse": "7fff00",
    "chocolate": "d2691e", "coral": "ff7f50", "cornflowerblue": "6495ed",
    "cornsilk": "fff8dc", "crimson": "dc143c", "cyan": "00ffff",
    "darkblue": "00008b", "darkcyan": "008b8b", "darkgoldenrod": "b8860b",
    "darkgray": "a9a9a9", "darkgreen": "006400", "darkgrey": "a9a9a9",
    "darkkhaki": "bdb76b", "darkmagenta": "8b008b", "darkolivegreen": "556b2f",
    "darkorange": "ff8c00", "darkorchid": "9932cc", "darkred": "8b0000",
    "darksalmon": "e9967a", "darkseagreen": "8fbc8f", "darkslateblue": "483d8b",
    "darkslategray": "2f4f4f", "darkslategrey": "2f4f4f",
    "darkturquoise": "00ced1", "darkviolet": "9400d3", "deeppink": "ff1493",
    "deepskyblue": "00bfff", "dimgray": "696969", "dimgrey": "696969",
    "dodgerblue": "1e90ff", "firebrick": "b22222", "floralwhite": "fffaf0",
    "forestgreen": "228b22", "fuchsia": "ff00ff", "gainsboro": "dcdcdc",
    "ghostwhite": "f8f8ff", "gold": "ffd700", "goldenrod": "daa520",
    "gray": "808080", "green": "008000", "greenyellow": "adff2f",
    "grey": "808080", "honeydew": "f0fff0", "hotpink": "ff69b4",
    "indianred": "cd5c5c", "indigo": "4b0082", "ivory": "fffff0",
    "khaki": "f0e68c", "lavender": "e6e6fa", "lavenderblush": "fff0f5",
    "lawngreen": "7cfc00", "lemonchiffon": "fffacd", "lightblue": "add8e6",
    "lightcoral": "f08080", "lightcyan": "e0ffff",
    "lightgoldenrodyellow": "fafad2", "lightgray": "d3d3d3",
    "lightgreen": "90ee90", "lightgrey": "d3d3d3", "lightpink": "ffb6c1",
    "lightsalmon": "ffa07a", "lightseagreen": "20b2aa",
    "lightskyblue": "87cefa", "lightslategray": "778899",
    "lightslategrey": "778899", "lightsteelblue": "b0c4de",
    "lightyellow": "ffffe0", "lime": "00ff00", "limegreen": "32cd32",
    "linen": "faf0e6", "magenta": "ff00ff", "maroon": "800000",
    "mediumaquamarine": "66cdaa", "mediumblue": "0000cd",
    "mediumorchid": "ba55d3", "mediumpurple": "9370db",
    "mediumseagreen": "3cb371", "mediumslateblue": "7b68ee",
    "mediumspringgreen": "00fa9a", "mediumturquoise": "48d1cc",
    "mediumvioletred": "c71585", "midnightblue": "191970",
    "mintcream": "f5fffa", "mistyrose": "ffe4e1", "moccasin": "ffe4b5",
    "navajowhite": "ffdead", "navy": "000080", "oldlace": "fdf5e6",
    "olive": "808000", "olivedrab": "6b8e23", "orange": "ffa500",
    "orangered": "ff4500", "orchid": "da70d6", "palegoldenrod": "eee8aa",
    "palegreen": "98fb98", "paleturquoise": "afeeee",
    "palevioletred": "db7093", "papayawhip": "ffefd5", "peachpuff": "ffdab9",
    "peru": "cd853f", "pink": "ffc0cb", "plum": "dda0dd", "powderblue": "b0e0e6",
    "purple": "800080", "rebeccapurple": "663399", "red": "ff0000",
    "rosybrown": "bc8f8f", "royalblue": "4169e1", "saddlebrown": "8b4513",
    "salmon": "fa8072", "sandybrown": "f4a460", "seagreen": "2e8b57",
    "seashell": "fff5ee", "sienna": "a0522d", "silver": "c0c0c0",
    "skyblue": "87ceeb", "slateblue": "6a5acd", "slategray": "708090",
    "slategrey": "708090", "snow": "fffafa", "springgreen": "00ff7f",
    "steelblue": "4682b4", "tan": "d2b48c", "teal": "008080",
    "thistle": "d8bfd8", "tomato": "ff6347", "turquoise": "40e0d0",
    "violet": "ee82ee", "wheat": "f5deb3", "white": "ffffff",
    "whitesmoke": "f5f5f5", "yellow": "ffff00", "yellowgreen": "9acd32",
}

# Words that look like colors in a declaration but carry no color of their own.
NON_COLOR_KEYWORDS = {
    "transparent", "currentcolor", "inherit", "initial", "unset", "revert",
    "none", "auto",
}


@dataclass(frozen=True)
class Color:
    """An sRGB color with alpha. r/g/b are 0-255 floats, a is 0-1."""
    r: float
    g: float
    b: float
    a: float = 1.0

    # -- constructors ------------------------------------------------------
    @property
    def rgb255(self) -> tuple[int, int, int]:
        return (
            int(round(max(0.0, min(255.0, self.r)))),
            int(round(max(0.0, min(255.0, self.g)))),
            int(round(max(0.0, min(255.0, self.b)))),
        )

    @property
    def hex(self) -> str:
        return "#{:02x}{:02x}{:02x}".format(*self.rgb255)

    @property
    def hexa(self) -> str:
        r, g, b = self.rgb255
        return f"#{r:02x}{g:02x}{b:02x}{int(round(self.a * 255)):02x}"

    @property
    def opaque(self) -> bool:
        return self.a >= 0.999

    def over(self, bg: Color) -> Color:
        """Composite self over an opaque background."""
        if self.opaque:
            return Color(self.r, self.g, self.b, 1.0)
        a = self.a
        return Color(
            self.r * a + bg.r * (1 - a),
            self.g * a + bg.g * (1 - a),
            self.b * a + bg.b * (1 - a),
            1.0,
        )

    # -- css serialisations -----------------------------------------------
    def css_rgb(self) -> str:
        r, g, b = self.rgb255
        if self.opaque:
            return f"rgb({r} {g} {b})"
        return f"rgb({r} {g} {b} / {round(self.a, 4)})"

    def css_hsl(self) -> str:
        h, s, l = self.hsl()
        if self.opaque:
            return f"hsl({h} {s}% {l}%)"
        return f"hsl({h} {s}% {l}% / {round(self.a, 4)})"

    def css_oklch(self) -> str:
        L, C, H = self.oklch()
        if self.opaque:
            return f"oklch({L}% {C} {H})"
        return f"oklch({L}% {C} {H} / {round(self.a, 4)})"

    # -- spaces ------------------------------------------------------------
    def hsl(self) -> tuple[float, float, float]:
        r, g, b = (v / 255 for v in (self.r, self.g, self.b))
        mx, mn = max(r, g, b), min(r, g, b)
        l = (mx + mn) / 2
        if abs(mx - mn) < 1e-9:
            return (0.0, 0.0, round(l * 100, 1))
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:
            h = ((g - b) / d) % 6
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        return (round(h * 60, 1), round(s * 100, 1), round(l * 100, 1))

    def oklab(self) -> tuple[float, float, float]:
        lr, lg, lb = (_srgb_to_linear(v) for v in (self.r, self.g, self.b))
        l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb
        m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb
        s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb
        l_, m_, s_ = _cbrt(l), _cbrt(m), _cbrt(s)
        return (
            0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
        )

    def oklch(self) -> tuple[float, float, float]:
        L, a, b = self.oklab()
        C = math.hypot(a, b)
        if C < 0.001:
            # Achromatic. Hue is undefined; reporting a rounding artefact as a
            # hue angle would be a lie, so it is pinned to 0.
            return (round(L * 100, 2), 0.0, 0.0)
        H = math.degrees(math.atan2(b, a)) % 360
        return (round(L * 100, 2), round(C, 4), round(H, 1))

    @property
    def chroma(self) -> float:
        _, a, b = self.oklab()
        return math.hypot(a, b)

    @property
    def is_neutral(self) -> bool:
        return self.chroma < 0.02

    def luminance(self) -> float:
        # Quantized on purpose: we report this color as an 8-bit hex, so the
        # ratio must be the one you get by recomputing from that hex. Using the
        # unrounded floats would print ratios that disagree with our own output.
        r, g, b = self.rgb255
        lr, lg, lb = (_srgb_to_linear(v) for v in (r, g, b))
        return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb


def _srgb_to_linear(v: float) -> float:
    c = v / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    v = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return v * 255.0


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def oklab_to_color(L: float, a: float, b: float, alpha: float = 1.0) -> Color:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return Color(
        _linear_to_srgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        _linear_to_srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        _linear_to_srgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
        alpha,
    )


# CIE Lab, which CSS specifies on a D50 white point — unlike OKLab above, and
# unlike sRGB, which is D65. Both conversions are needed, so the constants are
# spelled out rather than folded together: the D50 white point, the Bradford
# adaptation to D65, and D65 XYZ to linear sRGB, each as given in CSS Color 4.
_D50 = (0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585)
_KAPPA = 24389 / 27
_EPSILON = 216 / 24389

_D50_TO_D65 = (
    (0.9554734527042182, -0.023098536874261423, 0.0632593086610217),
    (-0.028369706963208136, 1.0099954580058226, 0.021041398966943008),
    (0.012314001688319899, -0.020507696433477912, 1.3303659366080753),
)
_XYZ_TO_LINEAR_SRGB = (
    (3.2409699419045226, -1.537383177570094, -0.4986107602930034),
    (-0.9692436362808796, 1.8759675015077202, 0.04155505740717559),
    (0.05563007969699366, -0.20397695888897652, 1.0569715142428786),
)


def lab_to_color(L: float, a: float, b: float, alpha: float = 1.0) -> Color:
    """CIE Lab (D50, as CSS defines it) to sRGB.

    Worth having because Tailwind v4 and friends now ship `lab()` alongside a
    hex fallback, and the `lab()` form is written second — so on a modern build
    it is the one that wins the cascade, and skipping it loses the color
    outright rather than falling back.
    """
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0

    xr = fx ** 3 if fx ** 3 > _EPSILON else (116.0 * fx - 16.0) / _KAPPA
    yr = ((L + 16.0) / 116.0) ** 3 if L > _KAPPA * _EPSILON else L / _KAPPA
    zr = fz ** 3 if fz ** 3 > _EPSILON else (116.0 * fz - 16.0) / _KAPPA

    xyz = (xr * _D50[0], yr * _D50[1], zr * _D50[2])
    d65 = tuple(sum(row[i] * xyz[i] for i in range(3)) for row in _D50_TO_D65)
    lin = tuple(sum(row[i] * d65[i] for i in range(3))
                for row in _XYZ_TO_LINEAR_SRGB)
    return Color(_linear_to_srgb(lin[0]), _linear_to_srgb(lin[1]),
                 _linear_to_srgb(lin[2]), alpha)


def contrast_ratio(a: Color, b: Color) -> float:
    la, lb = a.luminance(), b.luminance()
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def wcag_label(ratio: float) -> str:
    if ratio >= 7:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if ratio >= 3:
        return "AA large"
    return "fail"


def delta_ok(a: Color, b: Color) -> float:
    """Perceptual distance in OKLab. ~0.02 is the edge of noticeable."""
    la, aa, ba = a.oklab()
    lb, ab, bb = b.oklab()
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)


# ---------------------------------------------------------------- parsing

_HEX = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_FUNC = re.compile(r"^([a-zA-Z-]+)\((.*)\)$", re.S)


def _split_args(body: str) -> tuple[list[str], str | None]:
    """Split CSS function args on commas or whitespace, honouring `/` alpha."""
    body = body.strip()
    alpha = None
    if "/" in body:
        # Only split on a top-level slash (not inside a nested function).
        depth = 0
        for i, ch in enumerate(body):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "/" and depth == 0:
                body, alpha = body[:i], body[i + 1:].strip()
                break
    parts = [p for p in re.split(r"[,\s]+", body.strip()) if p]
    return parts, alpha


def _num(tok: str, ref: float = 255.0) -> float | None:
    """Parse a number or percentage against a reference scale."""
    tok = tok.strip()
    if not tok or tok == "none":
        return 0.0
    try:
        if tok.endswith("%"):
            return float(tok[:-1]) / 100.0 * ref
        return float(tok)
    except ValueError:
        return None


def _alpha(tok: str | None) -> float:
    if tok is None:
        return 1.0
    v = _num(tok, 1.0)
    if v is None:
        return 1.0
    return max(0.0, min(1.0, v))


def _hue(tok: str) -> float | None:
    tok = tok.strip().lower()
    for unit, mul in (("deg", 1.0), ("grad", 0.9), ("rad", 180 / math.pi),
                      ("turn", 360.0)):
        if tok.endswith(unit):
            try:
                return float(tok[: -len(unit)]) * mul
            except ValueError:
                return None
    try:
        return float(tok)
    except ValueError:
        return None


def parse_color(text: str) -> Color | None:
    """Parse a CSS color. Returns None for anything not understood.

    Handles hex (3/4/6/8), rgb(), rgba(), hsl(), hsla(), oklch(), oklab(),
    and named colors, in both comma and space-separated syntax.
    """
    if not text:
        return None
    s = text.strip()
    low = s.lower()

    if low in NON_COLOR_KEYWORDS:
        # `transparent` is a real color (transparent black) but tells us
        # nothing about a palette, so it is deliberately dropped.
        return None
    if low in NAMED:
        h = NAMED[low]
        return Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    m = _HEX.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3 or len(h) == 4:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if len(h) == 8:
            return Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
                         int(h[6:8], 16) / 255)
        return None

    m = _FUNC.match(s)
    if not m:
        return None
    fn = m.group(1).lower()
    parts, slash_alpha = _split_args(m.group(2))
    if not parts:
        return None

    if fn in ("rgb", "rgba"):
        if len(parts) < 3:
            return None
        vals = [_num(p, 255.0) for p in parts[:3]]
        if any(v is None for v in vals):
            return None
        a = slash_alpha if slash_alpha is not None else (
            parts[3] if len(parts) > 3 else None
        )
        return Color(vals[0], vals[1], vals[2], _alpha(a))

    if fn in ("hsl", "hsla"):
        if len(parts) < 3:
            return None
        h = _hue(parts[0])
        s_ = _num(parts[1], 1.0)
        l_ = _num(parts[2], 1.0)
        if h is None or s_ is None or l_ is None:
            return None
        a = slash_alpha if slash_alpha is not None else (
            parts[3] if len(parts) > 3 else None
        )
        r, g, b = _hsl_to_rgb(h, max(0.0, min(1.0, s_)), max(0.0, min(1.0, l_)))
        return Color(r, g, b, _alpha(a))

    if fn in ("oklch", "oklab"):
        if len(parts) < 3:
            return None
        L = _num(parts[0], 1.0)
        if L is None:
            return None
        if fn == "oklch":
            C = _num(parts[1], 0.4)
            H = _hue(parts[2])
            if C is None or H is None:
                return None
            a_, b_ = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
        else:
            a_ = _num(parts[1], 0.4)
            b_ = _num(parts[2], 0.4)
            if a_ is None or b_ is None:
                return None
        alpha = slash_alpha if slash_alpha is not None else (
            parts[3] if len(parts) > 3 else None
        )
        return oklab_to_color(L, a_, b_, _alpha(alpha))

    if fn in ("lch", "lab"):
        # CIE Lab, not OKLab: L runs 0-100 here, and a percentage on the axes
        # means 125 (or 150 for lch chroma), per CSS Color 4.
        if len(parts) < 3:
            return None
        L = _num(parts[0], 100.0)
        if L is None:
            return None
        if fn == "lch":
            C = _num(parts[1], 150.0)
            H = _hue(parts[2])
            if C is None or H is None:
                return None
            a_, b_ = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
        else:
            a_ = _num(parts[1], 125.0)
            b_ = _num(parts[2], 125.0)
            if a_ is None or b_ is None:
                return None
        alpha = slash_alpha if slash_alpha is not None else (
            parts[3] if len(parts) > 3 else None
        )
        return lab_to_color(L, a_, b_, _alpha(alpha))

    return None


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[float, float, float]:
    h = h % 360
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return ((r + m) * 255, (g + m) * 255, (b + m) * 255)


# Matches anything that could be a color value inside a declaration.
# Built with %-formatting rather than an f-string on purpose: the pattern
# contains regex quantifiers like {3,8}, which an f-string would require
# doubling to {{3,8}} — harder to read and easy to get wrong on a later edit.
COLOR_TOKEN = re.compile(
    r"""
    \#[0-9a-fA-F]{3,8}\b
  | (?:rgba?|hsla?|oklch|oklab|color|lab|lch)\s*\([^()]*(?:\([^()]*\)[^()]*)*\)
  | \b(?:%s)\b
    """ % "|".join(sorted(NAMED, key=len, reverse=True)),  # noqa: UP031
    re.X | re.I,
)


def find_colors(value: str) -> list[Color]:
    """Pull every color out of a declaration value, in order."""
    out = []
    for m in COLOR_TOKEN.finditer(value):
        c = parse_color(m.group(0))
        if c is not None:
            out.append(c)
    return out


# Boundaries sit midway between the OKLCH hue angles of the named colors.
# These are not the HSL angles: pure red is ~29 degrees in OKLCH, not 0, so
# reusing HSL boundaries here names red "orange".
_HUE_BUCKETS = [
    (42, "red"), (78, "orange"), (122, "yellow"), (168, "green"),
    (202, "teal"), (240, "cyan"), (282, "blue"), (315, "violet"),
    (345, "magenta"), (360, "red"),
]


def hue_name(c: Color) -> str:
    """A coarse hue name, used for generated token names."""
    if c.is_neutral:
        return "grey"
    _, _, h = c.oklch()
    for edge, name in _HUE_BUCKETS:
        if h < edge:
            return name
    return "red"
