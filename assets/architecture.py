"""Generates the architecture diagram in the README: architecture.svg and
architecture-dark.svg next to this script.

    python3 assets/architecture.py

A new service goes into SERVICES (five per row; a third row needs more height).
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent

THEMES = {
    "light": dict(
        bg="#FBF6EE", panel="#FFFFFF", stroke="#E7D9C6", text="#3D2416", muted="#86695A",
        orange="#D9772E", teal="#1A8FA0", ochre="#B98A2E",
        orange_tint="#FBEADB", teal_tint="#E1F1F3", band="#1A8FA0", band_op="0.08", card="#FFFDF9",
    ),
    "dark": dict(
        bg="#17110E", panel="#211915", stroke="#3B2E26", text="#FCE6BF", muted="#B39A84",
        orange="#E8873F", teal="#33AFC0", ochre="#D3A548",
        orange_tint="#3A2516", teal_tint="#15323A", band="#33AFC0", band_op="0.10", card="#271E19",
    ),
}

SANS = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

W, H = 1200, 700
LEFT = (24, 30, 300, 646)
BAND = (344, 30, 66, 646)
POD = (430, 30, 746, 646)
BAND_X = BAND[0] + BAND[2] / 2

SERVICES = [
    # route, name, line 1, line 2, category, optional
    ("blender", "Blender", "GUI on Xvfb", "Cycles on the GPU", "orange", False),
    ("freecad", "FreeCAD", "GUI on Xvfb", "CAD, FEM, STEP", "orange", False),
    ("build123d", "build123d", "CAD as Python", "STEP, STL, DXF", "orange", False),
    ("kicad", "KiCad", "kicad-cli + pcbnew", "ERC, DRC, Gerber", "teal", False),
    ("ngspice", "ngspice", "SPICEBridge", "AC, transient, DC", "teal", False),
    ("openmodelica", "OpenModelica", "omc, headless", "Modelica + MSL", "teal", False),
    ("inkscape", "Inkscape", "+ potrace", "SVG, DXF, PDF", "ochre", False),
    ("comfyui", "ComfyUI", "image generation", "3D optional", "ochre", False),
    ("browser", "Browser", "Chromium", "Playwright", "ochre", False),
    ("voice", "Voice", "Kokoro + Whisper", "optional", "ochre", True),
]

PORTS = [
    # y center, port, name, detail, protocol, client
    (509, ":8090", "dufs file server", "/workspace/projects over HTTP and WebDAV, on the volume", "HTTP"),
    (569, ":6080", "noVNC desktop", "watch Blender, FreeCAD and the browser, step in", "VNC"),
    (629, ":8188", "ComfyUI web UI", "build and run workflows by hand", "HTTP"),
]


def text(x, y, s, size, fill, weight=400, family=SANS, anchor="start", extra=""):
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def rect(x, y, w, h, fill, stroke=None, rx=10, extra=""):
    s = f' stroke="{stroke}" stroke-width="1.5"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{s}{extra}/>'


def arrow(x1, y, x2, color, marker, label, t):
    pill_w = 12 + 7.2 * len(label)
    return "\n".join([
        f'<line x1="{x1}" y1="{y}" x2="{x2 - 2}" y2="{y}" stroke="{color}" stroke-width="2" '
        f'marker-end="url(#{marker})"/>',
        rect(BAND_X - pill_w / 2, y - 10, pill_w, 20, t["panel"], color, rx=10),
        text(BAND_X, y + 4, label, 11, color, 600, MONO, "middle"),
    ])


def build(t):
    o = []
    o.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-labelledby="title desc">'
    )
    o.append("<title id=\"title\">Sandburg architecture</title>")
    o.append(
        '<desc id="desc">Claude Code with the sandburg plugin on your machine connects through '
        "Tailscale to the GPU pod. There, mcp-proxy on port 9090 routes /service/mcp with a bearer "
        "token to the MCP servers for Blender, FreeCAD, build123d, KiCad, ngspice, OpenModelica, "
        "Inkscape, ComfyUI, the browser and voice. The tailnet also reaches the file server on "
        "port 8090, the noVNC desktop on 6080 and the ComfyUI web UI on 8188.</desc>"
    )
    o.append("<defs>")
    for name, color in (("a-teal", t["teal"]), ("a-muted", t["muted"])):
        o.append(
            f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" '
            f'fill="{color}"/></marker>'
        )
    o.append("</defs>")
    o.append(rect(0, 0, W, H, t["bg"], rx=18))

    # Panels
    o.append(rect(*LEFT, t["panel"], t["stroke"], rx=14))
    o.append(rect(*POD, t["panel"], t["stroke"], rx=14))
    o.append(text(44, 62, "YOUR MACHINE", 12, t["muted"], 700, extra=' letter-spacing="1.5"'))
    o.append(text(450, 62, "GPU POD", 12, t["muted"], 700, extra=' letter-spacing="1.5"'))
    o.append(text(1156, 62, "this Docker image on RunPod or any host with an NVIDIA GPU", 12,
                  t["muted"], anchor="end"))

    # Tailscale band
    bx, by, bw, bh = BAND
    o.append(rect(bx, by, bw, bh, t["band"], rx=12,
                  extra=f' fill-opacity="{t["band_op"]}" stroke="{t["teal"]}" stroke-opacity="0.5" '
                        f'stroke-width="1.5" stroke-dasharray="5 5"'))
    cy = 380
    o.append(text(BAND_X, cy, "TAILSCALE  ·  YOUR TAILNET", 12, t["teal"], 700, anchor="middle",
                  extra=f' letter-spacing="1.5" transform="rotate(-90 {BAND_X} {cy})"'))

    # Claude Code card
    o.append(rect(44, 84, 260, 178, t["card"], t["stroke"], rx=12))
    o.append(text(64, 118, "Claude Code", 20, t["text"], 700))
    o.append(text(64, 140, "+ plugin “sandburg”", 13, t["muted"]))
    for i, chip in enumerate(("MCP servers for every service", "skill: folders and workflows",
                              "sandburg command: files")):
        y = 156 + i * 32
        o.append(rect(64, y, 220, 26, t["orange_tint"], rx=13))
        o.append(text(78, y + 17, chip, 12.5, t["text"], 500))

    # Claude fetches files itself
    o.append(f'<line x1="174" y1="262" x2="174" y2="482" stroke="{t["muted"]}" stroke-width="1.5" '
             f'stroke-dasharray="4 5" marker-end="url(#a-muted)"/>')
    o.append(text(186, 366, "fetches and uploads", 12, t["muted"]))
    o.append(text(186, 383, "files on its own", 12, t["muted"]))

    # Local clients
    o.append(rect(44, 484, 260, 50, t["card"], t["stroke"], rx=12))
    o.append(text(64, 505, "sandburg command", 15, t["text"], 700))
    o.append(text(64, 523, "or Finder, Explorer, curl", 12, t["muted"]))
    o.append(rect(44, 544, 260, 110, t["card"], t["stroke"], rx=12))
    o.append(text(64, 594, "Your web browser", 15, t["text"], 700))
    o.append(text(64, 613, "desktop and ComfyUI", 12, t["muted"]))

    # mcp-proxy
    o.append(rect(450, 84, 706, 56, t["orange_tint"], t["orange"], rx=10))
    o.append(text(470, 110, "mcp-proxy", 17, t["text"], 700))
    o.append(text(560, 110, ":9090", 15, t["orange"], 700, MONO))
    o.append(text(470, 129, "one HTTP endpoint with a bearer token, /<service>/mcp → stdio MCP server",
                  12.5, t["muted"]))

    # Service cards
    gap, cols, ch = 12, 5, 124
    cw = (706 - gap * (cols - 1)) / cols
    for i, (route, name, l1, l2, cat, optional) in enumerate(SERVICES):
        x = 450 + (i % cols) * (cw + gap)
        y = 158 + (i // cols) * (ch + gap)
        color = t[cat]
        dash = ' stroke-dasharray="5 4"' if optional else ""
        o.append(rect(x, y, cw, ch, t["card"], rx=10,
                      extra=f' stroke="{t["stroke"]}" stroke-width="1.5"{dash}'))
        o.append(f'<path d="M{x + 10} {y} H{x + cw - 10}" stroke="{color}" stroke-width="4" '
                 f'stroke-linecap="round"/>')
        o.append(text(x + 14, y + 30, f"/{route}", 12, color, 600, MONO))
        o.append(text(x + 14, y + 58, name, 16, t["text"], 700))
        o.append(text(x + 14, y + 82, l1, 12, t["muted"]))
        o.append(text(x + 14, y + 100, l2, 12, t["muted"],
                      extra=' font-style="italic"' if l2 in ("optional", "3D optional") else ""))

    # Legend
    ly = 445
    for lx, label, cat in ((450, "3D and CAD", "orange"), (560, "Electronics and simulation", "teal"),
                           (750, "2D, images, web, speech", "ochre")):
        o.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{t[cat]}"/>')
        o.append(text(lx + 16, ly, label, 12, t["muted"]))
    lx = 930
    o.append(rect(lx, ly - 10, 18, 12, "none", rx=3,
                  extra=f' stroke="{t["muted"]}" stroke-width="1.2" stroke-dasharray="3 2"'))
    o.append(text(lx + 26, ly, "off by default", 12, t["muted"]))

    # Ports
    o.append(text(450, 474, "ALSO IN THE TAILNET", 11, t["muted"], 700, extra=' letter-spacing="1.5"'))
    for yc, port, name, detail, _ in PORTS:
        o.append(rect(450, yc - 25, 706, 50, t["teal_tint"], rx=10))
        o.append(text(470, yc + 5, port, 15, t["teal"], 700, MONO))
        o.append(text(536, yc + 5, name, 15, t["text"], 700))
        o.append(text(716, yc + 5, detail, 12.5, t["muted"]))

    # Connections across the tailnet
    o.append(arrow(304, 112, 450, t["teal"], "a-teal", "MCP", t))
    for yc, _, _, _, proto in PORTS:
        o.append(arrow(304, yc, 450, t["muted"], "a-muted", proto, t))

    o.append("</svg>")
    return "\n".join(o) + "\n"


for theme, suffix in (("light", ""), ("dark", "-dark")):
    (OUT / f"architecture{suffix}.svg").write_text(build(THEMES[theme]), encoding="utf-8")
