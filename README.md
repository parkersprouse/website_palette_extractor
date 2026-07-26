# palettekit

Extract the color palette a website actually uses, and render it as a
self-contained interactive page.

Values are **read from the site's stylesheets**, not sampled from a screenshot,
so they are the exact declared colors rather than pixels that have been through
antialiasing and JPEG compression.

Python 3.10+ (tested on 3.10 through 3.14). No dependencies for the core
today; Pillow and numpy only if you use `--images`.

If using the system's available Python binary:
```bash
python3 -m palettekit site.har -o "palettes/site"      # from a HAR export (best)
python3 -m palettekit https://example.com -o "palettes/site"
python3 -m palettekit ./saved-page/ -o "palettes/site" # local html/css
open palettes/site/index.html
```

If using `uv`:

```bash
uv run -m palettekit site.har -o "palettes/site"      # from a HAR export (best)
uv run -m palettekit https://example.com -o "palettes/site"
uv run -m palettekit ./saved-page/ -o "palettes/site" # local html/css
open palettes/site/index.html
```

There is also `palettekit.pyz`, the same program as one file:

```bash
python3 palettekit.pyz site.har -o "palettes/site"
# or
uv run palettekit.pyz site.har -o "palettes/site"
```

Or install it, which puts a `palettekit` command on your path:

```bash
pip install .              # core, no dependencies
pip install ".[images]"    # adds pillow + numpy for --images
palettekit site.har -o "palettes/site"
```

## Input: prefer a HAR

A HAR export is what the browser actually loaded, so it includes stylesheets
injected at runtime and works on sites that refuse automated requests. In
Chrome or Firefox: DevTools → Network → reload → right-click → **Save all as
HAR with content**.

`--images` additionally checks whether the artwork carries color the CSS does
not. On an image-led site that is worth knowing before you trust a
stylesheet-only reading.

Passing a URL works, but the page is fetched without running JavaScript. Colors
applied at runtime will be missing, and many sites return 403 to a non-browser
request. The tool says so rather than silently returning a thin palette.

## Output

| File | What it is |
|---|---|
| `index.html` | Interactive palette. Standalone — no server, no network. |
| `*.json` | Canonical. Every token in hex/rgb/hsl/oklch, with provenance, contrast, and where each color was used. |
| `*.css` | Custom properties. |
| `*.scss` | Variables plus a map. |
| `*.ts` | Typed const object and a key union. |
| `*.tailwind.js` | A `theme.extend.colors` block. |

The page lets you switch the copy format between hex, rgb, hsl, oklch and
as-declared, toggle unrendered colors, and see the selector each color came
from. Click any swatch to copy it.

## Light and dark themes

When a site ships two themes, both are extracted and the report gets a toggle.

Two mechanisms are recognised: a `prefers-color-scheme` media query, and a
class or attribute on a wrapper element — `.dark`, `.theme-dark`, `.is-light`,
`[data-theme="dark"]`, `[data-bs-theme=dark]`. The second is the common one,
since Tailwind's `dark:` variant compiles to it.

Each theme is extracted from scratch rather than tagged onto one pass, because
a theme has its own ground — so every contrast ratio you see is measured
against the background that theme actually uses, and colors with alpha are
flattened over the right one. Switching the toggle restyles the whole report,
not just the swatches.

The two palettes share one set of token names, paired by rank within each group
against that theme's own ground. So `ink-2` is the strongest body text in both,
and you can read a theme switch as one value changing rather than two unrelated
lists. The `.css` file uses this directly:

```css
:root                                  { --c-ground: #ffffff; … }
@media (prefers-color-scheme: dark) {
  :root                                { --c-ground: #0b0f14; … }
}
[data-theme="dark"]                    { --c-ground: #0b0f14; … }
```

Both forms are written because there is no telling which one your project uses
— delete the one you don't want.

The JSON grows a `themes` array and a `defaultTheme`; the top-level `ground`,
`stats` and `colors` still mirror the default theme, so anything already
reading the file keeps working. **The scss, ts and tailwind outputs carry the
default theme only.**

A site with no theme scopes produces exactly what it did before — one palette,
no toggle. `--no-themes` forces that.

One caveat, for sites storing theme colors as bare channel triplets
(`--background: 0 0% 3.9%`, the shadcn/ui pattern). Assembled at the point of
use — `hsl(var(--background))`, including `hsl(var(--x) / 50%)` and
`rgb(var(--x))` — those read normally and end up in the palette.

Used raw, as `background-color: var(--background)`, they do not, and that is
correct: `background-color: 0 0% 3.9%` is invalid CSS, so a browser discards it
and paints nothing. Reading a color there would put something in your palette
that the page never shows. You get a note saying so, rather than a silently
thin result.

You also get a note when a theme's ground had to be inferred — when nothing
sets a readable background on `html`, `body` or `:root`, usually because the
page is painted from a wrapper element. Every contrast ratio in that theme is
measured against the inferred ground, so it is worth knowing.

## What it decides, and why

**Ground is resolved by the cascade, not by counting.** The page background is
whichever background rule that lands on the page comes *last*. Weighting by
usage instead gets this wrong on any site that loads a framework stylesheet
before its own — which is most of them. Everything else depends on this, since
colors with alpha are flattened over the ground and every contrast ratio is
measured against it.

"Lands on the page" means the rule actually selects this document's `<html>` or
`<body>`, not just that it's written `body { … }`. Sites built with a utility
framework paint the page from the element — `<body class="bg-light-primary
dark:bg-dark-primary">` — and those classes beat the stylesheet's own `body`
rule. Reading the class attribute is the only way to tell that utility from the
identical-looking one sitting on a card.

**Colors declared with alpha are reported both ways** — flattened to the hex
you actually see, and as originally declared, under `source.declaredAs`.

**Merging happens in OKLab, on the rendered color, within a role.** `#1a1a1a`
and `#191919` become one token. A grey used for body text and the same grey used
for a card background stay two, because they are two things in any theme worth
having. Use `--flat` for one token per distinct color instead.

**Three statuses:**

- `live` — actually painted on the page.
- `saved` — a custom property nothing references. On sites built with a design
  tool this is usually the designer's saved swatches: real intent, not on this
  page.
- `inert` — a declaration that paints nothing, such as
  `drop-shadow(0 0 0 #13330d)`, where every length is zero.

Only `live` colors go into the css/scss/ts/tailwind files, so what you paste
into a project is what the site actually paints. Everything stays in the JSON
and the report, labelled. `--include-unused` overrides this.

**Naming.** Neutrals become `ink-N`, `surface-N`, `line-N`, ordered by
lightness. Colors with real hue get hue names from their OKLCH angle. The
chroma bar for "has a hue" is deliberately above the bar for "is achromatic":
the tinted greys every framework ships sit around 0.03 chroma and are greys
doing a grey's job, so calling one `blue-2` would be worse than useless.

## Framework and page-builder CSS

The biggest source of noise is a site's own platform. A page-builder or
component framework can contribute hundreds of colors that have nothing to do
with the design.

```bash
python3 -m palettekit site.har --list-sources
```

lists every stylesheet in cascade order with its color count, so you can see
the split, then:

```bash
python3 -m palettekit site.har --exclude bootstrap --exclude cdn.example.com
```

Third-party stylesheets are down-weighted by default rather than dropped;
`--all` disables that, `--no-third-party` drops them entirely.

Note that excluding a stylesheet also removes any `var()` references in it, so a
custom property defined in your CSS but consumed only by the framework will flip
from `live` to `saved`. That is accurate for the input you gave it, but worth
knowing before you read too much into a status.

## Options

```
-o, --out DIR         output directory (default: palette-out)
--prefix TEXT         CSS custom property prefix (default: c)
--var-name TEXT       exported name in the TypeScript file
--merge D             OKLab distance below which colors merge (default 0.02)
--flat                one token per color, ignoring role
--limit N             keep only the top N by score
--min-score F         drop colors scoring below F
--only TEXT           only read stylesheets matching TEXT (repeatable)
--exclude TEXT        skip stylesheets matching TEXT (repeatable)
--list-sources        show the stylesheets found, then exit
--no-themes           treat a two-theme site as one theme
--all                 do not down-weight third-party stylesheets
--no-third-party      ignore other-origin stylesheets entirely
--include-unused      put saved/inert colors in the code outputs too
--images              also quantise images (needs pillow + numpy)
--formats LIST        which outputs to write
--timeout SECONDS     network timeout for URL fetches
```

## Limits worth knowing

- **No JavaScript is executed.** A HAR captures styles that were injected before
  you exported, which covers most of it, but a color computed in JS and applied
  to an element property is not in any stylesheet and will not be found.
- **The cascade is approximated, not implemented.** Ground detection follows
  document order, and `var()` resolution takes the last definition. Specificity,
  `@layer` and scoped custom properties are not modelled, apart from a few
  narrow rules for theme overrides and for the page background. This is fine for
  gathering a palette and wrong for predicting exact computed styles.
- **Ranking is a heuristic.** Score reflects where a color is used, not just
  how often. Treat the order as a strong hint, not a measurement.
- `color-mix()`, `light-dark()` and relative color syntax are not evaluated;
  such values are skipped rather than guessed at. `lab()` and `lch()` **are**
  read — modern Tailwind emits them after a hex fallback, so they win the
  cascade and skipping them would drop the color entirely.

## Example

`example/` holds the output for the page this was first built against, so you
can open `example/index.html` and see the result without running anything.

## Tests

```bash
python3 test_palettekit.py
```

65 tests covering the color maths, cascade ordering, theme scoping, ground
detection, the merge rules, and the status classifications. Worth running after
any edit — several of these exist because the obvious implementation was quietly
wrong.

## Licence note

Color values are not copyrightable, so reusing a palette is fine. Fonts,
images, and the page itself are not covered by that — check separately before
reusing anything other than the numbers.
