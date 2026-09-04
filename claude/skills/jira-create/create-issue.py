#!/usr/bin/env python3
"""Create a Jira Cloud issue/sub-task, handling TGH's required 'Is Capitalizable?' field.

The jira CLI cannot set customfield_12220 (it silently drops --custom and Jira
rejects the create with 400 'Is Capitalizable? is required'), so this script
calls the REST API directly. Token comes from JIRA_API_TOKEN env var and is
never printed.

Usage:
  create-issue.py --summary "..." [--type Task|Sub-task|Story|Bug] [--parent TGH-3027]
                  [--assignee me|email] [--label DPD]... [--capitalizable Yes|No]
                  [--body-file path.md] [--project TGH]

Body file supports a small markdown subset: '## ' headings, '- ' bullets,
everything else becomes paragraphs.
"""
import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.parse

SERVER = "https://hellofresh.atlassian.net"


def jira_login():
    """Read the login email from the jira CLI config (single source of truth,
    keeps the email out of this repo)."""
    cfg = os.path.expanduser("~/.config/.jira/.config.yml")
    try:
        with open(cfg) as f:
            for line in f:
                if line.startswith("login:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    sys.exit(f"Could not read login from {cfg}")


LOGIN = jira_login()
TOKEN = os.environ.get("JIRA_API_TOKEN")
if not TOKEN:
    sys.exit("JIRA_API_TOKEN is not set in the environment")


def req(method, path, payload=None):
    r = urllib.request.Request(
        SERVER + path,
        method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={
            "Authorization": "Basic " + base64.b64encode(f"{LOGIN}:{TOKEN}".encode()).decode(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r) as resp:
            body = resp.read().decode()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Jira API {e.code}: {e.read().decode()}")


def account_id_for(assignee):
    if assignee == "me":
        return req("GET", "/rest/api/3/myself")["accountId"]
    users = req("GET", "/rest/api/3/user/search?" + urllib.parse.urlencode({"query": assignee}))
    if not users:
        sys.exit(f"No Jira user found for: {assignee}")
    return users[0]["accountId"]


def to_adf(text):
    """Minimal markdown -> ADF: '## ' headings, '- ' bullets, else paragraphs."""
    content = []
    bullets = []

    def flush_bullets():
        if bullets:
            content.append({
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": b}]}]}
                    for b in bullets
                ],
            })
            bullets.clear()

    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            flush_bullets()
        elif line.startswith("## "):
            flush_bullets()
            content.append({"type": "heading", "attrs": {"level": 2},
                            "content": [{"type": "text", "text": line[3:]}]})
        elif line.startswith("- "):
            bullets.append(line[2:])
        else:
            flush_bullets()
            content.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
    flush_bullets()
    return {"type": "doc", "version": 1, "content": content}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--summary", required=True)
    p.add_argument("--type", default="Task", help="Issue type; sub-tasks are 'Sub-task' (hyphen!)")
    p.add_argument("--parent", help="Parent issue key (mandatory for Sub-task)")
    p.add_argument("--assignee", default="me", help="'me' or a user email")
    p.add_argument("--label", action="append", default=[])
    p.add_argument("--capitalizable", default="Yes", choices=["Yes", "No"])
    p.add_argument("--body-file", help="Markdown file for the description")
    p.add_argument("--project", default="TGH")
    args = p.parse_args()

    fields = {
        "project": {"key": args.project},
        "issuetype": {"name": args.type},
        "summary": args.summary,
        "assignee": {"accountId": account_id_for(args.assignee)},
        "labels": args.label,
        # TGH required field; jira CLI cannot set it (dropped from --custom)
        "customfield_12220": {"value": args.capitalizable},
    }
    if args.parent:
        fields["parent"] = {"key": args.parent}
    if args.body_file:
        with open(args.body_file) as f:
            fields["description"] = to_adf(f.read())

    result = req("POST", "/rest/api/3/issue", {"fields": fields})
    print(f"{result['key']}  {SERVER}/browse/{result['key']}")


if __name__ == "__main__":
    main()
