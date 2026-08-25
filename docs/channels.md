# External channels

External channels let a named Kiro Bot receive work from another system while
keeping the source conversation attached. Every accepted provider event passes
through the same Engine as browser and CLI turns, so governance, quotas,
permissions, persistence and cancellation still apply.

## Safety and delivery model

- Signing and reply secrets are read from environment variables at request or
  delivery time. Only environment-variable names are stored.
- Slack signatures include the untouched body and timestamp. Requests older
  than five minutes are rejected.
- GitHub uses the `X-Hub-Signature-256` HMAC over the untouched body.
- WhatsApp uses Meta's GET verification-token challenge and validates every
  notification with `X-Hub-Signature-256` using the Meta app secret.
- Email and generic webhooks use `X-Kiro-Timestamp` plus an HMAC over
  `<timestamp>.<raw body>` and the same five-minute replay window.
- Provider delivery IDs are unique per binding, so webhook retries do not
  create another bot request.
- Optional allowed-source and allowed-sender lists are exact matches. Use Slack
  channel/user IDs, a GitHub `owner/repository`, or email addresses.
- Previous requests and retained bot replies from the same source thread are
  included up to a bounded message and character budget. Raw provider payloads
  are not stored.
- Completed user/assistant exchanges are also appended to the named bot's
  shared-memory ledger. A bounded relevance-and-recency bundle from other
  surfaces can be supplied for continuity; the current source thread is
  excluded because its authoritative history is already present.
- Each external turn uses a fresh, non-persisted Kiro ACP session with the
  selected bot's configuration. Only the bounded source-thread history and
  explicitly retrieved shared evidence are supplied, preventing unrelated
  remote threads from inheriting an entire ACP transcript.
- Retrieved cross-surface text is marked as historical, potentially untrusted
  evidence rather than instructions. Raw provider payloads, configured secret
  values, tool payloads and permission decisions are not copied into shared
  memory; user and assistant text is retained as written.
- Slack, GitHub and WhatsApp replies are delivered only through fixed official
  provider API hosts. Payloads cannot choose an arbitrary callback URL.

## Create a connection

Run the daemon with the relevant secret variables, open the **Channels** panel,
and select **Add**. For example:

```bash
export KIRO_SLACK_SIGNING_SECRET='replace-with-your-signing-secret'
export KIRO_SLACK_BOT_TOKEN='replace-with-your-bot-token'
uv run kiro-bot serve
```

Enter `KIRO_SLACK_SIGNING_SECRET` and `KIRO_SLACK_BOT_TOKEN` in the form—not the
secret values themselves. The resulting request URL has one of these forms:

```text
https://your-host/hooks/slack/<connection-id>
https://your-host/hooks/github/<connection-id>
https://your-host/hooks/whatsapp/<connection-id>
https://your-host/hooks/email/<connection-id>
https://your-host/hooks/webhook/<connection-id>
```

The server still binds to loopback by default. Put it behind an authenticated,
TLS-terminating ingress before accepting internet traffic. Do not expose the
local daemon directly.

For local testing, run the separate hooks-only relay in a second terminal:

```bash
uv run kiro-bot serve-hooks
```

It listens on `127.0.0.1:8766`, forwards only authenticated `/hooks/*` requests
to the control room on port 8765, caps request/response sizes, and returns 404
for `/app`, `/api`, WebSocket and every other path. Point an HTTPS tunnel at
port 8766, never at the control-room port.

## Slack

Create a Slack app, set its Events API request URL to the generated Slack URL,
and subscribe to `app_mention`. A signed `url_verification` challenge is handled
automatically. Direct `message` events are ignored unless their text contains
the configured invocation phrase. Bot-authored messages are always ignored to
prevent reply loops.

Set the optional outbound token environment variable to enable replies through
`chat.postMessage`; replies use the originating channel and thread timestamp.

## GitHub

Configure a repository or organization webhook with a strong secret and send
`issue_comment`, `issues`, or `pull_request_review_comment` events. The harness
accepts created/edited human messages containing the configured invocation
phrase and ignores bot accounts. The GitHub delivery ID provides deduplication.

Set an outbound token environment variable with permission to create issue
comments to deliver the bot's response back to the issue or pull-request
conversation. This channel does not push code or merge anything.

## WhatsApp

Create a **WhatsApp** channel and configure three separate environment
variables:

```bash
export KIRO_WHATSAPP_APP_SECRET='replace-with-the-meta-app-secret'
export KIRO_WHATSAPP_VERIFY_TOKEN='choose-a-long-random-verification-token'
export KIRO_WHATSAPP_ACCESS_TOKEN='replace-with-the-cloud-api-access-token'
```

Enter those variable names into the signing-secret, verification-token and
reply-token fields respectively. In the Meta App Dashboard, set the callback to
the generated `/hooks/whatsapp/<connection-id>` URL, enter the same verification
token value, and subscribe the WhatsApp Business Account to `messages`.

The GET verification request returns Meta's challenge only when the configured
token matches. POST notifications are separately authenticated using the app
secret. These are deliberately different credentials.

Inbound text, interactive button/list replies, button messages and captioned
image/video/document messages are normalized. Delivery/status notifications,
unsupported media-only messages and malformed payloads are acknowledged but do
not invoke Kiro. Each business phone-number ID and sender number forms a stable
source thread; the WhatsApp message ID supplies deduplication.

When the access-token environment variable is configured, the response is sent
through Meta's fixed Graph API host to the originating sender and references the
incoming message. Long answers are divided into bounded text messages. Override
the Graph API version when necessary with, for example:

```bash
export KIRO_META_GRAPH_API_VERSION='v25.0'
```

This adapter replies to inbound conversations. It does not implement proactive
template campaigns, contact management or media downloads.

## Email gateway

The email route accepts a normalized, signed JSON message from a trusted mail
gateway:

```json
{
  "message_id": "provider-message-id",
  "thread_id": "stable-thread-id",
  "in_reply_to": "optional-parent-message-id",
  "from": "sender@example.com",
  "to": ["kiro@example.com"],
  "subject": "Investigate the failed build",
  "text": "Please inspect the attached failure context."
}
```

Native Gmail push is intentionally not claimed here. Gmail Pub/Sub
notifications contain a mailbox address and history ID; a separate OAuth
synchronizer must retrieve the corresponding messages before normalizing them
into this contract. Until that connector is added, use a mail gateway capable
of posting the complete signed message.

## Generic signed webhook

The generic contract is:

```json
{
  "delivery_id": "unique-event-id",
  "thread_id": "ticket-184",
  "sender": "arin",
  "source": "internal-support",
  "text": "Investigate why this workflow failed.",
  "context": {"ticket": 184, "priority": "P2"}
}
```

Given raw body bytes `BODY`, Unix timestamp `STAMP`, and signing secret
`SECRET`, send:

```text
X-Kiro-Timestamp: STAMP
X-Kiro-Signature-256: sha256=HMAC_SHA256(SECRET, STAMP + "." + BODY)
```

The event response is acknowledged immediately. Its durable processing status,
bot run ID and retained response are available through `/api/channel-events`.
