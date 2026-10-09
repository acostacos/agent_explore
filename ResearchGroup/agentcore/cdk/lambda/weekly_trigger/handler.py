"""Weekly trigger: invokes the main_researcher AgentCore Runtime in weekly_digest mode.

Invoked by EventBridge Scheduler (Mondays 08:00 Asia/Manila). The runtime itself builds the digest and
sends it to Telegram; this function only starts the run and retries once if the invocation fails.
"""

import json
import logging
import os
import time
import uuid

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 30
ATTEMPT_TIMEOUT_SECONDS = 540
MIN_ATTEMPT_SECONDS = 120
SAFETY_MARGIN_SECONDS = 20
PAYLOAD = {"mode": "weekly_digest"}
# SigV4-invoked runtimes only get a workload access token (needed for AgentCore Identity) when a user id is sent.
RUNTIME_USER_ID = "weekly-digest-scheduler"


def make_client(read_timeout: int):
    return boto3.client(
        "bedrock-agentcore",
        config=Config(read_timeout=read_timeout, connect_timeout=10, retries={"max_attempts": 1}),
    )


def invoke_once(client, runtime_arn: str, session_id: str) -> dict:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        runtimeUserId=RUNTIME_USER_ID,
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(PAYLOAD).encode("utf-8"),
    )
    body = response["response"].read().decode("utf-8")
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = {"raw": body}
    if isinstance(parsed, dict) and "error" in parsed:
        raise RuntimeError(f"Runtime returned an error: {str(parsed['error'])[:500]}")
    return parsed


def run(client_factory, runtime_arn: str, remaining_seconds, sleep=time.sleep) -> dict:
    """Try up to MAX_ATTEMPTS times. ``remaining_seconds`` returns the Lambda time left."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        timeout = int(min(ATTEMPT_TIMEOUT_SECONDS, remaining_seconds() - SAFETY_MARGIN_SECONDS))
        if timeout < MIN_ATTEMPT_SECONDS:
            logger.error("Not enough time left for attempt %s", attempt)
            break
        try:
            logger.info("Invoking weekly digest (attempt %s/%s, timeout %ss)", attempt, MAX_ATTEMPTS, timeout)
            result = invoke_once(client_factory(timeout), runtime_arn, str(uuid.uuid4()))  # session id >= 33 chars
            sent = result.get("sent") if isinstance(result, dict) else None
            return {"status": "ok", "attempt": attempt, "sent": sent}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.exception("Attempt %s failed", attempt)
            if attempt < MAX_ATTEMPTS:
                sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Weekly digest failed after {MAX_ATTEMPTS} attempts: {last_error}")


def handler(event, context):
    runtime_arn = os.environ["MAIN_RESEARCHER_RUNTIME_ARN"]
    return run(make_client, runtime_arn, lambda: context.get_remaining_time_in_millis() / 1000)
