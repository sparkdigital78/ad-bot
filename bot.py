import os
import time
import signal
import sys
import random
from playwright.sync_api import sync_playwright

current_context = None

# Ensure video artifact directory exists from start
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

# Distribute accounts evenly across shards
SHARD_ASSIGNED_EMAILS = [
    email for idx, email in enumerate(ALL_EMAILS)
    if idx % total_shards == (shard_index - 1)
]

print(f"--> [SHARD {shard_index}/{total_shards}] Total list size: {len(ALL_EMAILS)}")
print(f"--> [SHARD {shard_index}/{total_shards}] Assigned to this shard ({len(SHARD_ASSIGNED_EMAILS)}): {SHARD_ASSIGNED_EMAILS}")

if not SHARD_ASSIGNED_EMAILS:
    print(f"--> [SHARD {shard_index}] No accounts assigned to this worker. Exiting cleanly...")
    sys.exit(0)

# Stagger startup with randomized jitter
startup_delay = (shard_index - 1) * random.randint(3, 8)
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
            for frame in page.frames:
                frame_element = frame.get_by_text(phrase, exact=False)
                if frame_element.count() > 0 and frame_element.first.is_visible():
                    return True
        except Exception:
            pass

    try:
        has_limit = page.evaluate("""() => {
            const allNodes = Array.from(document.querySelectorAll('*'));
            return allNodes.some(node => 
                node.textContent && 
                node.textContent.includes('You have used all your ad watch opportunities for today')
            );
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
                "text=/^close$/i",
                "text='Close'",
                "text='close'",
                "#dismiss-button",
                "[aria-label*='close' i]",
                "[aria-label*='dismiss' i]",
                "button:has-text('Close')",
                "div:has-text('Close')"
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
                                print(f"--> [SUCCESS] Frame locator '{sel}' clicked 'Close' (attempt {attempt + 1})!")
                                page.wait_for_timeout(1000)
                                return True
                except Exception:
                    pass

        try:
            closed = page.evaluate("""() => {
                function clickCloseInDoc(doc) {
                    const allEls = Array.from(doc.querySelectorAll('*'));
                    for (let el of allEls) {
                        const txt = (el.textContent || '').trim().toLowerCase();
                        const id = (el.id || '').toLowerCase();
                        if (txt === 'close' || txt === '×' || id.includes('dismiss')) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                el.click();
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                                return true;
                            }
                        }
                    }
                    return false;
                }

                if (clickCloseInDoc(document)) return true;

                const iframes = document.querySelectorAll('iframe');
                for (let f of iframes) {
                    try {
                        if (f.contentDocument && clickCloseInDoc(f.contentDocument)) return true;
                    } catch(e) {}
                }
                return false;
            }""")
            if closed:
                print(f"--> [SUCCESS] JavaScript clicked 'Close' text (attempt {attempt + 1})!")
                page.wait_for_timeout(1000)
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

    print("--> [RECOVERY] Ad overlay did not respond. Refreshing page to clear modal...")
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
                frame.locator("text=/^ok$/i"),
                frame.locator("button:has-text('OK')"),
                frame.locator("div[role='dialog'] button")
            ]
            for loc in locators:
                try:
                    count = loc.count()
                    for i in range(count):
                        element = loc.nth(i)
                        if element.is_visible():
                            element.click(force=True)
                            page.wait_for_timeout(1000)
                            return True
                except Exception:
                    pass
        page.wait_for_timeout(800)

    return True


def click_watch_ad(page):
    try:
        human_delay(1.5, 3.0)

        for _ in range(3):
            page.mouse.wheel(0, 200)
            time.sleep(0.2)

        ad_title = page.get_by_text("Watch ad to earn credits", exact=False).first
        
        clicked = False
        if ad_title.is_visible():
            card_container = page.locator("div").filter(has=ad_title).filter(has_text="Go Now").last
            btn = card_container.locator("button, a, div").filter(has_text="Go Now").last
            
            if btn.is_visible():
                btn.scroll_into_view_if_needed()
                human_delay(0.5, 1.0)
                btn.click(force=True)
                print("--> [CLICK] Found and clicked 'Go Now' for Watch Ad!")
                clicked = True

        if not clicked:
            page.evaluate("""() => {
                const elements = Array.from(document.querySelectorAll('*'));
                const targetText = elements.find(el => el.textContent && el.textContent.trim() === 'Watch ad to earn credits');
                if (targetText) {
                    let parent = targetText.parentElement;
                    while (parent && !parent.textContent.includes('Go Now')) {
                        parent = parent.parentElement;
                    }
                    if (parent) {
                        const goBtn = Array.from(parent.querySelectorAll('*')).find(el => el.textContent && el.textContent.trim().toLowerCase() === 'go now');
                        if (goBtn) goBtn.click();
                    }
                }
            }""")

        page.wait_for_timeout(3500)

        if check_daily_limit_reached(page):
            print("--> [LIMIT POPUP DETECTED] Popup appeared right after clicking 'Go Now'!")
            return "LIMIT_REACHED"

        page.wait_for_timeout(1500)

        has_ad = page.evaluate("""() => {
            const googleFullscreen = document.querySelector('[id*="goog"], [src*="googleads"], [id*="google_ads"], iframe[src*="doubleclick"]');
            const videoElement = document.querySelector('video');
            const activeModal = document.querySelector('div[role="dialog"], [class*="modal-open"], [class*="overlay"]');
            
            if (videoElement || googleFullscreen) return true;
            if (activeModal) {
                const rect = activeModal.getBoundingClientRect();
                if (rect.width > 250 && rect.height > 250) return true;
            }
            return false;
        }""")

        if has_ad:
            force_unpause_videos(page)
            return True

        for frame in page.frames:
            if "google" in frame.url or "doubleclick" in frame.url:
                force_unpause_videos(page)
                return True

        return False
    except Exception as e:
        print(f"--> Error in click_watch_ad: {e}")
        return False


def watch_single_ad_for_account(page, account):
    """Logs into account, watches 1 ad, and returns status."""
    email = account["email"]
    password = account["password"]

    print(f"--- Logging into: {email} ---")
    page.goto("https://easemate.ai/Dashboard", wait_until="networkidle")
    human_delay(1.0, 2.0)

    handle_daily_checkin_modal(page)
    human_delay(0.5, 1.0)

    page.get_by_text("Log In", exact=True).first.click()
    human_delay(1.0, 1.5)

    try:
        email_option = page.get_by_text("Continue with Email", exact=True)
        if email_option.is_visible():
            email_option.click()
            human_delay(0.8, 1.5)
    except Exception:
        pass

    page.wait_for_selector("input[placeholder='Enter your email address']")
    page.type("input[placeholder='Enter your email address']", email, delay=random.randint(40, 90))
    human_delay(0.5, 1.0)

    try:
        limit_err = page.locator("text=/signature limit exceeded/i")
        if limit_err.count() > 0 and limit_err.first.is_visible():
            print(f"[{email}] SIGNATURE LIMIT EXCEEDED on login input! Dropping account from round-robin...")
            return "LIMIT_REACHED"
    except Exception:
        pass

    page.type("input[placeholder='Enter your Password']", password, delay=random.randint(40, 90))
    human_delay(0.5, 1.0)

    page.get_by_role("button", name="Log in").last.click()
    page.wait_for_timeout(4000)

    handle_daily_checkin_modal(page)

    try:
        limit_err = page.locator("text=/signature limit exceeded/i")
        if limit_err.count() > 0 and limit_err.first.is_visible():
            print(f"[{email}] SIGNATURE LIMIT EXCEEDED after submit! Dropping account from round-robin...")
            return "LIMIT_REACHED"
    except Exception:
        pass

    print(f"[{email}] Navigating to Earn Credits page...")
    page.goto("https://easemate.ai/earn-credits", wait_until="load")
    human_delay(2.0, 3.5)

    handle_daily_checkin_modal(page)
    page.mouse.wheel(0, 500)
    human_delay(1.0, 1.5)

    if check_daily_limit_reached(page):
        print(f"[{email}] >>> DAILY LIMIT DETECTED! Dropping {email} permanently from cycle. <<<")
        return "LIMIT_REACHED"

    print(f"[{email}] Attempting to watch 1 ad...")
    ad_status = click_watch_ad(page)

    if ad_status == "LIMIT_REACHED" or check_daily_limit_reached(page):
        print(f"[{email}] >>> DAILY LIMIT DETECTED! Dropping {email} permanently from cycle. <<<")
        return "LIMIT_REACHED"

    if ad_status is False:
        print(f"[{email}] Ad failed to load. Reloading earn-credits page...")
        page.goto("https://easemate.ai/earn-credits", wait_until="load")
        human_delay(2.0, 3.5)
        handle_daily_checkin_modal(page)
        page.mouse.wheel(0, 500)

        if check_daily_limit_reached(page):
            print(f"[{email}] >>> DAILY LIMIT DETECTED! Dropping {email} permanently from cycle. <<<")
            return "LIMIT_REACHED"

        ad_status = click_watch_ad(page)
        if ad_status == "LIMIT_REACHED" or check_daily_limit_reached(page):
            print(f"[{email}] >>> DAILY LIMIT DETECTED! Dropping {email} permanently from cycle. <<<")
            return "LIMIT_REACHED"

        if ad_status is False:
            print(f"[{email}] Ad network served no ad. Moving to next account in rotation.")
            return "NO_AD"

    page.wait_for_timeout(1000)

    if check_daily_limit_reached(page):
        print(f"[{email}] >>> DAILY LIMIT DETECTED! Dropping {email} permanently from cycle. <<<")
        return "LIMIT_REACHED"

    print(f"[{email}] Watching video ad (35s)...")
    for _ in range(7):
        force_unpause_videos(page)
        time.sleep(5)

    print(f"[{email}] Closing ad player...")
    page.wait_for_timeout(1000)
    click_close_button(page)

    page.wait_for_timeout(1000)
    click_ok_button(page)
    human_delay(1.5, 2.5)

    if check_daily_limit_reached(page):
        print(f"[{email}] >>> DAILY LIMIT DETECTED! Dropping {email} permanently from cycle. <<<")
        return "LIMIT_REACHED"

    print(f"[{email}] SUCCESS: Watched 1 ad successfully! Switching to next account in cycle.")
    return "SUCCESS"


def run_all_accounts():
    global current_context

    active_accounts = list(ACCOUNTS)
    round_number = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
                "--autoplay-policy=no-user-gesture-required"
            ]
        )

        while active_accounts:
            print("\n" + "=" * 70)
            print(f"[ROUND {round_number}] Active accounts remaining in shard: {len(active_accounts)}")
            print("=" * 70)

            accounts_to_remove = []

            for account in active_accounts:
                email = account["email"]
                print("\n" + "-" * 50)
                print(f"[SHARD {shard_index}/{total_shards}] Round {round_number} -> Account: {email}")
                print("-" * 50)

                v_width = random.choice([1920, 1536, 1440, 1366])
                v_height = random.choice([1080, 864, 900, 768])

                context = browser.new_context(
                    viewport={"width": v_width, "height": v_height},
                    record_video_dir="videos/",
                    record_video_size={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                    locale="en-US",
                    timezone_id="America/New_York"
                )
                
                page = context.new_page()
                
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    window.chrome = { runtime: {} };
                """)
                
                current_context = context

                try:
                    status = watch_single_ad_for_account(page, account)
                    
                    if status == "LIMIT_REACHED":
                        print(f"--> [DROPPED] Removing {email} permanently from future rounds.")
                        accounts_to_remove.append(account)

                except Exception as e:
                    print(f"Error executing {email}: {e}")

                context.close()
                current_context = None

            for acc in accounts_to_remove:
                if acc in active_accounts:
                    active_accounts.remove(acc)

            round_number += 1

        print("\n" + "=" * 70)
        print(f"SUMMARY: ALL ACCOUNTS IN SHARD {shard_index}/{total_shards} HAVE COMPLETED THEIR DAILY LIMITS!")
        print("=" * 70)

        browser.close()


if __name__ == "__main__":
    run_all_accounts()
