"""Comprehensive author name normalization and location detection system."""
import re
import os
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger('nzz_scraper')


@dataclass
class ParsedAuthor:
    """Represents a parsed and normalized author."""
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    location: Optional[str] = None
    department: Optional[str] = None
    normalized_name: str = ""  # Standard format: "First Middle Last"
    original_string: str = ""  # Original input string
    
    def __post_init__(self):
        """Generate normalized name after initialization."""
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        self.normalized_name = " ".join(parts).strip()


class AuthorNormalizer:
    """Normalizes author names and separates locations/departments from names."""
    
    # Note: We use logic-based location detection (geopy + LLM) instead of hardcoded lists
    # This allows the system to detect any location dynamically without maintaining lists
    
    # Known departments/sections
    KNOWN_DEPARTMENTS = {
        'nzz', 'nzz-redaktion', 'redaktion', 'folio', 'geschichte', 'history', 'kultur', 'culture', 'feuilleton',
        'debatte', 'debate', 'wirtschaft', 'economy', 'sport', 'politik', 'politics',
        'international', 'inland', 'domestic', 'ausland', 'foreign', 'meinung', 'opinion',
        'zuerich', 'zurich', 'schweiz', 'switzerland', 'visuals',
        # Job titles that might appear
        'chefredaktor', 'editor-in-chief', 'ressortleiter', 'section head',
        'korrespondent', 'correspondent', 'reporter', 'redaktor', 'editor',
    }
    
    # Common name prefixes
    NAME_PREFIXES = {'von', 'van', 'de', 'da', 'di', 'del', 'der', 'den', 'du', 'le', 'la', 'ten', 'el', 'al'}
    
    # Common name suffixes
    NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'phd', 'md'}
    
    def __init__(self, use_geopy: bool = True, use_llm: bool = True, llm_model_name: Optional[str] = None):
        """Initialize the normalizer.
        
        Args:
            use_geopy: If True, use geopy library for location detection (default: True)
            use_llm: If True, use LLM for classification (default: True)
            llm_model_name: Name of Ollama model to use (default: "gemma3:270m").
                          Can be overridden with OLLAMA_MODEL environment variable.
        """
        self.use_geopy = use_geopy
        self.geocoder = None
        self.location_cache = {}  # Cache for location lookups to reduce API calls
        
        # Initialize LLM classifier
        self.llm_classifier = None
        if use_llm:
            try:
                # Try relative import first (if in same directory)
                try:
                    from .llm_classifier import LLMLocationClassifier
                except ImportError:
                    # Fallback to absolute import
                    from llm_classifier import LLMLocationClassifier
                
                model_name = llm_model_name or os.getenv('OLLAMA_MODEL', 'gemma3:270m')
                self.llm_classifier = LLMLocationClassifier(model_name=model_name, use_llm=True)
                if self.llm_classifier.use_llm:
                    logger.info("LLM classifier initialized for location/name detection")
                else:
                    logger.warning("LLM classifier not available - will use geopy/heuristics")
            except ImportError:
                logger.warning("llm_classifier module not found. LLM classification disabled.")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM classifier: {str(e)}")
        
        if use_geopy:
            try:
                from geopy.geocoders import Nominatim
                from geopy.exc import GeocoderTimedOut, GeocoderServiceError
                self.geocoder = Nominatim(user_agent="nzz_scraper", timeout=3)
                self.GeocoderTimedOut = GeocoderTimedOut
                self.GeocoderServiceError = GeocoderServiceError
                logger.info("Geopy initialized for location detection")
            except ImportError:
                logger.warning("geopy not installed. Install with: pip install geopy")
                logger.warning("Falling back to heuristic location detection")
                self.use_geopy = False
                self.geocoder = None
    
    def is_location(self, term: str, context: Optional[str] = None) -> bool:
        """Check if a term is a location using LLM (primary) and geopy (fallback).
        
        Args:
            term: Term to check
            context: Optional context string (e.g., full author string)
            
        Returns:
            True if term is a location
        """
        if not term or len(term.strip()) < 2:
            return False
        
        term_clean = term.strip()
        term_lower = term_clean.lower()
        
        # Check cache first
        if term_lower in self.location_cache:
            return self.location_cache[term_lower]
        
        # Check known departments (definitely not locations) - this is OK to keep as it's a small, stable list
        if term_lower in self.KNOWN_DEPARTMENTS:
            self.location_cache[term_lower] = False
            return False
        
        # CRITICAL: Pre-check for common name patterns to avoid false positives
        # If it looks like a name (2 words, both capitalized, no location indicators), be conservative
        words = term_clean.split()
        both_capitalized = False
        has_location_connector = False
        has_location_keyword = False
        
        if len(words) == 2:
            # Check if both words are capitalized (common name pattern)
            both_capitalized = words[0][0].isupper() and words[1][0].isupper()
            # Check for location indicators
            has_location_connector = any(conn in term_lower for conn in [' de ', ' am ', ' on ', ' in ', ' bei ', ' an ', ' al-', ' al '])
            has_location_keyword = any(kw in term_lower for kw in ['valley', 'city', 'town', 'gazastreifen', 'gaza'])
            
            # If it looks like a name (both capitalized, no location indicators), be more conservative
            if both_capitalized and not has_location_connector and not has_location_keyword:
                # Check if it contains common name patterns (e.g., umlauts, common name endings)
                # This helps avoid false positives for names like "Jörg Scheller", "Katrin Büchenbacher"
                # Only proceed with LLM/geopy if we're confident it's not a name
                pass  # Continue to LLM/geopy check, but be more strict
        
        # Try LLM classifier first (most accurate)
        if self.llm_classifier and self.llm_classifier.use_llm:
            try:
                # Get full classification result to validate
                result = self.llm_classifier.classify_term(term_clean, context)
                locations = result.get('locations', [])
                names = result.get('names', [])
                
                # CRITICAL: Only trust LLM if locations actually appear in the input
                # If LLM returns locations that don't match the input, it's unreliable
                valid_locations = []
                for loc in locations:
                    loc_lower = loc.lower().strip()
                    # Check if location appears in the input (allowing for case differences)
                    if loc_lower in term_lower or any(word in term_lower for word in loc_lower.split()):
                        valid_locations.append(loc)
                
                # If LLM found valid locations, trust it
                if valid_locations:
                    # BUT: If it also found names that match the input, be more careful
                    valid_names = []
                    for name in names:
                        name_lower = name.lower().strip()
                        if name_lower in term_lower or any(word in term_lower for word in name_lower.split()):
                            valid_names.append(name)
                    
                    # If LLM found both names and locations, prioritize names (more conservative)
                    if valid_names and len(words) == 2 and both_capitalized and not has_location_connector:
                        # Likely a name, not a location
                        logger.debug(f"LLM found both names and locations for '{term_clean}', prioritizing name (found: {valid_names})")
                        self.location_cache[term_lower] = False
                        return False
                    
                    logger.debug(f"LLM classified '{term_clean}' as location (found: {valid_locations})")
                    self.location_cache[term_lower] = True
                    return True
                
                # If LLM found names that match the input, it's likely a name, not a location
                valid_names = []
                for name in names:
                    name_lower = name.lower().strip()
                    if name_lower in term_lower or any(word in term_lower for word in name_lower.split()):
                        valid_names.append(name)
                
                if valid_names and not valid_locations:
                    # LLM found names but no valid locations - likely a name
                    logger.debug(f"LLM classified '{term_clean}' as name (found: {valid_names})")
                    self.location_cache[term_lower] = False
                    return False
                    
            except Exception as e:
                logger.debug(f"LLM classification error for '{term_clean}': {str(e)}, falling back to geopy")
        
        # Use geopy to check if it's a location
        if self.use_geopy and self.geocoder:
            try:
                # CRITICAL: For two-word terms that look like names, be more conservative
                # Only use geopy if we're confident it's not a name
                if len(words) == 2 and both_capitalized and not has_location_connector and not has_location_keyword:
                    # This looks like a name - be very conservative with geopy
                    # Only trust geopy if it's a very clear location match
                    pass  # Continue but be strict
                
                # Try to geocode the term
                location = self.geocoder.geocode(term_clean, exactly_one=True, timeout=3)
                if location:
                    # Check if the result is actually a location (not just a partial match)
                    # Prioritize results that are cities, countries, or regions
                    location_type = location.raw.get('type', '').lower()
                    place_type = location.raw.get('class', '').lower()
                    
                    # For two-word terms that look like names, require stronger evidence
                    if len(words) == 2 and both_capitalized and not has_location_connector:
                        # Require that it's clearly a place type (not just a partial match)
                        if place_type not in ['place', 'boundary', 'administrative']:
                            # Not a clear location - might be a false positive
                            self.location_cache[term_lower] = False
                            return False
                        # Also check that the address contains location indicators
                        address_lower = location.address.lower()
                        if not any(indicator in address_lower for indicator in ['city', 'town', 'country', 'state', 'region', 'county', 'place']):
                            # Not a clear location match
                            self.location_cache[term_lower] = False
                            return False
                    
                    # Accept if it's a place, city, town, country, etc.
                    if place_type in ['place', 'boundary', 'administrative']:
                        self.location_cache[term_lower] = True
                        return True
                    # Also accept if location type suggests it's a geographic location
                    if location_type in ['city', 'town', 'village', 'country', 'state', 'region', 'county']:
                        self.location_cache[term_lower] = True
                        return True
                    # If it's a named place (not a building or POI), it's likely a location
                    if 'place' in location.address.lower() or 'city' in location.address.lower():
                        self.location_cache[term_lower] = True
                        return True
                    
                    # Otherwise, it might be a false positive (e.g., a person's name that matches a place)
                    self.location_cache[term_lower] = False
                    return False
                else:
                    # Not found in geocoding service
                    self.location_cache[term_lower] = False
                    return False
            except (self.GeocoderTimedOut, self.GeocoderServiceError) as e:
                # Rate limit or service error - cache as unknown and return False
                logger.debug(f"Geopy error for '{term_clean}': {str(e)}")
                self.location_cache[term_lower] = False
                return False
            except Exception as e:
                # Other error - log and return False
                logger.debug(f"Error checking location '{term_clean}': {str(e)}")
                self.location_cache[term_lower] = False
                return False
        else:
            # Geopy not available - return False (better to miss a location than incorrectly classify)
            # Without geopy/LLM, we can't reliably detect locations
            self.location_cache[term_lower] = False
            return False
    
    def is_department(self, term: str, context: Optional[str] = None) -> bool:
        """Check if a term is a department/section using LLM (primary) and heuristics (fallback).
        
        Args:
            term: Term to check
            context: Optional context string (e.g., full author string)
            
        Returns:
            True if term is a department
        """
        if not term or len(term.strip()) < 2:
            return False
        
        term_clean = term.strip()
        term_lower = term_clean.lower()
        
        # Check known departments (quick check for common ones)
        if term_lower in self.KNOWN_DEPARTMENTS:
            return True
        
        # Try LLM classifier first (most accurate)
        if self.llm_classifier and self.llm_classifier.use_llm:
            try:
                is_dept = self.llm_classifier.is_department(term_clean, context, min_confidence=0.6)
                if is_dept:
                    logger.debug(f"LLM classified '{term_clean}' as department")
                return is_dept
            except Exception as e:
                logger.debug(f"LLM classification error for '{term_clean}': {str(e)}, falling back to heuristics")
        
        # Fallback to known departments only
        return term_lower in self.KNOWN_DEPARTMENTS
    
    def parse_author_string(self, author_string: str) -> List[ParsedAuthor]:
        """Parse an author string that may contain multiple authors, locations, and departments.
        
        Handles formats like:
        - "Mumbai, Ulrich, von, Schwerin"
        - "Bangkok, Andreas, Babst"
        - "International, Gordana, Mijuk"
        - "Schweiz und Debatte Daniel Foppa"
        - "Kultur Peer Teuwsen"
        - "NZZ, Geschichte, Claudia, Mäder"
        - "Patrizia Trebbi Claudio Gmür Jürg Sturzenegger"
        
        Args:
            author_string: Raw author string from article
            
        Returns:
            List of ParsedAuthor objects
        """
        if not author_string or not author_string.strip():
            return []
        
        author_string = author_string.strip()
        parsed_authors = []
        
        # STEP 1: Check for comma-separated "Name, Location" format BEFORE LLM
        # This handles common cases faster and more reliably
        # Pattern: "Name, Location" or "Name, Location1 und Location2"
        if ',' in author_string:
            # First check for "und" / "and" separator for multiple locations
            if ' und ' in author_string.lower() or ' and ' in author_string.lower():
                # Pattern: "Name, Location1 und Location2"
                comma_parts = [p.strip() for p in author_string.split(',', 1)]
                if len(comma_parts) == 2:
                    name_part, locations_part = comma_parts
                    if name_part and locations_part:
                        # Split locations by "und" / "and"
                        location_list = re.split(r'\s+und\s+|\s+and\s+', locations_part, flags=re.IGNORECASE)
                        location_list = [loc.strip() for loc in location_list if loc.strip()]
                        
                        # Check if name_part looks like a name
                        name_words = name_part.split()
                        name_looks_valid = len(name_words) >= 2 and all(w[0].isupper() if w else False for w in name_words[:2])
                        
                        if name_looks_valid and location_list:
                            # Validate locations - ensure they're actually locations, not names
                            validated_locations = []
                            for loc in location_list:
                                # Check if location is actually a location (not a name)
                                if self.is_location(loc, context=author_string):
                                    validated_locations.append(loc)
                                # Also check if it's not the name itself
                                elif loc.lower() not in name_part.lower():
                                    # Heuristic: if capitalized and >=3 chars, might be a location
                                    if loc[0].isupper() and len(loc) >= 3:
                                        validated_locations.append(loc)
                            
                            # Use first validated location (primary location)
                            if validated_locations:
                                primary_location = validated_locations[0]
                                author = self._parse_name_to_author(name_part, primary_location, None, author_string)
                                if author:
                                    return [author]
            
            # Standard "Name, Location" format (single comma, no "und")
            if author_string.count(',') == 1:
                parts = [p.strip() for p in author_string.split(',', 1)]
                if len(parts) == 2:
                    name_part, location_part = parts
                    if location_part and name_part:
                        # Check if name_part looks like a name (2+ words, capitalized)
                        name_words = name_part.split()
                        name_looks_valid = len(name_words) >= 2 and all(w[0].isupper() if w else False for w in name_words[:2])
                        
                        if name_looks_valid:
                            # CRITICAL: For comma-separated format, be more aggressive about splitting
                            # If name_part is clearly a name and location_part looks like a location,
                            # split it even if is_location() doesn't confirm it
                            
                            # Check if location_part looks like a location (heuristic + logic)
                            location_words = location_part.split()
                            
                            # Heuristic indicators that it's a location:
                            # 1. Contains location keywords (gazastreifen, valley, city, etc.)
                            location_keywords = ['gazastreifen', 'gaza', 'valley', 'city', 'town', 'nördlicher', 'südlicher', 'östlicher', 'westlicher', 'nord', 'süd', 'ost', 'west']
                            has_location_keyword = any(kw in location_part.lower() for kw in location_keywords)
                            
                            # 2. Contains location connectors (de, am, al-, etc.)
                            location_connectors = [' de ', ' am ', ' on ', ' in ', ' bei ', ' an ', ' al-', ' al ']
                            has_location_connector = any(conn in location_part.lower() for conn in location_connectors)
                            
                            # 3. Multi-word capitalized (likely city name)
                            is_multi_word_capitalized = len(location_words) > 1 and all(w[0].isupper() if w else False for w in location_words)
                            
                            # 4. Single word capitalized (likely city name)
                            is_single_word_capitalized = len(location_words) == 1 and location_part[0].isupper() and len(location_part) >= 3
                            
                            # 5. Logic-based detection
                            is_location_confirmed = self.is_location(location_part, context=author_string)
                            
                            # If ANY of these indicators are true, treat as location and split
                            if (has_location_keyword or has_location_connector or is_location_confirmed or 
                                (is_multi_word_capitalized and not self.is_department(location_part, context=author_string)) or
                                (is_single_word_capitalized and not self.is_department(location_part, context=author_string))):
                                # Split it: name_part is the name, location_part is the location
                                author = self._parse_name_to_author(name_part, location_part, None, author_string)
                                if author:
                                    return [author]
        
        # STEP 2: Check if entire string is a standalone location (single OR multi-word)
        # NOTE: Return empty list - standalone locations shouldn't create author entries
        # CRITICAL: Skip this check if string contains comma - comma-separated format is handled in STEP 1
        if ',' not in author_string:  # Only check for standalone locations if no comma
            words = author_string.split()
            if len(words) == 1:
                if self.is_location(author_string, context=author_string):
                    # It's a standalone location - don't create an author entry
                    return []
            elif len(words) >= 2:
                # Check if it's a multi-word location using logic-based detection
                # BUT exclude names with prefixes (e.g., "Michael von Ledebur", "Hans ten Doornkaat")
                
                # First, check if it's a name with a prefix - if so, skip location check
                # Check for common name prefixes in middle position
                # BUT: Some prefixes like "de", "da" can also be location connectors
                # Distinguish: if it's a location connector pattern, treat as location, not name prefix
                is_name_with_prefix = False
                if len(words) == 3:
                    middle_word = words[1].lower()
                    # Check if middle word is a name prefix
                    if middle_word in self.NAME_PREFIXES:
                        # BUT: if it's a location connector pattern, it's a location, not a name
                        # Location connectors: "de", "da", "am", "on", "in", "bei", "an"
                        location_connectors = ['de', 'da', 'am', 'on', 'in', 'bei', 'an']
                        if middle_word in location_connectors:
                            # This is a location connector, not a name prefix
                            is_name_with_prefix = False
                        else:
                            # This is a name prefix (like "von", "van", "el", "ten")
                            is_name_with_prefix = True
                
                if not is_name_with_prefix:
                    # Check if first word is capitalized (locations usually start with capital)
                    # Also check for common location patterns like "X de Y", "X am Y", "X on Y", "X al-Y"
                    first_word_capitalized = words[0][0].isupper() if words[0] else False
                    has_location_connector = any(connector in author_string.lower() for connector in [' de ', ' am ', ' on ', ' in ', ' bei ', ' an '])
                    
                    # Check for Arabic location patterns
                    has_arabic_location_pattern = any(pattern in author_string.lower() for pattern in [' al-', ' al ']) and len(words) >= 2
                    
                    # Check for location keywords (geographic terms)
                    location_keywords = ['gazastreifen', 'gaza', 'westjordanland', 'westbank', 'palästina', 'palestine', 'valley', 'city', 'town']
                    has_location_keyword = any(keyword in author_string.lower() for keyword in location_keywords)
                    
                    # Check with is_location() - this will be used later for Pattern 3
                    is_location_confirmed = self.is_location(author_string, context=author_string)
                    
                    # If it looks like a location pattern, use logic-based detection
                    if first_word_capitalized or has_location_connector or has_arabic_location_pattern or has_location_keyword:
                        # First try logic-based detection (geopy + LLM)
                        if is_location_confirmed:
                            # It's a standalone multi-word location - don't create an author entry
                            return []
                    
                    # Pattern-based fallback for common location formats
                    # This catches cases where geopy/LLM might not recognize it but it's clearly a location
                    
                    # Pattern 1: Location with connector (e.g., "Rio de Janeiro", "Frankfurt am Main")
                    if (has_location_connector or has_arabic_location_pattern) and len(words) >= 3:
                        # Check if first and last words are capitalized (city names)
                        if words[0][0].isupper() and words[-1][0].isupper():
                            # Likely a location - filter it out
                            return []
                    
                    # Pattern 2: Location with keyword (e.g., "Yosemite Valley", "nördlicher Gazastreifen")
                    if has_location_keyword:
                        # Likely a location description - filter it out
                        return []
                    
                    # Pattern 3: Two-word capitalized strings that are common city names
                    # Common pattern: "City Name" where both are capitalized
                    # CRITICAL: Filter well-known city patterns, but let STEP 3 LLM handle ambiguous cases
                    if len(words) == 2 and first_word_capitalized and words[1][0].isupper():
                        # Known city patterns: first word is a common location word
                        # These are well-known cities, so filter them even if is_location() doesn't confirm
                        common_location_starters = ['new', 'tel', 'san', 'rio', 'são', 'sao', 'las', 'les', 'phnom', 'kiryat']
                        is_common_location_starter = words[0].lower() in common_location_starters
                        
                        # For well-known city patterns, filter them (they're almost always locations)
                        if is_common_location_starter:
                            # Well-known city pattern - filter it out
                            return []
                        
                        # For other two-word capitalized strings:
                        # Only filter if is_location() confirms it - don't filter ambiguous cases
                        # Let STEP 3 LLM handle ambiguous cases for better accuracy
                        if is_location_confirmed:
                            # Confirmed location - filter it out
                            return []
                        # Otherwise, let it reach STEP 3 for LLM classification
                        
                        # Also check if both words are longer (locations often have longer names)
                        # But avoid filtering names - only if it really looks like a location
                        word1_len = len(words[0])
                        word2_len = len(words[1])
                        if word1_len > 5 and word2_len > 3:
                            # Could be a location - but be conservative, let STEP 3 LLM decide
                            pass
        
        # Try LLM parsing first (most accurate)
        if self.llm_classifier and self.llm_classifier.use_llm:
            try:
                result = self.llm_classifier.classify_term(author_string)
                names = result.get('names', [])
                locations = result.get('locations', [])
                departments = result.get('departments', [])
                
                # CRITICAL: Check if entire string is a standalone location BEFORE processing LLM results
                # This prevents LLM from incorrectly parsing locations as names
                if len(author_string.split()) == 1:
                    author_string_lower = author_string.lower()
                    # Heuristic: If it's a capitalized single word (>=3 chars), it might be a location
                    if author_string[0].isupper() and len(author_string) >= 3:
                        # Skip if it's a known department
                        if author_string_lower in self.KNOWN_DEPARTMENTS or 'redaktion' in author_string_lower or author_string_lower == 'nzz':
                            pass  # Not a location, continue parsing
                        else:
                            # Check with is_location first
                            if self.is_location(author_string, context=author_string):
                                # It's a standalone location - don't create an author entry
                                return []
                            # Heuristic fallback: if it's capitalized, not a department, and doesn't look like a name
                            if not self._looks_like_name(author_string):
                                # It's likely a standalone location - don't create an author entry
                                return []
                
                # If LLM found names, create ParsedAuthor objects for each
                if names:
                    # CRITICAL: Validate that locations/departments actually appear in the original string
                    # The LLM should not make up locations/departments that aren't in the input
                    author_string_lower = author_string.lower()
                    
                    # Filter locations - only keep those that appear in the original string
                    validated_locations = []
                    for loc in locations:
                        loc_lower = loc.lower().strip()
                        # Check if location appears in original string (allowing for case differences)
                        if loc_lower in author_string_lower or any(word in author_string_lower for word in loc_lower.split()):
                            # CRITICAL: Don't allow multi-word strings that are clearly names to be locations
                            # If location is multi-word and matches a name exactly, it's a false positive
                            if len(loc.split()) > 1:
                                # Multi-word location - check if it matches any name exactly
                                is_name_match = any(name.lower() == loc_lower for name in names)
                                if is_name_match:
                                    # This is a name, not a location - skip it
                                    continue
                            # Additional check: don't allow the name itself to be a location
                            # If location matches a name, it's likely a false positive
                            is_name_match = any(name.lower() == loc_lower or loc_lower in name.lower() or name.lower() in loc_lower for name in names)
                            if not is_name_match:
                                validated_locations.append(loc)
                    
                    # Filter departments - only keep those that appear in the original string
                    validated_departments = []
                    for dept in departments:
                        dept_lower = dept.lower().strip()
                        # Check if department appears in original string
                        if dept_lower in author_string_lower or any(word in author_string_lower for word in dept_lower.split()):
                            # CRITICAL: Don't allow names to be classified as departments
                            # If department matches a name, it's likely a false positive
                            is_name_match = any(name.lower() == dept_lower or dept_lower in name.lower() or name.lower() in dept_lower for name in names)
                            if not is_name_match:
                                validated_departments.append(dept)
                    
                    locations = validated_locations
                    departments = validated_departments
                    
                    # Filter out locations from names (sometimes LLM puts locations in names array)
                    # CRITICAL: Also filter out names that don't appear in the original string
                    filtered_names = []
                    for name in names:
                        name_lower = name.lower().strip()
                        # CRITICAL: Only keep names that actually appear in the original string
                        # Check if name (or its parts) appear in original string
                        name_words = name_lower.split()
                        appears_in_original = any(word in author_string_lower for word in name_words) or name_lower in author_string_lower
                        
                        if not appears_in_original:
                            # Name doesn't appear in original - LLM made it up, skip it
                            logger.debug(f"Filtering out name '{name}' - not found in original string '{author_string}'")
                            continue
                        
                        # CRITICAL: Don't filter out names that are multi-word (like "Johannes C. Bockenheimer")
                        # These are clearly names, even if LLM also put them in locations
                        # Only filter single-word names that are locations
                        if len(name.split()) == 1:
                            # Skip if it's a known department
                            if name_lower in self.KNOWN_DEPARTMENTS or 'redaktion' in name_lower or name_lower == 'nzz':
                                if name not in departments:
                                    departments.append(name)
                                continue
                            # Quick check: if it's a location, move it (using logic-based detection)
                            if self.is_location(name, context=author_string):
                                if name not in locations:
                                    locations.append(name)
                                continue
                            # If it's a single word and looks like a location, check with is_location
                            if self.is_location(name, context=author_string):
                                # Double-check: if it matches a name pattern, it's likely a name
                                if not (name[0].isupper() and len(name) > 2):  # Common name pattern
                                    if name not in locations:
                                        locations.append(name)
                                    continue
                        else:
                            # Multi-word name - check if it's a known department
                            if name_lower in self.KNOWN_DEPARTMENTS or 'redaktion' in name_lower or name_lower == 'nzz':
                                if name not in departments:
                                    departments.append(name)
                                continue
                        
                        filtered_names.append(name)
                    
                    names = filtered_names
                    
                    # CRITICAL: If all names were filtered out (LLM returned invalid results), 
                    # fall back to heuristic immediately
                    if not names:
                        logger.debug(f"LLM returned names but all were filtered out for '{author_string}', using heuristic parsing")
                        heuristic_results = self._parse_author_string_heuristic(author_string)
                        if heuristic_results:
                            return heuristic_results
                        # If heuristic also fails, continue to see if we can use locations/departments
                    
                    # Use first location/department for all authors (or distribute if multiple)
                    location = locations[0] if locations else None
                    department = departments[0] if departments else None
                    
                    # Create ParsedAuthor for each name
                    for name in names:
                        # Clean name - remove any location that might be concatenated
                        clean_name = name.strip()
                        name_parts = clean_name.split()
                        
                        # CRITICAL: If this is a 2-word name and the last word is in locations,
                        # it's likely a false positive (last name classified as location)
                        # Only split if the last part appears SEPARATELY in the original string
                        if len(name_parts) >= 2:
                            last_part = name_parts[-1]
                            last_part_lower = last_part.lower()
                            
                            # Check if last part appears as a separate word in original (not just as part of the name)
                            # Split original string by common separators
                            original_parts = [p.strip().lower() for p in re.split(r'[,;]|\s+und\s+|\s+and\s+', author_string, flags=re.IGNORECASE)]
                            
                            # Only treat as location if it appears as a separate part in original
                            appears_separately = any(p == last_part_lower for p in original_parts)
                            
                            # Additional check: if the last part is a common last name pattern (capitalized, >3 chars),
                            # it's likely a name, not a location
                            # Only treat as location if logic confirms it (not just based on capitalization)
                            is_likely_name = (last_part[0].isupper() and len(last_part) > 3 and 
                                            not self.is_location(last_part, context=author_string))
                            
                            if appears_separately and not is_likely_name and self.is_location(last_part, context=author_string):
                                # Remove location from name
                                clean_name = " ".join(name_parts[:-1])
                                if last_part not in locations:
                                    locations.append(last_part)
                                location = last_part  # Use this location for this author
                            else:
                                # Last part is likely part of the name, not a location
                                # Remove it from locations if it was incorrectly added
                                if last_part in locations:
                                    locations.remove(last_part)
                        
                        author = self._parse_name_to_author(clean_name, location, department, author_string)
                        if author:
                            # Final validation: don't allow name to be its own location
                            if author.location:
                                # Check if location matches any part of the name
                                name_parts_lower = [p.lower() for p in author.normalized_name.split()]
                                loc_lower = author.location.lower()
                                if loc_lower in name_parts_lower or author.location.lower() == author.normalized_name.lower():
                                    author.location = None
                            parsed_authors.append(author)
                    
                    # If we successfully parsed names, return them
                    if parsed_authors:
                        return parsed_authors
                
                # If LLM found names but they were all filtered out or invalid, fall back to heuristic
                # This handles cases where LLM returns incorrect results
                if names and not parsed_authors:
                    logger.debug(f"LLM found names but all were filtered out for '{author_string}', using heuristic parsing")
                    heuristic_results = self._parse_author_string_heuristic(author_string)
                    if heuristic_results:
                        return heuristic_results
                
                # CRITICAL: If LLM returned empty results (no names, no locations, no departments),
                # it might be a simple name that LLM failed to parse - try heuristic
                if not names and not locations and not departments:
                    logger.debug(f"LLM returned empty results for '{author_string}', using heuristic parsing")
                    heuristic_results = self._parse_author_string_heuristic(author_string)
                    if heuristic_results:
                        return heuristic_results
                
                # If LLM only found locations/departments but no names, check if they're actually departments
                if not names and (locations or departments):
                    # Check if the whole string is a department (e.g., "NZZ-Redaktion", "NZZ")
                    author_string_lower = author_string.lower().strip()
                    if author_string_lower in self.KNOWN_DEPARTMENTS or 'redaktion' in author_string_lower or author_string_lower == 'nzz':
                        # Create a department-only entry
                        dept = departments[0] if departments else author_string
                        author = ParsedAuthor(
                            first_name="",
                            last_name=dept,
                            department=dept,
                            original_string=author_string
                        )
                        return [author]
                    logger.debug(f"LLM found only locations/departments for '{author_string}', using heuristic parsing")
            except Exception as e:
                logger.debug(f"LLM parsing failed for '{author_string}': {str(e)}, falling back to heuristic parsing")
        
        # Fallback to heuristic parsing if LLM not available, failed, or found no names
        return self._parse_author_string_heuristic(author_string)
    
    def _parse_author_string_heuristic(self, author_string: str) -> List[ParsedAuthor]:
        """Fallback heuristic parsing when LLM is not available or didn't find names."""
        author_string_lower = author_string.lower().strip()
        
        # Check if entire string is a department (e.g., "NZZ-Redaktion", "NZZ", "Visuals")
        if author_string_lower in self.KNOWN_DEPARTMENTS or 'redaktion' in author_string_lower or author_string_lower == 'nzz':
            author = ParsedAuthor(
                first_name="",
                last_name=author_string,
                department=author_string,
                original_string=author_string
            )
            return [author]
        
        # STEP 1: Check for comma-separated "Name, Location" format BEFORE other parsing
        # Pattern: "Name, Location" or "Name, Location1 und Location2"
        if ',' in author_string:
            # First check for "und" / "and" separator for multiple locations
            if ' und ' in author_string.lower() or ' and ' in author_string.lower():
                # Pattern: "Name, Location1 und Location2"
                comma_parts = [p.strip() for p in author_string.split(',', 1)]
                if len(comma_parts) == 2:
                    name_part, locations_part = comma_parts
                    if name_part and locations_part:
                        # Split locations by "und" / "and"
                        location_list = re.split(r'\s+und\s+|\s+and\s+', locations_part, flags=re.IGNORECASE)
                        location_list = [loc.strip() for loc in location_list if loc.strip()]
                        
                        # Check if name_part looks like a name
                        name_words = name_part.split()
                        name_looks_valid = len(name_words) >= 2 and all(w[0].isupper() if w else False for w in name_words[:2])
                        
                        if name_looks_valid and location_list:
                            # Validate locations - ensure they're actually locations, not names
                            validated_locations = []
                            for loc in location_list:
                                # Check if location is actually a location (not a name)
                                if self.is_location(loc, context=author_string):
                                    validated_locations.append(loc)
                                # Also check if it's not the name itself
                                elif loc.lower() not in name_part.lower():
                                    # Heuristic: if capitalized and >=3 chars, might be a location
                                    if loc[0].isupper() and len(loc) >= 3:
                                        validated_locations.append(loc)
                            
                            # Use first validated location (primary location)
                            if validated_locations:
                                primary_location = validated_locations[0]
                                author = self._parse_name_to_author(name_part, primary_location, None, author_string)
                                if author:
                                    return [author]
            
            # Standard "Name, Location" format (single comma, no "und")
            if author_string.count(',') == 1:
                parts = [p.strip() for p in author_string.split(',', 1)]
                if len(parts) == 2:
                    name_part, location_part = parts
                    if location_part and name_part:
                        # Check if name_part looks like a name (2+ words, capitalized)
                        name_words = name_part.split()
                        name_looks_valid = len(name_words) >= 2 and all(w[0].isupper() if w else False for w in name_words[:2])
                        
                        if name_looks_valid:
                            # For multi-word locations like "New York"
                            if len(location_part.split()) > 1:
                                words = location_part.split()
                                if all(w[0].isupper() for w in words):
                                    # Likely a location - use logic to confirm
                                    if self.is_location(location_part, context=author_string):
                                        author = self._parse_name_to_author(name_part, location_part, None, author_string)
                                        if author:
                                            return [author]
                                # Heuristic fallback: if both words capitalized and not a department, treat as location
                                elif not self.is_department(location_part, context=author_string):
                                    author = self._parse_name_to_author(name_part, location_part, None, author_string)
                                    if author:
                                        return [author]
                        else:
                            # Single word after comma - if capitalized and >3 chars, likely a location
                            # Use logic-based detection to confirm
                            if location_part[0].isupper() and len(location_part) >= 3:
                                # Check with logic-based detection
                                if self.is_location(location_part, context=author_string):
                                    author = self._parse_name_to_author(name_part, location_part, None, author_string)
                                    if author:
                                        return [author]
                                # If logic doesn't confirm but it looks like a location (capitalized city name),
                                # and name_part is clearly a name, still split it (heuristic fallback)
                                # This handles cases where geopy/LLM might miss obvious locations
                                elif not self.is_department(location_part, context=author_string):
                                    # Not a department, and looks like a location - split it
                                    author = self._parse_name_to_author(name_part, location_part, None, author_string)
                                    if author:
                                        return [author]
        
        # STEP 2: Check if entire string is a standalone location (single OR multi-word)
        # NOTE: Return empty list - standalone locations shouldn't create author entries
        words = author_string.split()
        if len(words) == 1:
            if self.is_location(author_string, context=author_string):
                # It's a standalone location - don't create an author entry
                return []
        elif len(words) >= 2:
            # Check if it's a multi-word location (e.g., "Rio de Janeiro", "Frankfurt am Main")
            # BUT exclude names with prefixes (e.g., "Michael von Ledebur", "Hans ten Doornkaat")
            
            # First, check if it's a name with a prefix - if so, skip location check
            # Check for common name prefixes in middle position
            is_name_with_prefix = False
            if len(words) == 3:
                # Check if middle word is a name prefix
                if words[1].lower() in self.NAME_PREFIXES:
                    is_name_with_prefix = True
            
            if not is_name_with_prefix:
                # Check if first word is capitalized (locations usually start with capital)
                # Also check for common location patterns like "X de Y", "X am Y", "X on Y"
                # Note: Exclude "von" from location connectors to avoid false positives
                first_word_capitalized = words[0][0].isupper() if words[0] else False
                has_location_connector = any(connector in author_string.lower() for connector in [' de ', ' am ', ' on ', ' in ', ' bei ', ' an '])
                
                # If it looks like a location pattern or first word is capitalized, check if it's a location
                if first_word_capitalized or has_location_connector:
                    if self.is_location(author_string, context=author_string):
                        # It's a standalone multi-word location - don't create an author entry
                        return []
                    # Also check if it matches known location patterns (e.g., "City de/am/on Location")
                    # This catches cases where geopy might not recognize it but it's clearly a location
                    if has_location_connector and len(words) >= 3:
                        # Pattern like "Rio de Janeiro", "Frankfurt am Main"
                        # Check if first and last words are capitalized (city names)
                        if words[0][0].isupper() and words[-1][0].isupper():
                            # Likely a location - filter it out
                            return []
        
        # STEP 3: Handle simple name patterns BEFORE complex parsing
        # This catches common cases that LLM might miss
        
        # Pattern 1: Three-word names (First Middle Last) - common pattern
        # Examples: "Leonie Charlotte Wagner", "Marc Felix Serrao", "Ingrid Meissl Årebo"
        if len(words) == 3:
            # Check if it looks like a name (all words capitalized, alphabetic or with Unicode)
            all_capitalized = all(w[0].isupper() if w else False for w in words)
            # Allow Unicode characters (like Å, ä, ö, ü) in names
            all_alpha_like = all(
                any(c.isalpha() for c in w.replace('-', '').replace("'", ''))  # Has at least one letter
                for w in words
            )
            
            if all_capitalized and all_alpha_like:
                # Check if middle word is NOT a location
                # But be conservative: if it's a three-word capitalized string, it's more likely a name
                # Only skip if middle word is clearly a location keyword
                middle_word = words[1]
                location_keywords = ['valley', 'city', 'town', 'street', 'gazastreifen', 'gaza', 'de', 'am', 'al-']
                is_location_keyword = any(kw in middle_word.lower() for kw in location_keywords)
                
                # Check with is_location, but don't trust it blindly for middle words
                # Middle words in three-word names are often names, not locations
                is_middle_location = self.is_location(middle_word, context=author_string) if not is_location_keyword else True
                
                # Only skip if it's clearly a location keyword, otherwise treat as name
                if not is_location_keyword:
                    # Treat as First Middle Last
                    author = self._parse_name_to_author(author_string, None, None, author_string)
                    if author:
                        return [author]
        
        # Pattern 2: Names with prefix in middle (e.g., "Michael von Ledebur", "Gioia da Silva")
        # Check if a prefix appears in the middle of a 3-word string
        if len(words) == 3 and words[1].lower() in self.NAME_PREFIXES:
            # This is "First prefix Last" pattern (e.g., "First von Last", "First da Last")
            author = self._parse_name_to_author(author_string, None, None, author_string)
            if author:
                return [author]
        
        # Pattern 3: Names with middle initial (e.g., "Richard C. Schneider")
        # Check if middle word is a single letter with period
        if len(words) == 3:
            middle_word = words[1]
            if len(middle_word) == 2 and middle_word[0].isupper() and middle_word[1] == '.':
                # This is "First M. Last" pattern
                author = self._parse_name_to_author(author_string, None, None, author_string)
                if author:
                    return [author]
        
        # Pattern 4: Four+ word names (e.g., "Christine Le Pape Racine")
        # Handle 4+ word names that might have prefixes or multiple middle names
        if len(words) >= 4:
            # Check if it contains prefixes
            has_prefix = any(w.lower() in self.NAME_PREFIXES for w in words[1:-1])
            # Check if it looks like a name (all words capitalized, mostly alphabetic)
            looks_like_name = all(w[0].isupper() and w.replace('-', '').replace("'", '').isalpha() for w in words)
            
            if has_prefix or looks_like_name:
                # Likely a name - parse it
                # For 4-word names, treat as First Middle1 Middle2 Last or First Prefix Middle Last
                author = self._parse_name_to_author(author_string, None, None, author_string)
                if author:
                    return [author]
        
        # Special handling for "Von" prefix at the start (e.g., "Von Tom Felber")
        if author_string.strip().startswith('Von ') or author_string.strip().startswith('von '):
            # Remove "Von" prefix and parse the rest
            name_without_von = author_string.replace('Von ', '', 1).replace('von ', '', 1).strip()
            if name_without_von:
                # Parse as a simple name
                name_parts = name_without_von.split()
                if len(name_parts) >= 2:
                    author = self._parse_name_to_author(name_without_von, None, None, author_string)
                    if author:
                        return [author]
        
        # Split by common separators
        parts = self._smart_split(author_string)
        
        # If only one part and it looks like a simple name (2 words, both capitalized), parse it directly
        if len(parts) == 1:
            part = parts[0].strip()
            # Check if it's a department first
            if part.lower() in self.KNOWN_DEPARTMENTS or 'redaktion' in part.lower():
                author = ParsedAuthor(
                    first_name="",
                    last_name=part,
                    department=part,
                    original_string=author_string
                )
                return [author]
            name_words = part.split()
            # Handle simple 2-word names (most common case)
            if len(name_words) == 2:
                # Check if both words are capitalized (name pattern)
                if all(w[0].isupper() if w else False for w in name_words):
                    # Simple "First Last" format - parse it
                    author = self._parse_name_to_author(part, None, None, author_string)
                    if author:
                        return [author]
        
        parsed_authors = []
        current_location = None
        current_department = None
        current_name_parts = []
        
        i = 0
        while i < len(parts):
            part = parts[i].strip()
            if not part:
                i += 1
                continue
            
            # Check if part contains a comma - might be "Name, Location" format
            # This should have been handled earlier, but check again in case we're in the loop
            if ',' in part and part.count(',') == 1:
                name_part, location_part = [p.strip() for p in part.split(',', 1)]
                # If name part looks like a name and location part looks like a location
                if name_part and location_part:
                    name_words = name_part.split()
                    # Check if location_part is actually a location
                    if self.is_location(location_part, context=author_string):
                        # This is "Name, Location" format
                        author = self._parse_name_to_author(name_part, location_part, current_department, author_string)
                        if author:
                            parsed_authors.append(author)
                        current_name_parts = []
                        current_location = None
                        i += 1
                        continue
            
            # Check if it's a department FIRST (departments are more specific)
            part_lower = part.lower().strip()
            is_dept = False
            # Check known departments
            if part_lower in self.KNOWN_DEPARTMENTS or 'redaktion' in part_lower or part_lower == 'nzz':
                is_dept = True
            else:
                # Use LLM/department check
                is_dept = self.is_department(part, context=author_string)
            
            if is_dept:
                if current_name_parts:
                    author = self._build_author(current_name_parts, current_location, current_department)
                    if author:
                        parsed_authors.append(author)
                    current_name_parts = []
                current_department = part
                i += 1
                continue
            
            # Check if it's a location (but be less aggressive - only if clearly a location)
            is_loc = False
            # Single word is more likely to be a location, but check carefully
            if len(part.split()) == 1:
                # Don't classify if it's part of a name we're building
                if current_name_parts:
                    # If we're building a name, this is likely part of the name, not a location
                    # Only check if logic confirms it's a location
                    is_loc = self.is_location(part, context=author_string)
                else:
                    # Use logic-based location detection (LLM/geopy)
                    is_loc = self.is_location(part, context=author_string)
            # Also check if it's a multi-word location (e.g., "New York")
            elif len(part.split()) == 2:
                # Check if both words are capitalized (might be location or name)
                words = part.split()
                if all(w[0].isupper() for w in words):
                    # Use logic-based detection to confirm it's a location
                    if self.is_location(part, context=author_string):
                        is_loc = True
            
            if is_loc:
                if current_name_parts:
                    author = self._build_author(current_name_parts, current_location, current_department)
                    if author:
                        parsed_authors.append(author)
                    current_name_parts = []
                current_location = part
                i += 1
                continue
            
            # Check if it's a name prefix (von, van, de, etc.)
            # Special handling for "Von" at the start (e.g., "Von Tom Felber")
            if part.lower() in self.NAME_PREFIXES:
                # If "Von" is at the start and we have no name parts yet, it's likely a prefix
                if part.lower() == 'von' and not current_name_parts and i == 0:
                    # "Von" at start - treat as prefix, skip it and treat next part as first name
                    if i + 1 < len(parts):
                        next_part = parts[i + 1].strip()
                        # If there's a third part, combine next two as "First Last"
                        if i + 2 < len(parts):
                            third_part = parts[i + 2].strip()
                            current_name_parts.append(f"{next_part} {third_part}")
                            i += 3  # Skip "Von", first, and last
                        else:
                            current_name_parts.append(next_part)
                            i += 2  # Skip both "Von" and next part
                        continue
                    else:
                        # No next part, just add "Von"
                        current_name_parts.append(part)
                        i += 1
                        continue
                # Otherwise, if we have name parts, it's a prefix
                elif current_name_parts:
                    current_name_parts.append(part)
                    i += 1
                    continue
                # If no name parts and not at start, might be ambiguous - treat as name part
                else:
                    current_name_parts.append(part)
                    i += 1
                    continue
            
            # If it looks like a name (especially if it has 2+ words with capitals), treat as name
            if self._looks_like_name(part) or (len(part.split()) >= 2 and all(w[0].isupper() if w else False for w in part.split()[:2])):
                current_name_parts.append(part)
                i += 1
                continue
            
            # Ambiguous case - if we have name parts, continue building
            if current_name_parts:
                # Check if next part looks like a name
                if i + 1 < len(parts) and (self._looks_like_name(parts[i + 1].strip()) or len(parts[i + 1].strip().split()) >= 2):
                    # Likely start of new author
                    author = self._build_author(current_name_parts, current_location, current_department)
                    if author:
                        parsed_authors.append(author)
                    current_name_parts = [part]
                else:
                    current_name_parts.append(part)
            else:
                # Start new name
                current_name_parts.append(part)
            
            i += 1
        
        # Finish last author
        if current_name_parts:
            author = self._build_author(current_name_parts, current_location, current_department)
            if author:
                parsed_authors.append(author)
        
        return parsed_authors
    
    def _parse_name_to_author(self, name: str, location: Optional[str], 
                              department: Optional[str], original_string: str) -> Optional[ParsedAuthor]:
        """Parse a name string into a ParsedAuthor object.
        
        Args:
            name: Name string (e.g., "Andreas Scheiner", "Daniel Böhm")
            location: Optional location
            department: Optional department
            original_string: Original author string for reference
            
        Returns:
            ParsedAuthor or None if invalid
        """
        if not name or not name.strip():
            return None
        
        # Remove "Von" prefix if present at the start
        name = name.strip()
        if name.startswith('Von ') or name.startswith('von '):
            name = name.replace('Von ', '', 1).replace('von ', '', 1).strip()
        
        # Split name into parts
        name_parts = name.strip().split()
        
        if not name_parts:
            return None
        
        # Handle different name formats
        first_name = name_parts[0]
        middle_name = None
        last_name = None
        
        if len(name_parts) == 1:
            # Single name - treat as last name
            last_name = name_parts[0]
            first_name = ""
        elif len(name_parts) == 2:
            first_name = name_parts[0]
            last_name = name_parts[1]
        elif len(name_parts) == 3:
            first_name = name_parts[0]
            # Check if middle part is a prefix
            if name_parts[1].lower() in self.NAME_PREFIXES:
                last_name = f"{name_parts[1]} {name_parts[2]}"
            # Check if middle part is a middle initial (single letter with period, e.g., "C.")
            elif len(name_parts[1]) == 2 and name_parts[1][0].isupper() and name_parts[1][1] == '.':
                middle_name = name_parts[1]
                last_name = name_parts[2]
            else:
                middle_name = name_parts[1]
                last_name = name_parts[2]
        else:
            # More than 3 parts
            first_name = name_parts[0]
            # Look for middle initial first (single letter with period)
            middle_initial_idx = None
            for i, part in enumerate(name_parts[1:-1], 1):  # Check all except first and last
                if len(part) == 2 and part[0].isupper() and part[1] == '.':
                    middle_initial_idx = i
                    break
            
            # Look for prefix
            prefix_idx = None
            for i, part in enumerate(name_parts[1:], 1):
                if part.lower() in self.NAME_PREFIXES:
                    prefix_idx = i
                    break
            
            if middle_initial_idx:
                # Middle initial found - treat it as middle_name
                middle_name = name_parts[middle_initial_idx]
                last_name = name_parts[-1]
                if middle_initial_idx > 1:
                    # There are other parts before the initial - could be additional middle names
                    # For now, just use the initial
                    pass
            elif prefix_idx:
                last_name = " ".join(name_parts[prefix_idx:])
                if prefix_idx > 1:
                    middle_name = " ".join(name_parts[1:prefix_idx])
            else:
                last_name = name_parts[-1]
                if len(name_parts) > 2:
                    middle_name = " ".join(name_parts[1:-1])
        
        if not last_name:
            return None
        
        # Validate location - don't allow name parts to be locations
        validated_location = location
        if location:
            location_lower = location.lower().strip()
            name_parts_lower = [p.lower() for p in name_parts]
            # Check if location is actually part of the name
            if location_lower in name_parts_lower:
                validated_location = None  # Location is part of the name, not a separate location
            # Also check if location appears separately in original string
            elif location_lower not in original_string.lower():
                validated_location = None  # Location doesn't appear in original string
            else:
                # Check if location appears as a separate word (not just as substring of name)
                original_lower = original_string.lower()
                # Split original by common separators
                original_parts = [p.strip().lower() for p in re.split(r'[,;]|\s+und\s+|\s+and\s+', original_string, flags=re.IGNORECASE)]
                if location_lower not in original_parts:
                    # Location might be concatenated with name, check more carefully
                    # If name ends with location, it's likely concatenated
                    normalized_lower = f"{first_name} {last_name}".lower().strip()
                    if normalized_lower.endswith(' ' + location_lower) or normalized_lower.endswith(location_lower):
                        validated_location = None  # Location is concatenated with name
        
        return ParsedAuthor(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            middle_name=middle_name.strip() if middle_name else None,
            location=validated_location,
            department=department,
            original_string=original_string
        )
    
    def _smart_split(self, text: str) -> List[str]:
        """Split text intelligently, preserving structure.
        
        Args:
            text: Text to split
            
        Returns:
            List of parts
        """
        # Split by comma, semicolon, "und", "and" (case-insensitive)
        # But be careful with "von" and other name prefixes
        parts = re.split(r'[,;]|\s+und\s+|\s+and\s+', text, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]
    
    def _looks_like_name(self, term: str) -> bool:
        """Check if a term looks like a name part.
        
        Args:
            term: Term to check
            
        Returns:
            True if it looks like a name (not a location)
        """
        if not term:
            return False
        
        # Single letter (like "J.") is likely a middle initial
        if len(term) == 1 or (len(term) == 2 and term.endswith('.')):
            return True
        
        # Check if it's all caps (likely abbreviation or department)
        if term.isupper() and len(term) > 2:
            return False
        
        # CRITICAL: If it's a single capitalized word, check if it's a location first
        # Common city names should not be considered as names
        if len(term.split()) == 1 and term[0].isupper() and len(term) >= 3:
            # Check if it's a known location (using is_location)
            # This prevents city names from being treated as names
            if self.is_location(term, context=term):
                return False  # It's a location, not a name
            # Heuristic: If it's a capitalized single word and not a common name pattern,
            # it's likely a location (city name) rather than a name
            term_lower = term.lower()
            if term_lower not in self.KNOWN_DEPARTMENTS and 'redaktion' not in term_lower and term_lower != 'nzz':
                # If it doesn't match common name patterns, it's likely a location
                if len(term) >= 5 or (len(term) >= 3 and not self._is_common_name(term)):
                    return False  # Likely a location, not a name
        
        # Check if it contains only letters, hyphens, apostrophes, and dots
        if re.match(r'^[A-ZÄÖÜa-zäöüß\-\'\.]+$', term):
            # Must start with capital letter
            if term[0].isupper() or term[0].islower():
                return True
        
        return False
    
    def _is_common_name(self, term: str) -> bool:
        """Check if a term is a common first or last name pattern.
        
        Args:
            term: Term to check
            
        Returns:
            True if it looks like a common name
        """
        if not term or len(term) < 2:
            return False
        
        term_lower = term.lower()
        # Very common first/last names (short list for performance)
        # This is a small heuristic list - not comprehensive, just for filtering obvious city names
        common_names = {
            'max', 'tom', 'tim', 'jan', 'leo', 'noa', 'luk', 'ben', 'sam', 'dan',
            'müller', 'schmidt', 'schneider', 'fischer', 'weber', 'meyer', 'wagner', 'becker',
            'schulz', 'hoffmann', 'schäfer', 'koch', 'bauer', 'richter', 'klein', 'wolf'
        }
        
        # Known city names that should NOT be treated as common names
        # These are common city names that are short (3-4 chars) and might be mistaken for names
        known_cities = {'rom', 'bern', 'biel', 'wien', 'paris', 'berlin', 'london', 'tokio', 'milan', 'kiew'}
        
        # If it's a known city, it's not a common name
        if term_lower in known_cities:
            return False
        
        # Check if it's a common name
        if term_lower in common_names:
            return True
        
        # Very short names (2 chars) are more likely to be names than locations
        # But 3-4 char names could be cities, so be more careful
        if len(term) == 2:
            return True
        
        return False
    
    def _build_author(self, name_parts: List[str], location: Optional[str], 
                     department: Optional[str]) -> Optional[ParsedAuthor]:
        """Build a ParsedAuthor from name parts.
        
        Args:
            name_parts: List of name parts
            location: Location string (if any)
            department: Department string (if any)
            
        Returns:
            ParsedAuthor or None if invalid
        """
        if not name_parts:
            return None
        
        # Filter out empty parts
        name_parts = [p for p in name_parts if p.strip()]
        
        if not name_parts:
            return None
        
        # Handle different name formats
        # Format 1: "First Last"
        # Format 2: "First Middle Last"
        # Format 3: "First von Last" (with prefix)
        # Format 4: "First M. Last" (with middle initial)
        
        first_name = name_parts[0]
        middle_name = None
        last_name = None
        
        # Check for middle initial (single letter with period) in name parts
        middle_initial_idx = None
        for i, part in enumerate(name_parts[1:-1] if len(name_parts) > 2 else [], 1):
            if len(part) == 2 and part[0].isupper() and part[1] == '.':
                middle_initial_idx = i
                break
        
        if len(name_parts) == 1:
            # Single name - could be first or last
            # If it's capitalized and looks like a name, treat as last name
            if self._looks_like_name(name_parts[0]):
                last_name = name_parts[0]
                first_name = ""  # Unknown first name
            else:
                return None  # Invalid
        elif len(name_parts) == 2:
            first_name = name_parts[0]
            last_name = name_parts[1]
        elif len(name_parts) == 3:
            first_name = name_parts[0]
            # Check if middle part is a prefix
            if name_parts[1].lower() in self.NAME_PREFIXES:
                last_name = f"{name_parts[1]} {name_parts[2]}"
            # Check if middle part is a middle initial (single letter with period, e.g., "C.")
            elif len(name_parts[1]) == 2 and name_parts[1][0].isupper() and name_parts[1][1] == '.':
                middle_name = name_parts[1]
                last_name = name_parts[2]
            else:
                middle_name = name_parts[1]
                last_name = name_parts[2]
        else:
            # More than 3 parts - try to intelligently parse
            first_name = name_parts[0]
            # Look for prefix
            prefix_idx = None
            for i, part in enumerate(name_parts[1:], 1):
                if part.lower() in self.NAME_PREFIXES:
                    prefix_idx = i
                    break
            
            if prefix_idx:
                # Everything after prefix is last name
                last_name = " ".join(name_parts[prefix_idx:])
                if prefix_idx > 1:
                    middle_name = " ".join(name_parts[1:prefix_idx])
            else:
                # Last part is last name, everything in between is middle
                last_name = name_parts[-1]
                if len(name_parts) > 2:
                    middle_name = " ".join(name_parts[1:-1])
        
        if not last_name:
            return None
        
        # Create ParsedAuthor
        author = ParsedAuthor(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            middle_name=middle_name.strip() if middle_name else None,
            location=location,
            department=department,
            original_string=" ".join(name_parts)
        )
        
        return author
    
    def normalize_name(self, author: ParsedAuthor) -> str:
        """Normalize an author name to a standard format.
        
        Args:
            author: ParsedAuthor object
            
        Returns:
            Normalized name string in format "First Middle Last"
        """
        return author.normalized_name
    
    def get_author_key(self, author: ParsedAuthor) -> str:
        """Get a unique key for an author (for deduplication).
        
        Args:
            author: ParsedAuthor object
            
        Returns:
            Unique key string (normalized name, case-insensitive)
        """
        return self.normalize_name(author).lower().strip()


# Example usage and testing
if __name__ == "__main__":
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
    ]
    
    for test in test_cases:
        print(f"\nInput: {test}")
        authors = normalizer.parse_author_string(test)
        for author in authors:
            print(f"  -> {author.normalized_name} (Location: {author.location}, Dept: {author.department})")

