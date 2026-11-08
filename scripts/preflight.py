import asyncio
import sys
from pathlib import Path

# Ensure src/ is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from invoiceflow.config import get_settings
from invoiceflow.infrastructure.database.session import DatabaseSessionManager


async def check_database(db_url: str) -> bool:
    print(f"[*] Checking database connection ({db_url})...", end=" ")
    try:
        db_manager = DatabaseSessionManager(database_url=db_url, echo=False)
        await db_manager.create_tables()
        await db_manager.close()
        print("[OK]")
        return True
    except Exception as exc:
        print(f"[FAIL] ({exc})")
        return False


def check_storage(storage_root: str) -> bool:
    print(f"[*] Checking local storage directory ({storage_root})...", end=" ")
    try:
        p = Path(storage_root)
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / ".preflight_probe"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print("[OK]")
        return True
    except Exception as exc:
        print(f"[FAIL] ({exc})")
        return False


def check_ai_provider() -> bool:
    settings = get_settings()
    print("[*] Checking AI provider configuration...", end=" ")
    if settings.LLM_PROVIDER == "openai":
        if settings.OPENAI_API_KEY:
            print(f"[OK] (Provider: OpenAI/ModelAPI, Model: {settings.OPENAI_MODEL_ID}, Base URL: {settings.OPENAI_BASE_URL})")
            return True
        else:
            print("[WARN] (OPENAI_API_KEY is empty; system will use Mock/Offline Fallback)")
            return True
    else:
        if settings.GEMINI_API_KEY:
            print(f"[OK] (Provider: Gemini, Model: {settings.GEMINI_MODEL_ID})")
            return True
        else:
            print("[WARN] (GEMINI_API_KEY is empty; system will use Mock/Offline Fallback)")
            return True


async def main() -> int:
    print("=" * 60)
    print(" InvoiceFlow AI - System Preflight Verification")
    print("=" * 60)
    settings = get_settings()
    
    db_ok = await check_database(settings.DATABASE_URL)
    storage_ok = check_storage(settings.LOCAL_STORAGE_DIR)
    _ = check_ai_provider()

    if db_ok and storage_ok:
        print("\nAll critical preflight checks passed successfully.")
        return 0
    else:
        print("\nPreflight checks failed. Please inspect errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
