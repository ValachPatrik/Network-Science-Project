# Author Parsing and Normalization

## Overview

The scraper includes sophisticated author name parsing and normalization that:
- Extracts author names from article metadata
- Separates locations from names (e.g., "Name, Location" format)
- Normalizes names (handles prefixes like "von", "van", "de")
- Detects and filters standalone locations
- Uses LLM (Ollama) and geopy for location detection

## Features

### 1. Comma-Separated Format
Handles "Name, Location" format:
- `"Andreas Müller, Berlin"` → Name: "Andreas Müller", Location: "Berlin"
- `"Name, Location1 und Location2"` → Multiple locations supported

### 2. Location Detection
- Uses LLM (primary) and geopy (fallback) to identify locations
- Filters standalone locations (e.g., "New York", "San Francisco")
- Handles multi-word locations (e.g., "Rio de Janeiro", "Frankfurt am Main")

### 3. Name Normalization
- Handles name prefixes: "von", "van", "de", "da", "el", "al", "ten"
- Parses middle initials (e.g., "Johannes C. Bockenheimer")
- Handles multi-word names

### 4. Department Detection
- Identifies departments/sections (e.g., "NZZ-Redaktion", "Bildredaktion")
- Separates departments from author names

## Code Flow

1. **STEP 1**: Check for comma-separated "Name, Location" format
2. **STEP 2**: Check if entire string is a standalone location (filter out)
3. **STEP 3**: Use LLM to classify names, locations, and departments
4. **Fallback**: Use heuristic parsing if LLM is unavailable

## Configuration

The `AuthorNormalizer` class can be configured:
- `use_llm=True` - Use LLM for classification (requires Ollama)
- `use_geopy=True` - Use geopy for location detection (requires geopy)
- `llm_model_name` - Model name (default: "gemma3:270m")

## Testing

Run the 1000-article test:
```bash
python debug/test_1000_authors.py
```



