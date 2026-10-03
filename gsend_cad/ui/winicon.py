"""Windows taskbar icon from the app files (no exe rebuild, no re-signing).

The taskbar button (and a pin made from it) takes its picture from the window's AppUserModel
properties, falling back to the .exe's embedded icon (a generic square on older builds, whose
icon wasn't square). This sets the window's relaunch icon to our .ico, plus the window's big /
small icons straight from the .ico. Everything is best-effort: any failure leaves Qt's icon.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

APP_ID = "GSEND.CADCAM"


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        super().__init__()
        h = s.strip("{}").replace("-", "")
        self.d1, self.d2, self.d3 = int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16)
        for k in range(8):
            self.d4[k] = int(h[16 + 2 * k:18 + 2 * k], 16)


class _PKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


_FMT = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"     # PKEY_AppUserModel_*
_ID, _CMD, _ICON, _NAME = 5, 2, 3, 4
_IID_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_VT_LPWSTR = 31


def _set_props(hwnd: int, props: dict):
    shell = ctypes.windll.shell32
    store = ctypes.c_void_p()
    if shell.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(_GUID(_IID_STORE)),
                                         ctypes.byref(store)) != 0 or not store:
        return
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PKEY), ctypes.POINTER(_PROPVARIANT))
    set_value = proto(vtbl[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    keep = []
    try:
        for pid, text in props.items():
            buf = ctypes.create_unicode_buffer(text)
            keep.append(buf)
            pv = _PROPVARIANT(vt=_VT_LPWSTR, p=ctypes.cast(buf, ctypes.c_void_p))
            set_value(store, ctypes.byref(_PKEY(_GUID(_FMT), pid)), ctypes.byref(pv))
        commit(store)
    finally:
        release(store)


def _set_icons(hwnd: int, ico: str):
    user = ctypes.windll.user32
    user.LoadImageW.restype = wintypes.HANDLE
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    for which, metric_x, metric_y in ((1, 11, 12), (0, 49, 50)):     # ICON_BIG (SM_CXICON), ICON_SMALL
        h = user.LoadImageW(None, ico, 1, user.GetSystemMetrics(metric_x), user.GetSystemMetrics(metric_y), 0x10)
        if h:
            user.SendMessageW(wintypes.HWND(hwnd), 0x0080, which, h)    # WM_SETICON


def apply(widget, ico: str):
    """Give a top-level window our taskbar icon (Windows only; quietly does nothing elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        exe = sys.executable
        _set_props(hwnd, {_ID: APP_ID, _CMD: f'"{exe}"', _ICON: f"{ico},0", _NAME: "G-SEND CAD/CAM"})
        _set_icons(hwnd, ico)
    except Exception:                       # never let the icon stop the app
        pass
