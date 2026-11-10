"""InvoiceFlow AI package."""

import os
import sys

_DLL_HANDLES: list[object] = []

if sys.platform == "win32":
    try:
        import site

        for p in site.getsitepackages():
            torch_lib = os.path.join(p, "torch", "lib")
            if os.path.isdir(torch_lib):
                _DLL_HANDLES.append(os.add_dll_directory(torch_lib))
        import torch  # noqa: F401  # Pre-initialize PyTorch runtime and DLLs on Windows
    except Exception:
        pass

__version__ = "0.1.0"
