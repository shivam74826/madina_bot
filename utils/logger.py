"""
=============================================================================
Logger Utility
=============================================================================
Centralized logging configuration for the trading bot.
Includes file logging, console output, and trade-specific CSV logging.
=============================================================================
"""

import logging
import os
import csv
from datetime import datetime
from logging.handlers import RotatingFileHandler

from config.settings import config


def setup_logging():
    """Initialize the logging system."""
    # Create log directories
    log_dir = os.path.dirname(config.logging.log_file)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(config.ai.model_save_path, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.logging.log_level))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)

    # File handler (rotating)
    file_handler = RotatingFileHandler(
        config.logging.log_file,
        maxBytes=config.logging.max_file_size,
        backupCount=config.logging.backup_count,
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(funcName)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_format)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    return root_logger


class TradeLogger:
    """Logs all trades to a CSV file for analysis."""

    def __init__(self):
        self.log_file = config.logging.trade_log_file
        log_dir = os.path.dirname(self.log_file)
        os.makedirs(log_dir, exist_ok=True)

        # Create CSV with headers if not exists
        if not os.path.exists(self.log_file):
            with open(self.log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "symbol", "action", "volume", "entry_price",
                    "stop_loss", "take_profit", "confidence", "strategy",
                    "reason", "ticket", "result",
                ])

    def log_trade(
        self,
        symbol: str,
        action: str,
        volume: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        strategy: str,
        reason: str,
        ticket: int = 0,
        result: str = "OPENED",
    ):
        """Log a trade to CSV."""
        try:
            with open(self.log_file, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    symbol, action, volume, entry_price,
                    stop_loss, take_profit, confidence, strategy,
                    reason, ticket, result,
                ])
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to log trade: {e}")

    def get_trade_history(self) -> list:
        """Read trade history from CSV."""
        trades = []
        try:
            with open(self.log_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
        except FileNotFoundError:
            pass
        return trades
