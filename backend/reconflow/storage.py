import hashlib
import io
import json
import warnings

import boto3
from PIL import Image
from pypdf import PdfReader

from reconflow.config import settings


def client(service):
    config = settings()
    local_credentials = (
        {"aws_access_key_id": "local", "aws_secret_access_key": "local"}
        if config.aws_endpoint_url
        else {}
    )
    return boto3.client(
        service,
        region_name=config.aws_region,
        endpoint_url=config.aws_endpoint_url,
        **local_credentials,
    )


def validate_document(content: bytes):
    if not content or len(content) > settings().max_upload_bytes:
        raise ValueError("Dateien dürfen höchstens 4 MB groß sein.")
    if content.startswith(b"%PDF-"):
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 5:
                raise ValueError("PDF benötigt 1 bis 5 Seiten und darf nicht verschlüsselt sein.")
            return "application/pdf"
        except Exception as exc:
            raise ValueError(
                "Ungültige oder verschlüsselte PDF. Erlaubt sind höchstens fünf Seiten."
            ) from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"PNG", "JPEG"} or image.width * image.height > 20000000:
                    raise ValueError("Nicht unterstütztes Bild")
                mime = "image/png" if image.format == "PNG" else "image/jpeg"
                image.verify()
                return mime
    except Exception as exc:
        raise ValueError("Bitte eine gültige PDF-, JPG- oder PNG-Datei verwenden.") from exc


def digest(content):
    return hashlib.sha256(content).hexdigest()


def put(key, content, mime):
    client("s3").put_object(
        Bucket=settings().s3_bucket,
        Key=key,
        Body=content,
        ContentType=mime,
        ServerSideEncryption="AES256",
    )


def get(key):
    return client("s3").get_object(Bucket=settings().s3_bucket, Key=key)["Body"].read()


def enqueue(job_id):
    client("sqs").send_message(
        QueueUrl=settings().sqs_queue_url, MessageBody=json.dumps({"job_id": job_id})
    )
