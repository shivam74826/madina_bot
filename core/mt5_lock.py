"""
Thread-safe wrapper around the MetaTrader5 module.

The MT5 Python library uses COM (Component Object Model) on Windows,
which is apartment-threaded and NOT safe to call from multiple threads
concurrently. This wrapper serializes all MT5 function calls with a
reentrant lock, preventing deadlocks when the Flask dashboard thread
and the main trading thread both need MT5 access.

Usage:
    from core.mt5_lock import mt5_safe as mt5
    # Then use mt5.xxx() as normal — all calls are thread-safe.
"""

import threading
import MetaTrader5 as _mt5

_lock = threading.RLock()


class _LockedMT5:
    """Proxy that serializes all MT5 function calls via a reentrant lock.

    Attribute/constant access (e.g. mt5.TIMEFRAME_M1) passes through
    without locking since those are just integers.
    """

    def __getattr__(self, name):
        attr = getattr(_mt5, name)
        if callable(attr):
            def locked_call(*args, **kwargs):
                with _lock:
                    # MT5 C-extension functions reject **kwargs even when empty;
                    # only forward kwargs when they are actually provided.
                    if kwargs:
                        return attr(*args, **kwargs)
                    return attr(*args)
            return locked_call
        return attr


mt5_safe = _LockedMT5()
