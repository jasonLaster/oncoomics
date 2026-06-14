FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/diana-omics/src
ENV DIANA_OMICS_ROOT=/opt/diana-omics
ARG S5CMD_VERSION=2.3.0
ARG MICROMAMBA_VERSION=latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        aria2 \
        awscli \
        bcftools \
        bwa \
        bzip2 \
        ca-certificates \
        curl \
        gzip \
        openjdk-17-jre-headless \
        procps \
        python3 \
        python3-pip \
        pigz \
        rsync \
        samtools \
        seqkit \
        sra-toolkit \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN aria2c --version

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) mamba_arch="64" ;; \
        arm64) mamba_arch="aarch64" ;; \
        *) echo "Unsupported micromamba architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fSL --retry 5 --retry-all-errors --retry-delay 5 "https://micro.mamba.pm/api/micromamba/linux-${mamba_arch}/${MICROMAMBA_VERSION}" \
        | tar -xj -C /usr/local/bin --strip-components=1 bin/micromamba; \
    MAMBA_ROOT_PREFIX=/opt/micromamba micromamba install -y -n base -c conda-forge -c bioconda bwa-mem2 minimap2; \
    for exe in /opt/micromamba/bin/bwa-mem2* /opt/micromamba/bin/minimap2; do \
        ln -sf "$exe" "/usr/local/bin/$(basename "$exe")"; \
    done; \
    MAMBA_ROOT_PREFIX=/opt/micromamba micromamba clean --all --yes; \
    bwa-mem2 version; \
    minimap2 --version

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) s5_arch="Linux-64bit" ;; \
        arm64) s5_arch="Linux-arm64" ;; \
        *) echo "Unsupported s5cmd architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/s5cmd.tar.gz "https://github.com/peak/s5cmd/releases/download/v${S5CMD_VERSION}/s5cmd_${S5CMD_VERSION}_${s5_arch}.tar.gz"; \
    tar -xzf /tmp/s5cmd.tar.gz -C /usr/local/bin s5cmd; \
    chmod +x /usr/local/bin/s5cmd; \
    rm -f /tmp/s5cmd.tar.gz; \
    s5cmd version

RUN mkdir -p /opt/diana-aws/bin \
    && printf '%s\n' '#!/bin/sh' 'export AWS_CA_BUNDLE="${AWS_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"' 'exec /usr/bin/aws "$@"' > /opt/diana-aws/bin/aws \
    && chmod +x /opt/diana-aws/bin/aws

WORKDIR /opt/diana-omics
COPY . /opt/diana-omics

RUN python3 -m pip install --break-system-packages -e '.[dev]'

CMD ["python3", "-m", "diana_omics", "--help"]
