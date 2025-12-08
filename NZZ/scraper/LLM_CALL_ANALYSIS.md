# Why LLM Is Not Being Called for Some Cases

## Problem

The test results show `llm_called: false` for all failing cases, but this is misleading. The LLM **IS** being called, but indirectly through `is_location()`, not in the main parsing flow.

## Code Flow Analysis

### Current Flow in `parse_author_string()`:

1. **STEP 1** (lines 327-409): Check for comma-separated "Name, Location" format
   - If found, returns early
   - Calls `is_location()` internally to validate locations

2. **STEP 2** (lines 411-502): Check if entire string is a standalone location
   - Calls `is_location()` which internally uses LLM/geopy
   - If `is_location()` returns True OR heuristic patterns match, returns `[]` early
   - **This prevents reaching STEP 3**

3. **STEP 3** (lines 504+): Main LLM parsing section
   - Only reached if STEP 1 and STEP 2 don't return early
   - This is where the main LLM classification happens

## Why LLM Appears "Not Called"

### For Locations (e.g., "San Francisco", "New York", "Tel Aviv"):

1. They are caught in **STEP 2**
2. `is_location()` is called, which internally calls LLM
3. If `is_location()` returns True, it returns `[]` immediately
4. **Never reaches STEP 3** where main LLM parsing happens
5. Test script shows `llm_called: false` because it only tracks LLM calls in STEP 3

### For Names (e.g., "Jörg Scheller", "Kathrin Klette"):

1. They should reach **STEP 3** (not caught by STEP 2)
2. LLM should be called in STEP 3
3. But test script shows `llm_called: false` - this suggests:
   - Either the test script isn't tracking LLM calls properly
   - OR these cases are being handled by heuristic parsing before LLM is called
   - OR there's an early return we're missing

## The Real Issue

The problem is that **STEP 2 returns early for locations**, preventing them from reaching the main LLM parsing section. This means:

1. **Locations are filtered out too early** - They're caught by `is_location()` or heuristic patterns in STEP 2
2. **LLM in STEP 3 never gets a chance** to properly classify ambiguous cases
3. **For ambiguous cases** (two-word capitalized strings that could be names or locations), we should let the LLM in STEP 3 make the decision

## Solution

We need to modify the flow so that:

1. **For clearly identifiable locations** (with location keywords, connectors, or confirmed by `is_location()`), filter them out in STEP 2 (current behavior is OK)

2. **For ambiguous cases** (two-word capitalized strings without clear location indicators), **don't filter in STEP 2** - let them reach STEP 3 where the LLM can properly classify them

3. **Improve STEP 2 logic** to be less aggressive for ambiguous cases:
   - Only filter if `is_location()` confirms it AND it has location indicators
   - Don't filter based solely on heuristic patterns for ambiguous two-word strings
   - Let STEP 3 LLM handle ambiguous cases

## Recommended Fix

Modify STEP 2 to be less aggressive for ambiguous cases:

```python
# In STEP 2, for two-word capitalized strings:
if len(words) == 2 and first_word_capitalized and words[1][0].isupper():
    # Only filter if:
    # 1. is_location() confirms it AND
    # 2. It has clear location indicators (keywords, connectors, or common location starters)
    
    # Don't filter ambiguous cases - let STEP 3 LLM handle them
    if is_location_confirmed and (has_location_keyword or has_location_connector or is_common_location):
        return []  # Filter it out
    # Otherwise, continue to STEP 3 for LLM classification
```

This ensures that:
- Clear locations are still filtered early (performance)
- Ambiguous cases reach the LLM for proper classification
- The LLM gets a chance to handle edge cases



