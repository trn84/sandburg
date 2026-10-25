# TODOs

Ideas for future versions of the Sandburg. Nothing here is planned in detail yet; the notes collect what we already know about each idea.

## Self-hosted WireGuard instead of Tailscale

Reach the Sandburg without a Tailscale account, through a WireGuard network you run yourself.

- **The pod has no `/dev/net/tun`** on RunPod and most GPU clouds, so neither kernel WireGuard nor `wireguard-go` works there. The tunnel has to run in userspace, as Tailscale does today (`--tun=userspace-networking` in `start-tailscale.sh`).
- **The pod can't accept incoming connections**, so it has to dial out to a hub with a public IP (a small VPS), and your machine connects to the same hub.
- Options:
  - [Headscale](https://github.com/juanfont/headscale) as a self-hosted Tailscale control server. This needs the least change: `tailscale up --login-server=<url>`, e.g. via a new `TS_LOGIN_SERVER` variable. Keeps MagicDNS, ACLs and ephemeral nodes.
  - Plain WireGuard with [wireproxy](https://github.com/pufferffish/wireproxy): a userspace WireGuard client that can publish selected local ports into the WireGuard network (`[TCPServerTunnel]`). New variables such as `WG_PRIVATE_KEY`, `WG_ADDRESS`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT`.
- **Plus for security:** with wireproxy only explicitly listed ports (9090, 8090, optionally 6080 and 8188) are reachable. Tailscale in userspace mode forwards every local port, including the unauthenticated Blender (9876) and FreeCAD (9875) bridges (see *Security* in the README).
- Document the hub setup (VPS, `wg0.conf`, keys) and the client side. The plugin's `host` then becomes the WireGuard IP of the pod.
- `start-tailscale.sh` and `start-wireguard.sh` should exclude each other; pick one via e.g. `NETWORK=tailscale|headscale|wireguard|none`.

## OpenCode instead of Claude Code

A client variant for [OpenCode](https://opencode.ai), so the Sandburg can be used with other LLMs (OpenAI, Gemini, local models via Ollama/vLLM, etc.).

- The server side stays the same: OpenCode speaks MCP over HTTP and can send the bearer token as a header (`"type": "remote"`, `url`, `headers` in `opencode.json`).
- Things the Claude Code plugin does today that need an equivalent:
  - the MCP server list (`plugin/.claude-plugin/plugin.json`): generate `opencode.json` from it, so the list of services is maintained in one place
  - the address/token configuration (`userConfig`, stored in the keychain): for OpenCode probably environment variables (`{env:SANDBURG_TOKEN}`)
  - the `SessionStart` hook that writes `~/.config/sandburg/config` for the `sandburg` command: document a manual setup or a small `sandburg configure` subcommand instead
  - the skill (`plugin/skills/sandburg/SKILL.md`) that explains folders and workflows: check whether OpenCode loads it as a skill, otherwise ship it as an `AGENTS.md` snippet or OpenCode agent
- **Many tools:** all services together expose a few hundred MCP tools. Smaller or local models handle that poorly. Allow enabling only a subset of services per project, and test which models cope with the Blender/FreeCAD/KiCad tools at all.
- Idea: run the model on the pod's GPU itself (vLLM or Ollama as an optional service, `ENABLE_LLM=1`), so the whole setup works without any cloud LLM. GPU memory has to be shared with ComfyUI, Blender and Voice.

## More cloud providers than RunPod

The image itself is provider-neutral; what is RunPod-specific is mostly the documentation (template fields, secrets, volume at `/workspace`).

- Candidates: [Vast.ai](https://vast.ai), [Lambda](https://lambda.ai), [Paperspace](https://www.paperspace.com), [Hetzner GPU servers](https://www.hetzner.com/dedicated-rootserver/matrix-gpu/), plain VMs on AWS, GCP or Azure with Docker and the NVIDIA Container Toolkit.
- Per provider, check and document:
  - how a container is started from `ghcr.io/<user>/sandburg:latest` (template, CLI, API) and how environment variables and secrets are passed
  - where the persistent volume is mounted; `WORKSPACE` can already be overridden in `common.sh`, but the README and plugin assume `/workspace`
  - container disk size limits (the image is about 18 GB)
  - whether the container receives `SIGTERM` on stop, which the clean Tailscale logout relies on
  - whether `/dev/net/tun` exists (it would allow kernel networking, but userspace mode must keep working)
- On full VMs (Hetzner, AWS, GCP) `docker compose` from the repository is enough. Add a short guide and possibly a cloud-init file that installs Docker, the NVIDIA toolkit and starts the Sandburg.
- Restructure the README: a provider-neutral setup plus one short section (or file under `docs/providers/`) per provider.
- Later maybe a `sandburg up --provider <name>` command that starts and stops pods via the provider APIs, so you only pay while you work.
