import os
import csv
import time
import signal
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright

# Ensure output directories exist
os.makedirs("videos", exist_ok=True)
os.makedirs("reports", exist_ok=True)

current_context = None


def shutdown_handler(sig, frame):
    global current_context
    print("\n--> [STOP / CANCEL DETECTED] Closing context to flush files...")
    if current_context:
        try:
            current_context.close()
        except Exception as e:
            print(f"--> Error closing context: {e}")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ============================================================
# LOAD ACCOUNTS & SHARD CONFIGURATION
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

print(f"--> [SHARD {shard_index}/{total_shards}] Total accounts: {len(ALL_EMAILS)}")
print(f"--> [SHARD {shard_index}/{total_shards}] Assigned to this shard: {len(SHARD_ASSIGNED_EMAILS)}")

if not SHARD_ASSIGNED_EMAILS:
    print(f"--> [SHARD {shard_index}] No accounts assigned. Exiting cleanly...")
    sys.exit(0)

CSV_REPORT_PATH = f"reports/advanced_credits_shard_{shard_index}.csv"
TXT_REPORT_PATH = f"reports/advanced_credits_shard_{shard_index}.txt"


def init_reports():
    """Creates the CSV and TXT report files with Advanced Credits headers."""
    with open(CSV_REPORT_PATH, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Email", "Status", "Advanced Credits"])

    with open(TXT_REPORT_PATH, mode="w", encoding="utf-8") as f:
        f.write(f"EASEMATE AI ADVANCED CREDITS REPORT (SHARD {shard_index}/{total_shards}) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 75 + "\n")
        f.write(f"{'EMAIL':<42} | {'STATUS':<12} | {'ADV CREDITS':<12}\n")
        f.write("-" * 75 + "\n")


def log_result(email, status, adv_credits="N/A"):
    """Appends a single account's Advanced Credits result to both CSV and TXT files immediately."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CSV_REPORT_PATH, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([now_str, email, status, adv_credits])

    with open(TXT_REPORT_PATH, mode="a", encoding="utf-8") as f:
        f.write(f"{email:<42} | {status:<12} | {str(adv_credits):<12}\n")


def dismiss_overlays(page, keep_login=True):
    """Clears promo popups and daily check-in modals without breaking active login."""
    try:
        page.evaluate("""(keepLogin) => {
            const modals = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"]'));
            modals.forEach(m => {
                const isLogin = m.querySelector('input[type="email"], input[placeholder*="email" i]') || 
                                (m.textContent && m.textContent.includes('Sign in to EaseMate'));
                if (keepLogin && isLogin) return;

                const closeBtn = m.querySelector('button, [class*="close"], svg, i, [aria-label*="close" i]');
                if (closeBtn) {
                    try { closeBtn.click(); } catch(e) {}
                }
                try { m.remove(); } catch(e) {}
            });
        }""", keep_login)
    except Exception:
        pass


def login_account(page, email, password):
    """Opens login modal, enters credentials, submits, and verifies login succeeded."""
    page.goto("https://easemate.ai/", wait_until="networkidle", timeout=25000)
    page.wait_for_timeout(1500)
    dismiss_overlays(page, keep_login=True)

    email_selector = "input[placeholder='Enter your email address']"
    password_selector = "input[placeholder='Enter your Password']"

    # Step 1: Open Login Modal
    for _ in range(3):
        if page.locator(email_selector).is_visible():
            break

        page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('button, a, div, span'));
            const btn = els.find(e => {
                const txt = (e.textContent || '').trim();
                return txt === 'Log In' || txt === 'Log in' || txt === 'Sign In' || txt === 'Sign in';
            });
            if (btn) btn.click();
        }""")
        page.wait_for_timeout(1500)

        email_btn = page.locator("text='Continue with Email'")
        if email_btn.count() > 0 and email_btn.first.is_visible():
            email_btn.first.click(force=True)
            page.wait_for_timeout(1000)

    if not page.locator(email_selector).is_visible():
        return False, "LOGIN_MODAL_FAILED"

    # Step 2: Fill Email & Password with native input events
    page.locator(email_selector).fill(email)
    page.locator(email_selector).dispatch_event("input")
    page.locator(email_selector).dispatch_event("change")
    page.wait_for_timeout(400)

    page.locator(password_selector).fill(password)
    page.locator(password_selector).dispatch_event("input")
    page.locator(password_selector).dispatch_event("change")
    page.wait_for_timeout(400)

    # Step 3: Submit Login
    submitted = page.evaluate("""() => {
        const passInput = document.querySelector("input[placeholder='Enter your Password']");
        if (!passInput) return false;
        const container = passInput.closest('form') || passInput.closest('div[role="dialog"], [class*="modal"]');
        if (!container) return false;
        const btn = Array.from(container.querySelectorAll('button, div[role="button"]')).find(
            b => (b.textContent || '').trim().toLowerCase() === 'log in'
        );
        if (btn) {
            btn.click();
            return true;
        }
        return false;
    }""")

    if not submitted:
        page.get_by_role("button", name="Log in").last.click(force=True)

    page.wait_for_timeout(4000)

    # Check for wrong password / error toast
    has_auth_error = page.evaluate("""() => {
        const txt = document.body.innerText.toLowerCase();
        return txt.includes('incorrect password') || txt.includes('account does not exist') || txt.includes('invalid email');
    }""")
    if has_auth_error:
        return False, "INVALID_CREDENTIALS"

    # Force close login modal if it lingered after login
    if page.locator(email_selector).is_visible():
        dismiss_overlays(page, keep_login=False)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

    return True, "OK"


def extract_advanced_credits(page):
    """Clicks the top-right profile avatar next to Dashboard and extracts only Advanced Credits."""
    dismiss_overlays(page, keep_login=False)
    page.wait_for_timeout(1000)

    avatar_clicked = page.evaluate("""() => {
        const dashBtn = Array.from(document.querySelectorAll('a, button, div, span')).find(
            el => (el.textContent || '').trim() === 'Dashboard' && el.offsetWidth > 0
        );
        if (dashBtn && dashBtn.parentElement) {
            const siblings = Array.from(dashBtn.parentElement.children);
            const dashIdx = siblings.indexOf(dashBtn);
            for (let i = dashIdx + 1; i < siblings.length; i++) {
                if (siblings[i].offsetWidth > 0) {
                    siblings[i].click();
                    return true;
                }
            }
            const grandParent = dashBtn.parentElement.parentElement;
            if (grandParent) {
                const avatar = grandParent.querySelector('img[alt*="avatar" i], [class*="avatar"], svg');
                if (avatar) {
                    avatar.click();
                    return true;
                }
            }
        }
        return false;
    }""")

    if not avatar_clicked:
        page.mouse.click(1885, 65)

    page.wait_for_timeout(2000)

    credit_data = page.evaluate("""() => {
        const result = { advanced: null, found: false };
        const allElements = Array.from(document.querySelectorAll('div, span, p'));
        
        const card = allElements.find(el => 
            el.textContent && 
            el.textContent.includes('Advanced Credits') &&
            el.innerText.length < 600
        );

        if (!card) return result;

        result.found = true;
        const lines = card.innerText.split('\\n').map(l => l.trim()).filter(Boolean);

        for (let i = 0; i < lines.length; i++) {
            if (lines[i].startsWith('Advanced Credits')) {
                const match = lines[i].match(/(\\d+)/);
                result.advanced = match ? match[1] : (lines[i + 1] || '0');
                break;
            }
        }
        return result;
    }""")

    return credit_data


def run_credit_check():
    global current_context
    init_reports()

    results_summary = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080"
            ]
        )

        for idx, email in enumerate(SHARD_ASSIGNED_EMAILS):
            print("\n" + "-" * 55)
            print(f"[{idx + 1}/{len(SHARD_ASSIGNED_EMAILS)}] Checking Advanced Credits for: {email}")
            print("-" * 55)

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
                logged_in, reason = login_account(page, email, email_password)
                if not logged_in:
                    print(f"--> [FAILED] Could not log in ({reason})")
                    log_result(email, reason)
                    results_summary.append((email, reason, "N/A"))
                    continue

                credits = extract_advanced_credits(page)
                if credits["found"]:
                    adv = credits["advanced"] or "0"
                    print(f"--> [SUCCESS] {email} => Advanced Credits: {adv}")
                    log_result(email, "SUCCESS", adv)
                    results_summary.append((email, "SUCCESS", adv))
                else:
                    print("--> [WARNING] Logged in, but could not read profile credit dropdown.")
                    log_result(email, "READ_ERROR")
                    results_summary.append((email, "READ_ERROR", "N/A"))

            except Exception as e:
                print(f"--> [ERROR] Exception on {email}: {e}")
                log_result(email, "ERROR")
                results_summary.append((email, "ERROR", "N/A"))
            finally:
                if current_context:
                    current_context.close()
                    current_context = None

        browser.close()

    # Print final summary table in GitHub Actions logs
    print("\n" + "=" * 75)
    print(f"FINAL ADVANCED CREDITS REPORT - SHARD {shard_index}/{total_shards}")
    print("=" * 75)
    print(f"{'EMAIL':<42} | {'STATUS':<12} | {'ADV CREDITS':<12}")
    print("-" * 75)
    for row in results_summary:
        print(f"{row[0]:<42} | {row[1]:<12} | {str(row[2]):<12}")
    print("=" * 75)
    print(f"--> Saved reports to '{CSV_REPORT_PATH}' and '{TXT_REPORT_PATH}'")


if __name__ == "__main__":
    run_credit_check()
  
