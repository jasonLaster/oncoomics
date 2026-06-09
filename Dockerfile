FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/diana-omics/py/src
ENV DIANA_OMICS_ROOT=/opt/diana-omics
ARG S5CMD_VERSION=2.3.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        aria2 \
        awscli \
        bcftools \
        bwa \
        ca-certificates \
        curl \
        gzip \
        openjdk-17-jre-headless \
        python3 \
        python3-pip \
        pigz \
        rsync \
        samtools \
        seqkit \
        sra-toolkit \
        unzip \
    && rm -rf /var/lib/apt/lists/*

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

RUN python3 -m pip install --break-system-packages -e 'py[dev]'

CMD ["python3", "-m", "diana_omics", "--help"]
