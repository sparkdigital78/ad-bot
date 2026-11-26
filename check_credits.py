import os
import time
import signal
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright

current_context = None


def shutdown_handler(sig, frame):
    global current_context
    print("\n--> [STOP / CANCEL DETECTED] Closing context...")
    if current_context:
        try:
            current_context.close()
        except Exception as e:
            print(f"--> Error closing context: {e}")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ============================================================
# LOAD ALL ACCOUNTS IN A SINGLE LIST
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

print(f"--> Total accounts to check in this run: {len(ALL_EMAILS)}")

if not ALL_EMAILS:
    print("--> No accounts found in emails.txt or ALL_EMAILS. Exiting...")
    sys.exit(0)

TXT_REPORT_PATH = "advanced_credits_report.txt"


def init_report():
    """Creates a clean 2-column report with Credits and Email."""
    with open(TXT_REPORT_PATH, mode="w", encoding="utf-8") as f:
        f.write(f"{'CREDITS':<10} | {'EMAIL'}\n")
        f.write("-" * 55 + "\n")


def log_result(adv_credits, email):
    """Appends Credits and Email row to advanced_credits_report.txt."""
    with open(TXT_REPORT_PATH, mode="a", encoding="utf-8") as f:
        f.write(f"{str(adv_credits):<10} | {email}\n")


def dismiss_overlays(page, keep_login=True):
    """Clears Daily Check-in, AI Agent promo modals, and backdrops."""
    try:
        page.evaluate("""(keepLogin) => {
            const modals = Array.from(document.querySelectorAll('div[role="dialog"], [class*="modal"], [class*="popup"]'));
            modals.forEach(m => {
                const isLogin = m.querySelector('input[type="email"], input[placeholder*="email" i]') || 
                                (m.textContent && m.textContent.includes('Sign in to EaseMate'));
                if (keepLogin && isLogin) return;

                if (m.textContent && m.textContent.includes('Advanced Credits') && m.textContent.includes('Free Credits')) return;

                const closeBtn = m.querySelector('button, [class*="close"], svg, i, [aria-label*="close" i]');
                if (closeBtn) {
                    closeBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                }
                try { m.remove(); } catch(e) {}
            });
            const backdrops = document.querySelectorAll('[class*="backdrop"], [class*="mask"], [class*="modal-backdrop"]');
            backdrops.forEach(b => {
                if (!keepLogin || !document.querySelector('input[placeholder*="email" i]')) {
                    try { b.remove(); } catch(e) {}
                }
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

    for _ in range(3):
        if page.locator(email_selector).is_visible():
            break

        page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('button, a, div, span'));
            const btn = els.find(e => {
                const txt = (e.textContent || '').trim();
                return txt === 'Log In' || txt === 'Log in' || txt === 'Sign In' || txt === 'Sign in';
            });
            if (btn) btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }""")
        page.wait_for_timeout(1500)

        email_btn = page.locator("text='Continue with Email'")
        if email_btn.count() > 0 and email_btn.first.is_visible():
            email_btn.first.click(force=True)
            page.wait_for_timeout(1000)

    if not page.locator(email_selector).is_visible():
        return False, "LOGIN_FAILED"

    page.locator(email_selector).fill(email)
    page.locator(email_selector).dispatch_event("input")
    page.locator(email_selector).dispatch_event("change")
    page.wait_for_timeout(400)

    page.locator(password_selector).fill(password)
    page.locator(password_selector).dispatch_event("input")
    page.locator(password_selector).dispatch_event("change")
    page.wait_for_timeout(400)

    submitted = page.evaluate("""() => {
        const passInput = document.querySelector("input[placeholder='Enter your Password']");
        if (!passInput) return false;
        const container = passInput.closest('form') || passInput.closest('div[role="dialog"], [class*="modal"]');
        if (!container) return false;
        const btn = Array.from(container.querySelectorAll('button, div[role="button"]')).find(
            b => (b.textContent || '').trim().toLowerCase() === 'log in'
        );
        if (btn) {
            btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            return true;
        }
        return false;
    }""")

    if not submitted:
        page.get_by_role("button", name="Log in").last.click(force=True)

    page.wait_for_timeout(4000)

    has_auth_error = page.evaluate("""() => {
        const txt = document.body.innerText.toLowerCase();
        return txt.includes('incorrect password') || txt.includes('account does not exist') || txt.includes('invalid email');
    }""")
    if has_auth_error:
        return False, "INVALID_LOGIN"

    if page.locator(email_selector).is_visible():
        dismiss_overlays(page, keep_login=False)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

    return True, "OK"


def read_credits_from_dom(page):
    """Parses the Advanced Credits number once the profile menu is visible."""
    return page.evaluate("""() => {
        const result = { advanced: null, found: false };
        const allElements = Array.from(document.querySelectorAll('div, span, p, li'));
        
        const card = allElements.find(el => 
            el.textContent && 
            el.textContent.includes('Advanced Credits') &&
            el.innerText.length < 700
        );

        if (!card) return result;

        result.found = true;
        const lines = card.innerText.split('\\n').map(l => l.trim()).filter(Boolean);

        for (let i = 0; i < lines.length; i++) {
            if (lines[i].startsWith('Advanced Credits')) {
                const match = lines[i].match(/(\\d+)/);
                if (match) {
                    result.advanced = match[1];
                } else if (i + 1 < lines.length && /^\\d+$/.test(lines[i + 1])) {
                    result.advanced = lines[i + 1];
                } else if (i > 0 && /^\\d+$/.test(lines[i - 1])) {
                    result.advanced = lines[i - 1];
                } else {
                    result.advanced = '0';
                }
                break;
            }
        }
        return result;
    }""")


def extract_advanced_credits(page):
    """Clears delayed promo modals and opens the top-right avatar to read Advanced Credits."""
    for _ in range(3):
        dismiss_overlays(page, keep_login=False)
        page.wait_for_timeout(1000)

    for _ in range(3):
        dismiss_overlays(page, keep_login=False)

        avatar_coords = page.evaluate("""() => {
            const dashBtn = Array.from(document.querySelectorAll('a, button, div, span')).find(
                el => (el.textContent || '').trim() === 'Dashboard' && el.getBoundingClientRect().width > 0
            );
            if (!dashBtn) return null;

            const dashRect = dashBtn.getBoundingClientRect();
            const allEls = Array.from(document.querySelectorAll('header *, nav *, div, button, img, span'));
            const candidates = allEls.filter(el => {
                const r = el.getBoundingClientRect();
                return r.width >= 24 && r.width <= 60 &&
                       r.height >= 24 && r.height <= 60 &&
                       r.left > dashRect.right &&
                       Math.abs(r.top - dashRect.top) < 25;
            });

            if (candidates.length > 0) {
                candidates.sort((a, b) => b.getBoundingClientRect().left - a.getBoundingClientRect().left);
                const target = candidates[0].getBoundingClientRect();
                return { x: target.left + target.width / 2, y: target.top + target.height / 2 };
            }
            return null;
        }""")

        if avatar_coords:
            page.mouse.move(avatar_coords["x"], avatar_coords["y"])
            page.wait_for_timeout(400)
            page.mouse.click(avatar_coords["x"], avatar_coords["y"])
        else:
            dash_loc = page.get_by_text("Dashboard", exact=True).first
            if dash_loc.is_visible():
                box = dash_loc.bounding_box()
                if box:
                    tx = box["x"] + box["width"] + 28
                    ty = box["y"] + box["height"] / 2
                    page.mouse.move(tx, ty)
                    page.wait_for_timeout(400)
                    page.mouse.click(tx, ty)
            else:
                page.mouse.click(1882, 72)

        page.wait_for_timeout(1800)
        dismiss_overlays(page, keep_login=False)

        data = read_credits_from_dom(page)
        if data["found"]:
            return data

    page.goto("https://easemate.ai/earn-credits", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(2000)
    dismiss_overlays(page, keep_login=False)

    dash_loc = page.get_by_text("Dashboard", exact=True).first
    if dash_loc.is_visible():
        box = dash_loc.bounding_box()
        if box:
            tx = box["x"] + box["width"] + 28
            ty = box["y"] + box["height"] / 2
            page.mouse.move(tx, ty)
            page.wait_for_timeout(400)
            page.mouse.click(tx, ty)
            page.wait_for_timeout(1800)

    return read_credits_from_dom(page)


def run_credit_check():
    global current_context
    init_report()

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

        for idx, email in enumerate(ALL_EMAILS):
            print(f"[{idx + 1}/{len(ALL_EMAILS)}] Checking: {email}")

            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            current_context = context

            try:
                logged_in, reason = login_account(page, email, email_password)
                if not logged_in:
                    print(f"--> [FAILED] {email} ({reason})")
                    log_result(reason, email)
                    results_summary.append((reason, email))
                    continue

                credits = extract_advanced_credits(page)
                if credits["found"]:
                    adv = credits["advanced"] or "0"
                    print(f"--> [SUCCESS] {adv} | {email}")
                    log_result(adv, email)
                    results_summary.append((adv, email))
                else:
                    print(f"--> [WARNING] READ_ERROR | {email}")
                    log_result("ERROR", email)
                    results_summary.append(("ERROR", email))

            except Exception as e:
                print(f"--> [ERROR] {email}: {e}")
                log_result("ERROR", email)
                results_summary.append(("ERROR", email))
            finally:
                if current_context:
                    current_context.close()
                    current_context = None

        browser.close()

    print("\n" + "=" * 55)
    print(f"{'CREDITS':<10} | {'EMAIL'}")
    print("-" * 55)
    for adv, email in results_summary:
        print(f"{str(adv):<10} | {email}")
    print("=" * 55)


if __name__ == "__main__":
    run_credit_check()
    
