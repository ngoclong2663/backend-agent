import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from .object_storage import IObjectStorage, StoredObject

# Epic 29 (Story 29.1): the type a read URL answers with, by the key's extension, so players and subtitle tracks load
CONTENT_TYPES = {
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "wav": "audio/wav",
    "vtt": "text/vtt",
    "srt": "application/x-subrip",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "pdf": "application/pdf",
}


class S3ObjectStorage(IObjectStorage):
    """boto3 against S3, or any S3-compatible server (`STORAGE_ENDPOINT`; empty: AWS). URLs for a browser are signed
    for `STORAGE_PUBLIC_ENDPOINT`, the address it reaches the server at (the signature covers the host)."""

    def __init__(
        self,
        endpoint: str,
        public_endpoint: str,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
    ):
        self.bucket = bucket
        self.client = self._client(endpoint, region, access_key, secret_key)
        self.public = self._client(public_endpoint or endpoint, region, access_key, secret_key)

    @staticmethod
    def _client(endpoint: str, region: str, access_key: str, secret_key: str) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=region,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_upload(self, key: str, content_type: str, expires_in: int) -> str:
        params = {"Bucket": self.bucket, "Key": key, "ContentType": content_type}
        return self.public.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in)

    def signed_url(self, key: str, expires_in: int) -> str:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        # Epic 29: a player needs the file's own type (and range requests, which S3 answers for GETs)
        content_type = CONTENT_TYPES.get(key.rsplit(".", 1)[-1].lower()) if "." in key else None
        if content_type:
            params["ResponseContentType"] = content_type
        return self.public.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)

    def stat(self, key: str) -> StoredObject | None:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return StoredObject(size=head["ContentLength"], content_type=head.get("ContentType") or "")

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def ensure_bucket(self, cors_origins: list[str]) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
        rule = {
            "AllowedOrigins": cors_origins or ["*"],
            "AllowedMethods": ["GET", "PUT"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3600,
        }
        self.client.put_bucket_cors(Bucket=self.bucket, CORSConfiguration={"CORSRules": [rule]})
