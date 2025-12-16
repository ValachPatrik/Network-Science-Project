"""NZZ article scraper v3 with raw tables for granular processing steps."""

import os
import time
import random
import logging
import re
import json
import threading
from queue import Queue
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import requests
from scraper import NZZScraper, logger
from database_v3 import DatabaseManagerV3, AuthorRaw, ArticleRaw

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class NZZScraperV3(NZZScraper):
    """NZZ scraper v3 with raw tables for granular processing."""

    def __init__(
        self,
        base_url="https://www.nzz.ch",
        articles_url="https://www.nzz.ch/neueste-artikel?page=2000",
    ):
        """Initialize the scraper v3.

        Args:
            base_url: Base URL for NZZ website
            articles_url: URL for articles list page (default uses page=2000 parameter)
        """
        super().__init__(base_url, articles_url)

        # Use v3 database manager with raw tables
        self.db = DatabaseManagerV3()

        # Override number of worker threads
        self.num_worker_threads = 20

        self.impressum_url = "https://www.nzz.ch/information/impressum-ld.148422"

        # One year limit for articles (make timezone-aware for comparison)
        from datetime import timezone

        self.one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)

        # Author scraping queue and threads for parallel processing
        self.author_queue = Queue()  # Queue for impressum authors to be scraped
        self.author_scraping_threads = []  # List of threads for author scraping
        self.author_scraping_active = False  # Flag to control author scraping threads
        self.num_author_worker_threads = 6  # Number of parallel author scraping threads

        logger.info(
            f"Scraper v3 initialized - Articles limit: 1 year (since {self.one_year_ago.date()})"
        )

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
        pattern = re.compile(r"([a-zäöüß])([A-ZÄÖÜ])")

        # Replace with space
        fixed = pattern.sub(r"\1 \2", name)

        # Now check if we should use comma instead of space
        parts = fixed.split(" ")
        if len(parts) >= 2:
            first_part = parts[0]
            # Check if first part is a known location or job title
            location_patterns = [
                r"^(Bundeshaus|Westschweiz|Berlin|Paris|London|Rom|Madrid|Wien|Warschau|Frankfurt|Brüssel|Tallinn|Tel Aviv|Moskau|Nairobi|Istanbul|Beirut|Mumbai|Bangkok|Taipeh|Peking|Tokio|Sydney|Washington|Chicago|Bahia|Rio de Janeiro)$",
                r"^(International|Geopolitics|Reisen|Reporter|Social Media|Audience Management|Produktionsredaktion|Art Director|Bildredaktion|Fotografen|Korrespondenten)$",
            ]

            job_title_patterns = [
                r"^(Chefredaktor|Stellvertreter|Tagesleitung|Format|Community|Podcast|Management|Geschichte|NZZ|Folio)$",
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

    def _extract_author_string(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract author as plain string from article page (NO PROCESSING).

        ⚠️⚠️⚠️ CRITICAL: DO NOT MODIFY THIS METHOD ⚠️⚠️⚠️
        This method MUST return the raw author string exactly as found on the page.
        Do NOT clean, split, normalize, or modify the string in any way.
        Only .strip() is allowed to remove leading/trailing whitespace.

        The raw string is stored in articles_raw.author column for later processing.
        Author links are extracted separately via _extract_author_links_from_article()
        and stored in articles_raw.author_links as JSON.

        Args:
            soup: BeautifulSoup object of the article page

        Returns:
            Plain author string exactly as found on the page (only .strip() applied), or None
        """
        # Try meta author tag - return raw string without any processing
        meta_author = soup.find("meta", {"name": "author"})
        if meta_author and meta_author.get("content"):
            author_text = meta_author.get(
                "content", ""
            ).strip()  # Only strip leading/trailing whitespace
            if author_text:
                # Return raw string - NO PROCESSING (no cleaning, no splitting, no normalization)
                return author_text

        # No fallback - parent class methods do processing, which we don't want
        # Return None if author not found in meta tag
        return None

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

    def scrape_author_profile(self, author_url: str, author_id: str) -> Optional[Dict]:
        """Scrape an author profile page.

        Args:
            author_url: URL to the author profile page
            author_id: The author ID (extracted from URL)

        Returns:
            Dictionary with author information, or None if failed
        """
        try:
            # Early check: skip if author already exists in database
            if self.db.author_raw_exists(author_id=author_id):
                logger.debug(
                    f"Skipping author profile {author_id} - already exists in database"
                )
                return None

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

            # Note: image_url is skipped in v3 (as per requirements)

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
                "url": author_url,
            }

            logger.info(f"Scraped author profile: {name} ({author_id})")
            return author_data

        except Exception as e:
            logger.error(
                f"Error scraping author profile {author_id}: {str(e)}", exc_info=True
            )
            return None

    def _extract_departments_from_impressum(
        self, soup: BeautifulSoup
    ) -> Dict[str, str]:
        """Extract department mapping from impressum page.

        Parses the impressum page structure where departments are organized as:
        ## **Department Name**
        Author 1 (abbr.)
        Author 2 (abbr.)
        ...

        Args:
            soup: BeautifulSoup object of impressum page

        Returns:
            Dictionary mapping author names to departments
        """
        author_departments = {}
        current_department = None

        # Find all h2 headings (department headers)
        headings = soup.find_all("h2")

        # Department keywords to identify department headings
        department_keywords = [
            "International",
            "Meinung",
            "Debatte",
            "Schweiz",
            "Zürich",
            "Wirtschaft",
            "Wissenschaft",
            "Technologie",
            "Mobilität",
            "Feuilleton",
            "Sport",
            "Wochenende",
            "Gesellschaft",
            "Reisen",
            "Reporter",
            "Nachrichten",
            "Video",
            "Social Media",
            "Format",
            "Community",
            "Podcast",
            "Audience Management",
            "Visuals",
            "Editorial Tech",
            "Produktionsredaktion",
            "Art Director",
            "Bildredaktion",
            "Fotografen",
            "Redaktion Deutschland",
            "Korrespondenten",
            "NZZ am Sonntag",
            "NZZ Folio",
            "NZZ Geschichte",
        ]

        for i, heading in enumerate(headings):
            heading_text = heading.get_text(strip=True)

            # Clean heading text (remove email addresses, etc.)
            heading_text = re.sub(r"\[email.*?\]", "", heading_text).strip()
            heading_text = re.sub(r"@.*", "", heading_text).strip()

            # Skip non-department headings
            if heading_text in [
                "Neue Zürcher Zeitung",
                "Chefredaktor",
                "Stellvertreter",
                "Tagesleitung",
                "Optimieren Sie Ihre Browsereinstellungen",
            ]:
                continue

            # Check if this is a department heading
            is_department = any(
                keyword in heading_text for keyword in department_keywords
            )

            if is_department:
                current_department = heading_text
                logger.debug(f"Found department: {current_department}")

            # Find all authors under this heading until next h2
            # Get the next h2 heading
            next_heading = None
            if i + 1 < len(headings):
                next_heading = headings[i + 1]

            # Get all content between this heading and next heading
            # Use find_all_next to get all elements until next h2
            if current_department:
                # Find all author links in the section
                section_start = heading
                section_end = next_heading if next_heading else None

                # Get all elements between this heading and next
                current = heading
                while current:
                    current = current.next_sibling
                    if current is None:
                        break
                    if section_end and current == section_end:
                        break

                    if hasattr(current, "find_all"):
                        # Look for author links
                        author_links = current.find_all(
                            "a", href=re.compile(r"/impressum/.*-ld\.\d+")
                        )
                        for link in author_links:
                            author_name = link.get_text(strip=True)
                            if author_name:
                                # Fix concatenated names
                                author_name = self._fix_concatenated_name(author_name)
                                author_departments[author_name] = current_department

                        # Also look for author pattern in text: "Name (abbr.)"
                        text = current.get_text()
                        author_pattern = re.compile(
                            r"([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)\s*\(([a-zäöüß]{1,4}\.)\)",
                            re.IGNORECASE,
                        )
                        matches = author_pattern.findall(text)
                        for name, abbrev in matches:
                            name = name.strip()
                            name = self._fix_concatenated_name(name)
                            if name:
                                author_departments[name] = current_department

        logger.info(
            f"Extracted {len(author_departments)} author-department mappings from impressum"
        )
        return author_departments

    def _impressum_author_worker(self):
        """Worker thread that processes impressum authors from the queue in parallel."""
        thread_name = threading.current_thread().name
        thread_short = thread_name.split("_")[-1] if "_" in thread_name else thread_name
        successful = 0
        failed = 0
        skipped = 0

        while self.author_scraping_active:
            try:
                # Get author from queue (blocks until available)
                author_task = self.author_queue.get(timeout=1)

                # Check for sentinel value (stop signal)
                if author_task is None:
                    self.author_queue.task_done()
                    break

                author_id = author_task.get("id")
                author_url = author_task.get("url")
                name_normalized = author_task.get("name")
                department = author_task.get("department")

                if not author_id or not author_url or not name_normalized:
                    self.author_queue.task_done()
                    skipped += 1
                    continue

                try:
                    # Check if author already exists
                    if not self.db.author_raw_exists(author_id=author_id):
                        # Scrape author profile
                        self.rate_limiter.wait(jitter=True)
                        author_data = self.scrape_author_profile(author_url, author_id)

                        if author_data:
                            # Save to authors_raw
                            self.db.save_author_raw(
                                author_id=author_data["id"],
                                name=author_data["name"],
                                title=author_data.get("title"),
                                alt_name=author_data.get("alternate_name"),
                                bio=author_data.get("bio"),
                                author_url=author_data["url"],
                                alias=name_normalized,
                                has_info=1,  # Page exists
                                department=department,
                            )
                            successful += 1
                        else:
                            # Save basic info if scraping failed
                            self.db.save_author_raw(
                                author_id=author_id,
                                name=name_normalized,
                                author_url=author_url,
                                has_info=0,  # Page doesn't exist or failed
                                department=department,
                            )
                            successful += 1
                    else:
                        # Update department if missing
                        session = self.db.Session()
                        try:
                            existing = (
                                session.query(AuthorRaw)
                                .filter_by(author_id=author_id)
                                .first()
                            )
                            if existing and not existing.department and department:
                                existing.department = department
                                session.commit()
                        finally:
                            session.close()
                        skipped += 1

                except Exception as e:
                    failed += 1
                    logger.error(
                        f"[{thread_short}] Error processing impressum author {name_normalized}: {str(e)}"
                    )

                self.author_queue.task_done()

            except:
                # Timeout or other error - continue loop
                continue

        logger.info(
            f"[{thread_short}] Impressum author worker done: {successful}✓ {failed}✗ {skipped}⊘"
        )

    def _load_impressum_authors(self):
        """Load authors from impressum page with departments and save to authors_raw (parallel processing)."""
        try:
            logger.info("STEP 1: Loading authors from impressum page...")
            self.rate_limiter.wait(jitter=True)
            r = self.session.get(self.impressum_url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Extract department mappings
            author_departments = self._extract_departments_from_impressum(soup)

            # Extract all text from the page
            text = soup.get_text()

            # Pattern to match author names with abbreviations
            author_pattern = re.compile(
                r"([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)\s*\(([a-zäöüß]{1,4}\.)\)",
                re.IGNORECASE,
            )
            matches = author_pattern.findall(text)

            # Extract author profile links
            author_links = soup.find_all("a", href=re.compile(r"/impressum/.*-ld\.\d+"))
            author_profiles = {}

            for link in author_links:
                href = link.get("href", "")
                if href:
                    url = self._make_absolute_url(href)
                    author_id = self._extract_id_from_url(url)
                    if author_id:
                        link_text = link.get_text(strip=True)
                        if link_text:
                            link_text = self._fix_concatenated_name(link_text)
                            name_normalized = re.sub(r"\s+", " ", link_text.strip())
                            author_profiles[name_normalized] = {
                                "url": url,
                                "id": author_id,
                                "name": name_normalized,
                            }

            # Start author scraping worker threads
            logger.info(
                f"Starting parallel author profile scraping with {self.num_author_worker_threads} threads..."
            )
            self.author_scraping_active = True
            self.author_scraping_threads = []

            for i in range(self.num_author_worker_threads):
                thread = threading.Thread(
                    target=self._impressum_author_worker,
                    daemon=True,
                    name=f"impressum_author_worker_{i+1}",
                )
                thread.start()
                self.author_scraping_threads.append(thread)

            # Add authors with profile links to queue
            authors_queued = 0
            for name_normalized, profile_info in author_profiles.items():
                author_id = profile_info["id"]
                author_url = profile_info["url"]
                department = author_departments.get(name_normalized)

                # Only queue if author doesn't exist
                if not self.db.author_raw_exists(author_id=author_id):
                    self.author_queue.put(
                        {
                            "id": author_id,
                            "url": author_url,
                            "name": name_normalized,
                            "department": department,
                        }
                    )
                    authors_queued += 1

            logger.info(f"Author queue size: {self.author_queue.qsize()}")
            logger.info(
                f"Queued {authors_queued} authors with profile links for parallel scraping"
            )

            # Process authors without profile links (synchronous - no scraping needed)
            saved_count = 0
            for name, abbrev in matches:
                name = name.strip()
                name = self._fix_concatenated_name(name)
                name_normalized = re.sub(r"\s+", " ", name)

                # Skip if already processed
                if name_normalized in author_profiles:
                    continue

                department = author_departments.get(name_normalized)

                # Save to authors_raw (no scraping needed - no profile link)
                if not self.db.author_raw_exists(name=name_normalized):
                    try:
                        self.db.save_author_raw(
                            author_id=None,  # No ID available
                            name=name_normalized,
                            alt_name=abbrev,
                            alias=name_normalized,
                            has_info=0,  # No page
                            department=department,
                        )
                        saved_count += 1
                    except Exception as e:
                        logger.debug(
                            f"Error saving impressum author {name_normalized}: {str(e)}"
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

            logger.info("Author profile scraping complete")

            # Count total saved authors
            session = self.db.Session()
            try:
                total_authors = session.query(AuthorRaw).count()
            finally:
                session.close()

            logger.info(
                f"STEP 1 COMPLETE: Impressum authors loaded and scraped ({total_authors} total authors, {authors_queued} profiles scraped in parallel, {saved_count} without profiles)"
            )
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Failed to load impressum authors: {str(e)}")
            # Make sure to stop threads on error
            self.author_scraping_active = False
            for _ in range(self.num_author_worker_threads):
                try:
                    self.author_queue.put(None)
                except:
                    pass
            raise

    def _extract_author_links_from_article(self, soup: BeautifulSoup) -> List[str]:
        """Extract all author links from article page.

        ⚠️ CRITICAL: This extracts links SEPARATELY from the author string.
        Links are stored in articles_raw.author_links as JSON array.
        The author string is extracted separately via _extract_author_string().

        Args:
            soup: BeautifulSoup object of article page

        Returns:
            List of author profile URLs (absolute URLs)
        """
        author_links = []

        # Find all author links (pattern: /impressum/author-name-ld.XXXXX)
        links = soup.find_all("a", href=re.compile(r"/impressum/.*-ld\.\d+"))
        for link in links:
            href = link.get("href", "")
            if href:
                url = self._make_absolute_url(href)
                author_links.append(url)

        return author_links

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract article content (same logic as v2/parent class)."""
        content_selectors = [
            ("div", {"class": lambda x: x and "article-content" in str(x).lower()}),
            ("div", {"class": lambda x: x and "article-body" in str(x).lower()}),
            ("article", {"class": lambda x: x and "content" in str(x).lower()}),
            (
                "div",
                {
                    "class": lambda x: x
                    and "content" in str(x).lower()
                    and "article" in str(x).lower()
                },
            ),
        ]

        for tag_name, attrs in content_selectors:
            element = soup.find(tag_name, attrs=attrs)
            if element:
                # Remove script and style elements
                for script in element(["script", "style", "nav", "footer", "header"]):
                    script.decompose()
                text = element.get_text(separator="\n", strip=True)
                if len(text) > 100:  # Only if meaningful content
                    return text

        # Fallback: get all text
        return soup.get_text(separator="\n", strip=True)

    def scrape_article(self, article_url: str, article_id: str) -> Optional[Dict]:
        """Scrape a single article and save to articles_raw.

        Args:
            article_url: URL of the article
            article_id: Article ID

        Returns:
            Dictionary with article data, or None if failed
        """
        try:
            # Early check: skip if article already exists in database
            if self.db.article_raw_exists(article_id):
                logger.debug(
                    f"Skipping article {article_id} - already exists in database"
                )
                return None

            # Check date limit - skip if older than 1 year
            # We'll check this after scraping to avoid unnecessary requests

            self.rate_limiter.wait(jitter=True)

            if random.random() < 0.1:
                self._set_random_user_agent()

            r = self.session.get(article_url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Extract article data
            title = self._extract_title(soup)
            content = self._extract_content(soup)
            tags_list = self._extract_tags(soup)  # Returns list
            tags = (
                ", ".join(tags_list) if tags_list else None
            )  # Convert to comma-separated string
            category = self._extract_category_from_url(article_url)
            article_date = self._extract_article_date(soup)
            article_updated = self._extract_article_updated_date(soup)
            description = self._extract_description(soup)

            # Check date limit (ensure both datetimes are timezone-aware for comparison)
            if article_date:
                # Make article_date timezone-aware if it's naive
                from datetime import timezone

                if article_date.tzinfo is None:
                    article_date = article_date.replace(tzinfo=timezone.utc)

                if article_date < self.one_year_ago:
                    logger.debug(
                        f"Skipping article {article_id} - older than 1 year ({article_date.date()})"
                    )
                    return None

            # CRITICAL: Extract author string as PLAIN TEXT with NO PROCESSING
            # Do NOT clean, split, normalize, or modify the string in any way
            # The raw string is stored in articles_raw.author for later processing
            author_string = self._extract_author_string(soup)

            # Extract author links separately (stored in articles_raw.author_links as JSON)
            # This is separate from the author string - links are extracted independently
            author_links = self._extract_author_links_from_article(soup)
            author_links_json = json.dumps(author_links) if author_links else None

            # Extract related articles
            related_articles = self._extract_related_articles(soup, article_id)
            # Store both IDs and URLs for related articles
            related_data = [
                {"id": ra["id"], "url": ra["url"]}
                for ra in related_articles
                if ra.get("id")
            ]
            related_articles_json = json.dumps(related_data) if related_data else None

            # Save to articles_raw
            self.db.save_article_raw(
                article_id=article_id,
                title=title,
                content=content,
                tags=tags,
                category=category,
                article_url=article_url,
                article_date=article_date,
                article_updated=article_updated,
                author=author_string,
                author_links=author_links_json,
                description=description,
                related_articles=related_articles_json,
            )

            # Add related articles to queue if they're not already in database
            # This allows related articles to be processed in real-time during scraping
            if (
                related_articles
                and hasattr(self, "scraping_queue")
                and hasattr(self, "scraping_active")
                and self.scraping_active
            ):
                for related_article in related_articles:
                    related_id = related_article.get("id")
                    related_url = related_article.get("url")

                    if related_id and related_url:
                        # Check if not already in database
                        if not self.db.article_raw_exists(related_id):
                            # Add to queue (will be processed by worker threads)
                            try:
                                self.scraping_queue.put(
                                    {"id": related_id, "url": related_url}
                                )
                                logger.debug(
                                    f"Added related article {related_id} to queue from article {article_id}"
                                )
                            except Exception as e:
                                logger.debug(
                                    f"Could not add related article {related_id} to queue: {str(e)}"
                                )

            logger.info(f"Scraped article: {title[:50]}... ({article_id})")

            return {
                "id": article_id,
                "url": article_url,
                "title": title,
                "related_articles": related_articles,
            }

        except Exception as e:
            logger.error(f"Error scraping article {article_id}: {str(e)}")
            return None

    def _article_scraping_worker(self):
        """Worker thread that processes articles from the queue.

        This runs in parallel with scrolling, processing articles as they're discovered.
        """
        thread_name = threading.current_thread().name
        thread_short = thread_name.split("_")[-1]
        successful = 0
        failed = 0
        skipped = 0

        while self.scraping_active:
            try:
                # Get article from queue (blocks until available)
                article = self.scraping_queue.get(timeout=1)

                # Check for sentinel value (stop signal)
                if article is None:
                    self.scraping_queue.task_done()
                    break

                article_id = article.get("id")
                article_url = article.get("url")

                if not article_id or not article_url:
                    self.scraping_queue.task_done()
                    skipped += 1
                    continue

                # Double-check if already exists (race condition protection)
                if self.db.article_raw_exists(article_id):
                    self.scraping_queue.task_done()
                    skipped += 1
                    continue

                try:
                    result = self.scrape_article(article_url, article_id)
                    if result:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    logger.error(
                        f"[{thread_short}] Error scraping article {article_id}: {str(e)}"
                    )

                self.scraping_queue.task_done()

            except:
                # Timeout or other error - continue loop
                continue

        logger.info(
            f"[{thread_short}] Article worker done: {successful}✓ {failed}✗ {skipped}⊘"
        )

    def _scrape_article_batch(self, articles: List[Dict]):
        """Scrape a batch of articles and save to articles_raw.

        Args:
            articles: List of article dictionaries with 'id' and 'url' keys
        """
        for article in articles:
            article_id = article.get("id")
            article_url = article.get("url")

            if not article_id or not article_url:
                continue

            # Check if already exists
            if self.db.article_raw_exists(article_id):
                continue

            try:
                self.scrape_article(article_url, article_id)
            except Exception as e:
                logger.error(f"Error scraping article {article_id}: {str(e)}")

    def _extract_related_articles(
        self, soup: BeautifulSoup, article_id: str
    ) -> List[Dict]:
        """Extract related articles from article page (same as v2)."""
        related_articles = []
        seen_urls = set()
        seen_ids = set()

        related_containers = soup.find_all(
            ["div", "section"], {"data-team-more-to-subject": True}
        )

        related_containers.extend(
            soup.find_all("div", {"class": lambda x: x and "max-w-[640px]" in str(x)})
        )

        for container in related_containers:
            article_elements = container.find_all("article")

            for article_elem in article_elements:
                link = article_elem.find("a", href=True)
                if not link:
                    continue

                href = link.get("href", "")
                if not href:
                    continue

                url = self._make_absolute_url(href)

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                related_id = self._extract_id_from_url(url)
                if not related_id:
                    continue

                if related_id in seen_ids or related_id == article_id:
                    continue
                seen_ids.add(related_id)

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

                related_date = None
                time_elem = article_elem.find("time", {"datetime": True})
                if time_elem:
                    datetime_attr = time_elem.get("datetime")
                    if datetime_attr:
                        try:
                            related_date = datetime.fromisoformat(
                                datetime_attr.replace("Z", "+00:00")
                            )
                        except:
                            try:
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
                            "date": related_date,
                        }
                    )

        return related_articles

    def run(
        self,
        headless: bool = True,
        clean_authors_raw: bool = False,
        clean_articles_raw: bool = False,
    ):
        """Run the scraper v3 with granular steps.

        Args:
            headless: Whether to run browser in headless mode (default: True)
            clean_authors_raw: If True, clean authors_raw table before scraping (default: False)
            clean_articles_raw: If True, clean articles_raw table before scraping (default: False)
        """
        try:
            logger.info("Starting NZZ scraper v3...")

            # Clean specified database tables before scraping (optional, only for testing)
            if clean_authors_raw or clean_articles_raw:
                logger.info("Cleaning specified database tables before scraping...")
                self.db.clean_database(
                    clean_authors_raw=clean_authors_raw,
                    clean_articles_raw=clean_articles_raw,
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

            # STEP 2: Now start article scraping (after impressum authors are done)
            # During article scraping, we will:
            # - Extract related articles from each article page
            # - Extract authors from each article page (stored in articles_raw)
            # - Save related articles to articles_raw
            logger.info("=" * 80)
            logger.info(
                "STEP 2: Starting article scraping (will analyze authors and related articles)..."
            )
            logger.info("=" * 80)

            # First, load all related articles from existing articles in database
            logger.info(
                "Loading related articles from existing articles in database..."
            )
            articles_from_related = 0  # Track articles from related articles
            seen_ids = set()  # Track all article IDs to avoid duplicates
            related_articles_to_queue = []  # Store related articles to add to queue

            session = self.db.Session()
            try:
                all_articles_raw = session.query(ArticleRaw).all()

                for article in all_articles_raw:
                    if article.related_articles:
                        try:
                            related_data = json.loads(article.related_articles)
                            # related_data is a list of dicts with 'id' and 'url'
                            for related_item in related_data:
                                if isinstance(related_item, dict):
                                    related_id = related_item.get("id")
                                    related_url = related_item.get("url")
                                else:
                                    # Backward compatibility: if it's just an ID string
                                    related_id = related_item
                                    related_url = None

                                # CRITICAL: Only add related articles that are NOT already in database
                                # Only add if:
                                # 1. Has valid ID and URL
                                # 2. NOT already in database (checked first - most important)
                                # 3. Not already in seen_ids (to avoid duplicates in this pass)
                                if related_id and related_url:
                                    # Check database first - only add if article doesn't exist
                                    if not self.db.article_raw_exists(related_id):
                                        # Check if not already queued in this pass
                                        if related_id not in seen_ids:
                                            seen_ids.add(related_id)
                                            related_articles_to_queue.append(
                                                {"id": related_id, "url": related_url}
                                            )
                                            articles_from_related += 1
                                        # else: already queued in this pass, skip
                                    else:
                                        # Already in database - skip (do not add to queue)
                                        pass
                        except Exception as e:
                            logger.debug(
                                f"Error parsing related articles for article {article.article_id}: {str(e)}"
                            )
                            pass
            finally:
                session.close()

            if articles_from_related > 0:
                logger.info(
                    f"Found {articles_from_related} related articles to scrape (will be added to queue)"
                )
            else:
                logger.info("No new related articles found (all already in database)")

            # Setup driver for infinite scroll
            if self.driver is None:
                self.setup_driver(headless=headless)

            # Start worker threads to process articles while scrolling
            import threading

            logger.info("=" * 80)
            logger.info(
                f"Starting parallel article scraping threads ({self.num_worker_threads} workers)..."
            )
            logger.info("=" * 80)
            self.scraping_active = True
            self.scraping_threads = []

            for i in range(self.num_worker_threads):
                thread = threading.Thread(
                    target=self._article_scraping_worker,
                    daemon=True,
                    name=f"article_worker_{i+1}",
                )
                thread.start()
                self.scraping_threads.append(thread)

            logger.info(
                f"Started {self.num_worker_threads} article scraping threads (processing queue in real-time)"
            )

            # Add related articles to queue BEFORE scrolling starts
            if articles_from_related > 0:
                logger.info(
                    f"Adding {articles_from_related} related articles to queue..."
                )
                for related_article in related_articles_to_queue:
                    # Double-check it's still not in database (race condition protection)
                    if not self.db.article_raw_exists(related_article["id"]):
                        self.scraping_queue.put(related_article)
                logger.info(
                    f"Added {len(related_articles_to_queue)} related articles to queue"
                )

            # Load page and start scrolling
            logger.info(f"Loading page: {self.articles_url}")
            self.driver.get(self.articles_url)
            time.sleep(2)
            self.rate_limiter.wait(jitter=True)

            scroll_count = 0
            max_scrolls = 500  # Safety limit
            articles_from_scrolling = 0  # Track articles from scrolling

            logger.info(
                "Scrolling to collect articles (1 year limit) - articles will be processed in parallel..."
            )

            while scroll_count < max_scrolls:
                try:
                    # Scroll to bottom
                    self.driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);"
                    )
                    time.sleep(0.5)

                    # Extract articles from current page
                    page_source = self.driver.page_source
                    current_articles = self._extract_articles_from_page_source(
                        page_source
                    )

                    # Add new articles to queue for processing
                    new_articles_in_batch = 0
                    for article in current_articles:
                        article_id = article.get("id")
                        if article_id and article_id not in seen_ids:
                            # Check date if available (ensure timezone-aware for comparison)
                            article_date = article.get("date")
                            if article_date:
                                from datetime import timezone

                                # Make article_date timezone-aware if it's naive
                                if article_date.tzinfo is None:
                                    article_date = article_date.replace(
                                        tzinfo=timezone.utc
                                    )

                                if article_date < self.one_year_ago:
                                    continue  # Skip articles older than 1 year

                            # Check if already exists in database
                            if not self.db.article_raw_exists(article_id):
                                # Add to queue for processing
                                self.scraping_queue.put(article)
                                seen_ids.add(article_id)
                                articles_from_scrolling += 1
                                new_articles_in_batch += 1

                    scroll_count += 1
                    if scroll_count % 10 == 0:
                        queue_size = self.scraping_queue.qsize()
                        logger.info(
                            f"  Scrolled {scroll_count} times, {articles_from_scrolling} articles queued, {queue_size} in queue..."
                        )

                    # Check if we're getting new articles
                    if scroll_count > 20 and len(current_articles) == 0:
                        logger.info("  No more articles found, stopping scroll")
                        break

                except Exception as e:
                    logger.error(f"Error during scrolling: {str(e)}")
                    break

            logger.info(
                f"Scrolling complete: {articles_from_scrolling} articles added to queue"
            )

            # Wait for all articles in queue to be processed
            logger.info("Waiting for all articles to be processed...")
            self.scraping_queue.join()

            # Signal worker threads to stop
            self.scraping_active = False
            for _ in range(self.num_worker_threads):
                self.scraping_queue.put(None)  # Sentinel value to stop threads

            # Wait for all worker threads to finish
            for thread in self.scraping_threads:
                thread.join(timeout=5)

            logger.info(
                f"Article scraping complete: {articles_from_scrolling} articles from scrolling, {articles_from_related} from related articles"
            )
            logger.info(
                "Article scraping complete, waiting for all articles to finish processing..."
            )

            # Summary
            session = self.db.Session()
            try:
                total_articles = session.query(ArticleRaw).count()
                total_authors = session.query(AuthorRaw).count()
            finally:
                session.close()

            logger.info("=" * 80)
            logger.info("SCRAPING SUMMARY (v3)")
            logger.info("=" * 80)
            logger.info(f"Total articles in database: {total_articles}")
            logger.info(f"  - Articles from scrolling: {articles_from_scrolling}")
            logger.info(f"  - Articles from related: {articles_from_related}")
            logger.info(f"Total authors in database: {total_authors}")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Error in run method: {str(e)}", exc_info=True)
        finally:
            if self.driver:
                self.driver.quit()
            # Cleanup method if it exists
            if hasattr(self, "cleanup"):
                self.cleanup()

    def _extract_articles_from_page_source(self, page_source: str) -> List[Dict]:
        """Extract articles from page source (same as parent class)."""
        soup = BeautifulSoup(page_source, "html.parser")
        articles = []
        seen_urls = set()
        seen_ids = set()

        article_elements = soup.find_all("article")

        for article_elem in article_elements:
            link = article_elem.find("a", href=True)
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue

            url = self._make_absolute_url(href)

            if url in seen_urls:
                continue
            seen_urls.add(url)

            article_id = self._extract_id_from_url(url)
            if not article_id:
                continue

            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

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

            article_date = None
            time_elem = article_elem.find("time", {"datetime": True})
            if time_elem:
                datetime_attr = time_elem.get("datetime")
                if datetime_attr:
                    try:
                        article_date = datetime.fromisoformat(
                            datetime_attr.replace("Z", "+00:00")
                        )
                    except:
                        try:
                            from dateutil import parser

                            article_date = parser.parse(datetime_attr)
                        except:
                            pass

            if title:
                articles.append(
                    {"id": article_id, "url": url, "title": title, "date": article_date}
                )

        return articles
