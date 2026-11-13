from botocore.exceptions import ClientError

from reconflow.config import settings
from reconflow.migrate import migrate
from reconflow.storage import client


def bootstrap():
    migrate()
    config = settings()
    # Cloud infrastructure is created only by Terraform, not by application startup.
    if config.aws_endpoint_url:
        try:
            client("s3").create_bucket(
                Bucket=config.s3_bucket,
                CreateBucketConfiguration={"LocationConstraint": config.aws_region},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
        client("sqs").create_queue(
            QueueName="reconflow-jobs", Attributes={"VisibilityTimeout": "1080"}
        )
    print("ReconFlow database and local services ready")


if __name__ == "__main__":
    bootstrap()
