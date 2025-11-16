"""Test department extraction from impressum page."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper_v3 import NZZScraperV3
from bs4 import BeautifulSoup
import requests

scraper = NZZScraperV3()

print("=" * 80)
print("TESTING DEPARTMENT EXTRACTION FROM IMPRESSUM")
print("=" * 80)
print()

# Fetch impressum page
r = requests.get(scraper.impressum_url)
soup = BeautifulSoup(r.text, 'html.parser')

# Extract departments
author_departments = scraper._extract_departments_from_impressum(soup)

print(f"Extracted {len(author_departments)} author-department mappings")
print()

# Show sample mappings
print("Sample author-department mappings (first 20):")
for i, (author, dept) in enumerate(list(author_departments.items())[:20], 1):
    print(f"{i:3d}. {author:40s} -> {dept}")

print()
print("Department distribution:")
from collections import Counter
dept_counts = Counter(author_departments.values())
for dept, count in dept_counts.most_common():
    print(f"  {dept:40s}: {count:3d} authors")

