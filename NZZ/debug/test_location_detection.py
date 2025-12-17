"""Test location detection for various location strings."""

import sys

sys.path.insert(0, ".")

from author_normalizer import AuthorNormalizer

an = AuthorNormalizer(use_llm=True, use_geopy=True)

# Test various location strings
location_tests = [
    "Rio de Janeiro",
    "Frankfurt am Main",
    "New York",
    "San Francisco",
    "São Paulo",
    "Yosemite Valley",
    "Deir al-Balah",
    "Mazra al-Nubani",
    "Los Angeles",
    "Buenos Aires",
]

print("=" * 70)
print("TESTING LOCATION DETECTION (Logic-Based)")
print("=" * 70)
print()

for location in location_tests:
    result = an.parse_author_string(location)
    is_location = an.is_location(location, context=location)

    if result:
        print(f"{location}:")
        print(f"  Parsed as name: {result[0].normalized_name}")
        print(f"  is_location() returned: {is_location}")
        print(f"  STATUS: FAIL (should be filtered)")
    else:
        print(f"{location}:")
        print(f"  Filtered (empty result)")
        print(f"  is_location() returned: {is_location}")
        print(f"  STATUS: OK")
    print()
