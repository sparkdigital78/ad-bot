import os
import time
import signal
import sys
import random
from playwright.sync_api import sync_playwright

current_context = None


def shutdown_handler(sig, frame):
    global current_context
    print("\n--> [STOP / CANCEL DETECTED] Closing context to flush video file...")
    if current_context:
        try:
            current_context.close()
            print("--> [SUCCESS] Video saved successfully!")
        except Exception as e:
            print(f"--> Error closing context: {e}")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ============================================================
# READ EMAILS & DYNAMICALLY SHARD ACCOUNTS
# ============================================================
raw_emails = ""
if os.path.exists("emails.txt"):
    print("--> Loading email list from 'emails.txt'...")
    with open("emails.txt", "r", encoding="utf-8") as f:
        raw_emails = f.read()
else:
    raw_emails = os.environ.get("ALL_EMAILS", "")

email_password = os.environ.get("ACCOUNT_PASSWORD", "Chetan@2026")
ALL_EMAILS = [e.strip().lower() for e in raw_emails.replace(",", " ").split() if e.strip()]

shard_index = int(os.environ.get("SHARD_INDEX", "1"))
total_shards = int(os.environ.get("TOTAL_SHARDS", "1"))

# Distribute accounts evenly across shards
SHARD_ASSIGNED_EMAILS = [
    email for idx, email in enumerate(ALL_EMAILS)
    if idx % total_shards == (shard_index - 1)
]

print(f"--> [SHARD {shard_index}/{total_shards}] Total list size: {len(ALL_EMAILS)}")
print(f"--> [SHARD {shard_index}/{total_shards}] Assigned to this shard: {len(SHARD_ASSIGNED_EMAILS)}")

if not SHARD_ASSIGNED_EMAILS:
    print(f"--> [SHARD {shard_index}] No accounts assigned to this worker. Exiting cleanly...")
    sys.exit(0)

# Stagger startup with randomized jitter to evade IP block correlation
startup_delay = (shard_index - 1) * random.randint(5, 12)
if startup_delay > 0:
    print(f"--> [STAGGER] Shard {shard_index} sleeping for {startup_delay}s before starting...")
    time.sleep(startup_delay)

ACCOUNTS = [{"id": i + 1, "email": email, "password": email_password} for i, email in enumerate(SHARD_ASSIGNED_EMAILS)]


def human_delay(min_s=1.0, max_s=2.5):
    """Adds natural human pauses between actions."""
    time.sleep(random.uniform(min_s, max_s))


def purge_popups(page):
    """Dismisses general overlays, promotional modals, and popups."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

    try:
        page.evaluate("""() => {
            const dialogs = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"]'));
            dialogs.forEach(d => {
                const isLogin = d.querySelector('input[placeholder*="email" i], input[type="email"]') ||
                                (d.textContent && d.textContent.includes('Sign in'));
                if (!isLogin) {
                    const closeBtn = d.querySelector('button, [class*="close"], svg, i, [aria-label*="close" i]');
                    if (closeBtn) closeBtn.click();
                }
            });
        }""")
    except Exception:
        pass


def handle_daily_checkin_modal(page):
    """Automatically handles 'Check In' and promotional popups."""
    try:
        checkin_btn = page.locator("button:has-text('Check In'), div:has-text('Check In')").last
        if checkin_btn.is_visible():
            print("--> [POPUP] Daily Check-in modal detected. Clicking 'Check In'...")
            human_delay(0.5, 1.2)
            checkin_btn.click(force=True)
            page.wait_for_timeout(1500)
            purge_popups(page)
            return True
    except Exception:
        pass

    purge_popups(page)
    return False


def force_unpause_videos(page):
    try:
        page.evaluate("""() => {
            function playAllVideos(doc) {
                const videos = Array.from(doc.querySelectorAll('video'));
                videos.forEach(v => {
                    v.muted = true;
                    v.play().catch(e => {});
                });
            }

            playAllVideos(document);

            const iframes = document.querySelectorAll('iframe');
            iframes.forEach(f => {
                try {
                    if (f.contentDocument) playAllVideos(f.contentDocument);
                } catch(e) {}
            });
        }""")
    except Exception:
        pass


def check_daily_limit_reached(page):
    """Checks for the exact daily limit phrase."""
    limit_phrases = [
        "You have used all your ad watch opportunities for today",
        "Please try again tomorrow",
        "used all your ad watch"
    ]
    
    for phrase in limit_phrases:
        try:
            element = page.get_by_text(phrase, exact=False)
            if element.count() > 0 and element.first.is_visible():
                return True
        except Exception:
            pass

        try:
            for frame in page
