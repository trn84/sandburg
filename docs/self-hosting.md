# Running Sandburg yourself

The Sandburg also runs without RunPod and Tailscale, with Docker and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), either on your own machine or on a server you reach through an SSH tunnel. Both use `docker-compose.yml` from this repository.

- [On your own machine](#on-your-own-machine)
- [On a server through an SSH tunnel](#on-a-server-through-an-ssh-tunnel)
- [Switching the plugin](#switching-the-plugin)

## On your own machine

```bash
cp .env.example .env      # leave TS_AUTHKEY empty, set SANDBURG_TOKEN
docker compose pull       # prebuilt image from ghcr.io/trn84/sandburg:latest
docker compose up -d
# MCP:     http://localhost:9090/<service>/mcp
# Files:   http://localhost:8090                 (user sandburg, password = token)
# Desktop: http://localhost:6080/vnc.html
# ComfyUI: http://localhost:8188
```

To build the image yourself instead, run `docker compose up -d --build`. Run `pull` explicitly when you want the GHCR image: if the image is missing locally, `up` builds it instead of pulling it. Set `SANDBURG_IMAGE` in `.env` to use a different image or tag.

`docker compose up` reads `.env` through `env_file`, with or without `-d`. After changing `.env`, run `docker compose up -d` again, which recreates the container. `docker compose restart` keeps the old values. Logs: `docker compose logs -f`.

The ports are only published on `127.0.0.1`, and the volume is the `workspace/` folder next to `docker-compose.yml`.

## On a server through an SSH tunnel

On a GPU server you can reach over SSH, start the container exactly as [on your own machine](#on-your-own-machine), with the repository and `.env` on the server. The ports stay on the server's `127.0.0.1`, and an SSH tunnel forwards them to your machine:

```bash
ssh -N -L 9090:127.0.0.1:9090 -L 8090:127.0.0.1:8090 \
       -L 6080:127.0.0.1:6080 -L 8188:127.0.0.1:8188 user@server
```

Or once in `~/.ssh/config`, then `ssh -N sandburg-server`:

```
Host sandburg-server
    HostName server.example.com
    User user
    LocalForward 9090 127.0.0.1:9090
    LocalForward 8090 127.0.0.1:8090
    LocalForward 6080 127.0.0.1:6080
    LocalForward 8188 127.0.0.1:8188
```

While the tunnel is open, everything is reachable at the same `localhost` addresses as with a local container. Only 9090 (MCP) and 8090 (files) are needed for Claude Code. 6080 and 8188 are for the desktop and the ComfyUI web UI in your browser.

The address in the plugin is therefore `127.0.0.1`, but the token is the **server's**: `SANDBURG_TOKEN` from the `.env` on the server, or `workspace/.sandburg-token` there if you left it empty. The token in a `.env` on your own machine does not apply. With the wrong token, all MCP servers fail with HTTP 401. To read it on the server:

```bash
ssh sandburg-server 'cd sandburg && grep "^SANDBURG_TOKEN=" .env || cat workspace/.sandburg-token'
```

## Switching the plugin

Under `/plugin` → **Installed** → *sandburg* → **Configure options** (or `/plugin configure sandburg@sandburg`), enter:

| | Address | Token |
|---|---|---|
| Pod | its Tailscale name (`TS_HOSTNAME`, default `sandburg`) | the pod's token (`SANDBURG_TOKEN` on RunPod, or `/workspace/.sandburg-token` on the pod) |
| Local container | `127.0.0.1` | `SANDBURG_TOKEN` from your `.env` (or `workspace/.sandburg-token` if you left it empty) |
| Server through an SSH tunnel | `127.0.0.1` | `SANDBURG_TOKEN` from the server's `.env` (or `workspace/.sandburg-token` on the server) |

In the VS Code extension, `/plugin` is not available. There, set the values in a terminal instead, e.g. for the local container (run in the repository, takes the token from `.env`):

```bash
printf '{"host":"127.0.0.1","token":"%s"}' "$(grep '^SANDBURG_TOKEN=' .env | cut -d= -f2-)" |
    claude plugin configure sandburg@sandburg --values-stdin
```

and back to the pod with `{"host":"sandburg","token":"<the pod's token>"}`.

Then start a new Claude Code session. The MCP servers connect with the new values, and the `sandburg` command only picks them up at session start. If you use the same `SANDBURG_TOKEN` everywhere, only the address changes when you switch.
