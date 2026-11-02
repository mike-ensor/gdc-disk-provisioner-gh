# Copyright 2026 Google LLC
# SPDX-License-Identifier: Apache-2.0

"""Ansible Jinja2 filter plugin to sanitize terminal control characters from command outputs."""

import re

ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\([a-zA-Z]')
BRAILLE_SPINNERS = set('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋⠙⠚⠒⠂⠂⠒⠲⠴⠤⠄⠅⠇⠇⠦⠤⠠⠡')


def clean_terminal_output(text, max_lines=50, max_chars=35000, as_lines=True):
    """Strips ANSI escape codes, terminal backspaces (\b, \x08), rubouts (\x7f),
    carriage returns (\r), and repetitive progress spinner frames, retaining only
    the most recent readable lines (default 50 lines) formatted as an array of
    clean lines so that JSON serializes each line with actual line-breaks."""
    if not isinstance(text, str):
        if isinstance(text, list):
            return text[-max_lines:] if max_lines else text
        return text

    # Normalize carriage returns and newlines into separate lines
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    cleaned_lines = []

    for line in lines:
        # Strip ANSI escape codes
        l = ANSI_REGEX.sub('', line)
        # Strip backspaces (\b, \x08) and rubouts (\x7f)
        l = re.sub(r'[\x08\x7f]+', '', l)
        l = l.strip('\r').rstrip()

        # Skip intermediate braille/ascii spinner frame lines
        if any(c in l for c in BRAILLE_SPINNERS):
            continue

        if l:
            cleaned_lines.append(l)

    if max_lines and len(cleaned_lines) > max_lines:
        cleaned_lines = cleaned_lines[-max_lines:]

    if as_lines:
        # If total characters across all lines exceeds max_chars, truncate from the beginning
        total_chars = sum(len(x) for x in cleaned_lines)
        while cleaned_lines and total_chars > max_chars:
            removed = cleaned_lines.pop(0)
            total_chars -= len(removed)
        return cleaned_lines

    result = '\n'.join(cleaned_lines)
    if max_chars and len(result) > max_chars:
        result = result[-max_chars:]

    return result


class FilterModule(object):
    """Ansible filter plugin registration."""

    def filters(self):
        return {
            'clean_terminal_output': clean_terminal_output,
            'clean_terminal_lines': clean_terminal_output,
            'gdc_clean_log': clean_terminal_output,
        }
