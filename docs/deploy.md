# Always-on hosting

KYN is local-first: the full product is a long-running Python daemon with SQLite,
WebSockets, and `kiro-cli` on the host. You can still run it **always on** in the
cloud with a small Fly.io deployment, and keep a fast marketing site on Vercel.

## Architecture

```text
Vercel (optional)          Fly.io (always on)
landing + UI SPA  ----API-->  kyn serve + SQLite volume
                              + built React UI at /app/
```

| Surface | URL | What runs |
| --- | --- | --- |
| **Full product (recommended)** | `https://<your-app>.fly.dev/` | UI + API + data on Fly |
| **Marketing only** | `https://<project>.vercel.app` | Static landing; install instructions |
| **Split** | Vercel UI + Fly API | Set `VITE_KYN_API_URL` on Vercel |

Agent work still requires **`kiro-cli`** on the machine that runs the daemon.
The stock Docker image does not include it. Install it on a custom image, or use
Fly for the control plane and keep agents on your laptop.

## 1. Fly.io — full KYN (always on)

Prerequisites: [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/), a Fly account.

```bash
# From the repo root
fly auth login

# Create app + volume (pick your own app name if "kyn" is taken)
fly apps create kyn
fly volumes create kyn_data --region iad --size 1

# Required: protect the public API
fly secrets set KYN_ACCESS_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Deploy
fly deploy
```

Open:

```text
https://<your-app>.fly.dev/app/?token=<your-KYN_ACCESS_TOKEN>
```

The `token` query param is saved in the browser session and used for API and
WebSocket calls. You can also send `Authorization: Bearer <token>` from scripts.

Create a bot (cwd must exist inside the container — use `/app` or a mounted path):

```bash
TOKEN=<your-token>
fly ssh console -C "uv run kyn bot create builder --cwd /app"
```

For real agent runs, install and sign in to `kiro-cli` on the Fly machine (custom
Docker layer or `fly ssh console` setup). Without it, the UI and schedules work;
ACP turns fail with “kiro-cli is not installed”.

### Health and persistence

- Health: `GET /api/health` (no auth)
- Data: SQLite and workspaces under `/data` (Fly volume `kyn_data`)
- Machine stays up: `min_machines_running = 1` in `fly.toml`

## 2. Vercel — marketing site (always on)

Connect the GitHub repo in the Vercel dashboard. Root `vercel.json` builds the
static SPA from `web-ui/`.

**Default:** landing + engineering only; “Start with a bot” scrolls to local install.

**Connected console (UI on Vercel, API on Fly):** in Vercel → Settings → Environment Variables:

| Variable | Example |
| --- | --- |
| `VITE_KYN_API_URL` | `https://kyn.fly.dev` |
| `VITE_KYN_ACCESS_TOKEN` | same as `KYN_ACCESS_TOKEN` on Fly |

On Fly, also set:

```bash
fly secrets set KYN_ALLOWED_ORIGINS="https://your-project.vercel.app"
```

Redeploy Vercel after changing env vars (they are baked at build time).

## 3. Local development (unchanged)

```bash
npm --prefix web-ui install && npm --prefix web-ui run build
uv sync --extra server --extra dev
uv run kyn serve
```

Open `http://127.0.0.1:8765/`.

## Security notes

- Never expose `kyn serve` on `0.0.0.0` without `KYN_ACCESS_TOKEN`.
- Channel webhooks (`/hooks/*`) keep their own provider signatures; they are not
  gated by `KYN_ACCESS_TOKEN`.
- Do not commit `.env` or Fly secrets.

## Environment reference

See [.env.example](../.env.example) for all variables.
