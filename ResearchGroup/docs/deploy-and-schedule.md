# Deploy, test and schedule

Prerequisites: [Brave key](brave-search-setup.md), [Telegram bot](telegram-bot-setup.md), and the
[secrets and Identity providers](secrets-and-agentcore-identity.md). Docker is required for the container builds
(or rely on the CodeBuild-based build that `agentcore deploy` uses). Target: account `437024520945`,
region `ap-southeast-1` (`agentcore/aws-targets.json`).

## 1. Run the tests

```powershell
cd ResearchGroup/app/research_tools;  uv sync; uv run pytest
cd ../main_researcher;                uv sync; uv run pytest
cd ../../agentcore/cdk;               npm install; npx jest
cd ../..;                             uv run --no-project --with pytest --with boto3 pytest agentcore/cdk/lambda/weekly_trigger
```

## 2. Try it locally (dry run, nothing sent to Telegram)

Terminal 1, the MCP server with a Brave key in the environment:

```powershell
cd ResearchGroup/app/research_tools
$env:BRAVE_API_KEY = "<your key>"
uv run python -m server        # http://localhost:8000/mcp
```

Terminal 2, the agent. It uses your AWS credentials for Bedrock (Haiku 4.5 global profile; it is active in
`ap-southeast-1`):

```powershell
cd ResearchGroup/app/main_researcher
$env:RESEARCH_TOOLS_LOCAL_URL = "http://localhost:8000/mcp"
$env:AWS_REGION = "ap-southeast-1"
uv run python -m main          # serves http://localhost:8080
```

Terminal 3:

```powershell
curl.exe -s -X POST http://localhost:8080/invocations -H "Content-Type: application/json" `
  -d '{"mode":"weekly_digest","dry_run":true}'
```

The response contains the digest text with `"sent": false`. Remove `dry_run` and set `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` in the agent's terminal to send a real message from your machine. `agentcore dev` also works for
the agent, but the research tools still need `RESEARCH_TOOLS_LOCAL_URL`.

## 3. Deploy

```powershell
cd ResearchGroup
$env:TELEGRAM_CHAT_ID = "<your chat id>"     # not secret; becomes a runtime env var
agentcore validate
agentcore deploy
```

If `TELEGRAM_CHAT_ID` is not set, synthesis prints a warning and the digest cannot be delivered.
You can also pass it as CDK context (`-c telegramChatId=...`) when deploying with `npx cdk deploy` directly.

What gets created: two runtimes (`main_researcher`, `research_tools`), the `research-gateway` Gateway (IAM auth) with an
`httpRuntime` target pointing at `research_tools`, the `WeeklyTrigger` Lambda, an EventBridge Scheduler schedule
`cron(0 8 ? * MON *)` in `Asia/Manila` (no scheduler retries, no Lambda async retries), and the IAM described in
[design.md](design.md).

## 4. Test the deployed system

Digest dry run through the runtime:

```powershell
agentcore invoke --runtime main_researcher '{"mode":"weekly_digest","dry_run":true}'
```

`agentcore invoke` sends its argument as a text prompt; `main_researcher` recognises a prompt that is a JSON object with
`"mode": "weekly_digest"` and treats it as a digest request (`main.normalize_payload`). The Lambda sends the structured
payload `{"mode": "weekly_digest"}` directly.

Full run through the Lambda (this sends the real Telegram message):

```powershell
$fn = aws cloudformation describe-stacks --stack-name AgentCore-ResearchGroup-default --region ap-southeast-1 `
  --query "Stacks[0].Outputs[?OutputKey=='WeeklyTriggerFunctionName'].OutputValue" --output text
aws lambda invoke --function-name $fn --region ap-southeast-1 --cli-read-timeout 900 out.json; Get-Content out.json
agentcore logs --runtime main_researcher
```

Chat mode (the normal agent still works):

```powershell
agentcore invoke --runtime main_researcher "What were the most discussed AI papers this week?"
```

## 5. Change the schedule or pause it

- Schedule: edit `SCHEDULE_EXPRESSION` and `SCHEDULE_TIMEZONE` in `agentcore/cdk/lib/cdk-stack.ts`, then redeploy.
  EventBridge Scheduler cron has six fields (`minutes hours day-of-month month day-of-week year`) and takes an explicit
  time zone ([schedule types](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html)).
- Pause without redeploying: in the EventBridge Scheduler console (or with `aws scheduler update-schedule`), set the
  schedule state to `DISABLED`. `update-schedule` replaces the whole schedule definition, so the console is simpler.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Telegram message "Weekly AI digest failed: ..." | Read the reason; check `agentcore logs --runtime main_researcher`. |
| "Workload access token has not been set" | The runtime was invoked over SigV4 without a user ID. The Lambda sets `runtimeUserId`; set `x-amzn-bedrock-agentcore-runtime-user-id` when calling manually. |
| Brave tools fail with "No Brave API key available" | `research_tools` did not get a workload access token through the gateway. Set `BRAVE_SECRET_ARN` to the Brave secret's ARN when deploying (`$env:BRAVE_SECRET_ARN = "<arn>"`); the stack grants read access and the server falls back to Secrets Manager. |
| Access denied reading an API key | Compare the runtime role with the policy in [secrets-and-agentcore-identity.md](secrets-and-agentcore-identity.md), step 4, and check the secret resource policy from step 2. |
| Gateway returns 403 | The caller needs `bedrock-agentcore:InvokeGateway`; the stack grants it to both runtimes. |
| Tools missing in the digest (it still sends) | `AGENTCORE_GATEWAY_RESEARCH_GATEWAY_URL` is unset or the gateway path failed; check the runtime logs. For a quick workaround, deploy with an OAuth `mcpServer` target (see design.md, section 6). |

Sources are listed in [sources.md](sources.md).
