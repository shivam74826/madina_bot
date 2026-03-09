"""
=============================================================================
FOREX AI TRADING BOT - UTILITIES & DIAGNOSTICS
=============================================================================
All utility, test, and diagnostic scripts consolidated into one file.
Run:  python utilities.py
Then pick a tool from the menu, or run directly:
    python utilities.py check_mt5
    python utilities.py check_status
    python utilities.py check_symbols
    ...

Add new utilities as functions below and register them in TOOLS dict.
=============================================================================
"""

import sys
import os
import time

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════════════════
# 1. CHECK MT5 CONNECTION
# ═══════════════════════════════════════════════════════════════════════════
def check_mt5():
    """Quick check if MetaTrader 5 terminal is available."""
    import MetaTrader5 as mt5

    print("MT5 Python package: OK")
    print(f"Version: {mt5.__version__}")

    init = mt5.initialize()
    if init:
        print("MT5 Terminal: CONNECTED!")
        info = mt5.account_info()
        if info:
            print(f"Account: {info.login}")
            print(f"Server: {info.server}")
            print(f"Balance: ${info.balance}")
            print(f"Name: {info.name}")
        else:
            print("No account logged in yet")
        mt5.shutdown()
    else:
        error = mt5.last_error()
        print("MT5 Terminal: NOT FOUND")
        print(f"Error code: {error}")
        print()
        print("=== ACTION NEEDED ===")
        print("You need to install MetaTrader 5 desktop application.")
        print("Download from: https://www.metatrader5.com/en/download")
        print("After installing, open MT5 and create a demo account.")


# ═══════════════════════════════════════════════════════════════════════════
# 2. CHECK TERMINAL & ACCOUNT STATUS
# ═══════════════════════════════════════════════════════════════════════════
def check_status():
    """Full terminal and account status with BTC symbol info."""
    import MetaTrader5 as mt5

    if not mt5.initialize():
        print("FAILED to initialize MT5:", mt5.last_error())
        return

    t = mt5.terminal_info()
    print("=" * 50)
    print("TERMINAL STATUS")
    print("=" * 50)
    print(f"  trade_allowed: {t.trade_allowed}")
    print(f"  connected: {t.connected}")
    print(f"  path: {t.path}")

    a = mt5.account_info()
    print()
    print("=" * 50)
    print("ACCOUNT STATUS")
    print("=" * 50)
    print(f"  login: {a.login}")
    print(f"  balance: ${a.balance}")
    print(f"  equity: ${a.equity}")
    print(f"  account trade_allowed: {a.trade_allowed}")
    print(f"  trade_mode: {a.trade_mode}")

    # Check BTC
    if not mt5.symbol_select("BTC", True):
        print("\nBTC: Could not select symbol")
    else:
        s = mt5.symbol_info("BTC")
        print()
        print("=" * 50)
        print("BTC SYMBOL INFO")
        print("=" * 50)
        print(f"  name: {s.name}")
        print(f"  description: {s.description}")
        print(f"  bid: {s.bid}  ask: {s.ask}")
        print(f"  volume_min: {s.volume_min}")
        print(f"  filling_mode: {s.filling_mode}")
        print(f"  trade_mode: {s.trade_mode}")

        modes = []
        if s.filling_mode & 1: modes.append("FOK")
        if s.filling_mode & 2: modes.append("IOC")
        if s.filling_mode & 4: modes.append("RETURN")
        print(f"  supported fills: {modes if modes else ['RETURN (default)']}")

    print()
    if t.trade_allowed:
        print(">>> AutoTrading is ENABLED - ready to trade!")
    else:
        print(">>> AutoTrading is DISABLED!")
        print(">>> Click the 'Algo Trading' button in MT5 toolbar (green icon)")

    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 3. CHECK SYMBOLS (GOLD, BTC, CRYPTO)
# ═══════════════════════════════════════════════════════════════════════════
def check_symbols():
    """Search and list available Gold, BTC, and crypto symbols."""
    import MetaTrader5 as mt5

    mt5.initialize()

    print("=== GOLD SYMBOLS ===")
    gold = mt5.symbols_get("*XAU*")
    if gold:
        for s in gold:
            print(f"  {s.name} - {s.description} (trade: {s.trade_mode})")
    else:
        gold = mt5.symbols_get("*GOLD*")
        if gold:
            for s in gold:
                print(f"  {s.name} - {s.description} (trade: {s.trade_mode})")
        else:
            print("  No gold symbols found")

    print("\n=== BTC/CRYPTO SYMBOLS ===")
    btc = mt5.symbols_get("*BTC*")
    if btc:
        for s in btc:
            print(f"  {s.name} - {s.description} (trade: {s.trade_mode})")
    else:
        print("  No BTC symbols found")

    crypto = mt5.symbols_get("*CRYPTO*")
    if crypto:
        for s in crypto:
            print(f"  {s.name} - {s.description}")

    print("\n=== ALL TRADEABLE SYMBOLS (first 30) ===")
    all_symbols = mt5.symbols_get()
    tradeable = [s for s in all_symbols if s.trade_mode == 0 or s.visible]
    for s in tradeable[:30]:
        print(f"  {s.name:20s} | {s.description[:40]:40s} | visible={s.visible} | trade_mode={s.trade_mode}")

    print(f"\nTotal symbols: {len(all_symbols)}, Visible: {len([s for s in all_symbols if s.visible])}")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 4. CHECK SYMBOLS (DETAILED - XAUUSD, BTCUSD variants)
# ═══════════════════════════════════════════════════════════════════════════
def check_symbols_detail():
    """Detailed check of XAUUSD, BTCUSD, and BTC ETF symbols."""
    import MetaTrader5 as mt5

    mt5.initialize()

    xau = mt5.symbol_info("XAUUSD")
    if xau:
        print(f"XAUUSD: min_lot={xau.volume_min}, max_lot={xau.volume_max}, "
              f"step={xau.volume_step}, trade_mode={xau.trade_mode}, digits={xau.digits}")
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick:
            print(f"  Last price: bid={tick.bid}, ask={tick.ask}")
    else:
        print("XAUUSD: NOT AVAILABLE")

    for sym in ["BTCUSD", "BTCUSD.", "BTCUSDm"]:
        info = mt5.symbol_info(sym)
        if info:
            print(f"{sym}: min_lot={info.volume_min}, trade_mode={info.trade_mode}")

    for sym in ["BTC", "GBTC", "FBTC", "BTCO"]:
        info = mt5.symbol_info(sym)
        if info:
            print(f"{sym}: min_lot={info.volume_min}, trade_mode={info.trade_mode}, digits={info.digits}")
            mt5.symbol_select(sym, True)
            tick = mt5.symbol_info_tick(sym)
            if tick:
                print(f"  Last price: bid={tick.bid}, ask={tick.ask}")

    ok = mt5.symbol_select("XAUUSD", True)
    print(f"\nXAUUSD enabled: {ok}")

    vis = [s.name for s in mt5.symbols_get() if s.visible]
    print(f"Visible symbols: {vis}")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 5. ENABLE ALGO TRADING (Ctrl+E / keyboard method)
# ═══════════════════════════════════════════════════════════════════════════
def enable_algo_keyboard():
    """Enable AutoTrading by sending Ctrl+E keystroke to MT5."""
    import ctypes
    import ctypes.wintypes
    import MetaTrader5 as mt5

    user32 = ctypes.windll.user32

    VK_CONTROL = 0x11
    VK_E = 0x45
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.wintypes.WORD),
            ("wScan", ctypes.wintypes.WORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _fields_ = [
            ("type", ctypes.wintypes.DWORD),
            ("_input", _INPUT),
        ]

    def send_key(vk, up=False):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp._input.ki.wVk = vk
        inp._input.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    # Find and focus MT5 window
    def find_mt5():
        result = []
        def cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "MetaTrader" in buf.value or "MetaQuotes" in buf.value:
                    if user32.IsWindowVisible(hwnd):
                        result.append(hwnd)
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return result

    windows = find_mt5()
    if not windows:
        print("MT5 window not found!")
        return

    hwnd = windows[0]
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    mt5.initialize()
    print(f"Before: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    # Ctrl+E toggles Algo Trading in MT5
    send_key(VK_CONTROL)
    time.sleep(0.05)
    send_key(VK_E)
    time.sleep(0.05)
    send_key(VK_E, up=True)
    time.sleep(0.05)
    send_key(VK_CONTROL, up=True)
    print("Sent Ctrl+E to MT5")
    time.sleep(2)

    mt5.initialize()
    state = mt5.terminal_info().trade_allowed
    print(f"After Ctrl+E: trade_allowed = {state}")
    if state:
        print("SUCCESS! AutoTrading is now ENABLED!")
    else:
        print("Still disabled. Try: enable_algo_pywinauto or enable_via_options")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 6. ENABLE ALGO TRADING (WM_COMMAND method)
# ═══════════════════════════════════════════════════════════════════════════
def enable_algo_wm_command():
    """Toggle AutoTrading using Windows WM_COMMAND messages."""
    import ctypes
    import ctypes.wintypes
    import MetaTrader5 as mt5

    user32 = ctypes.windll.user32
    WM_COMMAND = 0x0111
    BN_CLICKED = 0
    ALGO_CMD_ID = 32851

    def find_mt5():
        result = []
        def cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "MetaTrader" in buf.value or "MetaQuotes" in buf.value:
                    if user32.IsWindowVisible(hwnd):
                        result.append(hwnd)
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return result

    windows = find_mt5()
    if not windows:
        print("MT5 window not found!")
        return

    mt5_hwnd = windows[0]
    print(f"MT5 window: {mt5_hwnd}")

    mt5.initialize()
    print(f"Before: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    wparam = (BN_CLICKED << 16) | ALGO_CMD_ID
    result = user32.PostMessageW(mt5_hwnd, WM_COMMAND, wparam, 0)
    print(f"PostMessage result: {result}")
    time.sleep(1)

    mt5.initialize()
    state = mt5.terminal_info().trade_allowed
    print(f"After PostMessage({ALGO_CMD_ID}): trade_allowed = {state}")

    if not state:
        mt5.shutdown()
        result2 = user32.SendMessageW(mt5_hwnd, WM_COMMAND, ALGO_CMD_ID, 0)
        print(f"SendMessage result: {result2}")
        time.sleep(1)
        mt5.initialize()
        state2 = mt5.terminal_info().trade_allowed
        print(f"After SendMessage({ALGO_CMD_ID}): trade_allowed = {state2}")

    if mt5.terminal_info().trade_allowed:
        print("\nSUCCESS! Algo Trading is NOW ENABLED!")
    else:
        print("\nStill disabled. Try: enable_algo_pywinauto or enable_via_options")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 7. ENABLE ALGO TRADING (TB_CHECKBUTTON method)
# ═══════════════════════════════════════════════════════════════════════════
def enable_algo_toolbar():
    """Toggle AlgoTrading using TB_CHECKBUTTON/TB_PRESSBUTTON on the toolbar."""
    import ctypes
    import ctypes.wintypes
    import MetaTrader5 as mt5

    user32 = ctypes.windll.user32
    TB_PRESSBUTTON = 0x0403
    TB_CHECKBUTTON = 0x0402
    TB_GETSTATE = 0x0412
    WM_COMMAND = 0x0111
    ALGO_BTN_ID = 32851

    # Find toolbar handle via pywinauto
    try:
        from pywinauto import Application
    except ImportError:
        print("pywinauto not installed. Run: pip install pywinauto")
        return

    TOOLBAR_HWND = None
    try:
        app = Application(backend="win32").connect(title_re=".*MetaQuotes.*")
    except Exception:
        try:
            app = Application(backend="win32").connect(title_re=".*Demo Account.*")
        except Exception:
            app = Application(backend="win32").connect(class_name_re="Afx:.*")

    main_win = app.top_window()
    for ctrl in main_win.children():
        if ctrl.friendly_class_name() == "Toolbar":
            try:
                bc = ctrl.button_count()
                for i in range(bc):
                    info = ctrl.get_button(i)
                    if info.idCommand == 32851:
                        TOOLBAR_HWND = ctrl.handle
                        print(f"Found toolbar with Algo Trading button: hwnd={TOOLBAR_HWND}")
                        break
            except Exception:
                pass
        if TOOLBAR_HWND:
            break

    if not TOOLBAR_HWND:
        print("Could not find Algo Trading toolbar button.")
        return

    state = user32.SendMessageW(TOOLBAR_HWND, TB_GETSTATE, ALGO_BTN_ID, 0)
    print(f"Button state before: {state} (4=enabled-unchecked, 5=enabled-checked)")

    mt5.initialize()
    print(f"trade_allowed before: {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    print("\nTrying TB_CHECKBUTTON (check=True)...")
    user32.SendMessageW(TOOLBAR_HWND, TB_CHECKBUTTON, ALGO_BTN_ID, 1)
    time.sleep(0.5)

    mt5.initialize()
    ta = mt5.terminal_info().trade_allowed
    print(f"After TB_CHECKBUTTON: trade_allowed = {ta}")
    mt5.shutdown()

    if not ta:
        print("\nTrying TB_PRESSBUTTON...")
        user32.SendMessageW(TOOLBAR_HWND, TB_PRESSBUTTON, ALGO_BTN_ID, 1)
        time.sleep(0.3)
        user32.SendMessageW(TOOLBAR_HWND, TB_PRESSBUTTON, ALGO_BTN_ID, 0)
        time.sleep(0.5)
        mt5.initialize()
        ta2 = mt5.terminal_info().trade_allowed
        print(f"After TB_PRESSBUTTON: trade_allowed = {ta2}")
        mt5.shutdown()

    if not ta:
        parent = user32.GetParent(TOOLBAR_HWND)
        grandparent = user32.GetParent(parent) if parent else 0
        top_parent = user32.GetParent(grandparent) if grandparent else 0
        for target in [parent, grandparent, top_parent]:
            if target:
                user32.SendMessageW(target, WM_COMMAND, ALGO_BTN_ID, TOOLBAR_HWND)
                time.sleep(0.3)
        time.sleep(0.5)
        mt5.initialize()
        ta3 = mt5.terminal_info().trade_allowed
        print(f"After parent WM_COMMAND: trade_allowed = {ta3}")
        mt5.shutdown()

    mt5.initialize()
    final = mt5.terminal_info().trade_allowed
    print(f"\nFINAL: trade_allowed = {final}")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 8. ENABLE ALGO (PYWINAUTO DIRECT CLICK)
# ═══════════════════════════════════════════════════════════════════════════
def enable_algo_pywinauto():
    """Use pywinauto to directly click the Algo Trading toolbar button."""
    import ctypes
    import ctypes.wintypes

    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        from pywinauto import Application
    except ImportError:
        print("Need: pip install pyautogui pywinauto pygetwindow")
        return

    import MetaTrader5 as mt5

    mt5.initialize()
    print(f"Before: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    try:
        app = Application(backend="win32").connect(title_re=".*MetaQuotes.*")
    except Exception:
        try:
            app = Application(backend="win32").connect(title_re=".*Demo Account.*")
        except Exception:
            app = Application(backend="win32").connect(class_name_re="Afx:.*")

    main_win = app.top_window()
    print(f"Window: {main_win.window_text()}")
    main_win.set_focus()
    time.sleep(0.5)

    standard_tb = None
    algo_idx = None
    for ctrl in main_win.children():
        if ctrl.friendly_class_name() == "Toolbar":
            try:
                bc = ctrl.button_count()
                for i in range(bc):
                    info = ctrl.get_button(i)
                    if info.idCommand == 32851:
                        standard_tb = ctrl
                        algo_idx = i
                        rect = ctrl.get_button_rect(i)
                        print(f"Found Algo button at index {i}, rect={rect}")
                        break
            except Exception:
                pass
        if standard_tb:
            break

    if not standard_tb:
        print("Could not find Algo Trading button!")
        return

    # Method 1: pywinauto click_input
    try:
        rect = standard_tb.get_button_rect(algo_idx)
        mid_x = (rect.left + rect.right) // 2
        mid_y = (rect.top + rect.bottom) // 2
        standard_tb.click_input(coords=(mid_x, mid_y))
        time.sleep(1)
        mt5.initialize()
        ta = mt5.terminal_info().trade_allowed
        print(f"After click_input: trade_allowed = {ta}")
        mt5.shutdown()
        if ta:
            print("SUCCESS!")
            return
    except Exception as e:
        print(f"click_input failed: {e}")

    # Method 2: pyautogui with screen coords
    rect = standard_tb.get_button_rect(algo_idx)
    mid_x = (rect.left + rect.right) // 2
    mid_y = (rect.top + rect.bottom) // 2
    point = ctypes.wintypes.POINT(mid_x, mid_y)
    ctypes.windll.user32.ClientToScreen(standard_tb.handle, ctypes.byref(point))
    pyautogui.click(point.x, point.y)
    time.sleep(1)
    mt5.initialize()
    ta2 = mt5.terminal_info().trade_allowed
    print(f"After pyautogui click: trade_allowed = {ta2}")
    mt5.shutdown()
    if ta2:
        print("SUCCESS!")
        return

    # Method 3: WM_LBUTTONDOWN / WM_LBUTTONUP
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    MK_LBUTTON = 0x0001
    lparam = (mid_y << 16) | mid_x
    ctypes.windll.user32.PostMessageW(standard_tb.handle, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.1)
    ctypes.windll.user32.PostMessageW(standard_tb.handle, WM_LBUTTONUP, 0, lparam)
    time.sleep(1)
    mt5.initialize()
    ta3 = mt5.terminal_info().trade_allowed
    print(f"After WM_LBUTTON: trade_allowed = {ta3}")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 9. ENABLE VIA OPTIONS DIALOG
# ═══════════════════════════════════════════════════════════════════════════
def enable_via_options():
    """Open MT5 Options > Expert Advisors and enable algo trading checkbox."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        from pywinauto import Application
    except ImportError:
        print("Need: pip install pyautogui pywinauto")
        return

    import MetaTrader5 as mt5

    pyautogui.press("escape")
    time.sleep(0.3)

    mt5.initialize()
    print(f"BEFORE: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    app = Application(backend="win32").connect(title_re=".*MetaQuotes.*")
    main_win = app.top_window()
    main_win.set_focus()
    time.sleep(0.5)

    pyautogui.hotkey("ctrl", "o")
    time.sleep(2)

    options = None
    for w in app.windows():
        try:
            if "Options" in w.window_text():
                options = w
                break
        except Exception:
            pass

    if not options:
        print("Options dialog not found!")
        pyautogui.press("escape")
        return

    print(f"Found Options: '{options.window_text()}'")
    options.set_focus()
    time.sleep(0.3)

    tabs = None
    for ctrl in options.children():
        if "Tab" in ctrl.friendly_class_name():
            tabs = ctrl
            break

    if not tabs:
        print("TabControl not found!")
        pyautogui.press("escape")
        return

    tc = tabs.tab_count()
    ea_idx = None
    for i in range(tc):
        name = tabs.get_tab_text(i)
        print(f"  Tab [{i}]: {name}")
        if "Expert" in name:
            ea_idx = i

    if ea_idx is not None:
        tabs.select(ea_idx)
        time.sleep(0.5)

        # Find and enable checkboxes
        algo_cb = None
        disable_cb = None
        for ctrl in options.children():
            if ctrl.friendly_class_name() == "CheckBox":
                txt = ctrl.window_text()
                try:
                    checked = ctrl.get_check_state()
                except Exception:
                    checked = -1
                print(f"  [{'X' if checked == 1 else ' '}] '{txt}'")
                if "algorithmic" in txt.lower() or "algo" in txt.lower():
                    algo_cb = ctrl
                if "python" in txt.lower() or "external" in txt.lower():
                    disable_cb = ctrl

        # Enable algo checkbox
        if algo_cb:
            try:
                state = algo_cb.get_check_state()
            except Exception:
                state = 0
            if state != 1:
                print("Checking 'Allow algorithmic trading'...")
                algo_cb.check()
                time.sleep(0.2)

        # Uncheck "Disable via Python API" if found
        if disable_cb:
            try:
                state = disable_cb.get_check_state()
            except Exception:
                state = 0
            if state == 1:
                print("Unchecking 'Disable algorithmic trading via external Python API'...")
                disable_cb.uncheck()
                time.sleep(0.2)

        # Click OK
        for ctrl in options.children():
            if ctrl.friendly_class_name() == "Button" and ctrl.window_text() == "OK":
                ctrl.click()
                break
        time.sleep(1)
    else:
        print("Expert Advisors tab not found!")
        pyautogui.press("escape")

    mt5.initialize()
    final = mt5.terminal_info().trade_allowed
    print(f"\nAFTER: trade_allowed = {final}")
    if final:
        print("SUCCESS! Algo Trading is now ENABLED!")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 10. FIND BUTTON (TOOLBAR SCANNER)
# ═══════════════════════════════════════════════════════════════════════════
def find_button():
    """Use pywinauto to scan all toolbar buttons in MT5 window."""
    try:
        from pywinauto import Application
    except ImportError:
        print("Need: pip install pywinauto")
        return

    app = Application(backend="win32").connect(title_re=".*MetaTrader.*|.*MetaQuotes.*")
    main_win = app.top_window()
    print(f"Window: {main_win.window_text()}")

    print("\n=== Toolbar Controls ===")
    for ctrl in main_win.children():
        cls = ctrl.friendly_class_name()
        if "Tool" in cls or "Bar" in cls or "Rebar" in cls:
            print(f"  {cls}: hwnd={ctrl.handle}, rect={ctrl.rectangle()}")
            try:
                btn_count = ctrl.button_count()
                print(f"    Button count: {btn_count}")
                for i in range(btn_count):
                    try:
                        btn = ctrl.button(i)
                        info = ctrl.get_button(i)
                        print(f"    [{i}]: text='{btn.info.text}', id={info.idCommand}, "
                              f"state={info.fsState}, style={info.fsStyle}")
                    except Exception:
                        pass
            except Exception:
                pass

    print("\n=== All named child windows ===")
    for ctrl in main_win.children():
        cls = ctrl.friendly_class_name()
        txt = ctrl.window_text() if hasattr(ctrl, "window_text") else ""
        if txt or "ool" in cls.lower():
            print(f"  class={cls}, text='{txt[:50]}', hwnd={ctrl.handle}")


# ═══════════════════════════════════════════════════════════════════════════
# 11. TEST CONNECTION (EXNESS)
# ═══════════════════════════════════════════════════════════════════════════
def test_connect():
    """Test MT5 connection with Exness account credentials."""
    import MetaTrader5 as mt5
    from config.settings import config

    path = config.mt5.path

    print("Step 1: Initialize...", flush=True)
    ok = mt5.initialize(path, timeout=15000)
    print(f"Init result: {ok}", flush=True)

    if not ok:
        print(f"Init error: {mt5.last_error()}", flush=True)
        print("Step 1b: Init without path...", flush=True)
        ok = mt5.initialize(timeout=15000)
        print(f"Init2 result: {ok}", flush=True)
        if not ok:
            print(f"Init2 error: {mt5.last_error()}", flush=True)
            return

    ti = mt5.terminal_info()
    print(f"Terminal: {ti.name}, Connected: {ti.connected}, Trade allowed: {ti.trade_allowed}")

    ai = mt5.account_info()
    if ai:
        print(f"Logged in: {ai.login} @ {ai.server}")
        print(f"Balance: {ai.balance} {ai.currency}, Leverage: 1:{ai.leverage}")
    else:
        print("Not logged in. Trying login...")
        ok2 = mt5.login(config.mt5.login, password=config.mt5.password,
                         server=config.mt5.server, timeout=15000)
        print(f"Login result: {ok2}")
        if ok2:
            ai = mt5.account_info()
            print(f"Account: {ai.login} @ {ai.server}")
            print(f"Balance: {ai.balance} {ai.currency}")
        else:
            print(f"Login error: {mt5.last_error()}")

    # Symbol search
    print("\n--- Symbol Search ---")
    for pattern in ["*BTC*", "*XAU*", "*EURUSD*", "*GBPUSD*", "*USDJPY*"]:
        syms = mt5.symbols_get(pattern)
        if syms:
            print(f"  {pattern}: {[s.name for s in syms[:10]]}")
        else:
            print(f"  {pattern}: None found")

    mt5.shutdown()
    print("\nDONE")


# ═══════════════════════════════════════════════════════════════════════════
# 12. TEST EXNESS (TERMINAL DISCOVERY)
# ═══════════════════════════════════════════════════════════════════════════
def test_exness():
    """Discover MT5 terminals and test Exness connection."""
    import MetaTrader5 as mt5

    td = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "MetaQuotes", "Terminal")
    if os.path.exists(td):
        dirs = [d for d in os.listdir(td)
                if os.path.isdir(os.path.join(td, d)) and d != "Community"]
        print(f"Found {len(dirs)} MT5 terminal(s):")
        for d in dirs:
            origin = os.path.join(td, d, "origin.txt")
            if os.path.exists(origin):
                with open(origin) as f:
                    print(f"  {d[:16]}... => {f.read().strip()}")
            else:
                print(f"  {d[:16]}... => (no origin.txt)")

    print("\n--- Attempting Exness connection ---")
    init = mt5.initialize(r"C:\Program Files\MetaTrader 5\terminal64.exe")
    print(f"Initialize: {init}")
    if init:
        print(f"Terminal: {mt5.terminal_info().name if mt5.terminal_info() else 'N/A'}")
        from config.settings import config
        result = mt5.login(config.mt5.login, password=config.mt5.password,
                           server=config.mt5.server, timeout=15000)
        print(f"Login result: {result}")
        if result:
            info = mt5.account_info()
            print(f"Account: {info.login} @ {info.server}")
            print(f"Balance: {info.balance} {info.currency}, Leverage: 1:{info.leverage}")
            print(f"Trade allowed: {info.trade_allowed}")

            for sym_name in ["BTCUSDm", "BTCUSD"]:
                sym = mt5.symbol_info(sym_name)
                if sym:
                    print(f"\n{sym_name}: visible={sym.visible}, bid={sym.bid}, ask={sym.ask}")
                    break
            else:
                syms = mt5.symbols_get("*BTC*")
                if syms:
                    print(f"\nBTC symbols: {[s.name for s in syms[:10]]}")
        else:
            print(f"Login error: {mt5.last_error()}")
        mt5.shutdown()
    else:
        print(f"Init error: {mt5.last_error()}")


# ═══════════════════════════════════════════════════════════════════════════
# 13. TRADE BTC (DIRECT)
# ═══════════════════════════════════════════════════════════════════════════
def trade_btc():
    """Place a BTC trade directly, bypassing the bot's loop."""
    import MetaTrader5 as mt5
    from config.settings import config

    if not mt5.initialize(path=config.mt5.path, login=config.mt5.login,
                          password=config.mt5.password, server=config.mt5.server):
        print(f"MT5 init failed: {mt5.last_error()}")
        return

    print(f"Connected | Account: {config.mt5.login}")
    mt5.symbol_select("BTC", True)
    mt5.symbol_select("XAUUSD", True)

    acc = mt5.account_info()
    print(f"Balance: ${acc.balance}, Equity: ${acc.equity}")

    tick = mt5.symbol_info_tick("BTC")
    info = mt5.symbol_info("BTC")
    if tick is None:
        print(f"Cannot get BTC tick: {mt5.last_error()}")
        mt5.shutdown()
        return

    print(f"\nBTC: Bid={tick.bid}, Ask={tick.ask}, Min lot={info.volume_min}")

    if tick.bid == 0.0 and tick.ask == 0.0:
        print("\n*** Market CLOSED (price = 0.0) ***")
        mt5.shutdown()
        return

    volume = info.volume_min
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "BTC",
        "volume": float(volume),
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "deviation": 50,
        "magic": 123456,
        "comment": "AI_Bot_BTC",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    print(f"\nPlacing BUY: {volume} lots BTC @ {tick.ask}")
    result = mt5.order_send(request)
    if result is None:
        print(f"Order failed: {mt5.last_error()}")
    elif result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Rejected: code={result.retcode}, comment={result.comment}")
    else:
        print(f"*** SUCCESS! Ticket: {result.order}, Price: {result.price} ***")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 14. TRADE BTC (WITH AUTOTRADE CHECK + RETRIES)
# ═══════════════════════════════════════════════════════════════════════════
def trade_btc_retry():
    """Check AutoTrading status then try to place BTC trade."""
    import MetaTrader5 as mt5
    from config.settings import config

    mt5.shutdown()
    time.sleep(1)
    if not mt5.initialize(path=config.mt5.path, login=config.mt5.login,
                          password=config.mt5.password, server=config.mt5.server):
        print(f"Init failed: {mt5.last_error()}")
        return

    term = mt5.terminal_info()
    acc = mt5.account_info()
    print(f"Terminal trade_allowed: {term.trade_allowed}")
    print(f"Account trade_allowed: {acc.trade_allowed}, trade_expert: {acc.trade_expert}")
    print(f"Balance: ${acc.balance}")

    if not term.trade_allowed:
        print("\n*** AutoTrading is DISABLED ***")
        print("Enable it in MT5: Tools > Options > Expert Advisors > Allow algorithmic trading")
        mt5.shutdown()
        return

    print("\nAutoTrading is ENABLED!")
    mt5.symbol_select("BTC", True)
    time.sleep(0.5)
    tick = mt5.symbol_info_tick("BTC")
    info = mt5.symbol_info("BTC")
    print(f"BTC: Bid={tick.bid}, Ask={tick.ask}, Min lot={info.volume_min}")

    if tick.ask > 0:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "BTC",
            "volume": float(info.volume_min),
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "deviation": 50,
            "magic": 123456,
            "comment": "AI_Bot_BTC_Buy",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        print(f"\nPlacing BUY: {info.volume_min} lots BTC @ {tick.ask}")
        result = mt5.order_send(request)
        if result is None:
            print(f"Send failed: {mt5.last_error()}")
        elif result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"Rejected: code={result.retcode}, msg={result.comment}")
        else:
            print(f"*** SUCCESS! Ticket: {result.order}, Price: ${result.price} ***")
    else:
        print("Market closed - no price")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 15. TRADE BTC (FOK FILLING)
# ═══════════════════════════════════════════════════════════════════════════
def trade_btc_fok():
    """Place BTC trade using FOK filling mode."""
    import MetaTrader5 as mt5

    if not mt5.initialize():
        print("Failed to init MT5")
        return

    mt5.symbol_select("BTC", True)
    s = mt5.symbol_info("BTC")
    print(f"BTC: bid={s.bid}, ask={s.ask}, filling_mode={s.filling_mode}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "BTC",
        "volume": 1.0,
        "type": mt5.ORDER_TYPE_BUY,
        "price": s.ask,
        "deviation": 50,
        "magic": 123456,
        "comment": "BTC test trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    print(f"\nSending: BUY 1.0 BTC @ {s.ask} (FOK)")
    check = mt5.order_check(request)
    if check:
        print(f"Order check: retcode={check.retcode}, comment='{check.comment}'")
        print(f"  margin: {check.margin}, equity: {check.equity}")
    else:
        print(f"Order check failed: {mt5.last_error()}")

    result = mt5.order_send(request)
    if result:
        print(f"Order send: retcode={result.retcode}, comment='{result.comment}'")
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"  SUCCESS! Order={result.order}, Deal={result.deal}, Price={result.price}")
        elif result.retcode == 10027:
            print("  ERROR: AutoTrading disabled — Algo Trading button must be GREEN")
    else:
        print(f"Order send failed: {mt5.last_error()}")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 16. TRADE BTC (FULL TERMINAL STATUS CHECK)
# ═══════════════════════════════════════════════════════════════════════════
def trade_btc_full_check():
    """Full terminal flag check then BTC trade test."""
    import MetaTrader5 as mt5

    mt5.shutdown()
    time.sleep(2)

    ok = mt5.initialize()
    print(f"Init: {ok}")

    t = mt5.terminal_info()
    print(f"Path: {t.path}")
    print(f"Trade allowed: {t.trade_allowed}")

    for attr in dir(t):
        if "trade" in attr.lower() or "algo" in attr.lower() or "expert" in attr.lower():
            print(f"  t.{attr} = {getattr(t, attr)}")

    acc = mt5.account_info()
    print(f"\nAccount trade_allowed: {acc.trade_allowed}")
    print(f"Account trade_expert: {acc.trade_expert}")

    mt5.symbol_select("BTC", True)
    time.sleep(0.5)
    tick = mt5.symbol_info_tick("BTC")
    print(f"\nBTC: bid={tick.bid}, ask={tick.ask}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": "BTC",
        "volume": 1.0,
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "deviation": 50,
        "magic": 123456,
        "comment": "test",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    check = mt5.order_check(request)
    if check:
        print(f"Order check: retcode={check.retcode}, comment={check.comment}")

    result = mt5.order_send(request)
    if result:
        print(f"Order send: retcode={result.retcode}, comment={result.comment}")
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"*** SUCCESS! Ticket: {result.order}, Price: {result.price} ***")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 17. START MT5 AND TRADE
# ═══════════════════════════════════════════════════════════════════════════
def start_and_trade():
    """Start MetaTrader 5 terminal and attempt BTC trade once ready."""
    import subprocess
    import MetaTrader5 as mt5

    print("Starting MT5...")
    subprocess.Popen([r"C:\Program Files\MetaTrader 5\terminal64.exe"])

    print("Waiting for MT5 to start...")
    for i in range(20):
        time.sleep(1)
        if mt5.initialize():
            t = mt5.terminal_info()
            a = mt5.account_info()
            if a and a.login > 0:
                print(f"MT5 ready after {i+1}s | trade_allowed: {t.trade_allowed} | Balance: ${a.balance}")
                if t.trade_allowed:
                    print("\n=== ALGO TRADING ENABLED ===")
                    mt5.symbol_select("BTC", True)
                    time.sleep(0.5)
                    s = mt5.symbol_info("BTC")
                    if s and s.ask > 0:
                        request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": "BTC",
                            "volume": 1.0,
                            "type": mt5.ORDER_TYPE_BUY,
                            "price": s.ask,
                            "deviation": 50,
                            "magic": 123456,
                            "comment": "BTC test trade",
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": mt5.ORDER_FILLING_FOK,
                        }
                        result = mt5.order_send(request)
                        if result:
                            print(f"Order: retcode={result.retcode}, comment='{result.comment}'")
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"SUCCESS! Order={result.order}, Price={result.price}")
                    else:
                        print("BTC market closed or unavailable")
                else:
                    print("Algo Trading disabled — click the button in MT5 toolbar")
                mt5.shutdown()
                return
            mt5.shutdown()
    print("MT5 didn't start in 20 seconds")


# ═══════════════════════════════════════════════════════════════════════════
# 18. NAVIGATE OPTIONS DIALOG (DIAGNOSTIC)
# ═══════════════════════════════════════════════════════════════════════════
def navigate_options():
    """Navigate MT5 Options dialog tabs and list checkboxes (diagnostic)."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        from pywinauto import Application
    except ImportError:
        print("Need: pip install pyautogui pywinauto")
        return

    app = Application(backend="win32").connect(title_re=".*MetaQuotes.*")
    options = app.window(title="Options")
    options.set_focus()
    time.sleep(0.3)

    tab = options.child_window(class_name="SysTabControl32")
    tab_count = tab.tab_count()
    print(f"Tab count: {tab_count}")
    for i in range(tab_count):
        print(f"  Tab[{i}]: '{tab.get_tab_text(i)}'")

    ea_idx = None
    for i in range(tab_count):
        text = tab.get_tab_text(i)
        if "Expert" in text:
            ea_idx = i
            break

    if ea_idx is not None:
        tab.select(ea_idx)
        time.sleep(0.5)
        print(f"\nSwitched to '{tab.get_tab_text(ea_idx)}'")
        print("Checkboxes:")
        for ctrl in options.children():
            if ctrl.friendly_class_name() == "CheckBox":
                txt = ctrl.window_text()
                try:
                    checked = ctrl.get_check_state()
                except Exception:
                    checked = "?"
                print(f"  [{checked}] '{txt}'")
    else:
        print("Expert Advisors tab not found!")


# ═══════════════════════════════════════════════════════════════════════════
# 19. OPEN OPTIONS DIALOG (DIAGNOSTIC)
# ═══════════════════════════════════════════════════════════════════════════
def open_options():
    """Open MT5 Options dialog and list all controls."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        from pywinauto import Application
    except ImportError:
        print("Need: pip install pyautogui pywinauto")
        return

    import MetaTrader5 as mt5

    mt5.initialize()
    print(f"trade_allowed: {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    app = Application(backend="win32").connect(title_re=".*MetaQuotes.*")
    main_win = app.top_window()
    main_win.set_focus()
    time.sleep(0.5)

    pyautogui.hotkey("ctrl", "o")
    time.sleep(2)

    try:
        dlg = app.window(title_re=".*Options.*")
        if dlg.exists():
            print(f"Options dialog: {dlg.window_text()}")
            dlg.set_focus()
            time.sleep(0.5)
            print("\nControls:")
            for ctrl in dlg.children():
                cls = ctrl.friendly_class_name()
                txt = ctrl.window_text() if hasattr(ctrl, "window_text") else ""
                print(f"  {cls}: '{txt[:60]}'")
    except Exception as e:
        print(f"Error: {e}")

    pyautogui.press("escape")


# ═══════════════════════════════════════════════════════════════════════════
# 20. UNCHECK "DISABLE PYTHON API" CHECKBOX
# ═══════════════════════════════════════════════════════════════════════════
def uncheck_python_disable():
    """Uncheck 'Disable algorithmic trading via external Python API' in Options."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        from pywinauto import Application
    except ImportError:
        print("Need: pip install pyautogui pywinauto")
        return

    import MetaTrader5 as mt5

    pyautogui.press("escape")
    time.sleep(0.5)

    mt5.initialize()
    print(f"BEFORE: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    app = Application(backend="win32").connect(title_re=".*MetaQuotes.*")
    main_win = app.top_window()
    main_win.set_focus()
    time.sleep(0.5)

    pyautogui.hotkey("ctrl", "o")
    time.sleep(2)

    options = None
    for w in app.windows():
        try:
            if "Options" in w.window_text():
                options = w
                break
        except Exception:
            pass

    if not options:
        print("Options dialog not found!")
        return

    options.set_focus()
    time.sleep(0.3)

    tabs = None
    for ctrl in options.children():
        if "Tab" in ctrl.friendly_class_name():
            tabs = ctrl
            break

    tabs.select(3)  # Expert Advisors
    time.sleep(0.5)

    target_cb = None
    for ctrl in options.children():
        if ctrl.friendly_class_name() == "CheckBox":
            txt = ctrl.window_text()
            if "Python" in txt or "external" in txt.lower():
                target_cb = ctrl
                break

    if target_cb:
        try:
            state = target_cb.get_check_state()
        except Exception:
            state = -1
        print(f"Found: '{target_cb.window_text()}', checked={state}")
        if state == 1:
            print("UNCHECKING...")
            target_cb.uncheck()
            time.sleep(0.3)
        else:
            print("Already unchecked!")

        for ctrl in options.children():
            if ctrl.friendly_class_name() == "Button" and ctrl.window_text() == "OK":
                ctrl.click()
                break
        time.sleep(1)
    else:
        print("Target checkbox not found!")
        pyautogui.press("escape")

    mt5.initialize()
    final = mt5.terminal_info().trade_allowed
    print(f"\nAFTER: trade_allowed = {final}")
    if final:
        print("=== SUCCESS! Algo Trading via Python API is now ENABLED! ===")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# 21. TOGGLE ALGO (BRUTE FORCE WM_COMMAND IDS)
# ═══════════════════════════════════════════════════════════════════════════
def toggle_algo():
    """Try multiple WM_COMMAND IDs to toggle Algo Trading."""
    import ctypes
    import ctypes.wintypes
    import MetaTrader5 as mt5

    user32 = ctypes.windll.user32
    WM_COMMAND = 0x0111

    def find_mt5():
        result = []
        def cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "MetaTrader" in buf.value or "MetaQuotes" in buf.value:
                    result.append(hwnd)
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return result

    windows = find_mt5()
    if not windows:
        print("MT5 window not found!")
        return

    hwnd = windows[0]
    print(f"MT5 window: {hwnd}")

    mt5.initialize()
    print(f"Before: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()

    cmd_ids = [33042, 33043, 33020, 33021, 33022, 33050, 33051, 33052,
               32851, 32852, 32853, 32788, 32789, 32790,
               35000, 35001, 35002, 35010, 35011, 35012]

    for cmd_id in cmd_ids:
        user32.PostMessageW(hwnd, WM_COMMAND, cmd_id, 0)
        time.sleep(0.1)
    time.sleep(2)

    mt5.initialize()
    state = mt5.terminal_info().trade_allowed
    print(f"After WM_COMMAND sweep: trade_allowed = {state}")

    if not state:
        print("\nTrying re-login approach...")
        from config.settings import config
        auth = mt5.login(config.mt5.login, password=config.mt5.password, server=config.mt5.server)
        print(f"Login result: {auth}")
        print(f"After login: trade_allowed = {mt5.terminal_info().trade_allowed}")
    mt5.shutdown()


# ═══════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY — add new utilities here
# ═══════════════════════════════════════════════════════════════════════════
TOOLS = {
    "check_mt5":            ("Check MT5 connection",                   check_mt5),
    "check_status":         ("Full terminal & account status",         check_status),
    "check_symbols":        ("Search Gold, BTC, crypto symbols",       check_symbols),
    "check_symbols_detail": ("Detailed XAUUSD/BTCUSD symbol info",    check_symbols_detail),
    "enable_algo_keyboard": ("Enable Algo Trading via Ctrl+E",         enable_algo_keyboard),
    "enable_algo_wm":       ("Enable Algo via WM_COMMAND",             enable_algo_wm_command),
    "enable_algo_toolbar":  ("Enable Algo via TB_CHECKBUTTON",         enable_algo_toolbar),
    "enable_algo_click":    ("Enable Algo via pywinauto click",        enable_algo_pywinauto),
    "enable_via_options":   ("Enable via Options dialog checkboxes",   enable_via_options),
    "find_button":          ("Scan all MT5 toolbar buttons",           find_button),
    "test_connect":         ("Test MT5 connection with credentials",   test_connect),
    "test_exness":          ("Discover terminals & test Exness",       test_exness),
    "trade_btc":            ("Place BTC trade (direct)",               trade_btc),
    "trade_btc_retry":      ("Trade BTC with AutoTrade check",        trade_btc_retry),
    "trade_btc_fok":        ("Trade BTC with FOK filling",            trade_btc_fok),
    "trade_btc_full":       ("Full terminal check + BTC trade",       trade_btc_full_check),
    "start_and_trade":      ("Start MT5 terminal + BTC trade",        start_and_trade),
    "navigate_options":     ("Navigate Options dialog tabs",           navigate_options),
    "open_options":         ("Open Options & list controls",           open_options),
    "uncheck_python":       ("Uncheck 'Disable Python API'",          uncheck_python_disable),
    "toggle_algo":          ("Brute-force toggle Algo Trading",        toggle_algo),
}


# ═══════════════════════════════════════════════════════════════════════════
# INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════════════════
def show_menu():
    """Display the utility menu and run selected tool."""
    print()
    print("=" * 65)
    print("   FOREX AI BOT — UTILITIES & DIAGNOSTICS")
    print("=" * 65)
    print()

    names = list(TOOLS.keys())
    for i, name in enumerate(names, 1):
        desc = TOOLS[name][0]
        print(f"  {i:3d}. {desc:45s}  [{name}]")

    print(f"\n  {len(names)+1:3d}. Exit")
    print()

    try:
        choice = input("Pick a tool (number or name): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    # Resolve choice
    func = None
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(names):
            func = TOOLS[names[idx]][1]
        elif idx == len(names):
            return
    elif choice in TOOLS:
        func = TOOLS[choice][1]

    if func is None:
        print(f"Unknown selection: '{choice}'")
        return

    print()
    print("-" * 65)
    try:
        func()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    print("-" * 65)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Direct invocation: python utilities.py check_mt5
        name = sys.argv[1]
        if name in TOOLS:
            print(f"Running: {TOOLS[name][0]}")
            print("-" * 65)
            TOOLS[name][1]()
            print("-" * 65)
        else:
            print(f"Unknown tool: '{name}'")
            print(f"Available: {', '.join(TOOLS.keys())}")
    else:
        # Interactive menu
        while True:
            show_menu()
            try:
                again = input("Run another? [Y/n]: ").strip().lower()
                if again == "n":
                    break
            except (KeyboardInterrupt, EOFError):
                break
        print("Done.")
