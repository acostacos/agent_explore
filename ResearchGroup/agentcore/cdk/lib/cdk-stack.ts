import {
  AgentCoreApplication,
  AgentCoreMcp,
  AgentCorePaymentManager,
  AgentCorePaymentConnector,
  type AgentCoreProjectSpec,
  type AgentCoreMcpSpec,
  type CustomJWTAuthorizerConfig,
  type HarnessDeploymentConfig,
} from '@aws/agentcore-cdk';
import { Annotations, CfnOutput, Duration, Stack, type StackProps } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import { Construct } from 'constructs';
import * as path from 'path';

// ---- Weekly AI research digest -------------------------------------------------------------------
// Names must match agentcore/agentcore.json and docs/design.md.
const MAIN_RUNTIME = 'main_researcher';
const TOOLS_RUNTIME = 'research_tools';
/** AgentCore Identity API-key credential providers (created by hand, referencing Secrets Manager secrets). */
const BRAVE_PROVIDER = 'brave-search-api-key';
const TELEGRAM_PROVIDER = 'telegram-bot-token';
/** Monday 08:00 Manila time. */
const SCHEDULE_EXPRESSION = 'cron(0 8 ? * MON *)';
const SCHEDULE_TIMEZONE = 'Asia/Manila';

/**
 * Harness deployment config: role-scoped fields (for IAM role + container build)
 * plus the full validated spec + its config directory so the L3 construct can
 * synthesize the AWS::BedrockAgentCore::Harness resource.
 */
export type HarnessConfig = HarnessDeploymentConfig;

export interface ManualPaymentConnectorSpec {
  name: string;
  provider: 'CoinbaseCDP' | 'StripePrivy';
  provisionMode?: 'MANUAL';
  credentialName: string;
  credentialProviderArn: string;
}

export interface QuickCreatePaymentConnectorSpec {
  name: string;
  provider: 'CoinbaseCDP';
  provisionMode: 'QUICK_CREATE';
  credentialName?: never;
  credentialProviderArn?: never;
}

export type PaymentConnectorSpec = ManualPaymentConnectorSpec | QuickCreatePaymentConnectorSpec;

export interface PaymentSpec {
  name: string;
  description?: string;
  authorizerType: 'AWS_IAM' | 'CUSTOM_JWT';
  authorizerConfiguration?: { customJWTAuthorizer: CustomJWTAuthorizerConfig };
  autoPayment?: boolean;
  paymentToolAllowlist?: string[];
  networkPreferences?: string[];
  connectors: PaymentConnectorSpec[];
}

export interface AgentCoreStackProps extends StackProps {
  /**
   * The AgentCore project specification containing agents, memories, and credentials.
   */
  spec: AgentCoreProjectSpec;
  /**
   * The MCP specification containing gateways and servers.
   */
  mcpSpec?: AgentCoreMcpSpec;
  /**
   * Credential provider ARNs from deployed state, keyed by credential name.
   */
  credentials?: Record<string, { credentialProviderArn: string; clientSecretArn?: string }>;
  /**
   * Harness role configurations.
   */
  harnesses?: HarnessConfig[];
  /**
   * Parsed connectorParameters for non-S3 KB data sources, keyed by
   * connectorConfigFile path. Forwarded to AgentCoreApplication.
   */
  connectorParametersByFile?: Record<string, Record<string, unknown>>;
  /**
   * Payment specifications with resolved credential provider ARNs.
   */
  paymentSpec?: PaymentSpec[];
}

function toCdkId(name: string): string {
  return name.replace(/_/g, '');
}

/**
 * Decide whether a deployed runtime should receive payment env vars + IAM grants.
 * Payments today only ships a runtime shim for Python HTTP runtimes; injecting
 * AGENTCORE_PAYMENT_* env vars into TypeScript / MCP / A2A / AGUI runtimes
 * would surface env vars they cannot consume and would dilute least-privilege
 * IAM grants for runtimes that never call ProcessPayment.
 */
function isPaymentEligibleAgent(agent: { entrypoint?: string; protocol?: string }): boolean {
  if (agent.protocol && agent.protocol !== 'HTTP') {
    return false;
  }
  const entrypoint = typeof agent.entrypoint === 'string' ? agent.entrypoint : '';
  const entrypointFile = entrypoint.split(':')[0] ?? '';
  return entrypointFile.endsWith('.py');
}

/**
 * CDK Stack that deploys AgentCore infrastructure.
 *
 * This is a thin wrapper that instantiates L3 constructs.
 * All resource logic and outputs are contained within the L3 constructs.
 */
export class AgentCoreStack extends Stack {
  /** The AgentCore application containing all agent environments */
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { spec, mcpSpec, credentials, harnesses, connectorParametersByFile, paymentSpec } = props;

    // Create AgentCoreApplication with all agents and harness roles
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const appProps: Record<string, unknown> = { spec };
    if (harnesses?.length) {
      appProps.harnesses = harnesses;
    }
    if (connectorParametersByFile && Object.keys(connectorParametersByFile).length > 0) {
      appProps.connectorParametersByFile = connectorParametersByFile;
    }
    if (credentials) {
      appProps.credentials = credentials;
    }
    this.application = new AgentCoreApplication(this, 'Application', appProps as any);

    // Create AgentCoreMcp if there are gateways configured
    if (mcpSpec?.agentCoreGateways && mcpSpec.agentCoreGateways.length > 0) {
      new AgentCoreMcp(this, 'Mcp', {
        projectName: spec.name,
        mcpSpec,
        agentCoreApplication: this.application,
        credentials,
        projectTags: spec.tags,
      });
    }

    // Create payment infrastructure via CFN constructs
    if (paymentSpec && paymentSpec.length > 0) {
      for (const payment of paymentSpec) {
        const mgrId = toCdkId(payment.name);
        const manager = new AgentCorePaymentManager(this, `Payment${mgrId}`, {
          projectName: spec.name,
          name: payment.name,
          authorizerType: payment.authorizerType,
          description: payment.description,
          authorizerConfiguration: payment.authorizerConfiguration,
          tags: spec.tags,
        });

        const prefix = `AGENTCORE_PAYMENT_${payment.name.toUpperCase().replace(/-/g, '_')}`;

        // Wire env vars from construct output tokens into eligible agent environments only.
        // See isPaymentEligibleAgent — non-Python or non-HTTP runtimes have no shim that
        // can consume these env vars, and giving them sts:AssumeRole on the
        // ProcessPaymentRole would broaden the privilege surface unnecessarily.
        for (const env of this.application.environments.values()) {
          if (!isPaymentEligibleAgent(env.agent)) {
            continue;
          }
          env.runtime.addEnvironmentVariable(`${prefix}_MANAGER_ARN`, manager.paymentManagerArn);
          env.runtime.addEnvironmentVariable(`${prefix}_PROCESS_PAYMENT_ROLE_ARN`, manager.processPaymentRoleArn);

          // Grant runtime execution role permission to assume the ProcessPaymentRole.
          // The ProcessPaymentRole's trust policy allows AccountRootPrincipal, but the
          // caller still needs sts:AssumeRole on its own role to perform the assumption.
          env.runtime.role.addToPrincipalPolicy(
            new iam.PolicyStatement({
              actions: ['sts:AssumeRole'],
              resources: [manager.processPaymentRoleArn],
            })
          );

          // Grant payment data-plane actions directly to the runtime role.
          //
          // NOTE: This deviates from the canonical role model in the AgentCore Payments
          // beta guide, which assigns Get/List/Create instrument+session actions to a
          // separate ManagementRole and limits the agent's role to ProcessPayment only.
          // The current SDK plugin (AgentCorePaymentsPlugin.generate_payment_header)
          // calls GetPaymentInstrument internally during the 402 auto-pay path, so the
          // runtime role needs read access. CreatePaymentSession is included so
          // `agentcore invoke --auto-session` works without a separate ManagementRole
          // call. Tighten this if the SDK is updated to accept pre-fetched instrument
          // details and split create-session into a backend-only flow.
          env.runtime.role.addToPrincipalPolicy(
            new iam.PolicyStatement({
              actions: [
                'bedrock-agentcore:GetPaymentInstrument',
                'bedrock-agentcore:ListPaymentInstruments',
                'bedrock-agentcore:GetPaymentInstrumentBalance',
                'bedrock-agentcore:GetPaymentSession',
                'bedrock-agentcore:ListPaymentSessions',
                'bedrock-agentcore:CreatePaymentSession',
                'bedrock-agentcore:ProcessPayment',
              ],
              resources: [manager.paymentManagerArn, `${manager.paymentManagerArn}/*`],
            })
          );

          if (payment.autoPayment !== undefined) {
            env.runtime.addEnvironmentVariable(`${prefix}_AUTO_PAYMENT`, String(payment.autoPayment));
          }
          if (payment.paymentToolAllowlist) {
            env.runtime.addEnvironmentVariable(`${prefix}_TOOL_ALLOWLIST`, payment.paymentToolAllowlist.join(','));
          }
          if (payment.networkPreferences) {
            env.runtime.addEnvironmentVariable(`${prefix}_NETWORK_PREFERENCES`, payment.networkPreferences.join(','));
          }
          if (payment.authorizerType === 'CUSTOM_JWT') {
            env.runtime.addEnvironmentVariable(`${prefix}_AUTH_MODE`, 'bearer');
          }
        }

        // Create connectors for this manager
        for (const connector of payment.connectors) {
          const connId = toCdkId(connector.name);
          const schemaConnector =
            connector.provisionMode === 'QUICK_CREATE'
              ? connector
              : {
                  name: connector.name,
                  provider: connector.provider,
                  ...(connector.provisionMode && { provisionMode: connector.provisionMode }),
                  credentialName: connector.credentialName,
                };
          const compatibilityProps = {
            projectName: spec.name,
            paymentManager: manager,
            connector: schemaConnector,
            // Remove these legacy manual fields after the new L3 release is pinned.
            connectorName: connector.name,
            connectorType: connector.provider,
            ...(connector.provisionMode !== 'QUICK_CREATE' && {
              credentialProviderArn: connector.credentialProviderArn,
            }),
          };
          const conn = new AgentCorePaymentConnector(
            this,
            `Payment${mgrId}${connId}`,
            compatibilityProps as unknown as ConstructorParameters<typeof AgentCorePaymentConnector>[2]
          );

          // Wire first connector's ID as env var (eligible agents only)
          if (connector === payment.connectors[0]) {
            for (const env of this.application.environments.values()) {
              if (!isPaymentEligibleAgent(env.agent)) continue;
              env.runtime.addEnvironmentVariable(`${prefix}_CONNECTOR_ID`, conn.paymentConnectorId);
            }
          }

          new CfnOutput(this, `Payment${mgrId}${connId}ConnectorId`, {
            value: conn.paymentConnectorId,
          });
          if (connector.provisionMode === 'QUICK_CREATE') {
            const quickCreateConnector = conn as AgentCorePaymentConnector & {
              paymentConnectorStatus: string;
              authorizationUrl: string;
            };
            new CfnOutput(this, `Payment${mgrId}${connId}ConnectorStatus`, {
              value: quickCreateConnector.paymentConnectorStatus,
            });
            new CfnOutput(this, `Payment${mgrId}${connId}AuthorizationUrl`, {
              value: quickCreateConnector.authorizationUrl,
            });
          }
        }

        // CFN Outputs for post-deploy state parsing
        new CfnOutput(this, `Payment${mgrId}ManagerArn`, {
          value: manager.paymentManagerArn,
        });
        new CfnOutput(this, `Payment${mgrId}ManagerId`, {
          value: manager.paymentManagerId,
        });
        new CfnOutput(this, `Payment${mgrId}ProcessPaymentRoleArn`, {
          value: manager.processPaymentRoleArn,
        });
        new CfnOutput(this, `Payment${mgrId}ResourceRetrievalRoleArn`, {
          value: manager.resourceRetrievalRoleArn,
        });
      }
    }

    this.addWeeklyDigest();

    // Stack-level output
    new CfnOutput(this, 'StackNameOutput', {
      description: 'Name of the CloudFormation Stack',
      value: this.stackName,
    });
  }

  /**
   * Weekly digest wiring: runtime env vars, AgentCore Identity IAM, trigger Lambda and the schedule.
   * No-op when the project does not define the main_researcher runtime (e.g. in unit tests).
   */
  private addWeeklyDigest(): void {
    const main = this.application.environments.get(MAIN_RUNTIME);
    if (!main) {
      return;
    }

    // Telegram chat ID is not a secret; supply it at deploy time (env var or `-c telegramChatId=...`).
    const chatId = process.env.TELEGRAM_CHAT_ID ?? (this.node.tryGetContext('telegramChatId') as string | undefined);
    if (chatId) {
      main.runtime.addEnvironmentVariable('TELEGRAM_CHAT_ID', String(chatId));
    } else {
      Annotations.of(this).addWarning(
        'TELEGRAM_CHAT_ID is not set. Set the TELEGRAM_CHAT_ID env var (or -c telegramChatId=...) before deploying, ' +
          'otherwise the weekly digest cannot be delivered.'
      );
    }
    main.runtime.addEnvironmentVariable('TELEGRAM_PROVIDER_NAME', TELEGRAM_PROVIDER);
    this.grantApiKeyAccess(main.runtime.role, TELEGRAM_PROVIDER);

    const tools = this.application.environments.get(TOOLS_RUNTIME);
    if (tools) {
      tools.runtime.addEnvironmentVariable('BRAVE_PROVIDER_NAME', BRAVE_PROVIDER);
      this.grantApiKeyAccess(tools.runtime.role, BRAVE_PROVIDER);

      // Optional fallback: if AgentCore Identity does not receive a workload access token on the gateway hop,
      // research_tools can read the Brave secret straight from Secrets Manager (see docs/deploy-and-schedule.md).
      const braveSecretArn =
        process.env.BRAVE_SECRET_ARN ?? (this.node.tryGetContext('braveSecretArn') as string | undefined);
      if (braveSecretArn) {
        tools.runtime.addEnvironmentVariable('BRAVE_SECRET_ARN', braveSecretArn);
        tools.runtime.role.addToPrincipalPolicy(
          new iam.PolicyStatement({ actions: ['secretsmanager:GetSecretValue'], resources: [braveSecretArn] })
        );
      }
    }

    const logGroup = new logs.LogGroup(this, 'WeeklyTriggerLogs', { retention: logs.RetentionDays.THREE_MONTHS });
    const trigger = new lambda.Function(this, 'WeeklyTrigger', {
      description: 'Starts the weekly AI research digest on the main_researcher runtime',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda', 'weekly_trigger'), {
        exclude: ['test_*.py', '__pycache__', '.pytest_cache'],
      }),
      timeout: Duration.minutes(15),
      memorySize: 256,
      logGroup,
      environment: { MAIN_RESEARCHER_RUNTIME_ARN: main.runtime.runtimeArn },
    });
    trigger.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [main.runtime.runtimeArn, `${main.runtime.runtimeArn}/runtime-endpoint/*`],
      })
    );
    // Scheduler invokes Lambda asynchronously; disable Lambda's own retries so the only retry is the in-code one.
    new lambda.EventInvokeConfig(this, 'WeeklyTriggerInvokeConfig', {
      function: trigger,
      retryAttempts: 0,
      maxEventAge: Duration.hours(1),
    });

    const schedulerRole = new iam.Role(this, 'WeeklyScheduleRole', {
      assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
    });
    trigger.grantInvoke(schedulerRole);

    const schedule = new scheduler.CfnSchedule(this, 'WeeklyDigestSchedule', {
      description: 'Weekly AI research digest: Mondays 08:00 Asia/Manila',
      scheduleExpression: SCHEDULE_EXPRESSION,
      scheduleExpressionTimezone: SCHEDULE_TIMEZONE,
      flexibleTimeWindow: { mode: 'OFF' },
      state: 'ENABLED',
      target: {
        arn: trigger.functionArn,
        roleArn: schedulerRole.roleArn,
        retryPolicy: { maximumRetryAttempts: 0 },
      },
    });

    new CfnOutput(this, 'WeeklyTriggerFunctionName', { value: trigger.functionName });
    new CfnOutput(this, 'WeeklyDigestScheduleName', { value: schedule.ref });
  }

  /** Lets a runtime fetch an AgentCore Identity API key (credential provider) at runtime. */
  private grantApiKeyAccess(role: iam.IRole, providerName: string): void {
    const arn = (resource: string) =>
      `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:${resource}`;
    role.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: [
          'bedrock-agentcore:GetWorkloadAccessToken',
          'bedrock-agentcore:GetWorkloadAccessTokenForJWT',
          'bedrock-agentcore:GetWorkloadAccessTokenForUserId',
        ],
        resources: [
          arn('workload-identity-directory/default'),
          arn('workload-identity-directory/default/workload-identity/*'),
        ],
      })
    );
    role.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:GetResourceApiKey'],
        resources: [arn('token-vault/default'), arn(`token-vault/default/apikeycredentialprovider/${providerName}`)],
      })
    );
  }
}
