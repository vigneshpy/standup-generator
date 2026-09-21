#!/usr/bin/env python3
"""
Standup Generator
- Fetches last working day's work from GitHub PRs (merged, raised, reviewed) + Jira tickets
- Pre-selects today's tickets (carried over from yesterday + in-progress statuses)
- Outputs formatted standup ready to paste into Slack
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "vigneshpy")
GITHUB_ORGS = [o.strip() for o in os.getenv("GITHUB_ORGS", "getattune,lendsmartlabs").split(",") if o.strip()]

JIRA_DOMAIN = os.getenv("JIRA_DOMAIN", "lendsmartlabs.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "vignesh@lendsmart.ai")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

# Statuses that are pre-selected for "Today" (case-insensitive)
DEFAULT_TODAY_STATUSES = {
    s.strip().lower()
    for s in os.getenv("STANDUP_DEFAULT_STATUSES", "In Progress,Code In Review").split(",")
    if s.strip()
}

KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
LEADING_KEY_RE = re.compile(r"^\W*([A-Z][A-Z0-9]+-\d+)\W*")
PREFIX_RE = re.compile(r"^(fix|feat|chore|refactor|docs|test|style|perf|build|ci)(\([^)]*\))?!?:\s*", re.I)


# --- Dates ---

def get_last_workday(today=None):
    today = today or datetime.now()
    back = {0: 3, 6: 2}.get(today.weekday(), 1)  # Monday -> Friday, Sunday -> Friday
    return today - timedelta(days=back)


def resolve_since(args):
    if args.since:
        return datetime.strptime(args.since, "%Y-%m-%d")
    if args.days:
        return datetime.now() - timedelta(days=args.days)
    return get_last_workday()


def period_header(since, today=None):
    today = today or datetime.now()
    if since.date() == (today - timedelta(days=1)).date():
        return "Yesterday:"
    return f"Last working day ({since.strftime('%A')}):"


# --- Task text ---

def normalize_task(text, key=None):
    """'[RSNT-692] fix: enforce min' -> 'RSNT-692 enforce min'. One format for PRs and Jira."""
    text = PREFIX_RE.sub("", text.strip())
    m = LEADING_KEY_RE.match(text)
    if m:
        key = key or m.group(1)
        text = text[m.end():]
    text = PREFIX_RE.sub("", text).strip()
    return f"{key} {text}".strip() if key else text


def task_key(text):
    m = KEY_RE.search(text)
    return m.group(0) if m else None


# --- GitHub ---

def gh_search(org, *query, limit=20):
    cmd = [
        "gh", "search", "prs", "--owner", org,
        "--json", "title,repository,number,author",
        "--limit", str(limit), *query,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        print(f"  Warning: gh timed out for {org}")
        return []
    if result.returncode != 0:
        print(f"  Warning: gh error for {org}: {result.stderr.strip()[:200]}")
        return []
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as e:
        print(f"  Warning: bad gh output for {org}: {e}")
        return []


def fetch_github(since):
    """Returns (merged, raised, reviewed) PR lists since the given date."""
    d = since.strftime("%Y-%m-%d")
    merged, raised, reviewed = [], [], []
    for org in GITHUB_ORGS:
        merged += gh_search(org, "--author", GITHUB_USERNAME, "--merged-at", f">={d}")
        raised += gh_search(org, "--author", GITHUB_USERNAME, "--state", "open", "--created", f">={d}")
        reviewed += [
            pr for pr in gh_search(org, "--reviewed-by", GITHUB_USERNAME, "--updated", f">={d}")
            if pr.get("author", {}).get("login") != GITHUB_USERNAME
        ]
    for lst in (merged, raised, reviewed):
        lst.sort(key=lambda pr: pr.get("number", 0), reverse=True)
    return merged, raised, reviewed


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
            return json.loads(resp.read().decode()).get("issues", [])
    except urllib.error.HTTPError as e:
        print(f"  Warning: Jira API error {e.code}: {e.reason}")
    except Exception as e:
        print(f"  Warning: Jira fetch failed: {e}")
    return []


def fetch_jira_updated(since):
    jql = (
        f'assignee = currentUser() AND sprint in openSprints() '
        f'AND updatedDate >= "{since.strftime("%Y-%m-%d")}" ORDER BY updated DESC'
    )
    return jira_request(jql)


def fetch_jira_active():
    jql = (
        'assignee = currentUser() AND sprint in openSprints() '
        'AND status not in ("Done") ORDER BY priority DESC, updated DESC'
    )
    return jira_request(jql, max_results=15)


def jira_label(ticket):
    return normalize_task(ticket["fields"]["summary"], key=ticket["key"])


def jira_status(ticket):
    return ticket["fields"]["status"]["name"]


# --- Interactive editing ---

def parse_parts(line):
    return [p.strip() for p in line.split(",") if p.strip()]


def edit_list(tasks, title):
    """Show numbered tasks; Enter keeps, '-N' removes, any other text appends."""
    tasks = list(tasks)
    while True:
        print(f"\n  {title}")
        for i, t in enumerate(tasks, 1):
            print(f"    {i}. {t}")
        print("\n  Enter = keep | -N = remove item N | text = add task")
        line = input("    > ").strip()
        if not line:
            return tasks
        for part in parse_parts(line):
            if re.fullmatch(r"-\d+", part) and 1 <= int(part[1:]) <= len(tasks):
                tasks[int(part[1:]) - 1] = None
            else:
                tasks.append(part)
        tasks = [t for t in tasks if t]


def select_today(tickets, yesterday_tasks):
    """Pre-select carried-over and in-progress tickets; Enter accepts, numbers adjust."""
    if not tickets:
        return edit_list([], "Enter today's tasks:")

    carried = {task_key(t) for t in yesterday_tasks} - {None}
    # items: [label, status, selected]
    items = [
        [jira_label(t), jira_status(t),
         t["key"] in carried or jira_status(t).lower() in DEFAULT_TODAY_STATUSES]
        for t in tickets
    ]
    n_tickets = len(items)

    while True:
        print("\n  Today's tasks (* = selected):")
        for i, (label, status, sel) in enumerate(items, 1):
            print(f"   {'*' if sel else ' '} {i}. [{status}] {label}")
        print("\n  Enter = accept | 1,3 = pick exactly | +N add | -N remove | text = custom task")
        line = input("    > ").strip()
        if not line:
            return [label for label, _, sel in items if sel]

        parts = parse_parts(line)
        exact = [int(p) for p in parts if p.isdigit()]
        if exact:
            for i in range(n_tickets):
                items[i][2] = (i + 1) in exact
        for part in parts:
            if part.isdigit():
                continue
            m = re.fullmatch(r"([+-])(\d+)", part)
            if m and 1 <= int(m.group(2)) <= len(items):
                items[int(m.group(2)) - 1][2] = m.group(1) == "+"
            else:
                items.append([part, "custom", True])
        # drop deselected custom entries so numbering stays sane
        items = items[:n_tickets] + [it for it in items[n_tickets:] if it[2]]


# --- Output ---

def format_standup(yesterday_tasks, today_tasks, since, plain=False):
    """Slack style by default: bold headers, real bullet characters (paste-safe)."""
    head = (lambda h: h) if plain else (lambda h: f"*{h}*")
    bullet = "*        " if plain else "\u2022 "
    lines = [head(period_header(since))]
    lines += [f"{bullet}{t}" for t in yesterday_tasks]
    lines += ["", head("Today:")]
    lines += [f"{bullet}{t}" for t in today_tasks]
    return "\n".join(lines)


def copy_to_clipboard(text):
    for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
        try:
            if subprocess.run(cmd, input=text.encode(), timeout=5,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                print("  Copied to clipboard!")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("  (clipboard not available)")


def main():
    ap = argparse.ArgumentParser(description="Generate your daily standup from GitHub + Jira.")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="look back to this date (e.g. after a holiday)")
    ap.add_argument("--days", type=int, metavar="N", help="look back N days")
    ap.add_argument("--plain", action="store_true", help="old '*        ' layout without Slack bold/bullets")
    args = ap.parse_args()

    since = resolve_since(args)
    since_label = f"{since.strftime('%Y-%m-%d')} ({since.strftime('%A')})"
    print("\n=== Standup Generator ===\n")

    yesterday_tasks = []

    def add_unique(label):
        key = task_key(label)
        if key and any(task_key(t) == key for t in yesterday_tasks):
            return
        yesterday_tasks.append(label)

    print(f"  Fetching GitHub PRs since {since_label}...")
    merged, raised, reviewed = fetch_github(since)
    for pr in merged:
        add_unique(normalize_task(pr["title"]))
    for pr in raised:
        add_unique(f"{normalize_task(pr['title'])} (PR raised)")
    for pr in reviewed:
        yesterday_tasks.append(f"Reviewed PR: {normalize_task(pr['title'])}")
    print(f"  Found {len(merged)} merged, {len(raised)} raised, {len(reviewed)} reviewed")

    print(f"\n  Fetching Jira tickets updated since {since_label}...")
    jira_yesterday = fetch_jira_updated(since)
    print(f"  Found {len(jira_yesterday)} ticket(s)")
    for ticket in jira_yesterday:
        add_unique(jira_label(ticket))

    yesterday_tasks = edit_list(
        yesterday_tasks,
        f"{period_header(since)[:-1]} tasks:" if yesterday_tasks else "No activity found. Enter tasks manually:",
    )

    print("\n  Fetching your active Jira tickets...")
    today_tasks = select_today(fetch_jira_active(), yesterday_tasks)
    if not today_tasks:
        print("  No today tasks entered. Aborting.")
        sys.exit(0)

    standup = format_standup(yesterday_tasks, today_tasks, since, plain=args.plain)
    print("\n" + "=" * 40 + "\n  COPY BELOW INTO SLACK\n" + "=" * 40 + "\n")
    print(standup)
    print("\n" + "=" * 40 + "\n")
    copy_to_clipboard(standup)


if __name__ == "__main__":
    main()
