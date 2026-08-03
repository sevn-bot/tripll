FROM ubuntu:22.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates git python3 python3-minimal \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY repo.bundle /tmp/repo.bundle
COPY pr_metadata.json /workspace/pr_metadata.json

RUN git clone /tmp/repo.bundle repo \
    && cd repo \
    && git checkout ec877d5f079492d3c8bb5b009dcb2ddcf6b56e60

ENV REVIEW_REPO=/workspace/repo
ENV PR_METADATA=/workspace/pr_metadata.json
ENV AGENT_FINDINGS_PATH=/workspace/findings.json
