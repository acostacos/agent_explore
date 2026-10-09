"""MCP client for the research tools (Brave Search + arXiv).

Production path: the AgentCore Gateway URL injected by the CDK stack as
``AGENTCORE_GATEWAY_RESEARCH_GATEWAY_URL``; requests are signed with SigV4 (gateway auth type AWS_IAM).

Local path: set ``RESEARCH_TOOLS_LOCAL_URL`` (e.g. ``http://localhost:8000/mcp``) to talk to a locally
running ``app/research_tools`` server without authentication.
"""

import logging
import os
from typing import Optional

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

GATEWAY_URL_ENV = "AGENTCORE_GATEWAY_RESEARCH_GATEWAY_URL"
LOCAL_URL_ENV = "RESEARCH_TOOLS_LOCAL_URL"
SIGNING_SERVICE = "bedrock-agentcore"


class SigV4HttpxAuth(httpx.Auth):
    """httpx auth flow that signs each request with AWS SigV4 using the ambient credentials."""

    requires_request_body = True

    def __init__(self, service: str, region: str, session: Optional[boto3.Session] = None):
        self._service = service
        self._region = region
        self._session = session or boto3.Session()

    def auth_flow(self, request: httpx.Request):
        credentials = self._session.get_credentials()
        if credentials is None:
            raise RuntimeError("No AWS credentials available to sign the gateway request")
        frozen = credentials.get_frozen_credentials()
        headers = {"Content-Type": request.headers["content-type"]} if "content-type" in request.headers else {}
        aws_request = AWSRequest(method=request.method, url=str(request.url), data=request.content, headers=headers)
        SigV4Auth(frozen, self._service, self._region).add_auth(aws_request)
        for key, value in aws_request.headers.items():
            request.headers[key] = value
        yield request


def _region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or boto3.Session().region_name or "ap-southeast-1"


def get_streamable_http_mcp_client() -> Optional[MultiServerMCPClient]:
    """Returns an MCP client for the research tools, or None when no endpoint is configured."""
    local_url = os.getenv(LOCAL_URL_ENV)
    if local_url:
        logger.info("Using local research tools MCP server at %s", local_url)
        return MultiServerMCPClient({"research_tools": {"transport": "streamable_http", "url": local_url}})

    gateway_url = os.getenv(GATEWAY_URL_ENV)
    if not gateway_url:
        logger.warning("%s is not set; running without research tools", GATEWAY_URL_ENV)
        return None

    return MultiServerMCPClient(
        {
            "research_tools": {
                "transport": "streamable_http",
                "url": gateway_url,
                "auth": SigV4HttpxAuth(SIGNING_SERVICE, _region()),
            }
        }
    )
