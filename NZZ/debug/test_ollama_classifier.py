"""Test script for Ollama-based LLM classifier."""

from llm_classifier import LLMLocationClassifier

# Initialize classifier
print("Initializing LLM classifier with Ollama...")
classifier = LLMLocationClassifier(model_name="deepseek-r1:latest", use_llm=True)

if not classifier.use_llm:
    print("ERROR: LLM classifier not available. Check Ollama installation.")
    exit(1)

print("OK: LLM classifier initialized!\n")

# Test cases
test_cases = [
    ("Lugano", "Lugano, Andreas, Babst"),
    ("Innsbruck", "Innsbruck, Daniel, Foppa"),
    ("Oerlikon", "Oerlikon, Maria, Schmidt"),
    ("Buenos Aires", "Buenos Aires, John, Doe"),
    ("Wuhan", "Wuhan, Li, Zhang"),
    ("Dusseldorf", "Dusseldorf, Hans, Mueller"),
    ("Andreas", "Bangkok, Andreas, Babst"),
    ("Babst", "Bangkok, Andreas, Babst"),
    ("Daniel", "Innsbruck, Daniel, Foppa"),
    ("Kultur", "Kultur Peer Teuwsen"),
    ("NZZ", "NZZ, Geschichte, Claudia, Mäder"),
]

print("=" * 80)
print("Testing Location/Name Classification")
print("=" * 80)

for term, context in test_cases:
    result = classifier.classify_term(term, context)
    status = "OK" if result["type"] != "unknown" else "FAIL"
    print(f"\n{status} Term: '{term}' (Context: '{context}')")
    print(f"   Type: {result['type']}")
    print(f"   Confidence: {result['confidence']:.2f}")
    print(f"   Reasoning: {result['reasoning']}")

print("\n" + "=" * 80)
print("Quick Location Checks")
print("=" * 80)

locations = ["Lugano", "Innsbruck", "Oerlikon", "Buenos Aires", "Wuhan", "Dusseldorf"]
for loc in locations:
    is_loc = classifier.is_location(loc)
    print(
        f"{'OK' if is_loc else 'FAIL'} {loc}: {'Location' if is_loc else 'Not a location'}"
    )

print("\n" + "=" * 80)
print("Test Complete")
print("=" * 80)
