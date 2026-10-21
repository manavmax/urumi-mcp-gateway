# Provisioner image (Phase 5, ADR-060): python:3.12-slim + the helm CLI + the
# store chart baked at /charts/store. The ServiceAccount token provides API
# access; helm reads a generated kubeconfig (see tasks.HelmRunner). No kubectl,
# no shell entrypoint beyond uvicorn.
FROM python:3.12-slim

ARG HELM_VERSION=3.16.4
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /tmp/helm.tgz "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/helm.tgz -C /tmp \
    && mv /tmp/linux-amd64/helm /usr/local/bin/helm \
    && rm -rf /tmp/helm.tgz /tmp/linux-amd64 \
    && helm version --short

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
# the Makefile target stages helm/store here (chart/) right before the build;
# Docker cannot copy paths outside the context, so the chart rides along
COPY chart /charts/store

RUN useradd -u 1000 -m provisioner
USER 1000

EXPOSE 9000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
