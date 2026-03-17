"""Enable AutoTrading in MT5 by sending Ctrl+E keystroke via pyautogui."""
import sys
sys.path.insert(0, '.')
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# Find MT5 window
def find_mt5():
    result = [None]
    def cb(hwnd, _):
        l = user32.GetWindowTextLengthW(hwnd)
        if l > 0:
            buf = ctypes.create_unicode_buffer(l + 1)
            user32.GetWindowTextW(hwnd, buf, l + 1)
            if 'Exness' in buf.value and ('Demo' in buf.value or 'MT5' in buf.value):
                result[0] = hwnd
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result[0]

hwnd = find_mt5()
if not hwnd:
    print("MT5 window not found!")
    sys.exit(1)

# Bring MT5 to foreground
user32.ShowWindow(hwnd, 9)  # SW_RESTORE
time.sleep(0.3)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)

# Use pyautogui to send Ctrl+E (real input simulation)
import pyautogui
pyautogui.PAUSE = 0.1
pyautogui.hotkey('ctrl', 'e')
time.sleep(1.5)

# Check result
from core.mt5_lock import mt5_safe as mt5
mt5.initialize()
info = mt5.terminal_info()
print(f"AutoTrading enabled: {info.trade_allowed}")

if info.trade_allowed:
    print("SUCCESS! AutoTrading is now ON.")
else:
    print("Still off — trying again with direct keybd_event...")
    # Fallback: use keybd_event
    KEYEVENTF_KEYUP = 0x0002
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
    time.sleep(0.05)
    user32.keybd_event(0x45, 0, 0, 0)  # E down
    time.sleep(0.05)
    user32.keybd_event(0x45, 0, KEYEVENTF_KEYUP, 0)  # E up
    time.sleep(0.05)
    user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)  # Ctrl up
    time.sleep(1.5)
    
    info = mt5.terminal_info()
    print(f"AutoTrading enabled (attempt 2): {info.trade_allowed}")
