"""Static analysis tests verifying codebase normalization invariants.

These tests scan source and template files to assert:
- No unprotected fetch() calls remain in templates (Requirement 3.1, 3.6)
- View-backed model queries (ColorUsage.query, ColorUsagePlayer.query) are preserved (Requirement 1.7)
- No legacy query patterns remain in migrated modules (Requirement 1.5)

These are file-scanning tests — no database fixtures or app context required.
"""

import os
import re

# Base directory of the project
BASE_DIR = os.path.join(os.path.dirname(__file__), '..')

# Migrated modules that must not contain legacy query patterns
MIGRATED_MODULES = [
    os.path.join(BASE_DIR, 'app', 'services', 'stats_service.py'),
    os.path.join(BASE_DIR, 'app', 'decks', 'routes.py'),
    os.path.join(BASE_DIR, 'app', 'stats', 'routes.py'),
    os.path.join(BASE_DIR, 'app', 'main', 'routes.py'),
]

# Template files that must have protected fetch calls
TEMPLATE_FILES = [
    os.path.join(BASE_DIR, 'app', 'templates', 'decks', 'show.html'),
    os.path.join(BASE_DIR, 'app', 'templates', 'stats', 'playerstats.html'),
    os.path.join(BASE_DIR, 'app', 'templates', 'user.html'),
    os.path.join(BASE_DIR, 'app', 'templates', 'stats', 'colorstats.html'),
    os.path.join(BASE_DIR, 'app', 'templates', 'decks', 'archive.html'),
]

# Files that must retain view-backed model queries
VIEW_BACKED_FILES = [
    os.path.join(BASE_DIR, 'app', 'main', 'routes.py'),
    os.path.join(BASE_DIR, 'app', 'stats', 'routes.py'),
]


def _read_file(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


# ─── Fetch Error Handling Tests ───────────────────────────────────────────────


def _fetch_calls_are_protected(content: str) -> list[str]:
    """Return list of unprotected fetch calls found in the content.

    A fetch call is protected if it is either:
    - Inside a try/catch block (async/await pattern)
    - Followed by a .catch() handler in its promise chain

    The detection uses indentation to find .catch() at the same level as
    the initial fetch call, ignoring code inside .then() callbacks.
    """
    unprotected = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        if 'fetch(' not in line:
            continue

        # Check if this fetch is inside a try block (look backwards for 'try {')
        in_try_block = False
        for j in range(i - 1, max(i - 10, -1), -1):
            if 'try' in lines[j] and '{' in lines[j]:
                in_try_block = True
                break

        if in_try_block:
            continue

        # Determine the indentation level of the fetch call
        fetch_indent = len(line) - len(line.lstrip())

        # Check if the promise chain has a .catch() handler (look forward)
        # We look for .catch( at the same or similar indentation level
        has_catch = False
        for j in range(i + 1, min(i + 40, len(lines))):
            stripped = lines[j].lstrip()
            line_indent = len(lines[j]) - len(stripped)

            if '.catch(' in lines[j]:
                # Accept .catch() at the same indentation level as the fetch
                # or indented by one level (chained off .then())
                if line_indent <= fetch_indent + 8:
                    has_catch = True
                    break

            # Stop if we encounter a completely new statement at fetch level or above
            # (e.g. a new top-level function declaration, closing of the enclosing block)
            if line_indent <= fetch_indent and stripped and not stripped.startswith('.') and not stripped.startswith('//'):
                # A new statement at the same or lesser indent that isn't a chain continuation
                if re.match(r'(function\s|async\s+function\s|[a-zA-Z_$]\w*\s*\(|if\s*\(|for\s*\(|while\s*\(|}\s*$|return\s)', stripped):
                    break

        if not has_catch:
            unprotected.append(f"Line {i + 1}: {line.strip()}")

    return unprotected


def test_no_unprotected_fetch_calls_in_templates():
    """Verify all fetch() calls in template files have error handling.

    Requirements: 3.1, 3.6
    """
    all_unprotected = []

    for template_path in TEMPLATE_FILES:
        content = _read_file(template_path)
        unprotected = _fetch_calls_are_protected(content)
        if unprotected:
            filename = os.path.relpath(template_path, BASE_DIR)
            for call in unprotected:
                all_unprotected.append(f"{filename} - {call}")

    assert not all_unprotected, (
        "Found unprotected fetch() calls (missing .catch() or try/catch):\n"
        + "\n".join(all_unprotected)
    )


# ─── View-Backed Model Query Preservation Tests ──────────────────────────────


def test_color_usage_query_preserved():
    """Verify ColorUsage.query remains in the codebase (view-backed model).

    Requirement: 1.7
    """
    found = False
    for filepath in VIEW_BACKED_FILES:
        content = _read_file(filepath)
        if 'ColorUsage.query' in content:
            found = True
            break

    assert found, (
        "ColorUsage.query not found in any expected file. "
        "View-backed model queries must remain unchanged."
    )


def test_color_usage_player_query_preserved():
    """Verify ColorUsagePlayer.query remains in the codebase (view-backed model).

    Requirement: 1.7
    """
    found = False
    for filepath in VIEW_BACKED_FILES:
        content = _read_file(filepath)
        if 'ColorUsagePlayer.query' in content:
            found = True
            break

    assert found, (
        "ColorUsagePlayer.query not found in any expected file. "
        "View-backed model queries must remain unchanged."
    )


# ─── Legacy Query Pattern Absence Tests ──────────────────────────────────────


def test_no_legacy_model_query_in_migrated_modules():
    """Verify no Model.query. patterns remain in migrated modules.

    Excludes view-backed models (ColorUsage.query, ColorUsagePlayer.query).
    Requirement: 1.5
    """
    # Pattern matches Model.query. but excludes ColorUsage and ColorUsagePlayer
    legacy_pattern = re.compile(r'(?<!ColorUsage)(?<!ColorUsagePlayer)\.query\.')
    # Also match explicit Model.query. where Model is a capitalized identifier
    model_query_pattern = re.compile(r'\b([A-Z]\w*)\.query\.')

    violations = []

    for module_path in MIGRATED_MODULES:
        content = _read_file(module_path)
        filename = os.path.relpath(module_path, BASE_DIR)

        for i, line in enumerate(content.split('\n'), 1):
            matches = model_query_pattern.findall(line)
            for model_name in matches:
                if model_name not in ('ColorUsage', 'ColorUsagePlayer'):
                    violations.append(f"{filename}:{i} - {line.strip()}")

    assert not violations, (
        "Found legacy Model.query. patterns in migrated modules:\n"
        + "\n".join(violations)
    )


def test_no_legacy_db_session_query_in_migrated_modules():
    """Verify no db.session.query( patterns remain in migrated modules.

    Requirement: 1.5
    """
    pattern = re.compile(r'db\.session\.query\(')
    violations = []

    for module_path in MIGRATED_MODULES:
        content = _read_file(module_path)
        filename = os.path.relpath(module_path, BASE_DIR)

        for i, line in enumerate(content.split('\n'), 1):
            if pattern.search(line):
                violations.append(f"{filename}:{i} - {line.strip()}")

    assert not violations, (
        "Found legacy db.session.query( patterns in migrated modules:\n"
        + "\n".join(violations)
    )
