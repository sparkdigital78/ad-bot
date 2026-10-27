import os
import time
import signal
import sys
import random
from playwright.sync_api import sync_playwright

current_context = None

os.makedirs("videos", exist_ok=True)


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

SHARD_ASSIGNED_EMAILS = [
    email for idx, email in enumerate(ALL_EMAILS)
    if idx % total_shards == (shard_index - 1)
]

print(f"--> [SHARD {shard_index}/{total_shards}] Total list size: {len(ALL_EMAILS)}")
print(f"--> [SHARD {shard_index}/{total_shards}] Assigned to this shard ({len(SHARD_ASSIGNED_EMAILS)}): {SHARD_ASSIGNED_EMAILS}")

if not SHARD_ASSIGNED_EMAILS:
    print(f"--> [SHARD {shard_index}] No accounts assigned to this worker. Exiting cleanly...")
    sys.exit(0)

startup_delay = (shard_index - 1) * random.randint(3, 8)
if startup_delay > 0:
    print(f"--> [STAGGER] Shard {shard_index} sleeping for {startup_delay}s before starting...")
    time.sleep(startup_delay)

ACCOUNTS = [{"id": i + 1, "email": email, "password": email_password} for i, email in enumerate(SHARD_ASSIGNED_EMAILS)]


def human_delay(min_s=1.0, max_s=2.5):
    """Adds natural human pauses between actions."""
    time.sleep(random.uniform(min_s, max_s))


def purge_popups(page):
    """Dismisses and removes center modals, side promo cards, and floating overlays."""
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
                    if (closeBtn) {
                        closeBtn.click();
                    } else {
                        d.remove();
                    }
                }
            });

            const floatingWidgets = Array.from(document.querySelectorAll('div, iframe, a')).filter(el => {
                if (!el.textContent) return false;
                const txt = el.textContent.toLowerCase();
                return txt.includes('try it now') || txt.includes('put yourself into') || txt.includes('kling');
            });

            floatingWidgets.forEach(w => {
                let parent = w;
                for (let i = 0; i < 4; i++) {
                    if (parent && parent.parentElement && parent.parentElement !== document.body) {
                        parent = parent.parentElement;
                    }
                }
                if (parent && parent !== document.body) {
                    parent.remove();
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
    """Strict check for the exact daily limit toast message."""
    exact_limit_text = "You have used all your ad watch opportunities for today"
    
    try:
        element = page.get_by_text(exact_limit_text, exact=False)
        if element.count() > 0 and element.first.is_visible():
            return True
    except Exception:
        pass

    try:
        for frame in page.frames:
            frame_element = frame.get_by_text(exact_limit_text, exact=False)
            if frame_element.count() > 0 and frame_element.first.is_visible():
                return True
    except Exception:
        pass

    try:
        has_limit = page.evaluate("""() => {
            const toasts = Array.from(document.querySelectorAll('[class*="toast"], [class*="notification"], [class*="alert"], [role="status"]'));
            return toasts.some(t => t.textContent && t.textContent.includes('You have used all your ad watch opportunities for today'));
        }""")
        if has_limit:
            return True
    except Exception:
        pass

    return False


def click_close_button(page):
    print("--> Waiting for 'Close' button to appear...")

    for attempt in range(15):
        force_unpause_videos(page)
        page.wait_for_timeout(1000)

        for frame in page.frames:
            close_selectors = [
                "#dismiss-button",
                "text=/^close\$/i",
                "text='Close'",
                "text='close'",
                "[aria-label*='close' i]",
                "[aria-label*='dismiss' i]",
                "button:has-text('Close')",
                "div:has-text('Close')",
                "span:has-text('Close')"
            ]
            for sel in close_selectors:
                try:
                    loc = frame.locator(sel)
                    if loc.count() > 0:
                        for i in range(loc.count()):
                            el = loc.nth(i)
                            if el.is_visible():
                                box = el.bounding_box()
                                if box:
                                    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                else:
                                    el.click(force=True)
                                print(f"--> [SUCCESS] Clicked Close button via locator '{sel}' (attempt {attempt + 1})!")
                                page.wait_for_timeout(1000)
                                return True
                except Exception:
                    pass

        try:
            google_iframe_closed = page.evaluate("""() => {
                const adIframes = Array.from(document.querySelectorAll('iframe')).filter(f => {
                    const src = f.src || '';
                    return src.includes('google') || src.includes('doubleclick') || f.id.includes('goog');
                });

                for (let f of adIframes) {
                    const rect = f.getBoundingClientRect();
                    if (rect.width > 200 && rect.height > 200) {
                        return { x: rect.right - 25, y: rect.top + 25 };
                    }
                }
                return null;
            }""")

            if google_iframe_closed:
                page.mouse.click(google_iframe_closed["x"], google_iframe_closed["y"])
                print(f"--> [SUCCESS] Clicked Google Ad top-right Close coordinates ({google_iframe_closed['x']}, {google_iframe_closed['y']})!")
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass

        if attempt >= 3:
            coords = [(1515, 235), (1520, 240), (1500, 230), (1480, 240), (1540, 245)]
            for cx, cy in coords:
                try:
                    page.mouse.click(cx, cy)
                    page.wait_for_timeout(200)
                except Exception:
                    pass

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    print("--> [RECOVERY] Ad overlay did not respond. Reloading earn-credits page...")
    try:
        page.goto("https://easemate.ai/earn-credits", wait_until="load")
        page.wait_for_timeout(1000)
        return True
    except Exception:
        pass

    return False


def click_ok_button(page):
    page.wait_for_timeout(1000)
    
    for _ in range(3):
        try:
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)
        except Exception:
            pass

        try:
            ok_clicked = page.evaluate("""() => {
                function findOK(doc) {
                    const buttons = Array.from(doc.querySelectorAll('button, div[role="button"], a, span'));
                    for (let btn of buttons) {
                        const txt = btn.textContent ? btn.textContent.trim().toLowerCase() : '';
                        if ((txt === 'ok' || txt === 'claim' || txt === 'confirm' || txt === 'got it') && btn.offsetWidth > 0 && btn.offsetHeight > 0) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }

                if (findOK(document)) return true;

                const iframes = document.querySelectorAll('iframe');
                for (let f of iframes) {
                    try {
                        if (f.contentDocument && findOK(f.contentDocument)) return true;
                    } catch(e) {}
                }
                return false;
            }""")
            if ok_clicked:
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass

        for frame in page.frames:
            locators = [
                frame.get_by_role("button", name="OK"),
                frame.get_by_text("OK", exact=True),
                frame.locator
