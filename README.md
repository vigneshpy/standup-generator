# Standup Generator

CLI tool that auto-generates your daily standup by fetching data from GitHub and Jira. Outputs a formatted message ready to paste into Slack.

## What It Does

1. **Last working day's tasks** — Merged, raised and reviewed PRs from GitHub + updated Jira tickets from the current sprint
2. **Today's tasks** — Your active sprint tickets, with carried-over and in-progress ones pre-selected; Enter accepts
3. **Formats & copies** — Outputs the standup in your team's format and copies it to clipboard

## Output Format

```
Yesterday:
*        [CLIENT-7550] apply link tag missing on back fix
*        [CLIENT-7663] remove subscriber from task

Today:
*        RSNT-165 OVERRIDE CODE CLEAN UP
*        RSNT prod release
```

## Prerequisites

- Python 3.8+
- [GitHub CLI](https://cli.github.com/) (`gh`) — authenticated with `gh auth login`
- Jira API token — [create one here](https://id.atlassian.com/manage-profile/security/api-tokens)

### Install GitHub CLI

```bash
# Ubuntu/Debian
sudo apt install gh

# macOS
brew install gh

# Then authenticate
gh auth login
```

## Setup

1. Clone the repo:

```bash
git clone https://github.com/vigneshpy/standup-generator.git
cd standup-generator
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create your `.env` file:

```bash
cp .env.example .env
```

4. Edit `.env` and add your Jira API token:

```env
GITHUB_USERNAME=your-github-username
GITHUB_ORGS=org1,org2

JIRA_DOMAIN=your-company.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=your-jira-api-token
```

Or set them globally in `~/.bashrc`:

```bash
export JIRA_DOMAIN=your-company.atlassian.net
export JIRA_EMAIL=your-email@company.com
export JIRA_API_TOKEN=your-jira-api-token
export GITHUB_USERNAME=your-github-username
export GITHUB_ORGS=org1,org2
```

## Usage

```bash
python3 standup.py                    # looks back to the last working day
python3 standup.py --since 2026-09-17 # after a holiday: look back to a specific date
python3 standup.py --days 2           # or N days
```

Editing prompts: `Enter` keeps the list, `-2` removes item 2, `+3` adds ticket 3, `1,4` picks exactly, any other text is added as a custom task.

Optional `.env`: `STANDUP_DEFAULT_STATUSES=In Progress,Code In Review` controls which statuses are pre-selected for Today.

### Workflow

```
=== Standup Generator ===

  Fetching merged PRs since 2026-03-27 (Friday)...
  Found 5 merged PR(s):
    - [ui] [CLIENT-7550] apply link tag missing on back fix
    - [ui] [CLIENT-7663] remove subscriber from task

  Fetching Jira tickets updated since 2026-03-27 (Friday)...
  Found 3 Jira ticket(s):
    - [DEPLOYED TO DEV] RSNT-400 CLOSED LOAN ROLE
    - [ALLOCATED] RSNT-165 OVERRIDE CODE CLEAN UP

  Combined yesterday tasks (5):
    1. [CLIENT-7550] apply link tag missing on back fix
    2. [CLIENT-7663] remove subscriber from task
    ...

  Fetching your active Jira tickets...

  Select today's tasks:
  Select by number (comma-separated), or type custom tasks.
  Example: 1,3,5 or 1,3,write docs

    1. [DEPLOYED TO DEV] RSNT-400 CLOSED LOAN ROLE
    2. [ALLOCATED] RSNT-165 OVERRIDE CODE CLEAN UP

    > 1,2

========================================
  COPY BELOW INTO SLACK
========================================

Yesterday:
*        [CLIENT-7550] apply link tag missing on back fix
*        [CLIENT-7663] remove subscriber from task

Today:
*        RSNT-400 CLOSED LOAN ROLE
*        RSNT-165 OVERRIDE CODE CLEAN UP

========================================

  Copied to clipboard!
```

### Features

- Skips weekends automatically (Monday looks back to Friday); header says `Last working day (Friday):` when it isn't literally yesterday
- One line format for PRs and Jira: `RSNT-692 title`, with `fix:`/`feat:` prefixes stripped
- Deduplicates by ticket key across PRs and Jira
- Edit lists in place (`-N` remove, text add) instead of retyping
- Today's list pre-selects carried-over tickets and in-progress statuses
- Copies output to clipboard via `wl-copy`, `xclip` or `xsel`

## Data Sources

| Source | Yesterday | Today |
|--------|-----------|-------|
| GitHub PRs | Merged, raised and reviewed PRs since last workday | - |
| Jira | Updated tickets in current sprint | Active tickets in current sprint (not Done) |
