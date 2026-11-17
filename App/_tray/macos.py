"""macOS: keep the tray app in the menu bar only, with no Dock icon. Stdlib only (ctypes).

A Qt app started from Python shows a "Python" icon in the Dock; a menu-bar app should not. This
asks AppKit for the "accessory" activation policy, which is what an app bundle's LSUIElement
setting does. Anything unexpected leaves the app as it was: a Dock icon is cosmetic.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

ACCESSORY = 1  # NSApplicationActivationPolicyAccessory: no Dock icon, no menu bar of its own


def _runtime():
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))  # registers NSApplication
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    return objc, address


def _shared_application():
    objc, address = _runtime()
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    return objc, address, send(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"))


def menu_bar_only() -> bool:
    """On macOS, drop the Dock icon; returns whether AppKit accepted. Elsewhere, False."""
    if sys.platform != "darwin":
        return False
    try:
        objc, address, app = _shared_application()
        if not app:
            return False
        set_policy = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(address)
        return bool(set_policy(app, objc.sel_registerName(b"setActivationPolicy:"), ACCESSORY))
    except (OSError, AttributeError, TypeError, ValueError):
        return False


def activation_policy() -> int | None:
    """The app's current activation policy (0 regular, 1 accessory, 2 prohibited), for checks."""
    if sys.platform != "darwin":
        return None
    try:
        objc, address, app = _shared_application()
        get_policy = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(address)
        return int(get_policy(app, objc.sel_registerName(b"activationPolicy")))
    except (OSError, AttributeError, TypeError, ValueError):
        return None
