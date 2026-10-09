# Sources

External pages used for the setup guides and design. Accessed on 2026-10-09.

## Brave Search API

- [Quickstart](https://api-dashboard.search.brave.com/documentation/quickstart): account, plan activation, creating a key, first request.
- [Authentication](https://api-dashboard.search.brave.com/documentation/guides/authentication): `X-Subscription-Token` header, key rotation and revocation.
- [Rate limiting](https://api-dashboard.search.brave.com/documentation/guides/rate-limiting): one-second sliding window, `X-RateLimit-*` headers, 429 handling.
- [News search API reference](https://api-dashboard.search.brave.com/api-reference/news/news_search/get): endpoint, `freshness` values (`pd`, `pw`, `pm`, `py`), `count` 1 to 50.
- [News search documentation](https://api-dashboard.search.brave.com/app/documentation/news-search): freshness filtering overview.
- [Brave Search API](https://brave.com/search/api/): why a credit card is required for free plans.
- [How to get a Brave Search API key (Apidog)](https://apidog.com/blog/brave-api-key/): third-party summary of plans and the 401 troubleshooting checklist. Treat prices and limits as indicative; confirm on the Plans page.

## Telegram

- [From BotFather to Hello World](https://core.telegram.org/bots/tutorial): creating a bot with `/newbot`, tokens.
- [Telegram Bot Features](https://core.telegram.org/bots/features): BotFather commands, username rules, token security.
- [Telegram Bot API](https://core.telegram.org/bots/api): `sendMessage`, `getUpdates`, `parse_mode` HTML, 4096 character limit, 24 hour update retention.
- [How to get Telegram Bot Chat ID (gist)](https://gist.github.com/nafiesl/4ad622f344cd1dc3bb1ecbe468ff9f8a): `getUpdates` walkthrough for private chats and groups (community source).

## arXiv

- [arXiv API User's Manual](https://info.arxiv.org/help/api/user-manual.html): `search_query`, `cat:` prefix, `submittedDate` range in GMT (`YYYYMMDDTTTT`), `sortBy`, `sortOrder`.
- [Terms of Use for arXiv APIs](https://info.arxiv.org/help/api/tou.html): one request every three seconds, a single connection at a time.
- [arXiv API Basics](https://info.arxiv.org/help/api/basics.html): Atom response format.

## AWS

- [Configure credential provider (AgentCore Identity)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-providers.html): `create-api-key-credential-provider --api-key-secret-source EXTERNAL`.
- [Reference your own Secrets Manager secrets in AgentCore Identity](https://aws.amazon.com/blogs/machine-learning/reference-your-own-aws-secrets-manager-secrets-in-amazon-bedrock-agentcore-identity/): prerequisites, resource policy for the service principal, rotation behaviour.
- [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html): announcement of referenced secrets.
- [AgentCore harness security and access controls](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-security.html): `GetResourceApiKey` and token vault resource ARNs.
- [Security best practices for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html): `bedrock-agentcore.amazonaws.com` service principal.
- [Runtime OAuth and SigV4 inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html): linked from the SDK error about the user ID header.
- [Deploy MCP servers in AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html): `0.0.0.0:8000/mcp`, stateless streamable HTTP.
- [MCP protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html): `Mcp-Session-Id` handling in stateless mode.
- [Gateway VPC egress: Runtime as a target](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-vpc-egress.html): outbound auth to an MCP runtime through `mcpServer` targets (OAuth or none).
- [Connect an AgentCore Runtime hosted MCP server to Amazon Quick](https://aws.amazon.com/blogs/machine-learning/connect-an-agentcore-runtime-hosted-mcp-server-to-amazon-quick/): runtime invocation URL template.
- [CloudFormation: GatewayTarget HttpTargetConfiguration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrockagentcore-gatewaytarget-httptargetconfiguration.html) and [RuntimeTargetConfiguration](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrockagentcore-gatewaytarget-runtimetargetconfiguration.html): the `AgentcoreRuntime` HTTP target used by this project.
- [Secrets Manager examples using the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli_secrets-manager_code_examples.html): `create-secret`.
- [EventBridge Scheduler schedule types](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html): cron fields and time zones.
- [Amazon Bedrock inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html): global profile for Claude Haiku 4.5.

## Checked in this repository (not web sources)

- `@aws/agentcore-cdk` 0.1.0-alpha.54 in `agentcore/cdk/node_modules`: injects `AGENTCORE_GATEWAY_<NAME>_URL` and grants `InvokeGateway`; `httpRuntime` targets default to `GATEWAY_IAM_ROLE` and require a gateway with `protocolType: "None"`; `mcpServer` targets accept only OAuth or no outbound auth; the credential schema has no Secrets Manager reference.
- `bedrock_agentcore` SDK 1.24.1: `requires_api_key`, workload access token headers (`WorkloadAccessToken`, `X-Amz-Bedrock-AgentCore-Identity-WAT`), and the SigV4 user ID error message.
- AWS CLI 2.37.11 and boto3 1.43.110 help output: `--api-key-secret-source`, `--api-key-secret-config`, `runtimeUserId`.
