import os
import time
import signal
import sys
import random
from playwright.sync_api import sync_playwright

# Ensure video output directory exists immediately at startup
os.makedirs("videos", exist_ok=True)

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

ACCOUNTS = [{"id": i + 1, "email": email, "password": email_password} for i, email in enumerate(SHARD_ASSIGNED_EMAILS)]
TARGET_BATCH_SIZE = 15


def dismiss_all_modals_and_checkin(page):
    """Handles daily check-in and forcefully removes initial blocking overlays except login."""
    try:
        page.wait_for_timeout(500)
        page.evaluate("""() => {
            const modals = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"], [class*="overlay"]'));
            modals.forEach(m => {
                const isLogin = m.querySelector('input[type="email"], input[placeholder*="email" i]') || 
                                (m.textContent && m.textContent.includes('Sign in to EaseMate'));
                if (!isLogin && m.textContent && m.textContent.includes('Daily check-in')) {
                    const checkInBtn = Array.from(m.querySelectorAll('button, div[role="button"], span')).find(
                        b => b.textContent && b.textContent.trim().toLowerCase() === 'check in'
                    );
                    if (checkInBtn && !checkInBtn.disabled) {
                        try { checkInBtn.click(); } catch(e) {}
                    }
                    const closeBtn = m.querySelector('button, [class*="close"], svg, i, [aria-label*="close" i]');
                    if (closeBtn) {
                        try { closeBtn.click(); } catch(e) {}
                    }
                    try { m.remove(); } catch(e) {}
                }
            });
            const backdrops = document.querySelectorAll('[class*="backdrop"], [class*="mask"], [class*="modal-backdrop"]');
            backdrops.forEach(b => { 
                if (!document.querySelector('input[placeholder*="email" i]')) {
                    try { b.remove(); } catch(e) {}
                }
            });
        }""")
    except Exception as e:
        print(f"--> [POPUP DISMISS] Notice: {e}")


def purge_popups(page):
    """Dismisses side banner overlays and promo cards without touching login."""
    try:
        page.evaluate("""() => {
            const dialogs = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"]'));
            dialogs.forEach(d => {
                const isLogin = d.querySelector('input[placeholder*="email" i], input[type="email"]') ||
                                (d.textContent && d.textContent.includes('Sign in'));
                if (!isLogin) {
                    const closeBtn = d.querySelector('button, [class*="close"], svg, i, [aria-label*="close" i]');
                    if (closeBtn) {
                        try { closeBtn.click(); } catch(e) {}
                    }
                    try { d.remove(); } catch(e) {}
                }
            });
        }""")
    except Exception:
        pass


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
    """Checks for limit message anywhere in DOM or active toast banners."""
    try:
        has_limit_toast = page.evaluate("""() => {
            const searchText = 'used all your ad watch opportunities';
            const elements = Array.from(document.querySelectorAll('*'));
            for (let el of elements) {
                const text = (el.textContent || '').toLowerCase();
                if (text.includes(searchText)) {
                    return true;
                }
            }
            return false;
        }""")
        if has_limit_toast:
            return True

        limit_text = "used all your ad watch opportunities"
        for frame in page.frames:
            element = frame.get_by_text(limit_text, exact=False)
            if element.count() > 0 and element.first.is_visible():
                return True
    except Exception:
        pass
    return False


def ensure_login_form_ready(page):
    """Ensures email/password fields are open and visible on screen."""
    email_input = page.locator("input[placeholder='Enter your email address']")
    if email_input.is_visible():
        return True

    try:
        email_btn = page.locator("text='Continue with Email'")
        if email_btn.count() > 0 and email_btn.first.is_visible():
            email_btn.first.click(force=True)
            page.wait_for_timeout(800)
            if email_input.is_visible():
                return True
    except Exception:
        pass

    page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('button, a, div, span'));
        const btn = els.find(e => {
            const txt = (e.textContent || '').trim();
            return txt === 'Log in' || txt === 'Log In' || txt === 'Sign in' || txt === 'Sign In';
        });
        if (btn) btn.click();
    }""")
    page.wait_for_timeout(1500)

    try:
        email_btn = page.locator("text='Continue with Email'")
        if email_btn.count() > 0 and email_btn.first.is_visible():
            email_btn.first.click(force=True)
            page.wait_for_timeout(800)
    except Exception:
        pass

    return email_input.is_visible()


def submit_login_form(page, email, password):
    """Fills credentials, submits the login form, and forces the login modal to close."""
    email_selector = "input[placeholder='Enter your email address']"
    password_selector = "input[placeholder='Enter your Password']"

    page.wait_for_selector(email_selector, timeout=8000)
    page.fill(email_selector, email)
    page.wait_for_timeout(500)

    page.fill(password_selector, password)
    page.wait_for_timeout(500)

    submitted = page.evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input'));
        const passInput = inputs.find(i => i.type === 'password' || (i.placeholder && i.placeholder.includes('Password')));
        if (!passInput) return false;

        let form = passInput.closest('form');
        if (!form) form = passInput.closest('div[role="dialog"], [class*="modal"]');
        if (!form) return false;

        const loginBtn = Array.from(form.querySelectorAll('button, div[role="button"], input[type="submit"]')).find(b => {
            const txt = (b.textContent || '').trim().toLowerCase();
            return txt === 'log in' || txt === 'login' || txt === 'sign in';
        });

        if (loginBtn) {
            loginBtn.click();
            return true;
        }
        return false;
    }""")

    if not submitted:
        page.get_by_role("button", name="Log in").last.click(force=True)

    page.wait_for_timeout(3000)

    # Force close or purge the login modal if it didn't auto-close after success
    try:
        page.evaluate("""() => {
            const modals = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"]'));
            modals.forEach(m => {
                if (m.querySelector('input[type="password"]') || (m.textContent && m.textContent.includes('Sign in to EaseMate'))) {
                    const closeBtn = m.querySelector('button, [class*="close"], svg, i, [aria-label*="close" i]');
                    if (closeBtn) {
                        try { closeBtn.click(); } catch(e) {}
                    }
                    try { m.remove(); } catch(e) {}
                }
            });
            const backdrops = document.querySelectorAll('[class*="backdrop"], [class*="mask"], [class*="modal-backdrop"]');
            backdrops.forEach(b => { try { b.remove(); } catch(e) {} });
        }""")
    except Exception:
        pass

    page.wait_for_timeout(1000)


def click_close_button(page):
    print("--> Waiting for Ad 'Close' button to appear...")

    for attempt in range(12):
        force_unpause_videos(page)
        page.wait_for_timeout(1000)

        closed = page.evaluate("""() => {
            const allElements = Array.from(document.querySelectorAll('*'));
            for (let el of allElements) {
                const text = (el.textContent || '').trim();
                if (text === 'Close' || text === 'close' || text === '×') {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""")

        if closed:
            print(f"--> [SUCCESS] Clicked 'Close' button on overlay (attempt {attempt + 1})!")
            page.wait_for_timeout(1000)
            return True

        for frame in page.frames:
            for sel in ["[aria-label*='close' i]", "text='Close'", "text='close'", "#dismiss-button", "button:has-text('Close')"]:
                try:
                    loc = frame.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.click(force=True)
                        print(f"--> [SUCCESS] Frame locator '{sel}' clicked 'Close'!")
                        page.wait_for_timeout(1000)
                        return True
                except Exception:
                    pass

        if attempt >= 2:
            top_right_coords = [(1515, 235), (1500, 235), (1520, 240)]
            for cx, cy in top_right_coords:
                try:
                    page.mouse.click(cx, cy)
                    page.wait_for_timeout(300)
                except Exception:
                    pass

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    print("--> [FORCE PURGE] Removing remaining ad modal overlays from DOM...")
    page.evaluate("""() => {
        const adModals = document.querySelectorAll('[class*="modal"], [class*="overlay"], [class*="dialog"]');
        adModals.forEach(m => { try { m.remove(); } catch(e) {} });
    }""")
    return True


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
        dismiss_all_modals_and_checkin(page)
        purge_popups(page)
        page.wait_for_timeout(1000)

        page.evaluate("""() => {
            const el = Array.from(document.querySelectorAll('*')).find(
                e => e.children.length === 0 && e.textContent.includes('Watch ad to earn credits')
            );
            if (el) el.scrollIntoView({ block: 'center', inline: 'center' });
        }""")
        page.wait_for_timeout(800)

        clicked = page.evaluate("""() => {
            const elements = Array.from(document.querySelectorAll('*'));
            const title = elements.find(el => el.children.length === 0 && el.textContent.includes('Watch ad to earn credits'));
            if (!title) return false;

            let card = title;
            while (card && card.parentElement && !card.textContent.includes('Go Now')) {
                card = card.parentElement;
            }
            if (!card) return false;

            const btn = Array.from(card.querySelectorAll('*')).find(
                el => el.textContent && el.textContent.trim().toLowerCase() === 'go now'
            );
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }""")

        if clicked:
            print("--> [CLICK] Watch Ad 'Go Now' clicked successfully via JavaScript!")

        page.wait_for_timeout(1500)
        if check_daily_limit_reached(page):
            return "LIMIT_REACHED"

        page.wait_for_timeout(2000)
        dismiss_all_modals_and_checkin(page)

        has_ad = page.evaluate("""() => {
            const googleFullscreen = document.querySelector('[id*="goog_fullscreen"], [src*="googleads"], [id*="google_ads"]');
            const videoElement = document.querySelector('video');
            const activeModal = document.querySelector('div[role="dialog"], [class*="modal-open"], [class*="overlay"]');
            
            if (videoElement || googleFullscreen) return true;
            if (activeModal && !activeModal.textContent.includes('Daily check-in')) {
                const rect = activeModal.getBoundingClientRect();
                if (rect.width > 300 && rect.height > 300) return true;
            }
            return false;
        }""")

        if has_ad:
            force_unpause_videos(page)
            return True

        return False
    except Exception as e:
        print(f"--> Error in click_watch_ad: {e}")
        return False


def process_single_account(page, account):
    email = account["email"]
    password = account["password"]

    print(f"--- Logging into: {email} ---")
    page.goto("https://easemate.ai/earn-credits", wait_until="load")
    page.wait_for_timeout(1500)

    if not ensure_login_form_ready(page):
        print(f"[{email}] ERROR: Login inputs not accessible. Skipping account...")
        return "ERROR"

    submit_login_form(page, email, password)

    dismiss_all_modals_and_checkin(page)
    purge_popups(page)

    page.mouse.wheel(0, 500)
    page.wait_for_timeout(1000)

    if check_daily_limit_reached(page):
        print(f"[{email}] LIMIT DETECTED: Account has used all ad opportunities for today!")
        return "LIMIT_REACHED"

    print(f"[{email}] Starting ad task...")
    
    ad_started = False
    for attempt in range(3):
        dismiss_all_modals_and_checkin(page)
        purge_popups(page)
        page.wait_for_timeout(1000)

        result = click_watch_ad(page)
        if result == "LIMIT_REACHED":
            print(f"[{email}] LIMIT DETECTED from toast: 'You have used all your ad watch opportunities for today.'")
            return "LIMIT_REACHED"
        elif result is True:
            ad_started = True
            break
        
        print(f"[{email}] Warning: Ad failed to launch (attempt {attempt + 1}/3). Reloading page to retry...")
        page.goto("https://easemate.ai/earn-credits", wait_until="load")
        page.wait_for_timeout(2500)
        dismiss_all_modals_and_checkin(page)
        page.mouse.wheel(0, 500)

    if not ad_started:
        print(f"[{email}] ERROR: Ad network served no ad for this account. Skipping to next account...")
        return "ERROR"

    page.wait_for_timeout(1000)

    if check_daily_limit_reached(page):
        print(f"[{email}] LIMIT DETECTED: 'You have used all your ad watch opportunities for today.'")
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
    page.wait_for_timeout(2000)

    print(f"[{email}] SUCCESS: Ad cycle completed and reward claimed!")
    return "SUCCESS"


def run_all_accounts():
    global current_context
    total_assigned = len(SHARD_ASSIGNED_EMAILS)
    remaining_pool = list(ACCOUNTS)
    active_batch = []

    while remaining_pool and len(active_batch) < TARGET_BATCH_SIZE:
        active_batch.append(remaining_pool.pop(0))

    cycle_count = 1
    current_idx = 0

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

        while active_batch:
            if current_idx >= len(active_batch):
                current_idx = 0
                cycle_count += 1
                print("\n" + "=" * 60)
                print(f"   STARTING CYCLE {cycle_count} ACROSS CURRENT {len(active_batch)} ACTIVE ACCOUNTS")
                print("=" * 60)

            account = active_batch[current_idx]
            email = account["email"]

            print("\n" + "-" * 50)
            print(f" [PROGRESS STATUS - SHARD {shard_index}/{total_shards}]")
            print(f"  • Assigned To This Runner:   {total_assigned}")
            print(f"  • Currently Active Batch:    {len(active_batch)}")
            print(f"  • Waiting in Queue:          {len(remaining_pool)}")
            print("-" * 50)
            print(f"[Cycle {cycle_count} | Slot {current_idx + 1}/{len(active_batch)}] Account: {email}")

            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir="videos/",
                record_video_size={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            current_context = context

            try:
                status = process_single_account(page, account)
            except Exception as e:
                print(f"Error executing {email}: {e}")
                status = "ERROR"
            finally:
                if current_context:
                    current_context.close()
                    current_context = None

            if status == "LIMIT_REACHED":
                print(f"--> [REMOVING ACCOUNT] {email} reached limit. Dropping from active batch.")
                active_batch.pop(current_idx)

                if remaining_pool:
                    new_acc = remaining_pool.pop(0)
                    print(f"--> [ADDING NEW ACCOUNT] Pulled {new_acc['email']} into slot {current_idx + 1}.")
                    active_batch.insert(current_idx, new_acc)
                else:
                    print(f"--> Pool empty. Active batch size reduced to {len(active_batch)}.")
            else:
                current_idx += 1

        print("\n" + "=" * 60)
        print(f"SUMMARY: SHARD {shard_index}/{total_shards} HAS FINISHED ALL ASSIGNED ACCOUNTS!")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    run_all_accounts()
