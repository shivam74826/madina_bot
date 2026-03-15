"""
Email Notifier - sends trade alerts via Gmail SMTP.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from threading import Thread

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends email notifications for trade events."""

    def __init__(self):
        import os
        self.enabled = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
        self.sender = os.getenv("EMAIL_SENDER", "")
        self.password = os.getenv("EMAIL_APP_PASSWORD", "")
        raw_recipients = os.getenv("EMAIL_RECIPIENT", "shivampandey74826@gmail.com")
        self.recipients = [r.strip() for r in raw_recipients.split(",") if r.strip()]
        self.smtp_host = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))

        if self.enabled and (not self.sender or not self.password):
            logger.warning("Email notifier disabled: EMAIL_SENDER or EMAIL_APP_PASSWORD not set in .env")
            self.enabled = False

    def _send_async(self, subject: str, body_html: str):
        """Send email in background thread so it doesn't block trading."""
        if not self.enabled:
            return
        thread = Thread(target=self._send, args=(subject, body_html), daemon=True)
        thread.start()

    def _send(self, subject: str, body_html: str):
        """Actual SMTP send."""
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body_html, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())

            logger.debug(f"Email sent: {subject}")
        except Exception as e:
            logger.warning(f"Email send failed: {e}")

    # ─── Trade Event Notifications ───────────────────────────────────────

    def notify_trade_opened(self, order_result: dict, strategy: str = "", confidence: float = 0.0):
        """Send email when a new trade is opened."""
        symbol = order_result.get("symbol", "?")
        direction = order_result.get("type", "?")
        volume = order_result.get("volume", 0)
        price = order_result.get("price", 0)
        sl = order_result.get("sl", 0)
        tp = order_result.get("tp", 0)
        ticket = order_result.get("ticket", 0)
        slippage = order_result.get("slippage", 0)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        subject = f"TRADE OPENED | {direction} {symbol} @ {price:.2f}"
        body = f"""
        <div style="font-family:Arial; max-width:500px; margin:auto;">
            <h2 style="color:#2196F3;">New Trade Opened</h2>
            <table style="width:100%; border-collapse:collapse;">
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Time</b></td><td>{now}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Symbol</b></td><td>{symbol}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Direction</b></td>
                    <td style="color:{'#4CAF50' if direction=='BUY' else '#F44336'}; font-weight:bold;">{direction}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Entry Price</b></td><td>{price:.2f}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Lot Size</b></td><td>{volume}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Stop Loss</b></td><td style="color:#F44336;">{sl:.2f}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Take Profit</b></td><td style="color:#4CAF50;">{tp:.2f}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Strategy</b></td><td>{strategy}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Confidence</b></td><td>{confidence:.1%}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Ticket</b></td><td>#{ticket}</td></tr>
                <tr><td style="padding:6px;"><b>Slippage</b></td><td>{slippage:.5f} pts</td></tr>
            </table>
        </div>
        """
        self._send_async(subject, body)

    def notify_trade_closed(self, symbol: str, direction: str, ticket: int,
                            profit: float, close_price: float = 0, comment: str = ""):
        """Send email when a trade is closed."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = "#4CAF50" if profit >= 0 else "#F44336"
        result_text = "WIN" if profit >= 0 else "LOSS"

        subject = f"TRADE CLOSED | {result_text} {symbol} | P&L: ${profit:+.2f}"
        body = f"""
        <div style="font-family:Arial; max-width:500px; margin:auto;">
            <h2 style="color:{color};">Trade Closed - {result_text}</h2>
            <table style="width:100%; border-collapse:collapse;">
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Time</b></td><td>{now}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Symbol</b></td><td>{symbol}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Direction</b></td><td>{direction}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Ticket</b></td><td>#{ticket}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Close Price</b></td><td>{close_price:.2f}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Profit/Loss</b></td>
                    <td style="color:{color}; font-weight:bold; font-size:18px;">${profit:+.2f}</td></tr>
                <tr><td style="padding:6px;"><b>Comment</b></td><td>{comment}</td></tr>
            </table>
        </div>
        """
        self._send_async(subject, body)

    def notify_sl_modified(self, symbol: str, ticket: int, old_sl: float,
                           new_sl: float, reason: str = "Trailing Stop"):
        """Send email when stop loss is modified."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"SL UPDATED | {symbol} #{ticket} | {old_sl:.2f} -> {new_sl:.2f}"
        body = f"""
        <div style="font-family:Arial; max-width:500px; margin:auto;">
            <h2 style="color:#FF9800;">Stop Loss Modified</h2>
            <table style="width:100%; border-collapse:collapse;">
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Time</b></td><td>{now}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Symbol</b></td><td>{symbol}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Ticket</b></td><td>#{ticket}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Old SL</b></td><td>{old_sl:.2f}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>New SL</b></td>
                    <td style="font-weight:bold;">{new_sl:.2f}</td></tr>
                <tr><td style="padding:6px;"><b>Reason</b></td><td>{reason}</td></tr>
            </table>
        </div>
        """
        self._send_async(subject, body)

    def notify_partial_close(self, symbol: str, ticket: int, fraction: float, profit: float):
        """Send email when a partial close happens."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subject = f"PARTIAL CLOSE | {symbol} #{ticket} | {fraction:.0%} closed"
        body = f"""
        <div style="font-family:Arial; max-width:500px; margin:auto;">
            <h2 style="color:#9C27B0;">Partial Take Profit</h2>
            <table style="width:100%; border-collapse:collapse;">
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Time</b></td><td>{now}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Symbol</b></td><td>{symbol}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Ticket</b></td><td>#{ticket}</td></tr>
                <tr><td style="padding:6px; border-bottom:1px solid #eee;"><b>Closed</b></td><td>{fraction:.0%} of position</td></tr>
                <tr><td style="padding:6px;"><b>Realized P&L</b></td>
                    <td style="color:#4CAF50; font-weight:bold;">${profit:+.2f}</td></tr>
            </table>
        </div>
        """
        self._send_async(subject, body)


# Singleton instance
notifier = EmailNotifier()
