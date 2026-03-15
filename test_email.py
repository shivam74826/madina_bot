"""Quick test to verify email notifications work."""
from dotenv import load_dotenv
load_dotenv()

from utils.email_notifier import EmailNotifier

n = EmailNotifier()
print(f"Enabled: {n.enabled}")
print(f"Sender: {n.sender}")
print(f"Recipient: {n.recipients}")
print(f"Password set: {bool(n.password)}")

if n.enabled:
    n._send(
        "TEST | Forex Bot Email Working",
        "<h2 style='color:#4CAF50;'>Email notifications are active!</h2>"
        "<p>You will receive alerts for all trade opens, closes, SL changes, and partial closes.</p>"
    )
    print("Test email sent! Check your inbox.")
else:
    print("Email is disabled - check .env config")
