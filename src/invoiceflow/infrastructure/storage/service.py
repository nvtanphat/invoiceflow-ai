import os
import uuid
from abc import ABC, abstractmethod


class StoragePort(ABC):
    @abstractmethod
    async def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        """Save bytes and return immutable storage URI."""
        pass

    @abstractmethod
    async def get(self, uri: str) -> bytes:
        """Retrieve bytes by storage URI."""
        pass

    @abstractmethod
    async def get_local_path(self, uri: str) -> str:
        """Return local filesystem path if available, or download to temporary path."""
        pass


class LocalStorageService(StoragePort):
    def __init__(self, base_dir: str = "./data/storage"):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    async def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        tenant_dir = os.path.join(self.base_dir, str(tenant_id))
        os.makedirs(tenant_dir, exist_ok=True)
        unique_name = f"{uuid.uuid4()}_{filename}"
        full_path = os.path.join(tenant_dir, unique_name)

        with open(full_path, "wb") as f:
            f.write(content)

        return f"local://{tenant_id}/{unique_name}"

    async def get(self, uri: str) -> bytes:
        local_path = await self.get_local_path(uri)
        with open(local_path, "rb") as f:
            return f.read()

    async def get_local_path(self, uri: str) -> str:
        if not uri.startswith("local://"):
            raise ValueError(f"Invalid URI scheme for local storage: {uri}")
        relative = uri.replace("local://", "").replace("/", os.sep)
        return os.path.join(self.base_dir, relative)


class S3StorageService(StoragePort):
    """S3-compatible object storage service (MinIO, AWS S3, Cloudflare R2)."""

    def __init__(
        self,
        endpoint_url: str = "http://localhost:9000",
        access_key: str = "minioadmin",
        secret_key: str = "minioadmin",
        bucket_name: str = "invoiceflow-documents",
        region_name: str = "us-east-1",
    ):
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.region_name = region_name
        self._s3_client = None

    def _get_client(self):
        if self._s3_client is None:
            import boto3

            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region_name,
            )
            try:
                self._s3_client.create_bucket(Bucket=self.bucket_name)
            except Exception:
                pass
        return self._s3_client

    async def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        unique_name = f"{uuid.uuid4()}_{filename}"
        key = f"{tenant_id}/{unique_name}"
        client = self._get_client()
        client.put_object(Bucket=self.bucket_name, Key=key, Body=content)
        return f"s3://{self.bucket_name}/{key}"

    async def get(self, uri: str) -> bytes:
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid URI scheme for S3 storage: {uri}")
        parts = uri.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1]
        client = self._get_client()
        res = client.get_object(Bucket=bucket, Key=key)
        return res["Body"].read()

    async def get_local_path(self, uri: str) -> str:
        content = await self.get(uri)
        import tempfile

        ext = os.path.splitext(uri)[1]
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(content)
            return f.name

