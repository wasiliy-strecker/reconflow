"""Small control records in the existing private document bucket."""

import json
from functools import lru_cache

import boto3
from botocore.config import Config

from reconflow.config import settings
from reconflow.db import dumps

PREFIX = "benchmarks/"


@lru_cache
def client():
    c = settings()
    local = (
        {"aws_access_key_id": "local", "aws_secret_access_key": "local"}
        if c.aws_endpoint_url
        else {}
    )
    return boto3.client(
        "s3",
        region_name=c.aws_region,
        endpoint_url=c.aws_endpoint_url,
        config=Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"total_max_attempts": 2},
            signature_version="s3v4",
        ),
        **local,
    )


def put(key, value):
    client().put_object(
        Bucket=settings().s3_bucket,
        Key=PREFIX + key,
        Body=dumps(value).encode(),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )


def get(key):
    try:
        with client().get_object(Bucket=settings().s3_bucket, Key=PREFIX + key)["Body"] as body:
            return json.loads(body.read())
    except client().exceptions.NoSuchKey:
        return None


def remove(key):
    client().delete_object(Bucket=settings().s3_bucket, Key=PREFIX + key)


def controls():
    for page in (
        client()
        .get_paginator("list_objects_v2")
        .paginate(Bucket=settings().s3_bucket, Prefix=PREFIX + "control/")
    ):
        for row in page.get("Contents", []):
            yield row["Key"].rsplit("/", 1)[-1].removesuffix(".json")


def artifact_url():
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings().s3_bucket, "Key": settings().gpu_runner_artifact_key},
        ExpiresIn=600,
    )
