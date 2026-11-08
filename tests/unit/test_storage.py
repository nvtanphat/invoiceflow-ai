import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from invoiceflow.infrastructure.storage.service import LocalStorageService, S3StorageService


@pytest.mark.asyncio
async def test_local_storage_put_and_get():
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

        local_path = await storage.get_local_path(uri)
        assert os.path.exists(local_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_s3_storage_put_and_get():
    mock_boto_client = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = b"s3 sample binary content"
    mock_boto_client.get_object.return_value = {"Body": mock_body}

    with patch("boto3.client", return_value=mock_boto_client):
        storage = S3StorageService(
            endpoint_url="http://s3.local:9000",
            bucket_name="test-bucket",
        )
        uri = await storage.save("tenant-abc", "sample.pdf", b"s3 sample binary content")
        assert uri.startswith("s3://test-bucket/tenant-abc/")
        assert "sample.pdf" in uri

        mock_boto_client.put_object.assert_called_once()
        call_kwargs = mock_boto_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"s3 sample binary content"

        content = await storage.get(uri)
        assert content == b"s3 sample binary content"

        local_path = await storage.get_local_path(uri)
        assert os.path.exists(local_path)
        with open(local_path, "rb") as f:
            assert f.read() == b"s3 sample binary content"
        os.remove(local_path)


@pytest.mark.asyncio
async def test_s3_storage_invalid_uri():
    storage = S3StorageService()
    with pytest.raises(ValueError, match="Invalid URI scheme"):
        await storage.get("local://invalid/path.pdf")
