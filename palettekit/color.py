"""Color parsing and conversion.

Everything downstream depends on this being right, so the conversions are the
published matrices rather than approximations, and parsing refuses to guess:
a value it doesn't understand returns None instead of a plausible-looking color.

Reuses `tinycss2`'s tokenizer where a sub-value needs real CSS tokenization —
a `calc()` body, currently — rather than re-deriving CSS numeric syntax and
paren/function nesting by hand. Defer to a library already in the dependency
set for anything it already does correctly; hand-roll only what it can't do
(the arithmetic and CSS-type-checking `calc()` evaluation itself, which no
CSS tokenizer performs).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import tinycss2

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

# The two above run sRGB-ward, which is all a parser ever needed. `color-mix()`
# has to go the other way as well — a mix declared `in lab` means converting
# both arguments *into* Lab — so these are their inverses, as given in CSS
# Color 4's sample code. `test_lab_and_xyz_round_trip` asserts they really are
# inverses rather than trusting the transcription.
_LINEAR_SRGB_TO_XYZ = (
    (0.41239079926595934, 0.357584339383878, 0.1804807884018343),
    (0.21263900587151027, 0.715168678767756, 0.07219231536073371),
    (0.01933081871559182, 0.11919477979462598, 0.9505321522496607),
)
_D65_TO_D50 = (
    (1.0479298208405488, 0.022946793341019088, -0.05019222954313557),
    (0.029627815688159344, 0.990434484573249, -0.01707382502938514),
    (-0.009243058152591178, 0.015055144896577895, 0.7518742899580008),
)


def _apply(matrix, v) -> tuple[float, float, float]:
    return tuple(sum(row[i] * v[i] for i in range(3)) for row in matrix)


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
    lin = _apply(_XYZ_TO_LINEAR_SRGB, _apply(_D50_TO_D65, xyz))
    return Color(_linear_to_srgb(lin[0]), _linear_to_srgb(lin[1]),
                 _linear_to_srgb(lin[2]), alpha)


def color_to_lab(c: Color) -> tuple[float, float, float]:
    """sRGB to CIE Lab (D50) — the inverse of `lab_to_color`."""
    xyz = _apply(_D65_TO_D50, xyz_d65_of(c))
    ratio = [xyz[i] / _D50[i] for i in range(3)]
    f = [_cbrt(t) if t > _EPSILON else (_KAPPA * t + 16.0) / 116.0
         for t in ratio]
    return (116.0 * f[1] - 16.0, 500.0 * (f[0] - f[1]), 200.0 * (f[1] - f[2]))


def xyz_d65_of(c: Color) -> tuple[float, float, float]:
    return _apply(_LINEAR_SRGB_TO_XYZ,
                  tuple(_srgb_to_linear(v) for v in (c.r, c.g, c.b)))


def xyz_d65_to_color(x: float, y: float, z: float,
                     alpha: float = 1.0) -> Color:
    lin = _apply(_XYZ_TO_LINEAR_SRGB, (x, y, z))
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


def parse_color(text: str, appearance: str = "light") -> Color | None:
    """Parse a CSS color. Returns None for anything not understood.

    Handles hex (3/4/6/8), rgb(), rgba(), hsl(), hsla(), oklch(), oklab(),
    lab(), lch(), color-mix(), light-dark(), and named colors, in both comma
    and space-separated syntax.

    `appearance` is which branch a `light-dark()` resolves to, and it defaults
    to light because that is what a browser does when the document says nothing
    about `color-scheme`. Every caller that knows better passes the theme it is
    building.
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
    if fn == "color-mix":
        return parse_color_mix(m.group(2), appearance)
    if fn == "light-dark":
        return parse_light_dark(m.group(2), appearance)

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


# ------------------------------------------------------- interpolation spaces
#
# `color-mix(in <space>, …)` is defined as interpolation *in a named space*, so
# mixing needs each space in both directions — the public conversions above only
# ever ran sRGB-ward, because parsing only ever needed that. These are
# unrounded on purpose: `Color.hsl()` and `Color.oklch()` round for display, and
# rounding a coordinate before interpolating it puts the result off by a whole
# 8-bit step often enough to matter when the buckets are keyed on hex.

def _hsl_of(c: Color) -> tuple[float, float, float]:
    """Hue in degrees, saturation and lightness 0-1. Unrounded."""
    r, g, b = (v / 255.0 for v in (c.r, c.g, c.b))
    mx, mn = max(r, g, b), min(r, g, b)
    lightness = (mx + mn) / 2
    if abs(mx - mn) < 1e-12:
        return (0.0, 0.0, lightness)
    d = mx - mn
    s = d / (2 - mx - mn) if lightness > 0.5 else d / (mx + mn)
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h * 60.0, s, lightness)


def _polar(rect: tuple[float, float, float]) -> tuple[float, float, float]:
    """(L, a, b) to (L, C, H°) — the shape `oklch` and `lch` interpolate in."""
    lightness, a, b = rect
    return (lightness, math.hypot(a, b),
            math.degrees(math.atan2(b, a)) % 360.0)


def _rect(polar: tuple[float, float, float]) -> tuple[float, float, float]:
    lightness, chroma, hue = polar
    rad = math.radians(hue)
    return (lightness, chroma * math.cos(rad), chroma * math.sin(rad))


# name -> (to coords, from coords, hue index or None, "hue is powerless" test).
#
# A powerless hue is the reason the last field exists: a grey has no meaningful
# hue angle, and interpolating its arbitrary 0° against a real hue swings the
# result through colors neither argument contains. CSS Color 4 handles this by
# treating the angle as *missing* and carrying the other color's forward, which
# is what `_mix_hue` does with this predicate.
#
# **The thresholds differ per space because they are noise floors, not
# perceptual ones.** A true grey does not convert to a chroma of exactly zero:
# it lands at ~1e-5 in CIE Lab and ~4e-8 in OKLab, all of it accumulated
# rounding through the matrices. The nearest genuinely tinted grey, `#808081`,
# sits at 0.56 and 1.5e-3 in those same spaces. Each threshold has orders of
# magnitude of clearance on both sides; one shared constant does not, because
# Lab chroma runs to ~150 and OKLab chroma to ~0.4.
_SPACES: dict[str, tuple] = {
    "srgb": (
        lambda c: (c.r / 255.0, c.g / 255.0, c.b / 255.0),
        lambda v, a: Color(v[0] * 255.0, v[1] * 255.0, v[2] * 255.0, a),
        None, None,
    ),
    "srgb-linear": (
        lambda c: tuple(_srgb_to_linear(v) for v in (c.r, c.g, c.b)),
        lambda v, a: Color(*(_linear_to_srgb(x) for x in v), a),
        None, None,
    ),
    "hsl": (
        _hsl_of,
        lambda v, a: Color(*_hsl_to_rgb(v[0], max(0.0, min(1.0, v[1])),
                                        max(0.0, min(1.0, v[2]))), a),
        0, lambda v: v[1] < 1e-6,
    ),
    "hwb": (
        lambda c: (_hsl_of(c)[0], min(c.r, c.g, c.b) / 255.0,
                   1.0 - max(c.r, c.g, c.b) / 255.0),
        lambda v, a: _hwb_to_color(v[0], v[1], v[2], a),
        0, lambda v: v[1] + v[2] >= 1.0,
    ),
    "lab": (color_to_lab, lambda v, a: lab_to_color(v[0], v[1], v[2], a),
            None, None),
    "lch": (
        lambda c: _polar(color_to_lab(c)),
        lambda v, a: lab_to_color(*_rect(v), a),
        2, lambda v: v[1] < 1e-3,
    ),
    "oklab": (Color.oklab, lambda v, a: oklab_to_color(v[0], v[1], v[2], a),
              None, None),
    "oklch": (
        lambda c: _polar(c.oklab()),
        lambda v, a: oklab_to_color(*_rect(v), a),
        2, lambda v: v[1] < 1e-5,
    ),
    "xyz": (xyz_d65_of, lambda v, a: xyz_d65_to_color(*v, a), None, None),
    "xyz-d65": (xyz_d65_of, lambda v, a: xyz_d65_to_color(*v, a), None, None),
    "xyz-d50": (
        lambda c: _apply(_D65_TO_D50, xyz_d65_of(c)),
        lambda v, a: xyz_d65_to_color(*_apply(_D50_TO_D65, v), a),
        None, None,
    ),
}


def _hwb_to_color(h: float, w: float, b: float, alpha: float) -> Color:
    w, b = max(0.0, w), max(0.0, b)
    if w + b >= 1.0:
        grey = w / (w + b) * 255.0
        return Color(grey, grey, grey, alpha)
    rgb = _hsl_to_rgb(h, 1.0, 0.5)
    return Color(*((v / 255.0 * (1 - w - b) + w) * 255.0 for v in rgb), alpha)


_HUE_METHODS = ("shorter", "longer", "increasing", "decreasing")


def _mix_hue(h1: float, h2: float, method: str) -> tuple[float, float]:
    """The two angles adjusted so a straight lerp travels the intended arc."""
    h1, h2 = h1 % 360.0, h2 % 360.0
    d = h2 - h1
    if method == "longer":
        if 0 < d < 180:
            h1 += 360.0
        elif -180 < d <= 0:
            h2 += 360.0
    elif method == "increasing":
        if d < 0:
            h2 += 360.0
    elif method == "decreasing":
        if d > 0:
            h1 += 360.0
    else:                                   # shorter, the default
        if d > 180:
            h1 += 360.0
        elif d < -180:
            h2 += 360.0
    return h1, h2


def mix_colors(space: str, c1: Color, p1: float, c2: Color, p2: float,
               hue_method: str = "shorter") -> Color | None:
    """Interpolate two colors in `space`, `p1`/`p2` already normalised to sum 1.

    Alpha is **premultiplied**, per CSS Color 4: the coordinates are weighted by
    each color's own alpha before mixing and divided back out afterwards, so a
    translucent color contributes in proportion to how much of it there is.
    Hue is excluded from that, having no zero to scale toward.

    The zero-alpha short circuit is not an optimisation, it is accuracy. The
    corpus shape by a wide margin is Tailwind's opacity modifier —
    `color-mix(in oklab, <color> 25%, transparent)` — and the premultiplied
    algebra collapses there exactly: with the other alpha zero, every weighted
    coordinate is the first color's own, and the result is that color at
    `alpha * p1`. Running it through OKLab and back instead lands ±1 off on
    some channels, and buckets are keyed on the quantised hex, so that drift
    would invent palette entries out of rounding.
    """
    alpha = c1.a * p1 + c2.a * p2
    if alpha <= 0.0:
        # Both arguments fully transparent, or both weighted to nothing. The
        # result paints nothing; invariant 8 drops it downstream.
        return Color(0.0, 0.0, 0.0, 0.0)
    if c2.a <= 0.0:
        return Color(c1.r, c1.g, c1.b, alpha)
    if c1.a <= 0.0:
        return Color(c2.r, c2.g, c2.b, alpha)

    entry = _SPACES.get(space)
    if entry is None:
        return None                         # a space we do not implement
    to_space, from_space, hue_i, powerless = entry

    v1, v2 = list(to_space(c1)), list(to_space(c2))
    if hue_i is not None:
        # A grey's hue angle is arbitrary, so it is treated as missing and
        # takes the other color's — otherwise mixing a grey with a blue sweeps
        # through hues neither of them has.
        if powerless(v1) and not powerless(v2):
            v1[hue_i] = v2[hue_i]
        elif powerless(v2) and not powerless(v1):
            v2[hue_i] = v1[hue_i]
        v1[hue_i], v2[hue_i] = _mix_hue(v1[hue_i], v2[hue_i], hue_method)

    out = []
    for i in range(3):
        if i == hue_i:
            out.append(v1[i] * p1 + v2[i] * p2)
        else:
            out.append((v1[i] * c1.a * p1 + v2[i] * c2.a * p2) / alpha)
    return from_space(tuple(out), alpha)


# ------------------------------------------------------ color-mix, light-dark

def balanced_end(text: str, start: int) -> int:
    """Index just past the `)` closing the `(` at `start`, or -1.

    Quotes and escapes are honoured because a function argument can hold either
    — `url("a)b")` closes nothing.

    Public within the package because `cssparse.resolve_vars` needs the same
    answer for `var(--x, <fallback with parens>)`. One scanner, not two: a
    second copy would drift from this one, and the whole reason it exists is
    that the parenthesis-counting a regex can do is not enough.
    """
    depth, quote, i = 0, "", start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "\\":
            i += 2
            continue
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _split_top(body: str) -> list[str]:
    """Split on the commas that separate arguments, not the ones inside them."""
    parts, depth, quote, start, i = [], 0, "", 0, 0
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "\\":
            i += 2
            continue
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(body[start:i])
            start = i + 1
        i += 1
    parts.append(body[start:])
    return [p.strip() for p in parts]


_PERCENT = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+))%$")
_LEADING_PERCENT = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)%")
_LEADING_FUNC = re.compile(r"^[a-zA-Z][\w-]*\(")
_LEADING_TOKEN = re.compile(r"^(?:#[0-9a-fA-F]+|[a-zA-Z][\w-]*)")


def _split_component(text: str) -> tuple[str, str] | None:
    """`<color> <percentage>?` split into its two halves, either possibly empty.

    Written as a scan rather than a whitespace split because minified CSS omits
    the space: ground.news ships `color-mix(in oklab,var(--ring)50%,transparent)`
    and `var(--ring)50%` has no boundary a `split()` can find. The color token
    is read first — a balanced function call, a hex, or an identifier — and
    whatever trails it is the percentage.

    A percentage may also be written first, which the spec allows and nothing
    on the corpus does.
    """
    text = text.strip()
    if not text:
        return None
    lead = _LEADING_PERCENT.match(text)
    if lead:
        return (text[lead.end():].strip(), lead.group(0))

    if _LEADING_FUNC.match(text):
        end = balanced_end(text, text.index("("))
        if end < 0:
            return None
    else:
        m = _LEADING_TOKEN.match(text)
        if not m:
            return None
        end = m.end()
    return (text[:end].strip(), text[end:].strip())


_CALC_CALL = re.compile(r"^calc\(", re.I)


def _calc_tokens(body: str) -> list:
    """A `calc()` body's meaningful tokens, via `tinycss2`'s own tokenizer.

    `tinycss2` already tokenizes CSS numeric syntax correctly — percentages,
    a unit split cleanly off a dimension, scientific notation, a leading sign
    folded into the number — and groups nested parens into a
    `ParenthesesBlock` and nested functions into a `FunctionBlock`. Re-deriving
    any of that by hand (as an earlier version of this function did, with a
    regex) duplicates work the tokenizer this project already depends on does
    correctly, for a worse result. Whitespace and comments carry no meaning
    here, so they are dropped rather than threaded through the grammar below.
    """
    return [t for t in tinycss2.parse_component_value_list(body, skip_comments=True)
            if t.type != "whitespace"]


def _calc_factor(tokens: list, pos: list[int]) -> tuple[float, str | None] | None:
    """One signed number/percentage, or a parenthesized sub-expression."""
    if pos[0] >= len(tokens):
        return None
    tok = tokens[pos[0]]
    if tok.type == "literal" and tok.value == "+":
        pos[0] += 1
        return _calc_factor(tokens, pos)
    if tok.type == "literal" and tok.value == "-":
        pos[0] += 1
        inner = _calc_factor(tokens, pos)
        if inner is None:
            return None
        return (-inner[0], inner[1])
    if tok.type == "() block":
        pos[0] += 1
        inner_tokens = [t for t in tok.content if t.type != "whitespace"]
        inner_pos = [0]
        result = _calc_expr(inner_tokens, inner_pos)
        if result is None or inner_pos[0] != len(inner_tokens):
            return None
        return result
    if tok.type == "number":
        pos[0] += 1
        return (tok.value, None)
    if tok.type == "percentage":
        pos[0] += 1
        return (tok.value, "%")
    # A dimension (any unit but `%`), a function (`var()`, `min()`, nested
    # `calc()`), or anything else is outside the supported subset.
    return None


def _calc_term(tokens: list, pos: list[int]) -> tuple[float, str | None] | None:
    left = _calc_factor(tokens, pos)
    if left is None:
        return None
    value, unit = left
    while (pos[0] < len(tokens) and tokens[pos[0]].type == "literal"
           and tokens[pos[0]].value in ("*", "/")):
        op = tokens[pos[0]].value
        pos[0] += 1
        right = _calc_factor(tokens, pos)
        if right is None:
            return None
        rvalue, runit = right
        if op == "*":
            # CSS types this as <number> * <percentage>; percent * percent has
            # no percentage-typed result, so it is outside the subset.
            if unit and runit:
                return None
            value, unit = value * rvalue, (unit or runit)
        else:
            # A percentage divisor has no reciprocal in this type system.
            if runit or rvalue == 0:
                return None
            value = value / rvalue
    return (value, unit)


def _calc_expr(tokens: list, pos: list[int]) -> tuple[float, str | None] | None:
    left = _calc_term(tokens, pos)
    if left is None:
        return None
    value, unit = left
    while (pos[0] < len(tokens) and tokens[pos[0]].type == "literal"
           and tokens[pos[0]].value in ("+", "-")):
        op = tokens[pos[0]].value
        pos[0] += 1
        right = _calc_term(tokens, pos)
        if right is None:
            return None
        rvalue, runit = right
        # <percentage> + <number> is not a valid CSS type; only like units add.
        if unit != runit:
            return None
        value = value + rvalue if op == "+" else value - rvalue
    return (value, unit)


def eval_calc_percentage(body: str) -> float | None:
    """Evaluate a `calc()` body restricted to literal percentage arithmetic.

    Tokenizing is `tinycss2`'s job (`_calc_tokens`); this is the part no CSS
    library does for you — walking the token tree with CSS's own type rules
    for `calc()` (matched at each operator above) and refusing anything
    outside that: `var()`, a unit other than `%`, nested `min()`/`max()`,
    percent×percent, division by a percentage. `None` rather than a guess,
    same as an unrecognised interpolation space or a `color-mix()` this tool
    cannot otherwise read.
    """
    tokens = _calc_tokens(body)
    if not tokens:
        return None
    pos = [0]
    result = _calc_expr(tokens, pos)
    if result is None or pos[0] != len(tokens):
        return None
    value, unit = result
    if unit != "%":
        return None
    return value


def _mix_component(text: str, appearance: str) -> tuple[Color, float | None] | None:
    """One `color-mix()` argument: its color and its percentage, if written.

    `transparent` parses here though `parse_color` refuses it. On its own it
    tells a palette nothing and is deliberately dropped; as a mix argument it
    is the entire mechanism by which Tailwind expresses opacity, and reading it
    as "no color" would throw the declaration away.

    A `calc()` percentage evaluates when it is literal arithmetic (T5); outside
    that subset — a `var()` inside it, mixed units — it makes the whole mix
    unreadable rather than defaulting. Guessing 50% would print a color the
    page does not paint.
    """
    split = _split_component(text)
    if split is None:
        return None
    color_text, pct_text = split
    if color_text.lower() == "transparent":
        color = Color(0.0, 0.0, 0.0, 0.0)
    else:
        color = parse_color(color_text, appearance)
        if color is None:
            return None
    if not pct_text:
        return (color, None)
    if _CALC_CALL.match(pct_text):
        end = balanced_end(pct_text, pct_text.index("("))
        if end < 0 or end != len(pct_text):
            return None
        pct = eval_calc_percentage(pct_text[pct_text.index("(") + 1:end - 1])
        if pct is None:
            return None
        return (color, max(0.0, min(100.0, pct)))
    m = _PERCENT.match(pct_text)
    if not m:
        return None
    return (color, max(0.0, min(100.0, float(m.group(1)))))


def parse_color_mix(body: str, appearance: str) -> Color | None:
    """`color-mix(in <space>[ <method> hue], <c1> <p1>?, <c2> <p2>?)`."""
    parts = _split_top(body)
    if len(parts) != 3:
        return None

    head = parts[0].split()
    if len(head) < 2 or head[0].lower() != "in":
        return None
    space = head[1].lower()
    method = "shorter"
    if len(head) == 4 and head[3].lower() == "hue":
        method = head[2].lower()
        if method not in _HUE_METHODS:
            return None
    elif len(head) != 2:
        return None
    if space not in _SPACES:
        return None

    first = _mix_component(parts[1], appearance)
    second = _mix_component(parts[2], appearance)
    if first is None or second is None:
        return None
    (c1, p1), (c2, p2) = first, second

    # Percentage normalisation, CSS Color 5. An omitted percentage is whatever
    # the other one leaves over; both omitted is an even mix. When both are
    # written and fall short of 100% the shortfall is not padded with either
    # color — it scales the result's alpha, which is how
    # `color-mix(in oklab, red 30%, blue 30%)` comes out translucent.
    if p1 is None and p2 is None:
        p1 = p2 = 50.0
    elif p1 is None:
        p1 = 100.0 - p2
    elif p2 is None:
        p2 = 100.0 - p1
    total = p1 + p2
    if total <= 0:
        return None
    alpha_scale = min(1.0, total / 100.0)

    mixed = mix_colors(space, c1, p1 / total, c2, p2 / total, method)
    if mixed is None:
        return None
    return Color(mixed.r, mixed.g, mixed.b, mixed.a * alpha_scale)


def parse_light_dark(body: str, appearance: str) -> Color | None:
    """`light-dark(A, B)` — whichever branch the palette being built selects.

    Not a color function so much as a theme choice written inline, which is why
    it belongs to this tool rather than being skipped: a theme is already the
    unit everything here is built per. The branch is chosen by the caller's
    `appearance`, and the palette that asked is the one that paints it.
    """
    parts = _split_top(body)
    if len(parts) != 2:
        return None
    return parse_color(parts[1] if appearance == "dark" else parts[0],
                       appearance)


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


_WHOLE_VALUE_FUNCS = re.compile(r"\b(color-mix|light-dark)\s*\(", re.I)


def _whole_value_spans(value: str) -> list[tuple[int, int]]:
    """Ranges covered by a top-level `color-mix()` or `light-dark()` call.

    Top-level only: a `color-mix()` nested in another is evaluated by the outer
    one's recursion, not found again here.
    """
    spans: list[tuple[int, int]] = []
    for m in _WHOLE_VALUE_FUNCS.finditer(value):
        if spans and m.start() < spans[-1][1]:
            continue
        end = balanced_end(value, m.end() - 1)
        if end > 0:
            spans.append((m.start(), end))
    return spans


def find_colors(value: str, appearance: str = "light") -> list[Color]:
    """Pull every color out of a declaration value, in order.

    `color-mix()` and `light-dark()` are handled before the token scan and
    their spans are then excluded from it, because they are functions *of*
    colors: the two hexes in `light-dark(#fff, #18191b)` are one color, chosen
    by the theme, and the arguments to a `color-mix()` are not colors the page
    paints — the mix is.

    **A call this tool cannot evaluate contributes nothing, rather than falling
    back to the arguments inside it.** `color-mix(in oklch, #b4d455 calc(50% -
    var(--x)), transparent)` has a readable hex in it and that hex is not on
    the page; reporting it would be exactly the plausible-looking guess this
    module exists to refuse. A `calc()` percentage that is literal arithmetic
    — `calc(60 * 1%)` — evaluates instead (`eval_calc_percentage`, T5); this
    remains visible only at the per-declaration level — see `PLAN.md` phase 4
    and T5.
    """
    out = []
    spans = _whole_value_spans(value)
    cursor = 0
    for start, end in spans + [(len(value), len(value))]:
        for m in COLOR_TOKEN.finditer(value, cursor, start):
            c = parse_color(m.group(0), appearance)
            if c is not None:
                out.append(c)
        if end > start:
            c = parse_color(value[start:end], appearance)
            if c is not None:
                out.append(c)
        cursor = end
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
