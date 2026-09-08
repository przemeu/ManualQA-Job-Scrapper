import logging
import requests
import database

logger = logging.getLogger(__name__)

def send_desktop_notification(title: str, message: str, url: str = ""):
    """Trigger a native Windows 10/11 toast notification."""
    try:
        from windows_toasts import WindowsToaster, Toast
        toaster = WindowsToaster("Job Hunter QA")
        toast = Toast()
        toast.text_fields = [title, message]
        toaster.show_toast(toast)
        logger.info(f"Desktop notification sent: {title} | {message}")
        return True, "Desktop notification sent successfully"
    except Exception as e:
        logger.error(f"Failed to send desktop notification: {e}")
        return False, str(e)


def send_telegram_notification(token: str, chat_id: str, job: dict) -> tuple[bool, str]:
    """Send a formatted job offer alert to a Telegram chat."""
    if not token or not chat_id:
        return False, "Telegram Bot Token and Chat ID must be configured"
    
    title = job.get('title', 'Unknown Title')
    company = job.get('company', 'Unknown Company')
    source = job.get('source', '')
    city = job.get('city', 'Remote')
    pay = job.get('pay', 'Not given')
    url = job.get('url', '')
    
    text = (
        f"🎯 <b>New Manual QA Offer!</b>\n\n"
        f"💼 <b>{title}</b>\n"
        f"🏢 {company} ({source})\n"
        f"📍 {city}\n"
        f"💰 {pay}\n\n"
        f"👉 <a href=\"{url}\">Open & Apply Here</a>"
    )
    
    try:
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        resp = requests.post(endpoint, json=payload, timeout=10)
        data = resp.json()
        if data.get("ok"):
            logger.info(f"Telegram notification sent for {title}")
            return True, "Telegram alert sent successfully"
        else:
            err_msg = data.get("description", "Unknown Telegram API error")
            logger.error(f"Telegram API error: {err_msg}")
            return False, f"Telegram error: {err_msg}"
    except Exception as e:
        logger.error(f"Failed to connect to Telegram: {e}")
        return False, f"Network error: {str(e)}"


def send_telegram_test_message(token: str, chat_id: str) -> tuple[bool, str]:
    """Send a test message to verify Telegram credentials."""
    if not token or not chat_id:
        return False, "Please enter both Bot Token and Chat ID"
        
    text = (
        "🤖 <b>Job Hunter QA - Test Alert!</b>\n\n"
        "✅ Your Telegram notifications are configured and working properly!\n"
        "You will receive instant alerts here whenever new Manual QA jobs are found."
    )
    try:
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(endpoint, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return True, "Test alert sent! Check your Telegram app."
        else:
            return False, data.get("description", "Telegram error")
    except Exception as e:
        return False, str(e)


def notify_new_jobs(new_jobs: list):
    """Dispatch alerts for newly found jobs according to user settings."""
    if not new_jobs:
        return

    settings = database.get_all_settings()
    desktop_enabled = settings.get('desktop_notifications', 'true').lower() == 'true'
    telegram_enabled = settings.get('telegram_notifications', 'false').lower() == 'true'
    tg_token = settings.get('telegram_token', '').strip()
    tg_chat_id = settings.get('telegram_chat_id', '').strip()

    # 1. Desktop Notification
    if desktop_enabled:
        if len(new_jobs) == 1:
            job = new_jobs[0]
            send_desktop_notification(
                "🎯 New QA Offer Found!",
                f"{job.get('title')} ({job.get('city') or 'Remote'})"
            )
        else:
            send_desktop_notification(
                f"🎯 {len(new_jobs)} New QA Offers Found!",
                f"Latest: {new_jobs[0].get('title')} & {len(new_jobs) - 1} more"
            )

    # 2. Telegram Notifications
    if telegram_enabled and tg_token and tg_chat_id:
        import time
        for job in new_jobs:
            send_telegram_notification(tg_token, tg_chat_id, job)
            time.sleep(0.25)
