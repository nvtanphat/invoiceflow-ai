from abc import ABC, abstractmethod
import os
import re
import tempfile
import uuid


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

    def _sanitize_tenant(self, tenant_id: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_-]", "", str(tenant_id))
        if not clean:
            raise ValueError(f"Invalid tenant_id format: {tenant_id}")
        return clean

    def _sanitize_filename(self, filename: str) -> str:
        base = os.path.basename(str(filename))
        clean = re.sub(r"[^\w\s.-]", "", base).strip()
        return clean or "unnamed_document"

    async def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        safe_tenant = self._sanitize_tenant(tenant_id)
        safe_filename = self._sanitize_filename(filename)

        tenant_dir = os.path.abspath(os.path.join(self.base_dir, safe_tenant))
        if not tenant_dir.startswith(self.base_dir + os.sep) and tenant_dir != self.base_dir:
            raise ValueError(f"Path traversal detected in tenant directory: {tenant_id}")

        os.makedirs(tenant_dir, exist_ok=True)
        unique_name = f"{uuid.uuid4()}_{safe_filename}"
        full_path = os.path.abspath(os.path.join(tenant_dir, unique_name))

        if not full_path.startswith(self.base_dir + os.sep):
            raise ValueError(f"Path traversal detected in target file path: {filename}")

        with open(full_path, "wb") as f:
            f.write(content)

        return f"local://{safe_tenant}/{unique_name}"

    async def get(self, uri: str) -> bytes:
        local_path = await self.get_local_path(uri)
        with open(local_path, "rb") as f:
            return f.read()

    async def get_local_path(self, uri: str) -> str:
        if not uri.startswith("local://"):
            raise ValueError(f"Invalid URI scheme for local storage: {uri}")

        relative = uri.replace("local://", "").replace("/", os.sep)
        full_path = os.path.abspath(os.path.join(self.base_dir, relative))

        # Strict containment validation
        if not full_path.startswith(self.base_dir + os.sep) and full_path != self.base_dir:
            raise ValueError(f"Path traversal attempt blocked: {uri}")

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Storage object does not exist: {uri}")

        return full_path


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

    def _sanitize_tenant(self, tenant_id: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_-]", "", str(tenant_id))
        if not clean:
            raise ValueError(f"Invalid tenant_id format: {tenant_id}")
        return clean

    def _sanitize_filename(self, filename: str) -> str:
        base = os.path.basename(str(filename))
        clean = re.sub(r"[^\w\s.-]", "", base).strip()
        return clean or "unnamed_document"

    async def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        safe_tenant = self._sanitize_tenant(tenant_id)
        safe_filename = self._sanitize_filename(filename)
        unique_name = f"{uuid.uuid4()}_{safe_filename}"
        key = f"{safe_tenant}/{unique_name}"

        client = self._get_client()
        client.put_object(Bucket=self.bucket_name, Key=key, Body=content)
        return f"s3://{self.bucket_name}/{key}"

    async def get(self, uri: str) -> bytes:
        if not uri.startswith("s3://"):
            raise ValueError(f"Invalid URI scheme for S3 storage: {uri}")

        parts = uri.replace("s3://", "").split("/", 1)
        if len(parts) < 2:
            raise ValueError(f"Malformed S3 storage URI: {uri}")

        bucket, key = parts[0], parts[1]
        if bucket != self.bucket_name:
            raise ValueError(
                f"Unauthorized bucket access attempt: URI references '{bucket}' but service is locked to '{self.bucket_name}'."
            )

        client = self._get_client()
        res = client.get_object(Bucket=bucket, Key=key)
        return res["Body"].read()

    async def get_local_path(self, uri: str) -> str:
        content = await self.get(uri)
        ext = os.path.splitext(uri)[1]
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(content)
            return f.name
