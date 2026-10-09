FROM public.ecr.aws/docker/library/python:3.12-slim-trixie

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

ARG UV_DEFAULT_INDEX
ARG UV_INDEX

WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} \
    UV_INDEX=${UV_INDEX} \
    PATH="/app/.venv/bin:$PATH"

RUN useradd -m -u 1000 bedrock_agentcore

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=bedrock_agentcore:bedrock_agentcore . .
RUN uv sync --frozen --no-dev && /usr/local/bin/python -m pip uninstall -y uv

USER bedrock_agentcore

# AgentCore Runtime service contract: MCP servers listen on 0.0.0.0:8000/mcp
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
EXPOSE 8000

CMD ["python", "-m", "server"]
