"""NZZ article scraper v2 with enhanced features for related articles and authors."""

import os
import time
import random
import logging
import re
from queue import Queue
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import requests
from scraper import NZZScraper, logger
from database import DatabaseManager, Author
from author_normalizer import AuthorNormalizer, ParsedAuthor

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class NZZScraperV2(NZZScraper):
    """Enhanced NZZ scraper v2 with support for related articles and authors."""

    def __init__(
        self,
        base_url="https://www.nzz.ch",
        articles_url="https://www.nzz.ch/neueste-artikel?page=2000",
    ):
        """Initialize the scraper v2.

        Args:
            base_url: Base URL for NZZ website
            articles_url: URL for articles list page (default uses page=2000 parameter)
        """
        super().__init__(base_url, articles_url)

        # Override number of worker threads for article scraping (increase to 20)
        self.num_worker_threads = 20  # Number of parallel article scraping threads

        # Verify database path is in NZZ folder
        db_path = self.db.db_path
        db_dir = os.path.dirname(db_path)
        expected_dir = SCRIPT_DIR

        # Normalize paths for comparison
        db_dir = os.path.normpath(db_dir)
        expected_dir = os.path.normpath(expected_dir)

        if db_dir != expected_dir:
            logger.warning(f"Database path is not in expected NZZ folder!")
            logger.warning(f"Expected: {expected_dir}")
            logger.warning(f"Actual: {db_dir}")
            logger.warning(f"Database file: {db_path}")
        else:
            logger.info(f"Database is correctly located in NZZ folder: {db_path}")
        self.author_queue = Queue()  # Queue for author profiles to be scraped
        self.related_articles_queue = (
            Queue()
        )  # Queue for related articles to be scraped
        self.impressum_url = "https://www.nzz.ch/information/impressum-ld.148422"

        # Initialize author normalizer for comprehensive name parsing and normalization
        # Uses LLM via Ollama (primary) and geopy (fallback) for location detection
        # Ollama model name can be set via OLLAMA_MODEL environment variable (default: "gemma3:270m")
        llm_model_name = os.getenv("OLLAMA_MODEL", "gemma3:270m")
        self.author_normalizer = AuthorNormalizer(
            use_geopy=True, use_llm=True, llm_model_name=llm_model_name
        )
        self.currently_employed_authors = (
            set()
        )  # Cache of currently employed author names

        # Threading for parallel author processing
        import threading

        self.author_scraping_threads = []  # List of threads for author scraping
        self.author_scraping_active = False  # Flag to control author scraping threads
        self.num_author_worker_threads = 6  # Number of parallel author scraping threads

        # Note: _load_impressum_authors() will be called in run() method before article scraping
        # We don't call it here to avoid loading twice

    def _extract_related_articles(
        self, soup: BeautifulSoup, article_id: str
    ) -> List[Dict]:
        """Extract related articles from article page.

        Based on HTML structure:
        <div class="mx-auto max-w-[640px]..." data-team-more-to-subject="">
            <article>...</article>
        </div>

        Args:
            soup: BeautifulSoup object of the article page
            article_id: The ID of the current article

        Returns:
            List of dictionaries with 'id', 'url', and 'title' keys for related articles
        """
        related_articles = []
        seen_urls = set()
        seen_ids = set()

        # Look for container with data-team-more-to-subject attribute
        related_containers = soup.find_all(
            ["div", "section"], {"data-team-more-to-subject": True}
        )

        # Also look for divs with class containing "max-w-[640px]" which often contain related articles
        related_containers.extend(
            soup.find_all("div", {"class": lambda x: x and "max-w-[640px]" in str(x)})
        )

        for container in related_containers:
            # Find all article elements within the container
            article_elements = container.find_all("article")

            for article_elem in article_elements:
                # Find link inside article
                link = article_elem.find("a", href=True)
                if not link:
                    continue

                href = link.get("href", "")
                if not href:
                    continue

                url = self._make_absolute_url(href)

                # Skip if already seen
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Extract article ID
                related_id = self._extract_id_from_url(url)
                if not related_id:
                    continue

                # Skip if duplicate ID or same as current article
                if related_id in seen_ids or related_id == article_id:
                    continue
                seen_ids.add(related_id)

                # Extract title - look for chartbeat-teaser-title or h2
                title = None
                title_elem = article_elem.find(
                    "span", class_=lambda x: x and "chartbeat-teaser-title" in str(x)
                )
                if title_elem:
                    title = title_elem.get_text(strip=True)

                if not title:
                    title_elem = article_elem.find(["h1", "h2", "h3"])
                    if title_elem:
                        title = title_elem.get_text(strip=True)

                if not title:
                    title = link.get_text(strip=True)

                # Extract date if available (for 1 year limit check)
                related_date = None
                time_elem = article_elem.find("time", {"datetime": True})
                if time_elem:
                    datetime_attr = time_elem.get("datetime")
                    if datetime_attr:
                        try:
                            # Try ISO format first
                            related_date = datetime.fromisoformat(
                                datetime_attr.replace("Z", "+00:00")
                            )
                        except:
                            try:
                                # Fallback to dateutil parser if available
                                from dateutil import parser

                                related_date = parser.parse(datetime_attr)
                            except:
                                pass

                if title:
                    related_articles.append(
                        {
                            "id": related_id,
                            "url": url,
                            "title": title,
                            "date": related_date,  # May be None if not found
                        }
                    )

        return related_articles

    def _load_impressum_authors(self):
        """Load currently employed authors from the impressum page, scrape their profiles, and save them to database.

        This method is called in STEP 1 (before article scraping) and:
        1. Scrapes the impressum page
        2. Extracts all author names and profile URLs
        3. Scrapes each author profile individually (synchronously, one by one)
        4. Saves all authors to the database with currently_employed=1
        5. Populates self.currently_employed_authors set for later reference

        This ensures all impressum authors are fully scraped and saved to the database
        BEFORE article scraping begins, so we can properly link articles to authors
        and mark them as currently employed during article analysis.
        """
        try:
            logger.info("Loading currently employed authors from impressum page...")
            self.rate_limiter.wait(jitter=True)
            r = self.session.get(self.impressum_url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Extract all text from the page
            text = soup.get_text()

            # Pattern to match author names with abbreviations in parentheses
            # Examples: "Eric Gujer (eg.)", "Rico Bandle (rb.)", "David Signer (dai.)"
            # Also matches names without abbreviations: "Daniel Wechlin (daw.)"
            author_pattern = re.compile(
                r"([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)\s*\(([a-zäöüß]{1,4}\.)\)",
                re.IGNORECASE,
            )

            matches = author_pattern.findall(text)

            # Extract author profile links from impressum page
            author_links = soup.find_all("a", href=re.compile(r"/impressum/.*-ld\.\d+"))
            author_profiles = {}  # Map author names to profile URLs

            for link in author_links:
                href = link.get("href", "")
                if href:
                    url = self._make_absolute_url(href)
                    author_id = self._extract_id_from_url(url)
                    if author_id:
                        # Get author name from link text
                        link_text = link.get_text(strip=True)
                        if link_text:
                            # Fix concatenated names first (e.g., "SydneyBarbara" -> "Sydney, Barbara")
                            link_text = self._fix_concatenated_name(link_text)
                            # Clean the name
                            name_normalized = re.sub(r"\s+", " ", link_text.strip())
                            author_profiles[name_normalized] = {
                                "url": url,
                                "id": author_id,
                                "name": name_normalized,
                            }

            saved_count = 0
            scraped_count = 0

            # First, process authors with profile links (scrape their profiles)
            for name_normalized, profile_info in author_profiles.items():
                try:
                    author_id = profile_info["id"]
                    author_url = profile_info["url"]

                    # Check if author already exists
                    if not self.db.author_exists(author_id=author_id):
                        # Scrape author profile
                        self.rate_limiter.wait(jitter=True)
                        author_data = self.scrape_author_profile(author_url, author_id)

                        if author_data:
                            # Save author with full profile data
                            self.db.save_author(
                                name=author_data["name"],
                                author_id=author_data["id"],
                                author_url=author_data["url"],
                                title=author_data.get("title"),
                                alternate_name=author_data.get("alternate_name"),
                                bio=author_data.get("bio"),
                                image_url=author_data.get("image_url"),
                                currently_employed=1,  # Mark as currently employed
                            )
                            scraped_count += 1
                            saved_count += 1
                        else:
                            # If scraping failed, save basic info
                            self.db.save_author(
                                name=name_normalized,
                                author_id=author_id,
                                author_url=author_url,
                                currently_employed=1,
                            )
                            saved_count += 1
                    else:
                        # Author exists, update currently_employed status
                        session = self.db.Session()
                        try:
                            existing_author = (
                                session.query(Author)
                                .filter_by(author_id=author_id)
                                .first()
                            )
                            if existing_author:
                                existing_author.currently_employed = 1
                                session.commit()
                        finally:
                            session.close()

                    # Add to set
                    self.currently_employed_authors.add(name_normalized)
                except Exception as e:
                    logger.warning(
                        f"Error processing impressum author profile {name_normalized}: {str(e)}"
                    )

            # Then, process authors without profile links (from text pattern matching)
            for name, abbrev in matches:
                # Clean the name
                name = name.strip()
                # Fix concatenated names (e.g., "SydneyBarbara" -> "Sydney, Barbara")
                name = self._fix_concatenated_name(name)
                # Add to set (normalize by removing extra spaces)
                name_normalized = re.sub(r"\s+", " ", name)

                # Skip if already processed (has profile link)
                if name_normalized in author_profiles:
                    continue

                self.currently_employed_authors.add(name_normalized)
                # Also add variations (e.g., "Eric Gujer" and "Eric Gujer (eg.)")
                self.currently_employed_authors.add(f"{name_normalized} ({abbrev})")

                # Save author to database (without ID/URL, but marked as currently employed)
                # Check if author already exists
                if not self.db.author_exists(name=name_normalized):
                    try:
                        # Create author entry with name and alternate_name (abbreviation)
                        # Add name to alias list
                        alias_list = [name_normalized]
                        if name_normalized not in alias_list:
                            alias_list.append(name_normalized)
                        alias_str = ", ".join(alias_list)

                        self.db.save_author(
                            name=name_normalized,
                            author_id=None,
                            author_url=None,
                            alternate_name=abbrev,
                            alias=alias_str,
                            currently_employed=1,  # Mark as currently employed
                        )
                        saved_count += 1
                    except Exception as e:
                        logger.debug(
                            f"Error saving impressum author {name_normalized}: {str(e)}"
                        )
                else:
                    # Update existing author to mark as currently employed
                    existing_author = self.db.get_author_by_name_or_alias(
                        name=name_normalized
                    )
                    if existing_author:
                        # Update alias to include name if not already there
                        alias_list = []
                        if existing_author.alias:
                            alias_list = [
                                a.strip() for a in existing_author.alias.split(",")
                            ]
                        if name_normalized not in alias_list:
                            alias_list.append(name_normalized)
                        alias_str = ", ".join(alias_list)

                        # Update author
                        session = self.db.Session()
                        try:
                            fresh_author = (
                                session.query(Author)
                                .filter_by(name=name_normalized)
                                .first()
                            )
                            if fresh_author:
                                fresh_author.currently_employed = 1
                                fresh_author.alias = alias_str
                                if not fresh_author.alternate_name:
                                    fresh_author.alternate_name = abbrev
                                session.commit()
                        finally:
                            session.close()

            logger.info(
                f"Loaded {len(self.currently_employed_authors)} currently employed authors from impressum, scraped {scraped_count} author profiles, saved {saved_count} authors to database"
            )

        except Exception as e:
            logger.warning(f"Failed to load impressum authors: {str(e)}")
            # Continue without impressum data - will default to not currently employed

    def _is_author_currently_employed(self, author_name: str) -> bool:
        """Check if an author is currently employed based on impressum page.

        Args:
            author_name: The author's name (may include city, e.g., "Andreas Babst, Bangkok")

        Returns:
            bool: True if author is currently employed, False otherwise
        """
        if not self.currently_employed_authors:
            return False

        # Extract base name (before comma if city is present)
        base_name = author_name.split(",")[0].strip()

        # Check exact match
        if (
            author_name in self.currently_employed_authors
            or base_name in self.currently_employed_authors
        ):
            return True

        # Check if any currently employed author name is contained in the given name
        for employed_name in self.currently_employed_authors:
            # Remove abbreviation from employed name for comparison
            employed_base = re.sub(r"\s*\([^)]+\)", "", employed_name).strip()
            if (
                employed_base in author_name
                or author_name in employed_base
                or base_name in employed_base
            ):
                return True

        return False

    def _clean_author_name(self, name: str) -> str:
        """Clean author name by removing parentheses and their contents.

        Args:
            name: Author name string

        Returns:
            Cleaned author name without parentheses and their contents
        """
        import re

        # Remove parentheses and everything inside them
        cleaned = re.sub(r"\([^)]*\)", "", name)
        # Clean up extra spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _fix_concatenated_name(self, name: str) -> str:
        """Fix concatenated author names by adding spaces or commas where needed.

        Detects patterns like "SydneyBarbara" or "BangkokAndreas" and fixes them
        to "Sydney, Barbara" or "Bangkok, Andreas" (or with space if appropriate).

        Args:
            name: Author name string that may contain concatenated parts

        Returns:
            Fixed author name with proper separators
        """
        import re

        # Pattern to detect concatenated names: lowercase letter followed by uppercase letter
        # Examples: "SydneyBarbara", "BangkokAndreas", "ChefredaktorEric"
        # This pattern matches: [a-zäöüß][A-ZÄÖÜ]
        pattern = re.compile(r"([a-zäöüß])([A-ZÄÖÜ])")

        # Replace with space (we'll decide comma vs space based on context)
        fixed = pattern.sub(r"\1 \2", name)

        # Now check if we should use comma instead of space
        # If the first part looks like a location or job title, use comma
        # Common patterns: city names, job titles (Chefredaktor, Stellvertreter, etc.)
        parts = fixed.split(" ")
        if len(parts) >= 2:
            first_part = parts[0]
            # Check if first part is a known location or job title
            # Locations: cities, countries
            # Job titles: Chefredaktor, Stellvertreter, Tagesleitung, etc.
            location_patterns = [
                r"^(Bundeshaus|Westschweiz|Berlin|Paris|London|Rom|Madrid|Wien|Warschau|Frankfurt|Brüssel|Tallinn|Tel Aviv|Moskau|Nairobi|Istanbul|Beirut|Mumbai|Bangkok|Taipeh|Peking|Tokio|Sydney|Washington|Chicago|Bahia|Rio de Janeiro)$",
                r"^(International|Geopolitics|Reisen|Reporter|Social Media|Audience Management|Produktionsredaktion|Art Director|Bildredaktion|Fotografen|Korrespondenten)$",
            ]

            job_title_patterns = [
                r"^(Chefredaktor|Stellvertreter|Tagesleitung|Format|Community|Podcast|Management|Geschichte|Geschichte|NZZ|Folio)$",
            ]

            is_location_or_title = False
            for pattern_list in [location_patterns, job_title_patterns]:
                for pattern in pattern_list:
                    if re.match(pattern, first_part, re.IGNORECASE):
                        is_location_or_title = True
                        break
                if is_location_or_title:
                    break

            if is_location_or_title:
                # Use comma for location/job title + name
                fixed = ", ".join(parts)
            else:
                # Use space for regular name parts
                fixed = " ".join(parts)

        # Clean up any double spaces or commas
        fixed = re.sub(r"\s+", " ", fixed)
        fixed = re.sub(r",\s*,", ",", fixed)
        fixed = fixed.strip()

        return fixed

    def _split_author_names(self, author_text: str) -> List[str]:
        """Split author names by comma, 'und', or semicolon.

        Args:
            author_text: String containing one or more author names

        Returns:
            List of individual author names
        """
        import re

        # Split by comma, semicolon, or "und" (case-insensitive)
        # Use regex to split on these delimiters while preserving the text
        parts = re.split(r"[,;]|\s+und\s+", author_text, flags=re.IGNORECASE)
        # Clean each part and filter out empty strings
        authors = []
        for part in parts:
            cleaned = part.strip()
            if cleaned and len(cleaned) > 1:
                authors.append(cleaned)
        return authors

    def _extract_authors_from_article(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract authors from article page.

        Looks for author links in the format:
        <div class="mr-2 text-sm sm:text-base">
            <span><a href="/impressum/author-name-ld.XXXXX">Author Name</a>, </span>
            <span>Author Name Without Link</span>
        </div>

        Returns authors with links (id, url, name) and authors without links (name only).

        Args:
            soup: BeautifulSoup object of the article page

        Returns:
            List of dictionaries with 'id' (optional), 'url' (optional), and 'name' keys for authors
        """
        authors = []
        seen_urls = set()
        seen_ids = set()
        seen_names = set()  # Track names to avoid duplicates

        # Pattern 1: Look for div with class "mr-2 text-sm sm:text-base" (from user's example)
        author_divs = soup.find_all(
            "div", {"class": lambda x: x and "mr-2" in str(x) and "text-sm" in str(x)}
        )

        # Pattern 2: Look for links to /impressum/ pages anywhere on the page
        impressum_links = soup.find_all("a", href=re.compile(r"/impressum/.*-ld\.\d+"))

        # First, extract authors with links
        all_author_links = []

        for div in author_divs:
            links = div.find_all("a", href=re.compile(r"/impressum/.*-ld\.\d+"))
            all_author_links.extend(links)

        # Add impressum links that aren't already in the list
        for link in impressum_links:
            if link not in all_author_links:
                all_author_links.append(link)

        # Extract authors with links
        for link in all_author_links:
            href = link.get("href", "")
            if not href:
                continue

            url = self._make_absolute_url(href)

            # Skip if already seen
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Extract author ID from URL (pattern: /impressum/name-ld.XXXXX)
            author_id = self._extract_id_from_url(url)
            if not author_id:
                continue

            # Skip if duplicate ID
            if author_id in seen_ids:
                continue
            seen_ids.add(author_id)

            # Extract author name - get FULL text from link (including city if present)
            # Examples: "Andreas Babst, Bangkok" or "Michael Radunski, Berlin"
            # We preserve the full string including city - user will extract cities later
            name = link.get_text(strip=True).rstrip(",").strip()
            if not name:
                continue

            # Fix concatenated names first (e.g., "SydneyBarbara" -> "Sydney, Barbara")
            name = self._fix_concatenated_name(name)

            # Clean parentheses from name
            name = self._clean_author_name(name)
            if not name:
                continue

            # Track by normalized name (without city) to avoid duplicates
            # But preserve the full string including city
            name_parts = name.split(",")
            base_name = name_parts[0].strip().lower() if name_parts else name.lower()
            seen_names.add(base_name)

            authors.append({"id": author_id, "url": url, "name": name})

        # Second, extract authors without links from the same divs
        for div in author_divs:
            # Get all text spans that might contain author names
            spans = div.find_all("span")
            for span in spans:
                # Check if this span contains an author link (already processed)
                if span.find("a", href=re.compile(r"/impressum/.*-ld\.\d+")):
                    continue

                # Get FULL text from span (including city if present)
                # Examples: "Michael Radunski, Berlin" - preserve full string
                text = span.get_text(strip=True).rstrip(",").strip()
                if not text:
                    continue

                # Fix concatenated names first (e.g., "SydneyBarbara" -> "Sydney, Barbara")
                text = self._fix_concatenated_name(text)

                # Clean parentheses from text
                text = self._clean_author_name(text)
                if not text:
                    continue

                # Split by comma, "und", or semicolon to get individual authors
                individual_authors = self._split_author_names(text)
                for author_name in individual_authors:
                    if not author_name or len(author_name) < 2:
                        continue

                    # Check if it looks like an author name (not empty, reasonable length)
                    # Increased max length to accommodate city information
                    if len(author_name) > 200:
                        continue

                    # Extract base name (without city) for duplicate checking
                    # But preserve the full string including city
                    text_parts = author_name.split(",")
                    base_text = (
                        text_parts[0].strip().lower()
                        if text_parts
                        else author_name.lower()
                    )

                    # Skip if already seen (by base name, case-insensitive)
                    if base_text in seen_names:
                        continue

                    # Check if it's just punctuation or common words
                    if base_text in [
                        ",",
                        ".",
                        "und",
                        "and",
                        "von",
                        "von",
                        "der",
                        "die",
                        "das",
                    ]:
                        continue

                    seen_names.add(base_text)

                    # Add as author without link
                    authors.append(
                        {
                            "name": author_name
                            # No 'id' or 'url' - these are authors without links
                        }
                    )

                # Skip the rest of the processing for this span since we've already split it
                continue

        # Also try to extract from meta author tag as fallback
        # Note: Meta tag may contain cities (e.g., "Andreas Babst, Bangkok")
        # We preserve the full string - user's data engineering pipeline will extract cities
        meta_author = soup.find("meta", {"name": "author"})
        if meta_author and meta_author.get("content"):
            author_text = meta_author.get("content", "").strip()
            if author_text:
                # Fix concatenated names first (e.g., "SydneyBarbara" -> "Sydney, Barbara")
                author_text = self._fix_concatenated_name(author_text)
                # Clean parentheses from author text
                author_text = self._clean_author_name(author_text)
                if author_text:
                    # Split by comma, "und", or semicolon to get individual authors
                    individual_authors = self._split_author_names(author_text)
                    for author_name in individual_authors:
                        if not author_name or len(author_name) < 2:
                            continue

                        # Extract base name for duplicate checking (first part before comma)
                        name_parts = author_name.split(",")
                        base_name = (
                            name_parts[0].strip().lower()
                            if name_parts
                            else author_name.lower()
                        )

                        if base_name not in seen_names:
                            seen_names.add(base_name)
                            authors.append(
                                {
                                    "name": author_name  # Preserve full string including city if present
                                    # No 'id' or 'url' - from meta tag
                                }
                            )

        return authors

    def _extract_author_string(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract author as comma-separated string from article page.

        This is used for the article.author field (backward compatibility).
        Extracts all authors (with and without links) and returns as comma-separated string.
        Preserves full author strings including city information (e.g., "Andreas Babst, Bangkok").
        Authors are split by comma, "und", or semicolon and cleaned of parentheses.

        Args:
            soup: BeautifulSoup object of the article page

        Returns:
            Comma-separated string of author names (with cities if present), or None
        """
        authors = self._extract_authors_from_article(soup)
        if authors:
            # Preserve full author strings including cities
            author_names = [author["name"] for author in authors]
            return ", ".join(author_names)

        # Fallback: try meta author tag
        meta_author = soup.find("meta", {"name": "author"})
        if meta_author and meta_author.get("content"):
            # Clean and split author text
            author_text = meta_author.get("content", "").strip()
            author_text = self._clean_author_name(author_text)
            if author_text:
                # Split and rejoin to ensure proper formatting
                individual_authors = self._split_author_names(author_text)
                if individual_authors:
                    return ", ".join(individual_authors)

        return None

    def scrape_author_profile(self, author_url: str, author_id: str) -> Optional[Dict]:
        """Scrape an author profile page.

        Args:
            author_url: URL to the author profile page
            author_id: The author ID (extracted from URL)

        Returns:
            Dictionary with author information, or None if failed
        """
        try:
            # Wait with jitter for human-like behavior
            self.rate_limiter.wait(jitter=True)

            # Occasionally rotate user agent
            if random.random() < 0.1:  # 10% chance
                self._set_random_user_agent()

            r = self.session.get(author_url, timeout=30)
            # Handle 404 errors gracefully (author profile may not exist)
            if r.status_code == 404:
                logger.warning(f"Author profile not found (404): {author_url}")
                return None
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Extract name from h1
            name = None
            h1 = soup.find("h1")
            if h1:
                name = h1.get_text(strip=True)
                # Clean parentheses from name
                name = self._clean_author_name(name)

            # Extract title/job title
            title = None
            # Look for subtitle or job title near the name
            title_elem = soup.find("p", class_=lambda x: x and "font-sans" in str(x))
            if title_elem:
                title = title_elem.get_text(strip=True)

            # Extract alternate name (e.g., "rb.") from h4
            alternate_name = None
            h4 = soup.find("h4")
            if h4:
                alternate_name = h4.get_text(strip=True).strip("()")

            # Extract bio from paragraph
            bio = None
            bio_elem = soup.find(
                "p", class_=lambda x: x and "articlecomponent" in str(x)
            )
            if bio_elem:
                bio = bio_elem.get_text(strip=True)

            # Extract image URL
            image_url = None
            img = soup.find("img", src=True)
            if img:
                img_src = img.get("src", "")
                if img_src:
                    image_url = (
                        self._make_absolute_url(img_src)
                        if not img_src.startswith("http")
                        else img_src
                    )

            # Also try to extract from JSON-LD structured data
            json_ld_scripts = soup.find_all("script", type="application/ld+json")
            for script in json_ld_scripts:
                try:
                    import json

                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get("@type") == "ProfilePage":
                        main_entity = data.get("mainEntity", {})
                        if main_entity.get("@type") == "Person":
                            if not name:
                                name = main_entity.get("name")
                            if not title:
                                job_title = main_entity.get("jobTitle")
                                if job_title:
                                    title = job_title
                            if not alternate_name:
                                alternate_name = main_entity.get("alternateName")
                            if not image_url:
                                images = main_entity.get("image", [])
                                if (
                                    images
                                    and isinstance(images, list)
                                    and len(images) > 0
                                ):
                                    image_obj = images[0]
                                    if isinstance(image_obj, dict):
                                        image_url = image_obj.get("url")
                                    else:
                                        image_url = images[0]
                except:
                    pass

            if not name:
                logger.warning(
                    f"Could not extract name from author profile: {author_url}"
                )
                return None

            author_data = {
                "id": author_id,
                "name": name,
                "title": title,
                "alternate_name": alternate_name,
                "bio": bio,
                "image_url": image_url,
                "url": author_url,
            }

            logger.info(f"Scraped author profile: {name} ({author_id})")
            return author_data

        except Exception as e:
            logger.error(
                f"Error scraping author profile {author_id}: {str(e)}", exc_info=True
            )
            return None

    def scrape_article(self, article_url: str, article_id: str) -> Optional[Dict]:
        """Scrape a single article with enhanced features (related articles and authors).

        This method is called during article scraping (STEP 2) and:
        1. Extracts related articles from the article page
        2. Extracts authors from the article page (with and without links)
        3. Saves related articles to database and adds them to scraping queue
        4. Adds authors to author_queue for profile scraping (if not already in database)
        5. Links authors to articles based on impressum data (if available)

        Overrides the parent method to add:
        - Extraction of related articles
        - Extraction of authors (multiple, comma-separated)
        - Saving related articles to database
        - Saving authors to database
        - Adding related articles to scraping queue
        - Adding author profiles to scraping queue
        """
        # Call parent method to get basic article data
        article_data = super().scrape_article(article_url, article_id)

        if not article_data:
            return None

        # Check 1 year limit BEFORE extracting related articles
        # Only extract related articles if the article itself is not skipped
        from datetime import timezone

        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)

        article_date = article_data.get("article_date")
        article_will_be_skipped = False
        if article_date:
            # Make sure date is timezone-aware for comparison
            if article_date.tzinfo is None:
                article_date = article_date.replace(tzinfo=timezone.utc)

            # If article is older than 1 year, skip extracting related articles
            if article_date < one_year_ago:
                article_will_be_skipped = True
                logger.debug(
                    f"Article {article_id} is older than 1 year - skipping related articles extraction"
                )

        try:
            # Get the HTML again to extract related articles and authors
            # Only extract related articles if the article is NOT being skipped
            if not article_will_be_skipped:
                self.rate_limiter.wait(jitter=True)
                try:
                    r = self.session.get(article_url, timeout=30)
                    # Handle 404 errors gracefully (article deleted/moved)
                    if r.status_code == 404:
                        logger.warning(
                            f"Article {article_id} not found (404) when extracting related articles - likely deleted or moved"
                        )
                        return article_data  # Return what we have so far
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "html.parser")
                except requests.exceptions.HTTPError as e:
                    # Handle 404 errors gracefully
                    if (
                        hasattr(e, "response")
                        and e.response
                        and e.response.status_code == 404
                    ):
                        logger.warning(
                            f"Article {article_id} not found (404) when extracting related articles - likely deleted or moved"
                        )
                        return article_data  # Return what we have so far
                    # Re-raise other HTTP errors
                    raise

                # Extract related articles from article page
                related_articles = self._extract_related_articles(soup, article_id)

                # Save related articles to database and add to queue (if within 1 year limit)
                for related in related_articles:
                    try:
                        # Check if related article has a date in the extracted data
                        related_date = related.get("date")
                        if related_date:
                            # Make sure date is timezone-aware for comparison
                            if related_date.tzinfo is None:
                                related_date = related_date.replace(tzinfo=timezone.utc)

                            # Skip if older than 1 year - don't add to queue or save relationship
                            if related_date < one_year_ago:
                                logger.debug(
                                    f"Skipping related article {related['id']} - older than 1 year ({related_date.date()})"
                                )
                                continue

                        # Save relationship to database (even if date not available - will check when scraping)
                        self.db.save_related_article(
                            article_id=article_id,
                            related_article_id=related["id"],
                            related_article_url=related["url"],
                        )

                        # Add to main scraping queue if not already in database
                        # Date will be checked again when scraping the article (in _scrape_article_batch)
                        if not self.db.article_exists(related["id"]):
                            # Add to main scraping queue (related articles - added at bottom of queue)
                            # This is the second place where articles are added to the same queue
                            # Related articles are processed after scrolling articles (FIFO order)
                            # If article is older than 1 year, it will be skipped during scraping
                            self.scraping_queue.put(related)
                    except Exception as e:
                        logger.error(
                            f"Error saving related article {related['id']}: {str(e)}"
                        )
            else:
                # Article is being skipped - don't extract related articles
                # But we still need to extract authors for the article data
                self.rate_limiter.wait(jitter=True)
                try:
                    r = self.session.get(article_url, timeout=30)
                    # Handle 404 errors gracefully (article deleted/moved)
                    if r.status_code == 404:
                        logger.warning(
                            f"Article {article_id} not found (404) when extracting authors - likely deleted or moved"
                        )
                        return article_data  # Return what we have so far
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "html.parser")
                except requests.exceptions.HTTPError as e:
                    # Handle 404 errors gracefully
                    if (
                        hasattr(e, "response")
                        and e.response
                        and e.response.status_code == 404
                    ):
                        logger.warning(
                            f"Article {article_id} not found (404) when extracting authors - likely deleted or moved"
                        )
                        return article_data  # Return what we have so far
                    # Re-raise other HTTP errors
                    raise

            # Extract authors (with and without links) - always extract authors
            # (even if article is skipped, we want to save the author information)
            if "soup" not in locals():
                # If soup wasn't created above, create it now
                self.rate_limiter.wait(jitter=True)
                try:
                    r = self.session.get(article_url, timeout=30)
                    # Handle 404 errors gracefully (article deleted/moved)
                    if r.status_code == 404:
                        logger.warning(
                            f"Article {article_id} not found (404) when extracting authors - likely deleted or moved"
                        )
                        return article_data  # Return what we have so far
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "html.parser")
                except requests.exceptions.HTTPError as e:
                    # Handle 404 errors gracefully
                    if (
                        hasattr(e, "response")
                        and e.response
                        and e.response.status_code == 404
                    ):
                        logger.warning(
                            f"Article {article_id} not found (404) when extracting authors - likely deleted or moved"
                        )
                        return article_data  # Return what we have so far
                    # Re-raise other HTTP errors
                    raise

            authors = self._extract_authors_from_article(soup)

            # Always save author string (even if no authors with links found)
            # Use normalized names for the article author field
            if authors:
                normalized_author_names = []
                for author in authors:
                    author_name = author.get("name", "")
                    parsed_authors = self.author_normalizer.parse_author_string(
                        author_name
                    )
                    if parsed_authors:
                        # Use normalized names
                        for parsed in parsed_authors:
                            normalized_author_names.append(parsed.normalized_name)
                    else:
                        # Fallback to original name
                        normalized_author_names.append(author_name)
                article_data["author"] = ", ".join(normalized_author_names)
            else:
                # Fallback: try to get author from parent class method
                author_string = self._extract_author_string(soup)
                if author_string:
                    article_data["author"] = author_string
                    # Split the author string into individual authors and process them
                    individual_author_names = self._split_author_names(author_string)
                    for author_name in individual_author_names:
                        if author_name:
                            # Clean the name
                            cleaned_name = self._clean_author_name(author_name)
                            if cleaned_name:
                                authors.append({"name": cleaned_name})
                elif not article_data.get("author"):
                    # Final fallback: use parent's _extract_author method
                    parent_author = super()._extract_author(soup)
                    if parent_author:
                        article_data["author"] = parent_author
                        # Split the author string into individual authors and process them
                        individual_author_names = self._split_author_names(
                            parent_author
                        )
                        for author_name in individual_author_names:
                            if author_name:
                                # Clean the name
                                cleaned_name = self._clean_author_name(author_name)
                                if cleaned_name:
                                    authors.append({"name": cleaned_name})

            # Save authors to database and link to article
            # Collect author IDs for the article
            article_author_ids = []

            # Collect locations from authors (for article location field)
            article_locations = []

            # Process each author individually
            for author in authors:
                try:
                    author_name = author.get("name", "")

                    # Use normalizer to parse and normalize the author name
                    parsed_authors = self.author_normalizer.parse_author_string(
                        author_name
                    )

                    # If normalizer couldn't parse it, use original name
                    if not parsed_authors:
                        # Fallback: use original name as-is
                        parsed_authors = [
                            ParsedAuthor(
                                first_name=(
                                    author_name.split()[0]
                                    if author_name.split()
                                    else ""
                                ),
                                last_name=(
                                    " ".join(author_name.split()[1:])
                                    if len(author_name.split()) > 1
                                    else author_name
                                ),
                                original_string=author_name,
                            )
                        ]

                    # Process each parsed author
                    for parsed_author in parsed_authors:
                        # Get normalized name (without location/department)
                        normalized_name = parsed_author.normalized_name

                        # Collect location if present (for both authors with and without links)
                        if (
                            parsed_author.location
                            and parsed_author.location not in article_locations
                        ):
                            article_locations.append(parsed_author.location)

                        # Process authors with links (those with 'id' key)
                        if "id" in author and author.get("id"):
                            author_id = author["id"]
                            # Skip placeholder IDs (no-id-...) - these don't have real profile pages
                            if author_id.startswith("no-id-"):
                                continue
                            # Check if author exists by both ID and name (if available)
                            if not self.db.author_exists(author_id=author_id):
                                # Also check by normalized name to avoid duplicates
                                if (
                                    normalized_name
                                    and self.db.get_author_by_name_or_alias(
                                        name=normalized_name
                                    )
                                ):
                                    # Author exists by name, skip adding to queue
                                    continue
                                # Update author dict with normalized name
                                author["name"] = normalized_name
                                self.author_queue.put(author)
                            else:
                                # Author already exists, link immediately
                                self.db.link_article_to_author(article_id, author_id)
                                article_author_ids.append(author_id)
                                # Update currently_employed status based on impressum
                                is_employed = self._is_author_currently_employed(
                                    normalized_name
                                )
                                if is_employed:
                                    # Update author's currently_employed status
                                    session = self.db.Session()
                                    try:
                                        existing_author = (
                                            session.query(Author)
                                            .filter_by(author_id=author_id)
                                            .first()
                                        )
                                        if existing_author:
                                            existing_author.currently_employed = 1
                                            # Update alias to include normalized name
                                            alias_list = []
                                            if existing_author.alias:
                                                alias_list = [
                                                    a.strip()
                                                    for a in existing_author.alias.split(
                                                        ","
                                                    )
                                                ]
                                            if normalized_name not in alias_list:
                                                alias_list.append(normalized_name)
                                            existing_author.alias = ", ".join(
                                                alias_list
                                            )
                                            session.commit()
                                    finally:
                                        session.close()
                        else:
                            # Authors without links - use normalized name for matching
                            # But store original string in alias for reference
                            full_name = author_name.strip()  # Original with location
                            normalized = (
                                normalized_name.strip()
                            )  # Normalized without location

                            # Build alias list: normalized name, original name, location, department
                            alias_parts = [normalized]
                            if full_name != normalized:
                                alias_parts.append(full_name)
                            if parsed_author.location:
                                alias_parts.append(parsed_author.location)
                            if parsed_author.department:
                                alias_parts.append(parsed_author.department)
                            alias_str = ", ".join(alias_parts)

                            # Try to find author by normalized name or alias
                            existing_author = self.db.get_author_by_name_or_alias(
                                name=normalized, alias=normalized
                            )

                            if not existing_author:
                                # Check if author exists by name or alias
                                if not self.db.author_exists(
                                    name=normalized, alias=normalized
                                ):
                                    # Create author entry without ID/link
                                    # Use normalized name as primary name, store original in alias
                                    try:
                                        saved_author = self.db.save_author(
                                            name=normalized,  # Store normalized name (without location)
                                            author_id=None,
                                            author_url=None,
                                            alias=alias_str,  # Store original, location, department in alias
                                            currently_employed=0,  # Always False for authors without links
                                        )
                                        existing_author = saved_author
                                        logger.debug(
                                            f"Saved author without link: {normalized} (alias: {alias_str}, employed: False)"
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"Error saving author without link {normalized}: {str(e)}"
                                        )
                                else:
                                    # Author exists, get it
                                    existing_author = (
                                        self.db.get_author_by_name_or_alias(
                                            name=normalized, alias=normalized
                                        )
                                    )
                                    # Update alias to include new variations
                                    if existing_author:
                                        session = self.db.Session()
                                        try:
                                            fresh_author = (
                                                session.query(Author)
                                                .filter_by(name=normalized)
                                                .first()
                                            )
                                            if fresh_author:
                                                # Update alias
                                                alias_list = []
                                                if fresh_author.alias:
                                                    alias_list = [
                                                        a.strip()
                                                        for a in fresh_author.alias.split(
                                                            ","
                                                        )
                                                    ]
                                                for part in alias_parts:
                                                    if part not in alias_list:
                                                        alias_list.append(part)
                                                fresh_author.alias = ", ".join(
                                                    alias_list
                                                )
                                                session.commit()
                                        finally:
                                            session.close()

                        # Link author to article (by name or alias)
                        if existing_author:
                            # Get author_id before session closes (author object may be detached)
                            author_id_to_link = None
                            try:
                                author_id_to_link = existing_author.author_id
                            except Exception:
                                # Author object is detached, re-query to get author_id
                                session = self.db.Session()
                                try:
                                    # Try to get author by name or by getting the name from the detached object
                                    author_name_to_query = None
                                    try:
                                        author_name_to_query = existing_author.name
                                    except:
                                        author_name_to_query = cleaned_name

                                    if author_name_to_query:
                                        fresh_author = (
                                            session.query(Author)
                                            .filter_by(name=author_name_to_query)
                                            .first()
                                        )
                                        if fresh_author:
                                            author_id_to_link = fresh_author.author_id
                                finally:
                                    session.close()

                            # Link to article
                            if author_id_to_link:
                                self.db.link_article_to_author(
                                    article_id, author_id_to_link
                                )
                                article_author_ids.append(author_id_to_link)
                            else:
                                # For authors without ID, we can't link via association table
                                # But we'll still store the name in the article.author field
                                logger.debug(
                                    f"Author {full_name} has no ID, cannot link to article via association table"
                                )
                except Exception as e:
                    author_id = author.get("id", "no-id")
                    logger.error(f"Error processing author {author_id}: {str(e)}")

            # Store author IDs in article_data
            if article_author_ids:
                article_data["author_ids"] = ",".join(article_author_ids)

            # Store location in article_data (comma-separated if multiple)
            if article_locations:
                article_data["location"] = ", ".join(article_locations)

        except Exception as e:
            logger.error(
                f"Error extracting related articles/authors for {article_id}: {str(e)}",
                exc_info=True,
            )

        return article_data

    def _author_scraping_worker(self):
        """Background worker thread that processes authors from the queue in parallel."""
        import threading

        thread_name = threading.current_thread().name
        thread_short = thread_name.split("_")[-1] if "_" in thread_name else thread_name
        logger.info(f"[{thread_short}] Author worker started")

        successful = 0
        failed = 0
        skipped = 0

        while self.author_scraping_active:
            try:
                # Get author from queue (with timeout to check if still active)
                try:
                    author = self.author_queue.get(timeout=1)
                except:
                    continue

                # Check for sentinel value (None) to stop
                if author is None:
                    break

                try:
                    author_id = author["id"]
                    author_url = author["url"]

                    # Skip if author_id is a placeholder (no-id-...)
                    # This means the author doesn't have a real ID and shouldn't be scraped from profile
                    if author_id and author_id.startswith("no-id-"):
                        logger.debug(
                            f"[{thread_short}] Skipping placeholder author ID: {author_id}"
                        )
                        skipped += 1
                        self.author_queue.task_done()
                        continue

                    # Check for duplicates by both ID and name (if available)
                    # First check by ID
                    if self.db.author_exists(author_id=author_id):
                        logger.debug(
                            f"[{thread_short}] Author {author_id} already exists (by ID), skipping"
                        )
                        skipped += 1
                        self.author_queue.task_done()
                        continue

                    # Scrape author profile
                    author_data = self.scrape_author_profile(author_url, author_id)

                    if author_data:
                        author_name = author_data.get("name", "")

                        # Check for duplicates by name before saving
                        # This prevents creating duplicate authors with different IDs
                        if author_name:
                            existing_by_name = self.db.get_author_by_name_or_alias(
                                name=author_name
                            )
                            if existing_by_name:
                                # Author exists by name, check if we should update
                                # If the existing author has a real ID and this one does too, skip
                                # If existing has placeholder ID and this has real ID, update
                                if (
                                    existing_by_name.author_id
                                    and not existing_by_name.author_id.startswith(
                                        "no-id-"
                                    )
                                ):
                                    # Existing author has real ID, skip this one
                                    logger.debug(
                                        f"[{thread_short}] Author '{author_name}' already exists with ID {existing_by_name.author_id}, skipping"
                                    )
                                    skipped += 1
                                    self.author_queue.task_done()
                                    continue
                                elif author_id and not author_id.startswith("no-id-"):
                                    # Existing has placeholder, this has real ID - update it
                                    session = self.db.Session()
                                    try:
                                        existing_by_name.author_id = author_id
                                        existing_by_name.author_url = author_data.get(
                                            "url"
                                        )
                                        if author_data.get("title"):
                                            existing_by_name.title = author_data.get(
                                                "title"
                                            )
                                        if author_data.get("alternate_name"):
                                            existing_by_name.alternate_name = (
                                                author_data.get("alternate_name")
                                            )
                                        if author_data.get("bio"):
                                            existing_by_name.bio = author_data.get(
                                                "bio"
                                            )
                                        if author_data.get("image_url"):
                                            existing_by_name.image_url = (
                                                author_data.get("image_url")
                                            )
                                        is_employed = (
                                            self._is_author_currently_employed(
                                                author_name
                                            )
                                        )
                                        existing_by_name.currently_employed = (
                                            1 if is_employed else 0
                                        )
                                        session.commit()
                                        successful += 1
                                        logger.info(
                                            f"[{thread_short}] ✓ Updated author '{author_name}' with real ID {author_id}"
                                        )
                                    finally:
                                        session.close()
                                    self.author_queue.task_done()
                                    continue

                        # Check if author is currently employed
                        is_employed = self._is_author_currently_employed(author_name)

                        # Double-check before saving: check by both ID and name
                        if not self.db.author_exists(
                            author_id=author_id, name=author_name
                        ):
                            # Save author to database
                            self.db.save_author(
                                name=author_data["name"],
                                author_id=author_data["id"],
                                author_url=author_data["url"],
                                title=author_data.get("title"),
                                alternate_name=author_data.get("alternate_name"),
                                bio=author_data.get("bio"),
                                image_url=author_data.get("image_url"),
                                currently_employed=1 if is_employed else 0,
                            )
                            successful += 1
                            logger.info(
                                f"[{thread_short}] ✓ Author {author_data['name']} ({author_id})"
                            )
                        else:
                            # Author exists, update currently_employed status
                            session = self.db.Session()
                            try:
                                existing_author = (
                                    session.query(Author)
                                    .filter_by(author_id=author_id)
                                    .first()
                                )
                                if existing_author:
                                    existing_author.name = author_data["name"]
                                    if author_data.get("title"):
                                        existing_author.title = author_data["title"]
                                    if author_data.get("alternate_name"):
                                        existing_author.alternate_name = (
                                            author_data.get("alternate_name")
                                        )
                                    if author_data.get("bio"):
                                        existing_author.bio = author_data.get("bio")
                                    if author_data.get("image_url"):
                                        existing_author.image_url = author_data.get(
                                            "image_url"
                                        )
                                    existing_author.currently_employed = (
                                        1 if is_employed else 0
                                    )
                                    session.commit()
                                    successful += 1
                                    logger.info(
                                        f"[{thread_short}] ✓ Updated author {author_data['name']} ({author_id})"
                                    )
                            finally:
                                session.close()
                    else:
                        failed += 1
                        logger.warning(
                            f"[{thread_short}] ✗ Author {author_id}: Failed to scrape"
                        )

                    self.author_queue.task_done()

                except Exception as e:
                    failed += 1
                    author_id = (
                        author.get("id", "unknown")
                        if isinstance(author, dict)
                        else "unknown"
                    )
                    logger.error(
                        f"[{thread_short}] ✗ Author {author_id}: {str(e)}",
                        exc_info=True,
                    )
                    self.author_queue.task_done()

            except Exception as e:
                logger.error(
                    f"[{thread_name}] Error in author scraping worker: {str(e)}",
                    exc_info=True,
                )

        logger.info(
            f"[{thread_short}] Author worker done: {successful}✓ {failed}✗ {skipped}⊘"
        )

    def process_author_queue(self):
        """Process the author queue to scrape author profiles in parallel using threads."""
        import threading

        if self.author_queue.empty():
            logger.info("No authors in queue to process")
            return

        logger.info(
            f"Starting parallel author profile scraping with {self.num_author_worker_threads} threads..."
        )
        logger.info(f"Author queue size: {self.author_queue.qsize()}")

        # Start author scraping threads
        self.author_scraping_active = True
        self.author_scraping_threads = []

        for i in range(self.num_author_worker_threads):
            thread = threading.Thread(
                target=self._author_scraping_worker,
                daemon=True,
                name=f"author_worker_{i+1}",
            )
            thread.start()
            self.author_scraping_threads.append(thread)

        # Wait for all authors to be processed
        self.author_queue.join()

        # Signal threads to stop
        self.author_scraping_active = False
        for _ in range(self.num_author_worker_threads):
            self.author_queue.put(None)  # Sentinel value to stop threads

        # Wait for all threads to finish
        for thread in self.author_scraping_threads:
            thread.join(timeout=5)

        logger.info("Author profile scraping complete")

    def link_articles_to_authors_after_scraping(self):
        """Link articles to authors after all scraping is complete.

        This method finds all articles and links them to their authors based on
        the author field in the article. It matches authors by name.
        For each article, it splits the author string by comma, "und", or semicolon,
        cleans parentheses from each author name, and checks each individual author
        against the database to create associations.
        """
        logger.info("Linking articles to authors...")

        # Get all articles and authors
        articles = self.db.get_all_articles()
        session = self.db.Session()

        try:
            from database import Author

            all_authors = session.query(Author).all()

            # Create a name-to-author mapping (including aliases)
            name_to_author = {}
            for author in all_authors:
                # Map by full name (lowercase)
                if author.name:
                    name_to_author[author.name.lower()] = author
                    # Map by base name (before comma, if city is present)
                    if "," in author.name:
                        base_name = author.name.split(",")[0].strip().lower()
                        if base_name not in name_to_author:
                            name_to_author[base_name] = author
                # Map by alternate name
                if author.alternate_name:
                    name_to_author[author.alternate_name.lower()] = author
                # Map by alias - split comma-separated aliases and map each one
                if author.alias:
                    # Split alias by comma and map each individual alias
                    alias_parts = [a.strip() for a in author.alias.split(",")]
                    for alias_part in alias_parts:
                        if alias_part:
                            alias_lower = alias_part.lower()
                            if alias_lower not in name_to_author:
                                name_to_author[alias_lower] = author

            linked_count = 0
            for article in articles:
                if not article.author:
                    continue

                # Clean and split author names by comma, "und", or semicolon
                cleaned_author_string = self._clean_author_name(article.author)
                if not cleaned_author_string:
                    continue

                # Split into individual author names
                individual_author_names = self._split_author_names(
                    cleaned_author_string
                )

                # Process each individual author
                for author_name in individual_author_names:
                    if not author_name or len(author_name) < 2:
                        continue

                    # Clean the author name
                    cleaned_name = self._clean_author_name(author_name).strip()
                    if not cleaned_name:
                        continue

                    # Try to find author by exact name match (with city if present)
                    author_lower = cleaned_name.lower()
                    author = None

                    # First try exact match
                    if author_lower in name_to_author:
                        author = name_to_author[author_lower]
                    else:
                        # Try base name (before comma, if city is present)
                        if "," in cleaned_name:
                            base_name = cleaned_name.split(",")[0].strip().lower()
                            if base_name in name_to_author:
                                author = name_to_author[base_name]
                        else:
                            # Try to find by checking database directly
                            existing_author = self.db.get_author_by_name_or_alias(
                                name=cleaned_name
                            )
                            if existing_author:
                                author = existing_author

                    # If author found, create association
                    if author and author.author_id:
                        if self.db.link_article_to_author(
                            article.article_id, author.author_id
                        ):
                            linked_count += 1
                            logger.debug(
                                f"Linked article {article.article_id} to author {author.author_id} ({author.name})"
                            )
        except Exception as e:
            logger.error(f"Error linking articles to authors: {str(e)}", exc_info=True)
        finally:
            try:
                session.close()
            except:
                pass

        logger.info(f"Linked {linked_count} article-author relationships")

    def run(
        self,
        headless: bool = False,
        clean_articles: bool = False,
        clean_authors: bool = False,
        clean_related_articles: bool = False,
        clean_article_author_associations: bool = False,
    ):
        """Main method to run the scraping process with enhanced features.

        Args:
            headless: Whether to run browser in headless mode
            clean_articles: If True, clean articles table before scraping (default: False)
            clean_authors: If True, clean authors table before scraping (default: False)
            clean_related_articles: If True, clean related_articles table before scraping (default: False)
            clean_article_author_associations: If True, clean article_author_association table before scraping (default: False)
        """
        try:
            logger.info("Starting NZZ scraper v2...")

            # Clean specified database tables before scraping (optional, only for testing)
            if any(
                [
                    clean_articles,
                    clean_authors,
                    clean_related_articles,
                    clean_article_author_associations,
                ]
            ):
                logger.info("Cleaning specified database tables before scraping...")
                self.db.clean_database(
                    clean_articles=clean_articles,
                    clean_authors=clean_authors,
                    clean_related_articles=clean_related_articles,
                    clean_article_author_associations=clean_article_author_associations,
                )
                logger.info("Database tables cleaned")
            else:
                logger.info("Appending to existing database (no cleanup)")

            # STEP 1: Load and scrape all impressum authors FIRST (before article scraping)
            # This ensures all currently employed authors are in the database before we start
            # analyzing articles, so we can properly link articles to authors and mark them as employed
            logger.info("=" * 80)
            logger.info("STEP 1: Loading and scraping all impressum author profiles...")
            logger.info("=" * 80)
            self._load_impressum_authors()
            logger.info("=" * 80)
            logger.info(
                f"STEP 1 COMPLETE: Impressum authors loaded and scraped ({len(self.currently_employed_authors)} authors)"
            )
            logger.info("=" * 80)

            # STEP 2: Now start article scraping (after impressum authors are done)
            # During article scraping, we will:
            # - Extract related articles from each article page
            # - Extract authors from each article page
            # - Save related articles to database and add them to scraping queue
            # - Add authors to author_queue for profile scraping
            logger.info("=" * 80)
            logger.info(
                "STEP 2: Starting article scraping (will analyze authors and related articles)..."
            )
            logger.info("=" * 80)

            # Start author scraping threads BEFORE article scraping begins
            # This allows authors to be processed in parallel as they're added to the queue
            logger.info("=" * 80)
            logger.info(
                f"Starting parallel author scraping threads ({self.num_author_worker_threads} workers)..."
            )
            logger.info("=" * 80)
            import threading

            self.author_scraping_active = True
            self.author_scraping_threads = []

            for i in range(self.num_author_worker_threads):
                thread = threading.Thread(
                    target=self._author_scraping_worker,
                    daemon=True,
                    name=f"author_worker_{i+1}",
                )
                thread.start()
                self.author_scraping_threads.append(thread)

            logger.info(
                f"Started {self.num_author_worker_threads} author scraping threads (running in parallel with article scraping)"
            )

            # Get article list (uses page=2000 by default)
            # This starts article scraping with 6 worker threads
            # Authors are added to author_queue as articles are scraped
            # Author scraping threads process them in parallel
            articles = self.get_article_list()
            if not articles:
                logger.warning("No articles found")
                # Stop author threads if no articles found
                self.author_scraping_active = False
                for _ in range(self.num_author_worker_threads):
                    self.author_queue.put(None)
                for thread in self.author_scraping_threads:
                    thread.join(timeout=5)
                return

            logger.info(f"Found {len(articles)} articles on the page")
            logger.info(
                "Article scraping complete, waiting for author scraping to finish..."
            )

            # Wait for all authors in queue to be processed
            # Author scraping threads are already running and processing authors in parallel
            self.author_queue.join()

            # Signal author threads to stop
            self.author_scraping_active = False
            for _ in range(self.num_author_worker_threads):
                self.author_queue.put(None)  # Sentinel value to stop threads

            # Wait for all author threads to finish
            for thread in self.author_scraping_threads:
                thread.join(timeout=5)

            logger.info(
                "Author scraping complete (6 workers processed authors in parallel)"
            )

            # Link articles to authors
            self.link_articles_to_authors_after_scraping()

            # Summary
            total_in_db = self.db.get_article_count()
            logger.info("=" * 80)
            logger.info("SCRAPING SUMMARY (v2)")
            logger.info("=" * 80)
            logger.info(f"Total articles in database: {total_in_db}")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Error in run method: {str(e)}", exc_info=True)
        finally:
            self.cleanup()
