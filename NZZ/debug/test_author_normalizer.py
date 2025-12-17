"""Test script for author normalizer."""

from author_normalizer import AuthorNormalizer

normalizer = AuthorNormalizer()

test_cases = [
    "Mumbai, Ulrich, von, Schwerin",
    "Bangkok, Andreas, Babst",
    "International, Gordana, Mijuk",
    "Schweiz und Debatte Daniel Foppa",
    "Kultur Peer Teuwsen",
    "NZZ, Geschichte, Claudia, Mäder",
    "Patrizia Trebbi Claudio Gmür Jürg Sturzenegger NZZ Folio Aline Wanner",
    "Singapur",
    "Andreas Babst, Bangkok",
    "Michael Radunski, Berlin",
    "Eric Gujer",
    "Daniel Wechlin",
    "Peer Teuwsen",
]

print("=" * 80)
print("Author Name Normalization Test")
print("=" * 80)

for test in test_cases:
    print(f"\nInput: '{test}'")
    print("-" * 80)
    authors = normalizer.parse_author_string(test)

    if not authors:
        print("  -> No authors parsed")
    else:
        for i, author in enumerate(authors, 1):
            print(f"  Author {i}:")
            print(f"    Normalized Name: '{author.normalized_name}'")
            print(f"    First Name: '{author.first_name}'")
            if author.middle_name:
                print(f"    Middle Name: '{author.middle_name}'")
            print(f"    Last Name: '{author.last_name}'")
            if author.location:
                print(f"    Location: '{author.location}'")
            if author.department:
                print(f"    Department: '{author.department}'")
            print(f"    Original: '{author.original_string}'")

print("\n" + "=" * 80)
print("Test Complete")
print("=" * 80)
