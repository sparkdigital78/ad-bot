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
shard_file = f"completed_accounts_shard_{shard_index}.txt"

# Clear ALL_DONE lock if progress state was reset
if os.path.exists("ALL_DONE.txt") and not any(os.path.exists(f"completed_accounts_shard_{i}.txt") for i in range(1, total_shards + 1)):
    os.remove("ALL_DONE.txt")

# Combine all completed accounts across all shards
completed_set = set()
for s in range(1, total_shards + 1):
    s_file = f"completed_accounts_shard_{s}.txt"
    if os.path.exists(s_file):
        with open(s_file, "r", encoding="utf-8") as f:
            completed_set.update({line.strip().lower() for line in f if line.strip()})

if os.path.exists("completed_accounts.txt"):
    with open("completed_accounts.txt", "r", encoding="utf-8") as f:
        completed_set.update({line.strip().lower() for line in f if line.strip()})

print(f"--> [SHARD {shard_index}/{total_shards}] Found {len(completed_set)} total completed accounts across all shards.")

# Filter out accounts already done today
PENDING_EMAILS = [e for e in ALL_EMAILS if e not in completed_set]

# Distribute pending accounts evenly across shards
SHARD_ASSIGNED_EMAILS = [
    email for idx, email in enumerate(PENDING_EMAILS)
    if idx % total_shards == (shard_index - 1)
]

print(f"--> [SHARD {shard_index}/{total_shards}] Total list size: {len(ALL_EMAILS)}")
print(f"--> [SHARD {shard_index}/{total_shards}] Remaining pending: {len(PENDING_EMAILS)}")
print(f"--> [SHARD {shard_index}/{total_shards}] Assigned to this shard: {len(SHARD_ASSIGNED_EMAILS)}")

if not SHARD_ASSIGNED_EMAILS:
    print(f"--> [SHARD {shard_index}] No pending accounts assigned to this worker. Exiting cleanly...")
    sys.exit(0)

ACCOUNTS = [{"id": i + 1, "email": email, "password": email_password} for i, email in enumerate(SHARD_ASSIGNED_EMAILS)]
TARGET_BATCH_SIZE = 15  # Increased batch size to 15 accounts together


def purge_popups(page):
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
                    const closeBtn = d.querySelector('button, [class*="close"], svg, i');
                    if (closeBtn) closeBtn.click();
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
        page.wait_for_timeout(2000)

        btn = page.locator("div").filter(has_text="Watch ad to earn credits").get_by_text("Go Now").last
        if btn.is_visible():
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            btn.click(force=True)

        page.evaluate("""() => {
            const allElements = Array.from(document.querySelectorAll('*'));
            const watchAdTitle = allElements.find(el =>
                el.children.length === 0 && el.textContent.includes('Watch ad to earn credits')
            );
            if (!watchAdTitle) return;

            let card = watchAdTitle;
            while (card && card.parentElement && !card.textContent.includes('10 ads/day')) {
                card = card.parentElement;
            }
            if (!card) card = watchAdTitle.closest('div');
            if (!card) return;

            const goNowBtn = Array.from(card.querySelectorAll('*')).find(el =>
                el.textContent.trim().toLowerCase().includes('go now')
            );
            if (goNowBtn) goNowBtn.click();
        }""")

        page.wait_for_timeout(3500)

        has_ad = page.evaluate("""() => {
            const googleFullscreen = document.querySelector('[id*="goog_fullscreen"], [src*="googleads"], [id*="google_ads"]');
            const videoElement = document.querySelector('video');
            const activeModal = document.querySelector('div[role="dialog"], [class*="modal-open"], [class*="overlay"]');
            
            if (videoElement || googleFullscreen) return true;
            if (activeModal) {
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
    page.wait_for_timeout(3000)

    purge_popups(page)
    page.wait_for_timeout(1000)

    page.mouse.wheel(0, 500)
    page.wait_for_timeout(1000)

    if check_daily_limit_reached(page):
        print(f"[{email}] LIMIT DETECTED: Account has used all ad opportunities for today!")
        return "LIMIT_REACHED"

    print(f"[{email}] Starting ad task...")
    
    ad_started = False
    for attempt in range(3):
        purge_popups(page)
        page.wait_for_timeout(1000)

        if click_watch_ad(page):
            ad_started = True
            break
        
        print(f"[{email}] Warning: Ad failed to launch (attempt {attempt + 1}/3). Reloading page to retry...")
        page.goto("https://easemate.ai/earn-credits", wait_until="load")
        page.wait_for_timeout(3000)
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

    os.makedirs("videos", exist_ok=True)

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

            context.close()
            current_context = None

            if status == "LIMIT_REACHED":
                print(f"--> [REMOVING ACCOUNT] {email} reached limit. Dropping from active batch.")
                finished_acc = active_batch.pop(current_idx)

                with open(shard_file, "a", encoding="utf-8") as f:
                    f.write(f"{finished_acc['email']}\n")

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
