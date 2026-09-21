import os
import time
import signal
import sys
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
# READ EMAILS FROM emails.txt WITH FALLBACK TO SECRETS/ENV
# ============================================================
raw_emails = ""
if os.path.exists("emails.txt"):
    print("--> Loading email list from 'emails.txt'...")
    with open("emails.txt", "r", encoding="utf-8") as f:
        raw_emails = f.read()
else:
    print("--> 'emails.txt' not found. Falling back to ALL_EMAILS environment variable...")
    raw_emails = os.environ.get("ALL_EMAILS", "")

email_password = os.environ.get("ACCOUNT_PASSWORD", "")
ALL_EMAILS = [e.strip() for e in raw_emails.replace(",", " ").split() if e.strip()]

if not ALL_EMAILS:
    raise ValueError("ERROR: No email addresses found! Please create 'emails.txt' with your email list.")

ACCOUNTS = [{"id": i + 1, "email": email, "password": email_password} for i, email in enumerate(ALL_EMAILS)]
TARGET_BATCH_SIZE = 5


def purge_popups(page):
    """Safely removes promotional popups and carousels while leaving the Login Modal untouched."""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    try:
        page.evaluate("""() => {
            const modals = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"], [class*="card"]'));
            modals.forEach(m => {
                const isLoginForm = m.querySelector('input[placeholder*="email" i], input[type="email"]') ||
                                    (m.textContent && (m.textContent.includes('Sign in') || m.textContent.includes('Continue with Email')));
                const isPromo = m.textContent && (m.textContent.includes('GPT Image') || m.textContent.includes('SEEDANCE') || m.textContent.includes('WAN 3.0') || m.textContent.includes("WHAT'S NEW"));
                if (!isLoginForm && (isPromo || m.getAttribute('role') === 'dialog')) {
                    m.remove();
                }
            });

            const overlays = Array.from(document.querySelectorAll('[class*="backdrop"], [class*="overlay"]'));
            overlays.forEach(o => {
                if (!o.querySelector('input')) {
                    o.remove();
                }
            });
        }""")
    except Exception:
        pass


def check_daily_limit_reached(page):
    try:
        limit_text = "You have used all your ad watch opportunities for today"
        for frame in page.frames:
            element = frame.get_by_text(limit_text, exact=False)
            if element.count() > 0 and element.first.is_visible():
                return True
    except Exception:
        pass
    return False


def click_close_button(page):
    """5-Layer close engine specifically targeting Google Interstitial 'Close' buttons."""
    print("--> Waiting for 'Close' button to appear...")

    for attempt in range(15):
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
    
    for _ in range(5):
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
        page.wait_for_timeout(1000)

    return False


def click_watch_ad(page):
    try:
        clicked = page.evaluate("""() => {
            const allElements = Array.from(document.querySelectorAll('*'));
            const watchAdTitle = allElements.find(el =>
                el.children.length === 0 && el.textContent.includes('Watch ad to earn credits')
            );
            if (!watchAdTitle) return false;

            let card = watchAdTitle;
            while (card && card.parentElement && !card.textContent.includes('10 ads/day')) {
                card = card.parentElement;
            }
            if (!card) card = watchAdTitle.closest('div');
            if (!card) return false;

            const elements = Array.from(card.querySelectorAll('*'));
            const goNowBtn = elements.find(el =>
                el.textContent.trim().toLowerCase().includes('go now')
            );

            if (!goNowBtn) return false;

            goNowBtn.scrollIntoView({ behavior: 'instant', block: 'center' });
            goNowBtn.click();
            return true;
        }""")
        if clicked:
            return True
    except Exception:
        pass

    try:
        page.locator("div").filter(has_text="Watch ad to earn credits").get_by_text("Go Now").last.click(force=True)
        return True
    except Exception:
        pass
    return False


def process_single_account(page, account):
    email = account["email"]
    password = account["password"]

    print(f"--- Logging into: {email} ---")
    page.goto("https://easemate.ai/Dashboard", wait_until="load")
    page.wait_for_timeout(1000)

    purge_popups(page)
    page.wait_for_timeout(1000)

    page.get_by_text("Log In", exact=True).first.click()
    page.wait_for_timeout(1000)

    try:
        email_option = page.get_by_text("Continue with Email", exact=True)
        if email_option.is_visible():
            email_option.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    page.wait_for_selector("input[placeholder='Enter your email address']")
    page.fill("input[placeholder='Enter your email address']", email)
    page.wait_for_timeout(1000)

    page.fill("input[placeholder='Enter your Password']", password)
    page.wait_for_timeout(1000)

    page.get_by_role("button", name="Log in").last.click()
    page.wait_for_timeout(4000)

    print(f"[{email}] Navigating to Earn Credits page...")
    page.goto("https://easemate.ai/earn-credits", wait_until="load")
    
    page.wait_for_timeout(2500)

    purge_popups(page)
    page.wait_for_timeout(1000)

    page.mouse.wheel(0, 500)
    page.wait_for_timeout(1000)

    if check_daily_limit_reached(page):
        print(f"[{email}] LIMIT DETECTED: Account has used all ad opportunities for today!")
        return "LIMIT_REACHED"

    print(f"[{email}] Starting ad task...")
    purge_popups(page)
    page.wait_for_timeout(1000)

    if not click_watch_ad(page):
        print(f"[{email}] ERROR: Could not click 'Go Now'. Skipping...")
        return "ERROR"

    page.wait_for_timeout(1500)
    purge_popups(page)
    page.wait_for_timeout(1000)

    if check_daily_limit_reached(page):
        print(f"[{email}] LIMIT DETECTED: 'You have used all your ad watch opportunities for today.'")
        return "LIMIT_REACHED"

    print(f"[{email}] Watching video ad (35s)...")
    time.sleep(35)

    print(f"[{email}] Closing ad player...")
    page.wait_for_timeout(1000)
    if click_close_button(page):
        print(f"[{email}] Ad closed successfully.")
    else:
        print(f"[{email}] Warning: Close button click failed.")

    page.wait_for_timeout(1000)

    print(f"[{email}] Claiming reward...")
    if click_ok_button(page):
        print(f"[{email}] SUCCESS: Reward claimed!")
    else:
        print(f"[{email}] Warning: OK button not found.")

    page.wait_for_timeout(1000)

    return "SUCCESS"


def run_all_accounts():
    global current_context
    remaining_pool = list(ACCOUNTS)
    active_batch = []

    while remaining_pool and len(active_batch) < TARGET_BATCH_SIZE:
        active_batch.append(remaining_pool.pop(0))

    cycle_count = 1
    current_idx = 0

    os.makedirs("videos", exist_ok=True)

    with sync_playwright() as p:
        print(f"Total Accounts Loaded: {len(ACCOUNTS)}")
        
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        while active_batch:
            if current_idx >= len(active_batch):
                current_idx = 0
                cycle_count += 1
                print("\n" + "=" * 60)
                print(f"   STARTING CYCLE {cycle_count} ACROSS CURRENT {len(active_batch)} ACTIVE ACCOUNTS")
                print("=" * 60)

            account = active_batch[current_idx]
            print(f"\n[Cycle {cycle_count} | Slot {current_idx + 1}/{len(active_batch)}] Account: {account['email']}")

            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir="videos/",
                record_video_size={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            current_context = context
            page = context.new_page()

            try:
                status = process_single_account(page, account)
            except Exception as e:
                print(f"Error executing {account['email']}: {e}")
                status = "ERROR"

            context.close()
            current_context = None

            if status == "LIMIT_REACHED":
                print(f"--> [REMOVING ACCOUNT] {account['email']} reached limit. Dropping from active batch.")
                active_batch.pop(current_idx)

                if remaining_pool:
                    new_acc = remaining_pool.pop(0)
                    print(f"--> [ADDING NEW ACCOUNT] Pulled {new_acc['email']} into slot {current_idx + 1}.")
                    active_batch.insert(current_idx, new_acc)
                else:
                    print(f"--> Pool empty. Active batch size reduced to {len(active_batch)}.")
            else:
                current_idx += 1
                time.sleep(1)

        print("\n" + "=" * 60)
        print(f"ALL {len(ACCOUNTS)} ACCOUNTS HAVE REACHED THEIR DAILY AD LIMIT FOR TODAY!")
        print("=" * 60)
        browser.close()


if __name__ == "__main__":
    run_all_accounts()
