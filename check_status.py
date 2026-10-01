import os
import sys
import subprocess

total_shards = int(os.environ.get("TOTAL_SHARDS", "8"))

print("==========================================================")
print("              STARTING CHECK STATUS ENGINE               ")
print("==========================================================")

# 1. Pull latest git changes to aggregate all shard tracking files
try:
    subprocess.run(["git", "fetch", "origin", "main"], check=False)
    subprocess.run(["git", "rebase", "origin/main"], check=False)
except Exception as e:
    print(f"--> [CHECK STATUS] Note: Git sync check: {e}")

# 2. Check for ALL_DONE lock file
if os.path.exists("ALL_DONE.txt"):
    print("--> [CHECK STATUS] ALL_DONE.txt lock found! All accounts completed successfully.")
    sys.exit(0)

# 3. Read emails from emails.txt
if not os.path.exists("emails.txt"):
    print("--> [CHECK STATUS] ERROR: emails.txt not found. Exiting cleanly.")
    sys.exit(0)

with open("emails.txt", "r", encoding="utf-8") as f:
    raw_emails = f.read()

all_emails = [e.strip().lower() for e in raw_emails.replace(",", " ").split() if e.strip()]
total_emails = len(all_emails)

# 4. Read completed accounts across ALL shard files
completed_emails = set()

for s in range(1, total_shards + 1):
    s_file = f"completed_accounts_shard_{s}.txt"
    if os.path.exists(s_file):
        with open(s_file, "r", encoding="utf-8") as f:
            completed_emails.update({line.strip().lower() for line in f if line.strip()})

if os.path.exists("completed_accounts.txt"):
    with open("completed_accounts.txt", "r", encoding="utf-8") as f:
        completed_emails.update({line.strip().lower() for line in f if line.strip()})

completed_count = len(completed_emails)
pending_count = total_emails - completed_count

print(f"--> [CHECK STATUS] Total Accounts in List: {total_emails}")
print(f"--> [CHECK STATUS] Completed Accounts:    {completed_count}")
print(f"--> [CHECK STATUS] Pending Accounts:      {pending_count}")

if completed_count >= total_emails and total_emails > 0:
    print("--> [CHECK STATUS] All accounts completed across all shards! Writing ALL_DONE.txt...")
    with open("ALL_DONE.txt", "w", encoding="utf-8") as f:
        f.write("DONE\n")
    
    try:
        subprocess.run(["git", "add", "ALL_DONE.txt"], check=False)
        subprocess.run(["git", "commit", "-m", "update: marked ALL_DONE"], check=False)
        subprocess.run(["git", "push", "origin", "HEAD:main"], check=False)
    except Exception as e:
        print(f"--> Error pushing ALL_DONE.txt: {e}")
else:
    print(f"--> [CHECK STATUS] Run finished. {pending_count} accounts remaining for next manual trigger.")
    
