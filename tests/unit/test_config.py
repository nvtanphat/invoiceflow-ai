import os
import pytest
from pydantic import ValidationError


def test_settings_load_defaults():
    from invoiceflow.config import Settings

    settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        JWT_SECRET="test-secret-key-at-least-32-chars-long!",
    )
    assert settings.APP_NAME == "InvoiceFlow AI"
    assert settings.APP_ENV == "development"
    assert settings.API_V1_STR == "/api/v1"
    assert settings.STORAGE_KIND in ("local", "s3")
    assert settings.MAX_UPLOAD_SIZE_BYTES == 25 * 1024 * 1024


def test_settings_requires_jwt_secret():
    from invoiceflow.config import Settings

    # Missing JWT_SECRET or invalid short secret raises ValidationError
    with pytest.raises(ValidationError):
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            JWT_SECRET="short",
        )
