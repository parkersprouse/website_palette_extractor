"""Optional: check whether a page's imagery actually carries any color.

This never feeds the CSS token set. It answers a different question — "is the
palette in the stylesheet or in the artwork?" — which is worth asking before
trusting a stylesheet-only reading of a visually rich site.

Requires Pillow and numpy. scikit-learn is used when present; without it a
simple k-means runs on numpy alone.
"""
from __future__ import annotations

import io
import math

from .color import Color


def available() -> tuple[bool, str]:
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as e:
        return False, (
            f"Image analysis needs Pillow and numpy ({e.name} is missing). "
            f"Install with: pip install pillow numpy"
        )
    return True, ""


def analyse(images: list[bytes], k: int = 10, sample: int = 400,
            max_images: int = 60) -> dict | None:
    ok, _msg = available()
    if not ok or not images:
        return None

    import numpy as np
    from PIL import Image

    chunks = []
    used = 0
    for raw in images[:max_images]:
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            continue
        im.thumbnail((sample, sample))
        a = np.asarray(im).reshape(-1, 4)
        a = a[a[:, 3] > 128][:, :3]
        if len(a):
            chunks.append(a)
            used += 1

    if not chunks:
        return None

    px = np.concatenate(chunks).astype(np.float64)
    lab = _rgb_to_oklab(px)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    neutral_share = float((chroma < 0.02).mean() * 100)

    rng = np.random.default_rng(0)
    idx = rng.choice(len(lab), size=min(120_000, len(lab)), replace=False)
    sample_lab = lab[idx]

    centers, counts = _kmeans(sample_lab, k)
    order = np.argsort(-counts)
    total = counts.sum()

    dominant = []
    for i in order:
        rgb = _oklab_to_rgb(centers[i].reshape(1, 3))[0]
        c = Color(*rgb)
        dominant.append({
            "hex": c.hex,
            "sharePct": round(float(counts[i] / total * 100), 2),
            "neutral": bool(math.hypot(centers[i][1], centers[i][2]) < 0.02),
        })

    return {
        "imageCount": used,
        "pixelsSampled": int(len(px)),
        "neutralSharePct": round(neutral_share, 1),
        "verdict": (
            "The imagery is essentially greyscale and contributes no color to "
            "the palette."
            if neutral_share > 95 else
            "The imagery carries color the stylesheet does not; a palette read "
            "from CSS alone will be incomplete."
            if neutral_share < 70 else
            "The imagery is mostly neutral with some color present."
        ),
        "dominant": dominant,
    }


def _kmeans(x, k: int):
    import numpy as np
    try:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=k, n_init=6, random_state=0).fit(x)
        return km.cluster_centers_, np.bincount(km.labels_, minlength=k)
    except ImportError:
        pass

    rng = np.random.default_rng(0)
    centers = x[rng.choice(len(x), size=k, replace=False)].copy()
    labels = np.zeros(len(x), dtype=int)
    for _ in range(25):
        d = ((x[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new = d.argmin(axis=1)
        if (new == labels).all():
            break
        labels = new
        for i in range(k):
            m = labels == i
            if m.any():
                centers[i] = x[m].mean(axis=0)
    return centers, np.bincount(labels, minlength=k)


def _rgb_to_oklab(rgb):
    import numpy as np
    c = rgb / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    lms = np.cbrt(np.maximum(lin @ m1.T, 0))
    return lms @ m2.T


def _oklab_to_rgb(lab):
    import numpy as np
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    lms = (lab @ np.linalg.inv(m2).T) ** 3
    lin = lms @ np.linalg.inv(m1).T
    lin = np.clip(lin, 0, 1)
    srgb = np.where(lin <= 0.0031308, lin * 12.92,
                    1.055 * (lin ** (1 / 2.4)) - 0.055) * 255.0
    return srgb
