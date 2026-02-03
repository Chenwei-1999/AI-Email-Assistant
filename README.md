# AI Email Assistant (Browser + OpenAI Batch)

Automate unread email handling in Gmail or Outlook Web **without OAuth** by driving a logged-in browser session. The agent sends email content to OpenAI **Batch** to classify and draft replies, applies actions in the web UI, then generates a **Batch-based daily summary** to your own inbox.

This is a demo-style system optimized for low cost via Batch. It is not a production security product.

## What It Does

Actions (per email):
- `ignore`: mark as read (already read when opened)
- `auto_reply`: reply in professor tone
- `important`: do not reply, highlight in summary for you to handle

End of run:
- Sends a **GPT-written daily summary** (including replies that were sent).

## Quick Start

1. Activate your conda environment:

```bash
conda activate openclaw-email
```

2. Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

3. Set your OpenAI API key:

```bash
export OPENAI_API_KEY=...
```

4. Configure `config.yaml`:
- `provider: gmail` or `provider: outlook`
- `gmail.self_email` (or set `EMAIL_ADDRESS` in env)

## Browser Login (Manual, Once)

```bash
python gmail_batch_agent.py --login
```

This opens a real Chromium window and saves a persistent profile in `.gmail_profile/`.
Complete login for Gmail or Outlook once.

## Run

Standard run (submit a batch):

```bash
python gmail_batch_agent.py
```

Wait and apply results in the same run:

```bash
python gmail_batch_agent.py --wait
```

Dry-run (no replies sent, no summary sent):

```bash
python gmail_batch_agent.py --dry-run
```

## Outlook Web (English UI)

Set the provider:

```yaml
provider: outlook
```

Make sure you are already logged in at `outlook.office.com` or `outlook.live.com` in the same browser profile.

## CDP Mode (Reuse Existing Chrome)

If you already have a logged-in Chrome instance exposed by CDP (for OpenClaw, typically `http://127.0.0.1:18800`), set:

```yaml
gmail:
  cdp_url: "http://127.0.0.1:18800"
```

The agent will attach to that browser instead of launching a new one.

## How It Works

1. Collect unread emails from the inbox.
2. Submit a Batch request to classify and draft replies.
3. When Batch completes, open each thread and apply the action.
4. Submit a second Batch request to generate the daily summary.
5. Send the summary to your own inbox.

## Project Layout

- Entry point: `gmail_batch_agent.py`
- Core modules: `app/`
- Config: `config.yaml`
- State + batches: `.state/`

## Config Reference

Key fields in `config.yaml`:
- `provider`: `gmail` or `outlook`
- `gmail.profile_dir`: persistent profile path
- `gmail.cdp_url`: attach to an existing Chrome (optional)
- `gmail.search_query`: Gmail search syntax for unread collection
- `gmail.self_email`: where to send the daily summary
- `openai.model`: model used in Batch
- `openai.completion_window`: Batch window, e.g. `24h`

## Scheduled Run (macOS LaunchAgent, every 24h)

Create `~/Library/LaunchAgents/com.local.ai-email-assistant.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.ai-email-assistant</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/chenweixu/miniconda3/envs/openclaw-email/bin/python</string>
    <string>/Users/chenweixu/Desktop/website/agent/gmail_batch_agent/gmail_batch_agent.py</string>
  </array>
  <key>StartInterval</key>
  <integer>86400</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>OPENAI_API_KEY</key>
    <string>YOUR_KEY</string>
  </dict>
  <key>StandardOutPath</key>
  <string>/tmp/ai-email-assistant.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/ai-email-assistant.err</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.local.ai-email-assistant.plist
```

## Notes and Limits

- The agent opens unread messages, which Gmail/Outlook will mark as read.
- Batch results are not immediate. Use `--wait` if you want same-run replies + summary.
- For best reliability on macOS, keep `headless: false`.
- This demo assumes trusted accounts and does not include advanced safety controls.
