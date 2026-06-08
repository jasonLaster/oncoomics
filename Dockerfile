FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/diana-omics/py/src
ENV DIANA_OMICS_ROOT=/opt/diana-omics

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
        rsync \
        samtools \
        seqkit \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/diana-aws/bin \
    && printf '%s\n' '#!/bin/sh' 'export AWS_CA_BUNDLE="${AWS_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"' 'exec /usr/bin/aws "$@"' > /opt/diana-aws/bin/aws \
    && chmod +x /opt/diana-aws/bin/aws

WORKDIR /opt/diana-omics
COPY . /opt/diana-omics

RUN python3 -m pip install --break-system-packages -e 'py[dev]'

CMD ["python3", "-m", "diana_omics", "--help"]
