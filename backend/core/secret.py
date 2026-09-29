# -*- coding: utf-8 -*-
"""API Key 本地加密（Windows DPAPI，无新依赖；非 Windows 回退明文）

settings.json 中的 cloud.api_key 明文存放是既定风险（v2 §11）。
本模块用 Windows DPAPI（CryptProtectData）做本机绑定加密：
换机器/换用户无法解密，适合单机自用。加密后以 ENC(...) 包裹存储，
读取时自动解密；解密失败返回空串并提示重填，不阻断启动。
"""

import base64
import sys


def _dpapi_protect(plain: str) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            # pbData 必须用 c_void_p：c_char_p 取值会在第一个 NUL 处截断，
            # 再传给 string_at/LocalFree 会读错内存，直接崩解释器进程
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL

        raw = plain.encode("utf-8")
        buf = ctypes.create_string_buffer(raw)
        inp = DATA_BLOB(len(raw), ctypes.addressof(buf))
        out = DATA_BLOB()
        ok = crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return None
        try:
            enc = ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)
        return base64.b64encode(enc).decode("ascii")
    except Exception:
        return None


def _dpapi_unprotect(b64: str) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            # 同上，pbData 用 c_void_p 防止 NUL 截断导致崩进程
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL

        raw = base64.b64decode(b64)
        buf = ctypes.create_string_buffer(raw, len(raw))
        inp = DATA_BLOB(len(raw), ctypes.addressof(buf))
        out = DATA_BLOB()
        ok = crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return None
        try:
            plain = ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(out.pbData)
        return plain.decode("utf-8", errors="ignore")
    except Exception:
        return None


def encrypt_key(plain: str) -> str:
    """加密，明文为空直接返回空；非 Windows 或失败时原文返回（兼容旧库）"""
    if not plain:
        return ""
    if plain.startswith("ENC(") and plain.endswith(")"):
        return plain
    if sys.platform != "win32":
        return plain
    enc = _dpapi_protect(plain)
    return f"ENC({enc})" if enc else plain


def decrypt_key(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("ENC(") and stored.endswith(")"):
        b64 = stored[4:-1]
        if sys.platform != "win32":
            return ""
        plain = _dpapi_unprotect(b64)
        return plain if plain is not None else ""
    return stored
