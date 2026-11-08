import os
import shutil
import tempfile
import pytest


@pytest.mark.asyncio
async def test_local_storage_put_and_get():
    from invoiceflow.infrastructure.storage.service import LocalStorageService

    tmp_dir = tempfile.mkdtemp()
    try:
        storage = LocalStorageService(base_dir=tmp_dir)
        content = b"sample document payload"
        uri = await storage.save(
            tenant_id="tenant-123",
            filename="test.pdf",
            content=content,
        )
        assert uri.startswith("local://")

        retrieved = await storage.get(uri)
        assert retrieved == content

        # Check signed / download path exists
        local_path = await storage.get_local_path(uri)
        assert os.path.exists(local_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
