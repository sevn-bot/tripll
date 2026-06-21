# about-tripll — public help site

A small static site describing tripll, generated from YAML sources + Jinja2 templates.

## Layout

| Path | Role |
|------|------|
| `_sources/*.yaml` | Page content (`title`, `nav_label`, `nav_order`, `summary`, `body` HTML). |
| `_templates/*.j2` | `base.html.j2` (layout) + `generic.html.j2` (content block). |
| `assets/site.css` | Theme. |
| `_standards/coding-standards.md` | Normative coding standards (inherited from sevn.bot). |
| `*.html` | **Generated** — do not edit by hand. |

## Build

```bash
make about-site          # regenerate the HTML from sources
make about-site-check    # CI drift gate: fail if HTML is stale
```

The generator (`scripts/build_about_site.py`) is deterministic — output has no timestamps — so
`--check` reliably detects HTML that has drifted from its source. To add a page, drop a new
`_sources/<slug>.yaml` and run `make about-site`.
