#!/usr/bin/env python3
"""Substitute {{placeholders}} in the release-email template from env vars.

Plain str.replace (not a template engine) so arbitrary HTML in NOTES_HTML is
inserted verbatim and can't trigger template-syntax errors.
"""
import os
import sys

template = open(sys.argv[1], encoding="utf-8").read()

replacements = {
    "{{repo}}": os.environ.get("REPO", ""),
    "{{version}}": os.environ.get("VERSION", ""),
    "{{notes_html}}": os.environ.get("NOTES_HTML", ""),
    "{{release_url}}": os.environ.get("URL", "#"),
    "{{year}}": os.environ.get("YEAR", ""),
    "{{date_suffix}}": os.environ.get("DATE_SUFFIX", ""),
    "{{summary}}": os.environ.get("SUMMARY", ""),
}
for key, value in replacements.items():
    template = template.replace(key, value)

sys.stdout.write(template)
