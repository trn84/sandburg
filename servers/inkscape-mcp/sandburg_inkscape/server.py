"""MCP server for Inkscape and potrace.

Tools:
  convert        Export SVG/PDF/EPS/PNG/DXF/EMF/WMF (text to paths, drawing area …)
  preview        Return a file as a PNG image to the client (for visual checks)
  info           List size, viewBox and objects with bounding boxes
  run_actions    Run arbitrary Inkscape actions (tool for advanced use)
  trace_bitmap   Convert a raster image to SVG paths via potrace (e.g. a logo for a laser cutter)

Relative paths are resolved against SANDBURG_PROJECTS (default: /workspace/projects).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from defusedxml import ElementTree
from mcp.server.mcpserver import Image, MCPServer
from PIL import Image as PILImage

PROJECTS = Path(os.environ.get("SANDBURG_PROJECTS", "/workspace/projects"))
INKSCAPE = os.environ.get("INKSCAPE_BIN", "inkscape")
POTRACE = os.environ.get("POTRACE_BIN", "potrace")
TIMEOUT = int(os.environ.get("INKSCAPE_TIMEOUT", "300"))

EXPORT_TYPES = {"svg", "pdf", "eps", "ps", "png", "emf", "wmf", "dxf"}
# DXF R14 ("Desktop Cutting Plotter"), the common format for laser cutters and CAM
DXF_EXTENSION = "org.ekips.output.dxf_outlines"

server = MCPServer(
    name="sandburg-inkscape",
    instructions=(
        "Inkscape on the Sandburg. Files live under /workspace/projects; relative paths "
        "are resolved against it. You can also write SVG directly as text and only use this "
        "server to convert, check and view it as an image. For laser cutters: convert text to "
        "paths with text_to_path and export as DXF or SVG."
    ),
)


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else PROJECTS / p


def _existing(path: str) -> Path:
    p = _resolve(path)
    if not p.is_file():
        raise ValueError(f"file not found: {p}")
    return p


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Inkscape needs no window for exporting; it starts faster without DISPLAY
    env.pop("DISPLAY", None)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{Path(cmd[0]).name} failed with code {proc.returncode}:\n"
            f"{(proc.stderr or proc.stdout).strip()[-3000:]}"
        )
    return proc


def _export_args(
    output: Path,
    dpi: float | None,
    text_to_path: bool,
    area: str,
    plain_svg: bool,
    background: str | None,
) -> list[str]:
    ext = output.suffix.lower().lstrip(".")
    if ext not in EXPORT_TYPES:
        raise ValueError(f"output format .{ext} is not supported ({', '.join(sorted(EXPORT_TYPES))})")
    args = [f"--export-filename={output}", "--export-overwrite"]
    if ext == "dxf":
        args.append(f"--export-extension={DXF_EXTENSION}")
    if dpi:
        args.append(f"--export-dpi={dpi}")
    if text_to_path:
        args.append("--export-text-to-path")
    if area == "drawing":
        args.append("--export-area-drawing")
    if plain_svg and ext == "svg":
        args.append("--export-plain-svg")
    if background:
        args += [f"--export-background={background}", "--export-background-opacity=1"]
    return args


@server.tool()
def convert(
    input: str,
    output: str,
    dpi: float | None = None,
    text_to_path: bool = False,
    area: Literal["page", "drawing"] = "page",
    plain_svg: bool = False,
    background: str | None = None,
) -> dict:
    """Export a file to another format with Inkscape.

    The output format is determined by the extension of `output`: svg, pdf, eps, ps, png,
    emf, wmf or dxf (DXF R14, for laser cutters/CAM). Input can be SVG, PDF, EPS, AI,
    PNG/JPG and more.

    Args:
        input: Input file.
        output: Destination file; folders are created.
        dpi: Resolution for PNG (default 96).
        text_to_path: Convert text to paths (important for laser cutters and other machines).
        area: "page" = whole page, "drawing" = only the drawing, tightly cropped.
        plain_svg: For SVG output, strip Inkscape-specific data.
        background: Background color for PNG, e.g. "#ffffff".
    """
    src = _existing(input)
    dst = _resolve(output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([INKSCAPE, str(src), *_export_args(dst, dpi, text_to_path, area, plain_svg, background)])
    if not dst.is_file():
        raise RuntimeError(f"Inkscape reported success, but {dst} was not created")
    return {"output": str(dst), "bytes": dst.stat().st_size}


@server.tool()
def preview(path: str, dpi: float = 96, max_size: int = 1600, area: Literal["page", "drawing"] = "page") -> Image:
    """Return a file as a PNG image so you can look at the result yourself.

    Args:
        path: SVG, PDF, EPS or image file.
        dpi: Render resolution.
        max_size: Longest edge of the returned image in pixels.
        area: "page" or "drawing" (only the drawn area).
    """
    src = _existing(path)
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "preview.png"
        if src.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            img = PILImage.open(src)
        else:
            _run([INKSCAPE, str(src), *_export_args(png, dpi, False, area, False, "#ffffff")])
            img = PILImage.open(png)
        img = img.convert("RGB")
        img.thumbnail((max_size, max_size))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")


def _svg_header(path: Path) -> dict:
    try:
        root = ElementTree.parse(path).getroot()
    except Exception:  # not an SVG or broken – info() still returns the objects
        return {}
    return {k: root.get(k) for k in ("width", "height", "viewBox") if root.get(k) is not None}


@server.tool()
def info(path: str, limit: int = 200) -> dict:
    """List document size, viewBox and all objects with their bounding box (in px).

    Args:
        path: SVG file (other formats only return the object list).
        limit: Maximum number of listed objects.
    """
    src = _existing(path)
    proc = _run([INKSCAPE, str(src), "--query-all"])
    objects = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) != 5:
            continue
        obj_id, *nums = parts
        try:
            x, y, w, h = (round(float(n), 3) for n in nums)
        except ValueError:
            continue
        objects.append({"id": obj_id, "x": x, "y": y, "width": w, "height": h})
    result = {"path": str(src), "object_count": len(objects), "objects": objects[:limit]}
    if src.suffix.lower() == ".svg":
        result["document"] = _svg_header(src)
    if objects:
        result["drawing_bbox"] = objects[0]  # the first object is the root (whole drawing)
    return result


@server.tool()
def run_actions(input: str, actions: str, output: str | None = None) -> dict:
    """Apply Inkscape actions to a file (for anything convert doesn't cover).

    Example: actions="select-all:all;object-to-path;object-stroke-to-path" with
    output="laser/part-paths.svg". Separate multiple actions with ";". If `output` is set,
    the result is exported there; otherwise only the output of the actions is returned
    (e.g. for query actions). List of all actions: actions="action-list".
    """
    src = _existing(input)
    action_str = actions.strip().rstrip(";")
    if output:
        dst = _resolve(output)
        dst.parent.mkdir(parents=True, exist_ok=True)
        action_str += f";export-filename:{dst};export-overwrite;export-do"
    proc = _run([INKSCAPE, str(src), f"--actions={action_str}"])
    result: dict = {"stdout": proc.stdout.strip()[-20000:]}
    if output:
        result["output"] = str(_resolve(output))
    return result


@server.tool()
def trace_bitmap(
    input: str,
    output: str,
    threshold: float = 0.5,
    invert: bool = False,
    turdsize: int = 2,
    smooth: float = 1.0,
) -> dict:
    """Convert a raster image (PNG/JPG …) into an SVG made of paths with potrace.

    Good for logos, lettering and line drawings, e.g. as a template for laser cutters,
    plotters or PCB artwork. The result is monochrome.

    Args:
        input: Raster image.
        output: Destination SVG.
        threshold: Brightness threshold 0–1; anything darker than the threshold becomes filled.
        invert: Swap light and dark.
        turdsize: Ignore specks up to this size (in pixels).
        smooth: Curve smoothing (0 = angular, 1.3 = very round).
    """
    if not shutil.which(POTRACE):
        raise RuntimeError("potrace is not installed")
    src = _existing(input)
    dst = _resolve(output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.open(src) as img:
        gray = img.convert("L")
    level = max(0, min(255, int(threshold * 255)))

    def to_bit(v: int) -> int:
        dark = v < level
        return 0 if (dark != invert) else 255  # 0 = black = becomes filled

    bitmap = gray.point(to_bit, mode="1")
    with tempfile.TemporaryDirectory() as tmp:
        pbm = Path(tmp) / "input.pbm"
        bitmap.save(pbm)
        _run([POTRACE, str(pbm), "-s", "-o", str(dst), "-t", str(turdsize), "-a", str(smooth)])
    return {"output": str(dst), "bytes": dst.stat().st_size}


def main() -> None:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
