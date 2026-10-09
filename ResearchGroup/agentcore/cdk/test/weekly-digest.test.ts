import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as fs from 'fs';
import * as path from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';

const configRoot = path.resolve(__dirname, '..', '..');

function synth(chatId?: string) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const spec = JSON.parse(fs.readFileSync(path.join(configRoot, 'agentcore.json'), 'utf8')) as any;
  const app = new cdk.App({ context: chatId ? { telegramChatId: chatId } : {} });
  const stack = new AgentCoreStack(app, 'TestStack', {
    spec,
    // Mirrors bin/cdk.ts, which casts because the published schema type lags the CLI's.
    mcpSpec: {
      agentCoreGateways: spec.agentCoreGateways,
      mcpRuntimeTools: spec.mcpRuntimeTools,
      unassignedTargets: spec.unassignedTargets,
    } as any, // eslint-disable-line @typescript-eslint/no-explicit-any
    env: { account: '123456789012', region: 'ap-southeast-1' },
  });
  return { stack, template: Template.fromStack(stack) };
}

describe('weekly digest wiring', () => {
  const { template } = synth('424242');

  test('schedule runs Mondays 08:00 Asia/Manila with no scheduler retries', () => {
    template.hasResourceProperties('AWS::Scheduler::Schedule', {
      ScheduleExpression: 'cron(0 8 ? * MON *)',
      ScheduleExpressionTimezone: 'Asia/Manila',
      FlexibleTimeWindow: { Mode: 'OFF' },
      Target: Match.objectLike({ RetryPolicy: { MaximumRetryAttempts: 0 } }),
    });
  });

  test('trigger lambda has a 15 minute timeout and may invoke the runtime', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Handler: 'handler.handler',
      Runtime: 'python3.13',
      Timeout: 900,
    });
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({ Action: 'bedrock-agentcore:InvokeAgentRuntime', Effect: 'Allow' }),
        ]),
      },
    });
  });

  test('lambda async retries are disabled', () => {
    template.hasResourceProperties('AWS::Lambda::EventInvokeConfig', { MaximumRetryAttempts: 0 });
  });

  test('gateway uses IAM auth and an httpRuntime target', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Gateway', { AuthorizerType: 'AWS_IAM' });
    template.hasResourceProperties('AWS::BedrockAgentCore::GatewayTarget', {
      TargetConfiguration: { Http: { AgentcoreRuntime: Match.anyValue() } },
      CredentialProviderConfigurations: [{ CredentialProviderType: 'GATEWAY_IAM_ROLE' }],
    });
  });

  test('main_researcher gets the chat id, provider name and gateway url', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      EnvironmentVariables: Match.objectLike({
        TELEGRAM_CHAT_ID: '424242',
        TELEGRAM_PROVIDER_NAME: 'telegram-bot-token',
        AGENTCORE_GATEWAY_RESEARCH_GATEWAY_URL: Match.anyValue(),
      }),
    });
  });

  test('research_tools gets the Brave provider name', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      EnvironmentVariables: Match.objectLike({ BRAVE_PROVIDER_NAME: 'brave-search-api-key' }),
    });
  });

  test('runtimes may read their API key credential providers', () => {
    const policies = JSON.stringify(template.findResources('AWS::IAM::Policy'));
    expect(policies).toContain('bedrock-agentcore:GetResourceApiKey');
    expect(policies).toContain('apikeycredentialprovider/telegram-bot-token');
    expect(policies).toContain('apikeycredentialprovider/brave-search-api-key');
  });
});

test('missing chat id produces a warning, not a failure', () => {
  const saved = process.env.TELEGRAM_CHAT_ID;
  delete process.env.TELEGRAM_CHAT_ID;
  try {
    const { stack } = synth();
    const annotations = cdk.App.of(stack)!.synth().getStackByName(stack.stackName).messages;
    expect(JSON.stringify(annotations)).toContain('TELEGRAM_CHAT_ID is not set');
  } finally {
    if (saved !== undefined) process.env.TELEGRAM_CHAT_ID = saved;
  }
});
