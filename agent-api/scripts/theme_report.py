"""Epic 34 (Story 34.1): the reference apps' themes measured, against the baseline.

    python -m scripts.theme_report [--baseline [name=frontend-spec.json ...]] [--html OUT]

The reference requirements are `tests/fixtures/themes/requirements/<name>.md`. Each app's theme is read from its newest
recorded draft: `tests/fixtures/drafts/theme-<name>/frontend-spec.json` (drafted with the design turn, Story 34.5), else
`domain-<name>-v10`. A theme is measured as the app draws it: its colours and its leading look's font pairing.
`--baseline` writes the themes and their measures to `tests/fixtures/themes/baseline.json` (taken once, before the
design turn; `name=path` adds a recorded draft that has no fixture). `--html OUT` writes a blind page: each app's
baseline and current theme as swatches and a type specimen, in random order, the answer key folded away.
"""

import html
import json
import random
import sys
from datetime import date
from pathlib import Path

from src.orchestrator.drafting.themes import distinctness, theme_measures
from src.orchestrator.frontend.app.plan import pairing_theme

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
REQUIREMENTS = FIXTURES / "themes" / "requirements"
BASELINE = FIXTURES / "themes" / "baseline.json"


def drawn(spec: dict) -> dict:
    """The theme as the app draws it: the leading look's font pairing written into its typography."""
    theme = pairing_theme(spec.get("theme") or {}, spec.get("app") or {})
    return {key: theme[key] for key in ("colorScheme", "colors", "typography", "radius", "density") if key in theme}


def recorded(name: str) -> Path | None:
    for folder in (f"theme-{name}", f"domain-{name}-v10"):
        path = FIXTURES / "drafts" / folder / "frontend-spec.json"
        if path.exists():
            return path
    return None


def themes(extra: dict[str, Path] | None = None) -> dict[str, dict]:
    out = {}
    for requirement in sorted(REQUIREMENTS.glob("*.md")):
        path = (extra or {}).get(requirement.stem) or recorded(requirement.stem)
        if path is not None:
            out[requirement.stem] = drawn(json.loads(path.read_text()))
    return out


def measured(found: dict[str, dict]) -> dict:
    return {
        "apps": {name: {"theme": theme, "measures": theme_measures(theme)} for name, theme in found.items()},
        "distinctness": distinctness(found),
    }


def summary(result: dict) -> dict:
    apps = result["apps"].values()
    return {
        "apps": len(result["apps"]),
        "readable": sum(1 for app in apps if app["measures"]["readable"]),
        "withCliches": sum(1 for app in apps if app["measures"]["cliches"]),
        "withGreyNeutrals": sum(1 for app in apps if app["measures"]["greyNeutrals"]),
        "meanHueGap": result["distinctness"]["meanHueGap"],
        "sharedFonts": result["distinctness"]["sharedFonts"],
    }


def _swatches(theme: dict) -> str:
    colors = theme.get("colors") or {}
    cells = "".join(
        f'<div class="sw" style="background:{html.escape(colors.get(k, "#fff"))}"><span>{k}</span></div>'
        for k in ("primary", "accent", "secondary", "muted", "background", "foreground")
    )
    return f'<div class="sws">{cells}</div>'


def _specimen(name: str, theme: dict) -> str:
    colors, type_ = theme.get("colors") or {}, theme.get("typography") or {}
    heading, body = type_.get("headingFont", "Inter"), type_.get("bodyFont", "Inter")
    radius = {"none": "0", "sm": "4px", "md": "8px", "lg": "14px", "full": "999px"}.get(theme.get("radius") or "md")
    style = (
        f"background:{colors.get('background')};color:{colors.get('foreground')};"
        f"--p:{colors.get('primary')};--m:{colors.get('muted')};--r:{radius}"
    )
    return (
        f'<div class="card" style="{html.escape(style)}">'
        f"<h3 style=\"font-family:'{html.escape(heading)}'\">{html.escape(name.title())}: today's picks</h3>"
        f"<p style=\"font-family:'{html.escape(body)}'\">A short paragraph set in the body face, as a record's "
        f"description reads in the app. 1,240 items · 4.8 rating · updated 2 min ago.</p>"
        f'<div class="row" style="font-family:\'{html.escape(body)}\'"><button>Primary action</button>'
        f'<span class="chip">Muted chip</span></div>'
        f"<small style=\"font-family:'{html.escape(body)}'\">{html.escape(heading)} / {html.escape(body)}</small></div>"
    )


def blind_page(before: dict, after: dict, seed: int) -> str:
    rng = random.Random(seed)
    names = [name for name in after if name in before]
    families = sorted({f for t in [*before.values(), *after.values()] for f in (t.get("typography") or {}).values()
                       if isinstance(f, str)})  # fmt: skip
    fonts = "&".join("family=" + f.replace(" ", "+") + ":wght@400;600;700" for f in families)
    rows, key = [], []
    for name in names:
        pair = [("baseline", before[name]), ("designed", after[name])]
        rng.shuffle(pair)
        key.append(f"<li>{html.escape(name)}: A = {pair[0][0]}, B = {pair[1][0]}</li>")
        sides = "".join(
            f'<div class="side"><h4>{label}</h4>{_swatches(theme)}{_specimen(name, theme)}'
            f'<label><input type="radio" name="{html.escape(name)}" value="{label}"> I prefer {label}</label></div>'
            for label, (_, theme) in zip("AB", pair, strict=True)
        )
        rows.append(f'<section><h2>{html.escape(name)}</h2><div class="pair">{sides}</div></section>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Theme blind test</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{fonts}&display=swap">
<style>
:root{{--bg:#f6f5f2;--fg:#1d1c1a;--line:#d9d6cf}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;padding:24px max(16px,4vw)}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;text-transform:capitalize;margin:28px 0 10px}}
.pair{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.side{{border:1px solid var(--line);border-radius:10px;padding:12px;background:#fff;min-width:0}}
.side h4{{margin:0 0 8px}} .sws{{display:grid;grid-template-columns:repeat(6,1fr);gap:4px;margin-bottom:10px}}
.sw{{height:44px;border-radius:6px;border:1px solid #0001;display:flex;align-items:end}}
.sw span{{font-size:10px;background:#fffc;padding:0 3px;border-radius:3px;margin:2px}}
.card{{padding:18px;border-radius:var(--r);border:1px solid #0001;margin-bottom:10px}}
.card h3{{margin:0 0 6px;font-size:24px}} .card p{{margin:0 0 12px}}
.row{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}}
.card button{{background:var(--p);color:#fff;border:0;border-radius:var(--r);padding:8px 14px;font:inherit}}
.chip{{background:var(--m);padding:4px 10px;border-radius:var(--r)}} small{{opacity:.6}}
details{{margin-top:32px}}
</style></head><body>
<h1>Which theme would you ship?</h1><p>For each app: two themes in random order. Pick one, then open the key.</p>
{"".join(rows)}
<details><summary>Answer key</summary><ul>{"".join(key)}</ul></details>
</body></html>
"""


def main(args: list[str]) -> int:
    extra = {a.split("=", 1)[0]: Path(a.split("=", 1)[1]) for a in args if "=" in a}
    if "--baseline" in args:
        result = measured(themes(extra))
        result = {"taken": date.today().isoformat(), **result, "summary": summary(result)}
        BASELINE.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(result["summary"], indent=2))
        return 0
    baseline = json.loads(BASELINE.read_text())
    current = measured(themes(extra))
    for name, app in current["apps"].items():
        before = (baseline["apps"].get(name) or {}).get("measures") or {}
        now = app["measures"]
        print(
            f"{name:10} {before.get('primary', '-'):8} → {now['primary']:8}  "
            f"{'/'.join(before.get('fonts') or ['-'])} → {'/'.join(now['fonts'])}  "
            f"clichés {before.get('cliches', [])} → {now['cliches']}  grey {before.get('greyNeutrals', [])} → "
            f"{now['greyNeutrals']}  readable {before.get('readable')} → {now['readable']}"
        )
    print(json.dumps({"baseline": baseline["summary"], "current": summary(current)}, indent=2))
    if "--html" in args:
        out = Path(args[args.index("--html") + 1])
        before = {name: app["theme"] for name, app in baseline["apps"].items()}
        out.write_text(blind_page(before, {n: a["theme"] for n, a in current["apps"].items()}, seed=len(before)))
        print(f"blind page: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
