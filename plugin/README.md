# Sandburg – Claude Code plugin

Connects Claude Code to a running Sandburg (the Docker image from this repository,
e.g. on RunPod, reachable via Tailscale). The plugin connects all of the Sandburg's MCP servers
(Blender, FreeCAD, KiCad, build123d, Inkscape, ComfyUI, Browser, Voice), ships a
skill that explains the folders and workflows on the Sandburg to Claude, and the
`sandburg` command for uploading and downloading files.

## Installation

```bash
claude plugin install sandburg --marketplace <github-user>/sandburg
```

Or in a running Claude Code session: `/plugin install sandburg --marketplace <github-user>/sandburg`.

When enabling the plugin, Claude Code asks for the Sandburg's address (default `sandburg`) and
the token from `/workspace/.sandburg-token`. The token is stored in the system
keychain. A session-start hook also writes address and token to
`~/.config/sandburg/config` (readable only by you), because the `sandburg` command could
not reach them otherwise.

Both values can be changed later under `/plugin` → **Installed** tab → *sandburg* →
**Configure options**.

## The `sandburg` command

```bash
sandburg status                      # check reachability and services
sandburg ls freecad                  # list a folder on the Sandburg
sandburg get freecad/part.stl        # download a file (folders arrive as .zip)
sandburg put drawing.step freecad/   # upload a file
```

Privacy: the plugin only talks to your own Sandburg. It sends no data to
third parties.
