#!/usr/bin/env python3
"""
Standup Generator
- Fetches yesterday's work from GitHub PRs + Jira tickets
- Fetches current Jira tickets for today's task selection
- Outputs formatted standup ready to paste into Slack
"""

import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "vigneshpy")
GITHUB_ORGS = os.getenv("GITHUB_ORGS", "getattune,lendsmartlabs").split(",")

JIRA_DOMAIN = os.getenv("JIRA_DOMAIN", "lendsmartlabs.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "vignesh@lendsmart.ai")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_ACCOUNT_ID = os.getenv("JIRA_ACCOUNT_ID", "609b658c3fae6f00683ad32d")


def get_last_workday():
    today = datetime.now()
    if today.weekday() == 0:  # Monday
        return today - timedelta(days=3)
    elif today.weekday() == 6:  # Sunday
        return today - timedelta(days=2)
    else:
        return today - timedelta(days=1)


# --- GitHub ---

def fetch_github_prs():
    last_workday = get_last_workday()
    since_date = last_workday.strftime("%Y-%m-%d")
    all_prs = []

    for org in GITHUB_ORGS:
        org = org.strip()
        try:
            result = subprocess.run(
                [
                    "gh", "search", "prs",
                    "--author", GITHUB_USERNAME,
                    "--owner", org,
                    "--merged-at", f">={since_date}",
                    "--json", "title,repository,number",
                    "--limit", "20",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                prs = json.loads(result.stdout)
                all_prs.extend(prs)
            elif result.returncode != 0:
                print(f"  Warning: gh error for {org}: {result.stderr.strip()[:200]}")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            print(f"  Warning: Failed to fetch from {org}: {e}")

    all_prs.sort(key=lambda pr: pr.get("number", 0), reverse=True)
    return all_prs


def format_pr_title(title):
    title = title.strip()
    for prefix in ["fix:", "feat:", "chore:", "refactor:"]:
        if title.lower().startswith(prefix):
            title = title[len(prefix):].strip()
    return title


# --- Jira ---

def jira_request(jql, max_results=20):
    if not JIRA_API_TOKEN:
        print("  Warning: JIRA_API_TOKEN not set, skipping Jira fetch.")
        return []

    url = (
        f"https://{JIRA_DOMAIN}/rest/api/3/search/jql"
        f"?jql={urllib.request.quote(jql)}"
        f"&fields=summary,status,key"
        f"&maxResults={max_results}"
    )

    credentials = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("issues", [])
    except urllib.error.HTTPError as e:
        print(f"  Warning: Jira API error {e.code}: {e.reason}")
        return []
    except Exception as e:
        print(f"  Warning: Jira fetch failed: {e}")
        return []


def fetch_jira_updated():
    """Fetch current sprint tickets updated since last workday (for yesterday's tasks)."""
    last_workday = get_last_workday()
    since_date = last_workday.strftime("%Y-%m-%d")
    jql = (
        f'assignee = currentUser() '
        f'AND sprint in openSprints() '
        f'AND updatedDate >= "{since_date}" '
        f'ORDER BY updated DESC'
    )
    return jira_request(jql)


def fetch_jira_active():
    """Fetch current sprint tickets assigned to you (for today's tasks)."""
    jql = (
        f'assignee = currentUser() '
        f'AND sprint in openSprints() '
        f'AND status not in ("Done") '
        f'ORDER BY priority DESC, updated DESC'
    )
    return jira_request(jql, max_results=15)


# --- Formatting ---

def format_standup(yesterday_tasks, today_tasks):
    lines = ["Yesterday:"]
    for task in yesterday_tasks:
        lines.append(f"*        {task}")
    lines.append("")
    lines.append("Today:")
    for task in today_tasks:
        lines.append(f"*        {task}")
    return "\n".join(lines)


def prompt_tasks(label):
    print(f"\n  {label}:")
    print("  (Enter each task on a new line, empty line to finish)\n")
    tasks = []
    while True:
        task = input("    > ").strip()
        if not task:
            break
        tasks.append(task)
    return tasks


def select_tasks(tickets, label):
    """Show numbered Jira tickets and let user pick by number."""
    if not tickets:
        return prompt_tasks(label)

    print(f"\n  {label}:")
    print("  Select by number (comma-separated), or type custom tasks.")
    print("  Example: 1,3,5 or 1,3,write docs\n")

    ticket_map = {}
    for i, ticket in enumerate(tickets, 1):
        key = ticket["key"]
        summary = ticket["fields"]["summary"]
        status = ticket["fields"]["status"]["name"]
        label_text = f"{key} {summary}"
        ticket_map[i] = label_text
        print(f"    {i}. [{status}] {label_text}")

    print()
    selection = input("    > ").strip()
    if not selection:
        return []

    tasks = []
    for part in selection.split(","):
        part = part.strip()
        if part.isdigit() and int(part) in ticket_map:
            tasks.append(ticket_map[int(part)])
        elif part:
            tasks.append(part)

    # Allow adding more custom tasks
    print("\n  Add more tasks? (empty line to finish)\n")
    while True:
        task = input("    > ").strip()
        if not task:
            break
        tasks.append(task)

    return tasks


def copy_to_clipboard(text):
    for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
        try:
            proc = subprocess.run(cmd, input=text.encode(), timeout=5)
            if proc.returncode == 0:
                print("  Copied to clipboard!")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue


def main():
    print("\n=== Standup Generator ===\n")

    last_workday = get_last_workday()
    since_label = f"{last_workday.strftime('%Y-%m-%d')} ({last_workday.strftime('%A')})"

    yesterday_tasks = []

    # --- Fetch from GitHub ---
    print(f"  Fetching merged PRs since {since_label}...")
    prs = fetch_github_prs()
    if prs:
        print(f"  Found {len(prs)} merged PR(s):")
        for pr in prs:
            title = format_pr_title(pr["title"])
            repo = pr.get("repository", {}).get("name", "")
            print(f"    - [{repo}] {title}")
            yesterday_tasks.append(title)

    # --- Fetch from Jira (yesterday) ---
    print(f"\n  Fetching Jira tickets updated since {since_label}...")
    jira_yesterday = fetch_jira_updated()
    if jira_yesterday:
        print(f"  Found {len(jira_yesterday)} Jira ticket(s):")
        for ticket in jira_yesterday:
            key = ticket["key"]
            summary = ticket["fields"]["summary"]
            status = ticket["fields"]["status"]["name"]
            label = f"{key} {summary}"
            print(f"    - [{status}] {label}")
            if not any(key in t for t in yesterday_tasks):
                yesterday_tasks.append(label)

    # --- Yesterday summary ---
    if yesterday_tasks:
        print(f"\n  Combined yesterday tasks ({len(yesterday_tasks)}):")
        for i, task in enumerate(yesterday_tasks, 1):
            print(f"    {i}. {task}")
        print("\n  Edit? (press Enter to keep, or type new ones)")
        edits = prompt_tasks("Override yesterday tasks (or leave empty to keep)")
        if edits:
            yesterday_tasks = edits
    else:
        print("\n  No activity found from GitHub or Jira.")
        yesterday_tasks = prompt_tasks("Enter yesterday's tasks manually")

    # --- Fetch from Jira (today — active tickets) ---
    print("\n  Fetching your active Jira tickets...")
    jira_today = fetch_jira_active()
    today_tasks = select_tasks(jira_today, "Select today's tasks")

    if not today_tasks:
        print("  No today tasks entered. Aborting.")
        sys.exit(0)

    # --- Output ---
    standup = format_standup(yesterday_tasks, today_tasks)

    print("\n" + "=" * 40)
    print("  COPY BELOW INTO SLACK")
    print("=" * 40 + "\n")
    print(standup)
    print("\n" + "=" * 40 + "\n")

    copy_to_clipboard(standup)


if __name__ == "__main__":
    main()
