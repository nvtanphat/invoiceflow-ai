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
