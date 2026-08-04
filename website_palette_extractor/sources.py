"""Getting HTML and CSS into the pipeline, from a HAR, a URL, or local files."""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class Asset:
    """One retrieved resource."""
    url: str
    kind: str          # "html" | "css" | "image" | "other"
    text: str = ""
    data: bytes = b""
    origin: str = ""
    truncated: bool = False


@dataclass
class Bundle:
    """Everything we managed to collect for one page."""
    page_url: str = ""
    page_origin: str = ""
    assets: list[Asset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Asset]:
        return [a for a in self.assets if a.kind == kind]


def origin_of(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        return p.netloc or ""
    except ValueError:
        return ""


def _kind_for(mime: str, url: str) -> str:
    m = (mime or "").lower()
    u = url.lower().split("?")[0]
    if "html" in m or u.endswith((".html", ".htm")):
        return "html"
    if "css" in m or u.endswith(".css"):
        return "css"
    if m.startswith("image/") or u.endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp")
    ):
        return "image"
    return "other"


# ------------------------------------------------------------------ HAR

def load_har(path: str, want_images: bool = False) -> Bundle:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            har = json.load(fh)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"{path} is not valid JSON (line {e.lineno}, column {e.colno}). "
            f"Re-export it from the browser with 'Save all as HAR with "
            f"content' – a partial or truncated download will fail here."
        ) from e
    except OSError as e:
        raise RuntimeError(f"Could not open {path}: {e}") from e

    if not isinstance(har, dict) or "log" not in har:
        raise RuntimeError(
            f"{path} is JSON but not a HAR file (no 'log' key)."
        )

    log = har.get("log", {})
    entries = log.get("entries", [])
    bundle = Bundle()

    pages = log.get("pages") or []
    if pages:
        bundle.page_url = pages[0].get("title") or pages[0].get("id") or ""

    seen: set[tuple[str, str]] = set()
    truncated_any = []

    for e in entries:
        req = e.get("request", {})
        res = e.get("response", {})
        content = res.get("content", {})
        url = req.get("url", "")
        mime = content.get("mimeType", "")
        kind = _kind_for(mime, url)

        if kind == "image" and not want_images:
            continue
        if kind == "other":
            continue

        text = content.get("text")
        if text is None:
            continue

        key = (url, kind)
        if key in seen:
            continue
        seen.add(key)

        # A HAR records the decoded size; if the stored body is shorter, the
        # exporter capped it and we are looking at a partial file.
        declared = content.get("size")
        encoding = content.get("encoding")

        if encoding == "base64":
            try:
                raw = base64.b64decode(text)
            except Exception:
                continue
            if kind == "image":
                bundle.assets.append(
                    Asset(url=url, kind=kind, data=raw, origin=origin_of(url))
                )
                continue
            body = raw.decode("utf-8", errors="replace")
        else:
            body = text

        trunc = bool(
            isinstance(declared, int)
            and declared > 0
            and len(body.encode("utf-8", "ignore")) < declared * 0.98
        )
        if trunc:
            truncated_any.append(url)

        bundle.assets.append(
            Asset(url=url, kind=kind, text=body, origin=origin_of(url),
                  truncated=trunc)
        )

    if not bundle.page_url:
        html = bundle.by_kind("html")
        if html:
            bundle.page_url = html[0].url
    bundle.page_origin = origin_of(bundle.page_url)

    for u in truncated_any:
        bundle.warnings.append(f"Body truncated by the HAR exporter: {u}")
    if not bundle.by_kind("html"):
        bundle.warnings.append(
            "No HTML document in this HAR. Inline <style> blocks and inline "
            "style attributes cannot be read, so the palette may be partial."
        )
    return bundle


# ------------------------------------------------------------------ URL

def _decompress(raw: bytes, enc: str) -> bytes:
    enc = (enc or "").lower()
    try:
        if enc == "gzip":
            return gzip.decompress(raw)
        if enc == "deflate":
            return zlib.decompress(raw, -zlib.MAX_WBITS)
        if enc == "br":
            import brotli  # optional
            return brotli.decompress(raw)
    except Exception:
        return raw
    return raw


def _get(url: str, timeout: float = 20.0) -> tuple[bytes, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,text/css,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
        mime = r.headers.get("Content-Type", "")
        final = r.geturl()
    return _decompress(raw, enc), mime, final


def load_url(url: str, timeout: float = 20.0,
             max_sheets: int = 40) -> Bundle:
    from .cssparse import extract_stylesheet_links

    bundle = Bundle(page_url=url, page_origin=origin_of(url))
    try:
        raw, mime, final = _get(url, timeout)
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"{url} returned HTTP {e.code}. Many sites block automated "
            f"requests; export a HAR from your browser and pass that instead."
        ) from e
    except Exception as e:
        raise RuntimeError(f"Could not fetch {url}: {e}") from e

    html = raw.decode("utf-8", errors="replace")
    bundle.page_url = final
    bundle.page_origin = origin_of(final)
    bundle.assets.append(
        Asset(url=final, kind="html", text=html, origin=bundle.page_origin)
    )

    for href in extract_stylesheet_links(html)[:max_sheets]:
        abs_url = urllib.parse.urljoin(final, href)
        if abs_url.startswith("data:"):
            continue
        try:
            css_raw, css_mime, css_final = _get(abs_url, timeout)
            bundle.assets.append(
                Asset(url=css_final, kind="css",
                      text=css_raw.decode("utf-8", errors="replace"),
                      origin=origin_of(css_final))
            )
        except Exception as e:
            bundle.warnings.append(f"Could not fetch stylesheet {abs_url}: {e}")

    bundle.warnings.append(
        "Fetched without running JavaScript. Colors applied at runtime by "
        "scripts, or styles injected after load, will be missing. A HAR "
        "export from a real browser session captures those."
    )
    return bundle


# ------------------------------------------------------------------ local

def load_paths(paths: list[str]) -> Bundle:
    bundle = Bundle()
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for fn in files:
                    _add_file(bundle, os.path.join(root, fn))
        else:
            _add_file(bundle, p)
    html = bundle.by_kind("html")
    if html:
        bundle.page_url = html[0].url
    return bundle


def _add_file(bundle: Bundle, path: str) -> None:
    low = path.lower()
    if low.endswith((".html", ".htm")):
        kind = "html"
    elif low.endswith(".css"):
        kind = "css"
    else:
        return
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            bundle.assets.append(
                Asset(url=path, kind=kind, text=fh.read(), origin="")
            )
    except OSError as e:
        bundle.warnings.append(f"Could not read {path}: {e}")


def load_any(target: str, want_images: bool = False,
             timeout: float = 20.0) -> Bundle:
    """Dispatch on what the target looks like."""
    if target.lower().endswith(".har") and os.path.exists(target):
        return load_har(target, want_images=want_images)
    if re.match(r"^https?://", target, re.I):
        return load_url(target, timeout=timeout)
    if os.path.exists(target):
        return load_paths([target])
    raise RuntimeError(
        f"Don't know how to read {target!r}. Give a .har file, an http(s) URL, "
        f"or a path to an .html/.css file or a directory of them."
    )
