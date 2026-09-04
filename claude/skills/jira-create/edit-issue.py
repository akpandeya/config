#!/usr/bin/env python3
"""Edit summary/description of an existing Jira issue via the REST API.

The jira CLI's `issue edit` gets 403 Forbidden on TGH, so this script calls the
REST API directly, reusing create-issue.py's auth and markdown->ADF conversion.

Usage:
  edit-issue.py ISSUE-KEY [--summary "New title"] [--body-file path.md] [--body "text"]

At least one of --summary/--body-file/--body is required. Body supports the
same markdown subset as create-issue.py ('## ' headings, '- ' bullets).
"""
import argparse
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location(
    "cji", os.path.join(os.path.dirname(os.path.abspath(__file__)), "create-issue.py"))
cji = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cji)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("key", help="Issue key, e.g. TGH-3512")
    p.add_argument("--summary")
    p.add_argument("--body-file", help="Markdown file replacing the description")
    p.add_argument("--body", help="Inline markdown replacing the description")
    args = p.parse_args()

    if args.body_file and args.body:
        sys.exit("Pass either --body-file or --body, not both")
    fields = {}
    if args.summary:
        fields["summary"] = args.summary
    if args.body_file or args.body:
        text = open(args.body_file).read() if args.body_file else args.body
        fields["description"] = cji.to_adf(text)
    if not fields:
        sys.exit("Nothing to update: pass at least one of --summary, --body-file, --body")

    cji.req("PUT", f"/rest/api/3/issue/{args.key}", {"fields": fields})
    print(f"updated  {cji.SERVER}/browse/{args.key}")


if __name__ == "__main__":
    main()
