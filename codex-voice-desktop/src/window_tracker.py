import ctypes
import json
import time
from ctypes import wintypes


USER32 = ctypes.windll.user32
KERNEL32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
USER32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
USER32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]


def window_title(hwnd):
    length = USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value


def process_path(pid):
    handle = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(4096)
        buff = ctypes.create_unicode_buffer(size.value)
        ok = KERNEL32.QueryFullProcessImageNameW(handle, 0, buff, ctypes.byref(size))
        return buff.value if ok else ""
    finally:
        KERNEL32.CloseHandle(handle)


def rect_for(hwnd):
    rect = RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect


def is_codex_window(title, path, width, height):
    normalized = path.lower()
    if "openai.codex_" in normalized and normalized.endswith("chatgpt.exe"):
        return True
    if "\\codex\\" in normalized and normalized.endswith("chatgpt.exe"):
        return True
    if title == "ChatGPT" and "openai.codex" in normalized:
        return True
    return title == "ChatGPT" and width >= 700 and height >= 400


def find_codex_window():
    candidates = []

    def callback(hwnd, _lparam):
        if not USER32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        if not title:
            return True
        pid = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = process_path(pid.value)
        rect = rect_for(hwnd)
        if rect is None:
            return True
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return True
        if not is_codex_window(title, path, width, height):
            return True
        candidates.append({
            "found": True,
            "hwnd": int(hwnd),
            "pid": int(pid.value),
            "title": title,
            "left": int(rect.left),
            "top": int(rect.top),
            "right": int(rect.right),
            "bottom": int(rect.bottom),
            "width": int(width),
            "height": int(height),
            "minimized": bool(USER32.IsIconic(hwnd)),
        })
        return True

    USER32.EnumWindows(EnumWindowsProc(callback), 0)
    if not candidates:
        return {"found": False}
    candidates.sort(key=lambda item: item["width"] * item["height"], reverse=True)
    return candidates[0]


def main():
    while True:
        print(json.dumps(find_codex_window(), ensure_ascii=False), flush=True)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
