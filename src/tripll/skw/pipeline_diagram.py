"""Deterministic pipeline diagram artifacts (JSON enrichment + HTML).

Exports:
    PipelineStep — one node in the compiled run spine.
    build_pipeline_steps — ordered steps with resolved agent model params.
    render_pipeline_html — self-contained HTML diagram string.
    sync_pipeline_artifacts — write ``waves/<slug>.pipeline.{json,html}``.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tripll.skw.agent_config import AgentParams, resolve_agent_params
from tripll.skw.pipeline import PipelineBuilder
from tripll.skw.render import topo_sort
from tripll.skw.resolve_wave import agent_for_role, load_wave_data
from tripll.skw.validate import load_skw_config
from tripll.skw.wave_model import WavePlan

__all__ = [
    "PipelineStep",
    "build_pipeline_steps",
    "build_product_pipeline_steps",
    "render_pipeline_html",
    "render_product_pipeline_html",
    "sync_pipeline_artifacts",
    "sync_product_pipeline_artifact",
]


@dataclass(frozen=True)
class PipelineStep:
    """One node in the pipeline diagram."""

    kind: str
    step_id: str
    title: str
    agent_id: str | None = None
    role: str | None = None
    params: AgentParams | None = None
    review_gate: bool = False


def _params_for(
    *,
    kit_root: Path,
    skw_cfg: dict[str, Any],
    wave_data: dict[str, Any],
    stage: str,
    wave_id: str | None = None,
) -> AgentParams:
    return resolve_agent_params(
        kit_root=kit_root,
        stage=stage,
        wave_data=wave_data,
        wave_id=wave_id,
        skw_cfg=skw_cfg,
    )


def build_pipeline_steps(wave_path: Path, kit_root: Path) -> list[PipelineStep]:
    """Build ordered pipeline steps with resolved model parameters.

    Args:
        wave_path (Path): Active wave markdown file.
        kit_root (Path): Kit root directory.

    Returns:
        list[PipelineStep]: Deterministic step list for diagram export.

    Examples:
        >>> build_pipeline_steps(Path("waves/example-wave-plan.md"), Path("."))  # doctest: +SKIP
        [...]
    """
    wave_path = wave_path.resolve()
    kit_root = kit_root.resolve()
    data = load_wave_data(wave_path)
    skw_cfg = load_skw_config(kit_root)
    plans = WavePlan.from_wave_data(data)
    depends = {plan.id: plan.depends_on for plan in plans}
    order = topo_sort(depends)
    plan_by_id = {plan.id: plan for plan in plans}

    steps: list[PipelineStep] = [
        PipelineStep(kind="validate", step_id="validate", title="Validate wave-file")
    ]

    for wid in order:
        plan = plan_by_id[wid]
        agent_id = agent_for_role(plan.role)
        params = _params_for(
            kit_root=kit_root,
            skw_cfg=skw_cfg,
            wave_data=data,
            stage="run",
            wave_id=wid,
        )
        steps.append(
            PipelineStep(
                kind="wave",
                step_id=wid,
                title=plan.title,
                agent_id=agent_id,
                role=plan.role,
                params=params,
                review_gate=plan.review_gate,
            )
        )
        steps.append(
            PipelineStep(
                kind="verify",
                step_id=f"verify_{wid}",
                title=f"Verify {wid}",
            )
        )
        steps.append(
            PipelineStep(
                kind="commit",
                step_id=f"commit_{wid}",
                title=f"Commit {wid}",
            )
        )
        if plan.review_gate:
            steps.append(
                PipelineStep(
                    kind="review_gate",
                    step_id=f"review_gate_{wid}",
                    title=f"Review gate {wid}",
                    review_gate=True,
                )
            )

    review_params = _params_for(
        kit_root=kit_root,
        skw_cfg=skw_cfg,
        wave_data=data,
        stage="review",
    )
    generate_params = _params_for(
        kit_root=kit_root,
        skw_cfg=skw_cfg,
        wave_data=data,
        stage="generate",
    )
    steps.extend(
        [
            PipelineStep(
                kind="review",
                step_id="review",
                title="Branch review",
                agent_id=review_params.agent_id,
                params=review_params,
            ),
            PipelineStep(
                kind="cross_check",
                step_id="cross_check",
                title="Cross-check verdict",
            ),
            PipelineStep(
                kind="generate",
                step_id="generate",
                title="Post-review plan (on fail)",
                agent_id=generate_params.agent_id,
                params=generate_params,
            ),
        ]
    )
    return steps


def _kind_class(kind: str) -> str:
    return f"node node-{kind.replace('_', '-')}"


def _param_rows(params: AgentParams | None) -> list[tuple[str, str]]:
    if params is None:
        return []
    rows: list[tuple[str, str]] = [("model", params.model), ("bin", params.bin)]
    if params.max_tokens is not None:
        rows.append(("max_tokens", str(params.max_tokens)))
    if params.temperature is not None:
        rows.append(("temperature", str(params.temperature)))
    if params.thinking:
        rows.append(("thinking", params.thinking))
    if params.extra_args:
        rows.append(("extra_args", " ".join(params.extra_args)))
    return rows


def render_pipeline_html(
    *,
    title: str,
    slug: str,
    branch: str,
    base: str,
    steps: list[PipelineStep],
) -> str:
    """Render a deterministic, self-contained HTML pipeline diagram.

    Args:
        title (str): Plan title.
        slug (str): Plan slug.
        branch (str): Feature branch.
        base (str): Diff base ref.
        steps (list[PipelineStep]): Ordered pipeline steps.

    Returns:
        str: Full HTML document.

    Examples:
        >>> render_pipeline_html(title="T", slug="s", branch="b", base="main", steps=[])  # doctest: +SKIP
        '<!DOCTYPE html>'
    """
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(slug)} — pipeline</title>",
        "<style>",
        "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:24px;background:#faf9f7;color:#1a1a1a}",
        "h1{font-size:1.35rem;margin:0 0 4px}",
        ".meta{color:#555;font-size:.9rem;margin-bottom:20px}",
        ".flow{display:flex;flex-direction:column;gap:10px;max-width:920px}",
        ".node{border:1px solid #d4d0c8;border-radius:10px;padding:12px 14px;background:#fff}",
        ".node-validate,.node-verify,.node-commit,.node-cross-check{background:#f3f2ef}",
        ".node-review,.node-generate{border-color:#7c9cff}",
        ".node-review-gate{border-color:#e6a700;background:#fff9e6}",
        ".node-wave{border-color:#111}",
        ".head{display:flex;justify-content:space-between;gap:12px;align-items:baseline}",
        ".kind{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:#666}",
        ".title{font-weight:600}",
        ".agent{font-size:.85rem;color:#333;margin-top:4px}",
        ".params{margin-top:8px;font-size:.82rem;border-collapse:collapse;width:100%}",
        ".params td{padding:2px 8px 2px 0;vertical-align:top}",
        ".params td:first-child{color:#666;white-space:nowrap}",
        ".arrow{text-align:center;color:#999;font-size:.85rem}",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{html.escape(title)}</h1>",
        f'<p class="meta">slug={html.escape(slug)} · branch={html.escape(branch)} · base={html.escape(base)}</p>',
        '<div class="flow">',
    ]

    for index, step in enumerate(steps):
        if index > 0:
            parts.append('<div class="arrow">↓</div>')
        parts.append(f'<section class="{_kind_class(step.kind)}">')
        parts.append('<div class="head">')
        parts.append(f'<div><div class="kind">{html.escape(step.kind)}</div>')
        parts.append(
            f'<div class="title">{html.escape(step.step_id)} — {html.escape(step.title)}</div></div>'
        )
        parts.append("</div>")
        if step.agent_id:
            role_note = f" · role={step.role}" if step.role else ""
            parts.append(
                f'<div class="agent">agent: {html.escape(step.agent_id)}{html.escape(role_note)}</div>'
            )
        rows = _param_rows(step.params)
        if rows:
            parts.append('<table class="params">')
            for key, val in rows:
                parts.append(f"<tr><td>{html.escape(key)}</td><td>{html.escape(val)}</td></tr>")
            parts.append("</table>")
        if step.review_gate and step.kind == "wave":
            parts.append('<div class="agent">review_gate=true</div>')
        parts.append("</section>")

    parts.extend(["</div>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def build_product_pipeline_steps() -> list[PipelineStep]:
    """Build the tripll product spine for adoption diagrams (W7.2).

    Returns:
        list[PipelineStep]: Plan → RunGraph → lanes → gates → integrate, plus compounding nodes.

    Examples:
        >>> len(build_product_pipeline_steps()) >= 8  # doctest: +SKIP
        True
    """
    return [
        PipelineStep(kind="validate", step_id="plans", title="Wave-plan set"),
        PipelineStep(kind="wave", step_id="rungraph", title="RunGraph compile"),
        PipelineStep(kind="wave", step_id="lanes", title="Lanes & batches"),
        PipelineStep(kind="review_gate", step_id="pre0", title="Pre-0 human gate"),
        PipelineStep(kind="wave", step_id="dispatch", title="Dispatch waves"),
        PipelineStep(kind="verify", step_id="verify", title="Verify & retry"),
        PipelineStep(kind="commit", step_id="integrate", title="Integrate batches"),
        PipelineStep(kind="review", step_id="finding", title="Finding (run failure)"),
        PipelineStep(kind="generate", step_id="propose", title="Propose Rule"),
        PipelineStep(kind="review_gate", step_id="promote", title="Operator promote (R27)"),
        PipelineStep(kind="cross_check", step_id="pack", title="Pack into next brief"),
        PipelineStep(kind="verify", step_id="rules_check", title="make rules-check"),
    ]


def render_product_pipeline_html(*, steps: list[PipelineStep] | None = None) -> str:
    """Render the tripll product pipeline with the compounding loop (W7.2).

    Args:
        steps (list[PipelineStep] | None): Override step list; defaults to
            :func:`build_product_pipeline_steps`.

    Returns:
        str: Self-contained HTML document (no external asset fetch).

    Examples:
        >>> "compounding" in render_product_pipeline_html().lower()  # doctest: +SKIP
        True
    """
    spine = steps if steps is not None else build_product_pipeline_steps()
    main_steps = spine[:7]
    loop_steps = spine[7:]
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>tripll — product pipeline</title>",
        "<style>",
        "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:24px;background:#faf9f7;color:#1a1a1a}",
        "h1{font-size:1.35rem;margin:0 0 4px}",
        ".meta{color:#555;font-size:.9rem;margin-bottom:20px}",
        ".layout{display:grid;grid-template-columns:1fr 320px;gap:24px;max-width:1100px}",
        ".flow{display:flex;flex-direction:column;gap:10px}",
        ".loop{border:1px dashed #7c9cff;border-radius:12px;padding:14px;background:#f8faff}",
        ".loop h2{font-size:.95rem;margin:0 0 10px;color:#334}",
        ".node{border:1px solid #d4d0c8;border-radius:10px;padding:12px 14px;background:#fff}",
        ".node-validate,.node-verify,.node-commit,.node-cross-check{background:#f3f2ef}",
        ".node-review,.node-generate{border-color:#7c9cff}",
        ".node-review-gate{border-color:#e6a700;background:#fff9e6}",
        ".node-wave{border-color:#111}",
        ".head{display:flex;justify-content:space-between;gap:12px;align-items:baseline}",
        ".kind{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:#666}",
        ".title{font-weight:600}",
        ".arrow{text-align:center;color:#999;font-size:.85rem}",
        ".loop-arrow{text-align:center;color:#7c9cff;font-size:.82rem;margin:4px 0}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>tripll product pipeline</h1>",
        '<p class="meta">plan → RunGraph → lanes → gates → integrate · compounding loop (W2–W6)</p>',
        '<div class="layout">',
        '<div class="flow">',
    ]

    for index, step in enumerate(main_steps):
        if index > 0:
            parts.append('<div class="arrow">↓</div>')
        parts.append(f'<section class="{_kind_class(step.kind)}">')
        parts.append('<div class="head">')
        parts.append(f'<div><div class="kind">{html.escape(step.kind)}</div>')
        parts.append(
            f'<div class="title">{html.escape(step.step_id)} — {html.escape(step.title)}</div></div>'
        )
        parts.append("</div></section>")

    parts.extend(
        [
            "</div>",
            '<aside class="loop">',
            "<h2>Compounding loop</h2>",
            '<div class="flow">',
        ]
    )
    for index, step in enumerate(loop_steps):
        if index > 0:
            parts.append('<div class="loop-arrow">↻</div>')
        parts.append(f'<section class="{_kind_class(step.kind)}">')
        parts.append('<div class="head">')
        parts.append(f'<div><div class="kind">{html.escape(step.kind)}</div>')
        parts.append(
            f'<div class="title">{html.escape(step.step_id)} — {html.escape(step.title)}</div></div>'
        )
        parts.append("</div></section>")
    parts.extend(["</div>", "</aside>", "</div>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def sync_product_pipeline_artifact(out_path: Path) -> Path:
    """Write the committed product pipeline HTML (W7.2).

    Args:
        out_path (Path): Destination file (e.g. ``about-tripll/assets/pipeline.html``).

    Returns:
        Path: Written HTML path.

    Examples:
        >>> sync_product_pipeline_artifact(Path("/tmp/pipeline.html"))  # doctest: +SKIP
        PosixPath('/tmp/pipeline.html')
    """
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_product_pipeline_html(), encoding="utf-8")
    return out_path


def _enrich_builder_json(builder: PipelineBuilder, steps: list[PipelineStep]) -> dict[str, Any]:
    payload = builder.to_json()
    params_by_wave = {
        step.step_id: step.params.to_dict()
        for step in steps
        if step.kind == "wave" and step.params is not None
    }
    for state in payload.get("states", []):
        if not isinstance(state, dict):
            continue
        wid = state.get("id")
        if isinstance(wid, str) and wid in params_by_wave:
            state["model"] = params_by_wave[wid]
    pipeline_agents = {
        step.step_id: step.params.to_dict()
        for step in steps
        if step.kind in {"review", "generate"} and step.params is not None
    }
    payload["pipeline_agents"] = pipeline_agents
    return payload


def sync_pipeline_artifacts(wave_path: Path, kit_root: Path) -> tuple[Path, Path]:
    """Write ``waves/<slug>.pipeline.json`` and ``waves/<slug>.pipeline.html``.

    Args:
        wave_path (Path): Active wave markdown file.
        kit_root (Path): Kit root directory.

    Returns:
        tuple[Path, Path]: ``(json_path, html_path)``.

    Examples:
        >>> sync_pipeline_artifacts(Path("waves/example-wave-plan.md"), Path("."))  # doctest: +SKIP
        (Path('waves/example-wave-plan.pipeline.json'), ...)
    """
    wave_path = wave_path.resolve()
    kit_root = kit_root.resolve()
    data = load_wave_data(wave_path)
    builder = PipelineBuilder.from_wave_file(wave_path, kit_root)
    steps = build_pipeline_steps(wave_path, kit_root)
    out_dir = kit_root / "waves"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{builder.slug}.pipeline.json"
    html_path = out_dir / f"{builder.slug}.pipeline.html"
    json_path.write_text(
        json.dumps(_enrich_builder_json(builder, steps), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(
        render_pipeline_html(
            title=str(data.get("title", builder.slug)),
            slug=builder.slug,
            branch=builder.branch,
            base=builder.base,
            steps=steps,
        ),
        encoding="utf-8",
    )
    return json_path, html_path
