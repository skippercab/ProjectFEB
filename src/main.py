#!/usr/bin/env python3
"""Main entry point for Rider."""

import ctypes
import ctypes.util
import sys
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from projectfeb.core.config import Config
from projectfeb.utils.logging import setup_logging


def _configure_macos_app_identity(app_name: str = "Rider") -> None:
    """Set the macOS process name so the Dock uses Rider instead of python."""
    if sys.platform != "darwin":
        return

    try:
        libc_path = ctypes.util.find_library("c")
        objc_path = ctypes.util.find_library("objc")
        foundation_path = ctypes.util.find_library("Foundation")
        if libc_path:
            libc = ctypes.cdll.LoadLibrary(libc_path)
            if hasattr(libc, "setprogname"):
                libc.setprogname.argtypes = [ctypes.c_char_p]
                libc.setprogname.restype = None
                libc.setprogname(app_name.encode("utf-8"))

        if not objc_path or not foundation_path:
            return

        objc = ctypes.cdll.LoadLibrary(objc_path)
        ctypes.cdll.LoadLibrary(foundation_path)

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def send_message(
            receiver: int,
            selector: str,
            *args: object,
            restype: object = ctypes.c_void_p,
            argtypes: list[object] | None = None,
        ) -> int:
            objc.objc_msgSend.restype = restype
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *(argtypes or [])]
            return objc.objc_msgSend(
                receiver,
                objc.sel_registerName(selector.encode("utf-8")),
                *args,
            )

        ns_string_class = objc.objc_getClass(b"NSString")
        process_info_class = objc.objc_getClass(b"NSProcessInfo")
        if not ns_string_class or not process_info_class:
            return

        ns_app_name = send_message(
            send_message(ns_string_class, "alloc"),
            "initWithUTF8String:",
            app_name.encode("utf-8"),
            argtypes=[ctypes.c_char_p],
        )
        process_info = send_message(process_info_class, "processInfo")
        send_message(process_info, "setProcessName:", ns_app_name, argtypes=[ctypes.c_void_p])
    except Exception:
        return

def main():
    """Main application entry point."""
    _configure_macos_app_identity()

    try:
        from projectfeb.ui.main_window import ProjectFEBApp
    except ModuleNotFoundError as exc:
        if exc.name == "_tkinter":
            raise SystemExit(
                "Rider requires a Python build with Tk support. "
                "The current interpreter is missing _tkinter. "
                "On macOS, create a venv from a Tk-enabled Python 3.10+ interpreter "
                "and verify it with `python -c \"import tkinter\"` before launching Rider."
            ) from exc
        raise

    # Set up logging
    setup_logging()

    # Load configuration
    config = Config()

    # Create and run the application
    app = ProjectFEBApp(config)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()

if __name__ == "__main__":
    main()