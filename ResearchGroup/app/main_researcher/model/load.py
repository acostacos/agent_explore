import os

from langchain_aws import ChatBedrock

# Claude Haiku 4.5 through the global cross-region inference profile.
# https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")


def load_model() -> ChatBedrock:
    """Get Bedrock model client using IAM credentials."""
    return ChatBedrock(model_id=MODEL_ID, model_kwargs={"max_tokens": 8192, "temperature": 0.2})
