# Run Ari locally or remotely

Ari's macOS app is the simplest way to run the product. It starts the service on
your Mac and stores its data locally. Keep that Mac online for schedules and
incoming channel events. For phone or tablet access, use a private Tailscale
connection; see [desktop-app.md](desktop-app.md).

The service can also run on a server you control. Remote hosting requires the
selected engine CLIs, their own account sign-ins, persistent storage, and a
protected API. The stock container does not install or sign in to Kiro,
OpenCode, or Codex for you.

## Fly.io

The repository includes a Fly configuration and helper script. Install and
authenticate the [Fly CLI](https://fly.io/docs/flyctl/), then run:

```bash
./scripts/deploy-fly.sh
```

The script creates the `kyn` app and `kyn_data` volume when needed, sets a
`KYN_ACCESS_TOKEN` if one is not already configured, and deploys the service.
The script prints the generated token; save it securely. The web app accepts it
in the session-scoped URL below or as a bearer token for API clients:

```text
https://kyn.fly.dev/app/?token=<your-token>
```

Before sending agent work, install the ACP engines you plan to use on the host,
sign in to each engine using its own instructions, and configure any MCP/channel
secrets for that service. The default image does not bundle those CLIs. Keep the
Fly volume mounted at `/data` so Ari's SQLite state and workspaces persist.

The API supports `KYN_ALLOWED_ORIGINS` for browser origin checks. Keep the
access token private, use HTTPS, and review the network path before making the
service available to other people. Channel webhooks use their provider
signatures; they are not authenticated by the Ari API bearer token.

## Vercel

Vercel serves the marketing pages from the React app. The default build shows
the landing and product engineering pages. It does not provide a hosted Ari
service or agent engines by itself.

For a split setup, point the Vercel UI at a separately protected Ari service
with these build-time variables:

| Variable | Purpose |
| --- | --- |
| `VITE_KYN_API_URL` | Base URL of the Ari service |
| `VITE_KYN_ACCESS_TOKEN` | Bearer token for that service |

Add the Vercel domain to `KYN_ALLOWED_ORIGINS` on the service and rebuild the
Vercel site after changing its variables. The hosting project retains the
historical `KYN` variable names for compatibility; the product is Ari.

## Local development

```bash
npm --prefix web-ui install
npm --prefix web-ui run build
uv sync --extra server --extra dev
uv run ari serve
```

Open `http://127.0.0.1:8765/`. The service binds to loopback by default. The
CLI refuses unauthenticated non-loopback binding; configure `KYN_ACCESS_TOKEN`
before serving on a network interface.

## Environment reference

See [.env.example](../.env.example) for supported environment variables.
