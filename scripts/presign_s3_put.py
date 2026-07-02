#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import subprocess
from urllib.parse import quote, urlencode, urlparse


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError("Expected an S3 object URI like s3://bucket/path/to/object")
    return parsed.netloc, parsed.path.lstrip("/")


def aws_cli_credentials() -> dict[str, str]:
    output = subprocess.check_output(
        ["aws", "configure", "export-credentials", "--format", "process"],
        text=True,
    )
    credentials = json.loads(output)
    required = ["AccessKeyId", "SecretAccessKey"]
    missing = [key for key in required if not credentials.get(key)]
    if missing:
        raise RuntimeError(f"AWS credential export is missing {', '.join(missing)}")
    return credentials


def sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_access_key: str, date_stamp: str, region: str) -> bytes:
    date_key = sign(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
    date_region_key = sign(date_key, region)
    date_region_service_key = sign(date_region_key, "s3")
    return sign(date_region_service_key, "aws4_request")


def presign_put_url(uri: str, region: str, expires_in: int) -> str:
    bucket, key = parse_s3_uri(uri)
    credentials = aws_cli_credentials()
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    host = f"{bucket}.s3.{region}.amazonaws.com"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    signed_headers = "host"
    query: dict[str, str] = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{credentials['AccessKeyId']}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_in),
        "X-Amz-SignedHeaders": signed_headers,
    }
    if credentials.get("SessionToken"):
        query["X-Amz-Security-Token"] = credentials["SessionToken"]

    canonical_uri = "/" + quote(key, safe="/~")
    canonical_query = urlencode(sorted(query.items()), quote_via=quote, safe="-_.~")
    canonical_headers = f"host:{host}\n"
    canonical_request = "\n".join(
        [
            "PUT",
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        signing_key(credentials["SecretAccessKey"], date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"https://{host}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a presigned S3 PUT URL for one object.")
    parser.add_argument("s3_uri", help="Destination object URI, for example s3://bucket/path/file.fastq.gz")
    parser.add_argument("--region", default="us-east-1", help="AWS region for the bucket")
    parser.add_argument("--expires-in", type=int, default=3600, help="Seconds until the URL expires")
    args = parser.parse_args()
    if args.expires_in < 1 or args.expires_in > 604800:
        raise SystemExit("--expires-in must be between 1 and 604800 seconds")
    print(presign_put_url(args.s3_uri, args.region, args.expires_in))


if __name__ == "__main__":
    main()
