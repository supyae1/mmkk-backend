import requests

# Your Telegram bot credentials
TELEGRAM_BOT_TOKEN = ""  # put your bot token if you want alerts
TELEGRAM_CHAT_ID = ""    # your chat ID


def send_telegram_alert(message: str):
    """
    Send a simple text message to your Telegram chat.
    If token or chat id are empty, it does nothing.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        # For now just print error, we don't want alerts to break scoring
        print(f"Error sending Telegram alert: {e}")
