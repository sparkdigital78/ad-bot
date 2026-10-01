import os
import sys
import requests

repo = os.environ.get("GITHUB_REPOSITORY")
token = os.environ.get("GITHUB_TOKEN")
run_id = os.environ.get("GITHUB_RUN_ID")

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github.v3+json"
}

# 1. Stop if workflow was manually cancelled
if repo and token and run_id:
    try:
        run_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
        response = requests.get(run_url, headers=headers)
        if response.status_code == 200:
            run_data = response.json()
            if run_data.get("conclusion") == "cancelled":
                print("--> [CHECK STATUS] Workflow was manually CANCELLED. Stopping auto-chain.")
                sys.exit(0)
    except Exception as e:
        print(f"--> [CHECK STATUS] Could not check run conclusion: {e}")

# 2. HARD LOCK CHECK: If ALL_DONE.txt exists, stop immediately!
if os.path.exists("ALL_DONE.txt"):
    print("--> [CHECK STATUS] ALL_DONE.txt lock found! All accounts completed successfully.")
    print("--> Stopping workflow loop permanently for today.")
    sys.exit(0)

# 3. Read emails from emails.txt
if not os.path.exists("emails.txt"):
    print("--> [CHECK STATUS] emails.txt not found. Exiting cleanly.")
    sys.exit(0)

with open("emails.txt", "r", encoding="utf-8") as f:
    raw_emails = f.read()

all_emails = [e.strip().lower() for e in raw_emails.replace(",", " ").split() if e.strip()]
total_emails = len(all_emails)

# 4. Read completed accounts from completed_accounts.txt
completed_emails = set()
if os.path.exists("completed_accounts.txt"):
    with open("completed_accounts.txt", "r", encoding="utf-8") as f:
        completed_emails = {line.strip().lower() for line in f if line.strip()}

completed_count = len(completed_emails)
print(f"--> [CHECK STATUS] Total Accounts: {total_emails} | Completed: {completed_count}")

# 5. Trigger next run ONLY if accounts remain
if total_emails > 0 and completed_count < total_emails:
    print("--> [CHECK STATUS] Pending accounts remain! Triggering next workflow run...")
    if repo and token:
        dispatch_url = f"https://api.github.com/repos/{repo}/actions/workflows/run_bot.yml/dispatches"
        res = requests.post(dispatch_url, headers=headers, json={"ref": "main"})
        if res.status_code == 204:
            print("--> [SUCCESS] Next workflow run triggered successfully!")
        else:
            print(f"--> [ERROR] Failed to trigger dispatch: {res.status_code} - {res.text}")
else:
    print("--> [CHECK STATUS] All accounts completed. Stopping loop completely.")
    
