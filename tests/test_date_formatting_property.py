# Feature: raw-sql-to-orm, Property 8: Date Formatting
"""
Property test verifying that `format_date_german` produces a string matching
"D.M.YYYY" where D and M are non-zero-padded for any valid Python date object.

**Validates: Requirements 4.5**
"""
import re
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from app.api.formatters import format_date_german


# Strategy: generate dates with 4-digit years (the domain of this app is modern dates)
date_strategy = st.dates(
    min_value=date(1000, 1, 1),
    max_value=date(9999, 12, 31),
)

# Pattern: D.M.YYYY — day and month have no leading zeros, year is 4 digits
DATE_PATTERN = re.compile(r"^([1-9]|[12]\d|3[01])\.([1-9]|1[0-2])\.\d{4}$")


@given(d=date_strategy)
@settings(max_examples=100)
def test_format_date_german_produces_non_zero_padded_string(d: date):
    """Property 8: For any valid date, format_date_german SHALL produce a string
    matching "D.M.YYYY" where D and M are non-zero-padded.
    """
    result = format_date_german(d)

    # 1. Output is a string
    assert isinstance(result, str)

    # 2. Output matches the non-zero-padded pattern
    assert DATE_PATTERN.match(result), (
        f"Date {d} produced '{result}' which doesn't match D.M.YYYY pattern"
    )

    # 3. Parts when parsed back produce the original date
    parts = result.split(".")
    assert len(parts) == 3, f"Expected 3 dot-separated parts, got {len(parts)}"

    day_str, month_str, year_str = parts
    assert int(day_str) == d.day, f"Day mismatch: '{day_str}' != {d.day}"
    assert int(month_str) == d.month, f"Month mismatch: '{month_str}' != {d.month}"
    assert int(year_str) == d.year, f"Year mismatch: '{year_str}' != {d.year}"

    # 4. No leading zeros on day and month
    assert day_str[0] != "0", f"Day '{day_str}' has leading zero"
    assert month_str[0] != "0", f"Month '{month_str}' has leading zero"

    # 5. Year is exactly 4 digits
    assert len(year_str) == 4, f"Year '{year_str}' is not 4 digits"
