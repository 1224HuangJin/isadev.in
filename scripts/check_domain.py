#!/usr/bin/env python3
"""
Runs on every PR. Checks domains.json for:
- Valid JSON
- Only one new entry added
- No duplicate subdomains
- Valid NS record format
Posts a PR comment and closes the PR if anything is wrong.
"""

import json
import os
import re
import sys
import subprocess

import requests

ROOT_DOMAIN = "isadev.in"
DOMAINS_FILE = "domains.json"

GH_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
PR_NUMBER = os.environ["PR_NUMBER"]

SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")
NS_RE = re.compile(r"^[a-z0-9]([a-z0-9\-\.]{0,253}[a-z0-9])?$", re.IGNORECASE)


def gh_comment(body: str):
    requests.post(
        f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Content-Type": "application/json"},
        json={"body": body},
    )


def gh_close():
    requests.patch(
        f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Content-Type": "application/json"},
        json={"state": "closed"},
    )


def gh_label(label: str):
    requests.post(
        f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/labels",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Content-Type": "application/json"},
        json={"labels": [label]},
    )


def get_base_domains() -> list:
    """Load domains.json from main branch (before this PR)."""
    result = subprocess.run(
        ["git", "show", "origin/main:domains.json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return json.loads(result.stdout)


def get_pr_domains() -> list:
    """Load domains.json from the PR branch (current working tree)."""
    with open(DOMAINS_FILE) as f:
        return json.load(f)


def main():
    # Load both versions
    try:
        base = get_base_domains()
    except Exception as e:
        gh_comment(f"❌ Could not read `domains.json` from `main`: `{e}`")
        gh_close()
        sys.exit(1)

    try:
        pr = get_pr_domains()
    except json.JSONDecodeError as e:
        gh_comment(f"❌ `domains.json` is not valid JSON:\n```\n{e}\n```")
        gh_close()
        sys.exit(1)

    if not isinstance(pr, list):
        gh_comment("❌ `domains.json` must be a JSON array.")
        gh_close()
        sys.exit(1)

    base_subs = {entry["subdomain"].lower() for entry in base}
    pr_subs = [entry["subdomain"].lower() for entry in pr]

    # Check for duplicates within the file itself
    seen = set()
    for sub in pr_subs:
        if sub in seen:
            gh_comment(
                f"❌ Duplicate subdomain `{sub}` found inside `domains.json`.\n\n"
                "Each subdomain must appear only once."
            )
            gh_close()
            sys.exit(1)
        seen.add(sub)

    # Find what was added
    new_entries = [e for e in pr if e["subdomain"].lower() not in base_subs]

    # Find what was removed or modified (not allowed)
    pr_sub_set = {e["subdomain"].lower() for e in pr}
    removed = base_subs - pr_sub_set
    if removed:
        gh_comment(
            f"❌ Existing entries were removed or modified: `{', '.join(removed)}`\n\n"
            "Only adding new entries is allowed. Do not edit or remove existing ones."
        )
        gh_close()
        sys.exit(1)

    if len(new_entries) == 0:
        gh_comment("❌ No new entry found. Add your subdomain entry to `domains.json`.")
        gh_close()
        sys.exit(1)

    if len(new_entries) > 1:
        gh_comment(
            f"❌ You added {len(new_entries)} entries at once. Submit one subdomain per PR."
        )
        gh_close()
        sys.exit(1)

    entry = new_entries[0]

    # Validate fields
    subdomain = entry.get("subdomain", "")
    owner = entry.get("owner", "")
    ns_list = entry.get("ns", [])

    if not subdomain or not SUBDOMAIN_RE.match(subdomain):
        gh_comment(
            f"❌ Invalid subdomain `{subdomain}`.\n\n"
            "Must be lowercase alphanumeric and hyphens only."
        )
        gh_close()
        sys.exit(1)

    if not owner or not isinstance(owner, str):
        gh_comment("❌ Missing or invalid `owner` field. Must be your GitHub username.")
        gh_close()
        sys.exit(1)

    if not isinstance(ns_list, list) or len(ns_list) < 1:
        gh_comment("❌ `ns` must be a list with at least one nameserver.")
        gh_close()
        sys.exit(1)

    for ns in ns_list:
        if not NS_RE.match(ns):
            gh_comment(f"❌ Invalid nameserver `{ns}`.")
            gh_close()
            sys.exit(1)

    full_domain = f"{subdomain}.{ROOT_DOMAIN}"

    gh_label("pending review")
    gh_comment(
        f"✅ **`{full_domain}` is available.**\n\n"
        f"| | |\n|---|---|\n"
        f"| Subdomain | `{full_domain}` |\n"
        f"| Owner | [@{owner}](https://github.com/{owner}) |\n"
        f"| Nameservers | `{'`, `'.join(ns_list)}` |\n\n"
        "Waiting for a maintainer to review and merge."
    )
    print(f"OK: {full_domain} — available, PR kept open.")


if __name__ == "__main__":
    main()
