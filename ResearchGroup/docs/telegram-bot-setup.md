# Telegram bot and chat ID setup

You need two values: a **bot token** (secret) and your **chat ID** (not secret).

## 1. Create the bot

1. In Telegram, open a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot`. BotFather asks for a display name and a username. The username must be 5 to 32 characters
   (Latin letters, numbers, underscores) and end in `bot`, for example `carlo_ai_digest_bot`.
   The username cannot be changed later ([Telegram Bot Features](https://core.telegram.org/bots/features)).
3. BotFather replies with a token like `110201543:AAH...`. Treat it like a password: anyone with it controls the bot.
   You can revoke it at any time through BotFather ([From BotFather to Hello World](https://core.telegram.org/bots/tutorial)).

## 2. Get your chat ID

A bot can only message you after you have messaged it first.

1. Open your new bot in Telegram and press **Start** (or send any message).
2. Fetch updates. The token goes in the URL, so run this locally and do not share the output:

   ```powershell
   $token = Read-Host "Bot token"
   (curl.exe -s "https://api.telegram.org/bot$token/getUpdates") | ConvertFrom-Json |
     ForEach-Object { $_.result } | ForEach-Object { $_.message.chat } | Select-Object id, type, first_name
   ```

3. The `id` of the chat with `type` = `private` is your chat ID, for example `2100000038`
   (see this [walkthrough](https://gist.github.com/nafiesl/4ad622f344cd1dc3bb1ecbe468ff9f8a)).
   If the result list is empty, send the bot another message and retry. `getUpdates` does not work while a webhook
   is set for the bot, and updates are kept for at most 24 hours ([Bot API](https://core.telegram.org/bots/api)).
4. Optional, send a test message:

   ```powershell
   curl.exe -s -X POST "https://api.telegram.org/bot$token/sendMessage" `
     -H "Content-Type: application/json" `
     -d '{"chat_id":"<your chat id>","text":"<b>Hello</b> from the digest bot","parse_mode":"HTML"}'
   ```

For a group or channel, add the bot to it, post a message, and use the negative chat ID (groups and channels use IDs
like `-100...`). Channels need the bot to be an admin.

## 3. Where each value goes

| Value | Secret? | Where it goes |
| --- | --- | --- |
| Bot token | Yes | Secrets Manager, then the AgentCore Identity provider `telegram-bot-token` ([guide](secrets-and-agentcore-identity.md)) |
| Chat ID | No | The `TELEGRAM_CHAT_ID` environment variable when you run `agentcore deploy` ([guide](deploy-and-schedule.md)) |

## Message format the digest uses

The digest is sent with `parse_mode=HTML`. The prompt and `digest.sanitize_html` restrict output to `<b>`, `<i>`,
`<a href>` and `<code>`, and escape `&`, `<` and `>`. Telegram messages are limited to 4096 characters, so
`telegram.chunk_message` splits longer text at blank lines (limit 4000) before sending. If Telegram rejects the HTML,
the chunk is resent as plain text.

Sources are listed in [sources.md](sources.md).
