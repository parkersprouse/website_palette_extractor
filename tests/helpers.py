"""Fixtures shared across the test modules in this package."""
import os
import tempfile


def write_fixture(content: str, name: str = "page.html") -> str:
    """Write a fragment to a fresh temp dir and return its path."""
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


FIXTURE = """<!DOCTYPE html><html><head>
<style id="framework">
  body { background: #ffffff; color: #333333; }
  .btn { background: #cccccc; }
</style>
<style>
  :root { --brand: #2563eb; --never-used: #ff00ff; }
  body { background: #101418; }
  h1 { color: var(--brand); }
  p { color: rgba(255,255,255,0.75); }
  hr { border-top: 1px solid rgba(255,255,255,0.2); }
  .x { filter: drop-shadow(0 0 0 #00ff00); }
</style>
</head><body></body></html>
"""

UTILITY_GROUND = """<!DOCTYPE html><html><head><style>
  :root { --background: #ffffff; }
  .dark { --background: #0a0a0a; }
  body { background-color: var(--background); color: #333333; }
  .bg-light-primary { background-color: #eeefe9; }
  .bg-dark-primary { background-color: #262626; }
  .dark\\:bg-dark-primary:is(.dark *) { background-color: #262626; }
  .dark\\:bg-light-primary:is(.dark *) { background-color: #eeefe9; }
</style></head>
<body class="bg-light-primary dark:bg-dark-primary"></body></html>
"""

MEDIA_THEMES = """<!DOCTYPE html><html><head><style>
  :root { --bg: #ffffff; --fg: #1a1a1a; --brand: #2563eb; }
  body { background: var(--bg); color: var(--fg); }
  a { color: var(--brand); }
  .card { background: #f4f4f5; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0b0f14; --fg: #e8e8ea; --brand: #60a5fa; }
    .card { background: #16181d; }
  }
</style></head><body></body></html>
"""

CLASS_THEMES = """<!DOCTYPE html><html><head><style>
  html { background: #ffffff; }
  body { color: #222222; }
  .btn { background: #2563eb; }
  html.dark { background: #101010; }
  html.dark body { color: #eeeeee; }
  .dark .btn { background: #60a5fa; }
</style></head><body></body></html>
"""
