"""Resolve the Brave Search API key.

Resolution order:
1. ``BRAVE_API_KEY`` environment variable (local development and tests).
2. AgentCore Identity API-key credential provider named by ``BRAVE_PROVIDER_NAME``
   (default ``brave-search-api-key``). The provider references a Secrets Manager secret.
   The workload access token is taken from the incoming request headers when the runtime forwards it.
3. Secrets Manager directly, when ``BRAVE_SECRET_ARN`` is set (optional escape hatch if the
   workload access token is not delivered to this MCP runtime). JSON key: ``BRAVE_SECRET_JSON_KEY``
   (default ``api_key``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER_NAME = "brave-search-api-key"
WAT_HEADERS = ("workloadaccesstoken", "x-amz-bedrock-agentcore-identity-wat")


class MissingApiKeyError(RuntimeError):
    """Raised when no Brave API key can be resolved."""


def workload_token_from_headers(headers: Optional[Mapping[str, str]]) -> Optional[str]:
    """Return the workload access token from request headers, if any (case-insensitive)."""
    if not headers:
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    for name in WAT_HEADERS:
        if lowered.get(name):
            return lowered[name]
    return None


async def _from_identity(headers: Optional[Mapping[str, str]]) -> Optional[str]:
    provider = os.getenv("BRAVE_PROVIDER_NAME", DEFAULT_PROVIDER_NAME)
    try:
        from bedrock_agentcore.runtime import BedrockAgentCoreContext
        from bedrock_agentcore.services.identity import IdentityClient

        token = workload_token_from_headers(headers) or BedrockAgentCoreContext.get_workload_access_token()
        if not token:
            return None
        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "ap-southeast-1"
        client = IdentityClient(region)
        return await client.get_api_key(provider_name=provider, agent_identity_token=token)
    except Exception as exc:  # noqa: BLE001 - fall through to the next source
        logger.warning("AgentCore Identity lookup failed for %s: %s", provider, exc)
        return None


def _from_secrets_manager() -> Optional[str]:
    arn = os.getenv("BRAVE_SECRET_ARN")
    if not arn:
        return None
    try:
        import boto3

        raw = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
        json_key = os.getenv("BRAVE_SECRET_JSON_KEY", "api_key")
        try:
            return json.loads(raw)[json_key]
        except (ValueError, KeyError, TypeError):
            return raw
    except Exception as exc:  # noqa: BLE001
        logger.warning("Secrets Manager lookup failed: %s", exc)
        return None


async def get_brave_api_key(headers: Optional[Mapping[str, str]] = None) -> str:
    key = os.getenv("BRAVE_API_KEY")
    if key:
        return key
    key = await _from_identity(headers)
    if key:
        return key
    key = _from_secrets_manager()
    if key:
        return key
    raise MissingApiKeyError(
        "No Brave API key available. Set BRAVE_API_KEY locally, or configure the AgentCore Identity "
        "credential provider (BRAVE_PROVIDER_NAME) in the deployed runtime."
    )
