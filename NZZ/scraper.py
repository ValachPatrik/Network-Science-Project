"""NZZ article scraper."""
import os
import time
import random
import logging
import re
import threading
from queue import Queue
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from functools import wraps
from collections import defaultdict
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, InvalidSessionIdException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from database import DatabaseManager

# Get the directory where this script is located (NZZ folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Setup logging - create new log file for each run with timestamp
from datetime import datetime
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_file_path = os.path.join(SCRIPT_DIR, f'nzz_scraper_{timestamp}.log')
error_log_path = os.path.join(SCRIPT_DIR, f'nzz_scraper_errors_{timestamp}.log')

# Create logger
logger = logging.getLogger('nzz_scraper')
logger.setLevel(logging.DEBUG)  # Set to DEBUG to capture all levels

# Remove existing handlers if any
logger.handlers = []

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Custom error formatter class to handle exc_info properly with full verbose output
class ErrorFormatter(logging.Formatter):
    def format(self, record):
        import traceback
        import sys
        
        # Format the basic message
        msg = super().format(record)
        
        # Add file and line number
        if hasattr(record, 'pathname') and hasattr(record, 'lineno'):
            msg += f"\n\nFile: {record.pathname}"
            msg += f"\nLine: {record.lineno}"
            msg += f"\nFunction: {record.funcName if hasattr(record, 'funcName') else 'N/A'}"
        
        # Add full exception info if available
        if record.exc_info:
            msg += "\n\n" + "="*80
            msg += "\nFULL EXCEPTION TRACEBACK:"
            msg += "\n" + "="*80 + "\n"
            msg += ''.join(traceback.format_exception(*record.exc_info))
            msg += "\n" + "="*80
        elif record.exc_text:
            msg += "\n\n" + "="*80
            msg += "\nEXCEPTION TEXT:"
            msg += "\n" + "="*80 + "\n"
            msg += record.exc_text
            msg += "\n" + "="*80
        
        # Add stack trace if available
        if hasattr(record, 'stack_info') and record.stack_info:
            msg += "\n\n" + "="*80
            msg += "\nSTACK TRACE:"
            msg += "\n" + "="*80 + "\n"
            msg += record.stack_info
            msg += "\n" + "="*80
        
        # Add thread information
        if hasattr(record, 'threadName'):
            msg += f"\n\nThread: {record.threadName}"
        if hasattr(record, 'thread'):
            msg += f" (ID: {record.thread})"
        
        # Add process information
        if hasattr(record, 'processName'):
            msg += f"\nProcess: {record.processName}"
        if hasattr(record, 'process'):
            msg += f" (ID: {record.process})"
        
        # Add separator at the end
        msg += "\n\n" + "="*80 + "\n"
        return msg

error_formatter = ErrorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Main log file handler (INFO and above)
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Error log file handler (ERROR and above only)
error_handler = logging.FileHandler(error_log_path, encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(error_formatter)
logger.addHandler(error_handler)

# Console handler (INFO and above)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Log startup info
logger.info(f"Logging initialized - Main log: {log_file_path}")
logger.info(f"Error log: {error_log_path}")


class RateLimiter:
    """Advanced rate limiter to avoid anti-bot detection.
    
    Features:
    - Random delays to mimic human behavior
    - Variable delays based on request type
    - Exponential backoff on errors
    - Request throttling to avoid detection
    """
    def __init__(self, min_delay=2.0, max_delay=5.0, base_delay=2.5):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.base_delay = base_delay
        self.current_delay = base_delay
        self.request_count = 0
        self.last_request_time = 0
        self.error_count = 0
    
    def wait(self, jitter=True):
        """Wait for a delay period with optional randomization.
        
        Args:
            jitter: If True, adds random variation to delay (human-like behavior)
        """
        if jitter:
            # Add random jitter (±20% of delay) to mimic human behavior
            jitter_amount = self.current_delay * 0.2 * (random.random() * 2 - 1)
            delay = max(self.min_delay, self.current_delay + jitter_amount)
        else:
            delay = self.current_delay
        
        # Ensure delay is within bounds
        delay = max(self.min_delay, min(delay, self.max_delay))
        
        # Additional delay if requests are too frequent
        time_since_last = time.time() - self.last_request_time
        if time_since_last < delay:
            time.sleep(delay - time_since_last)
        
        self.last_request_time = time.time()
        self.request_count += 1
        
        # Occasionally add longer pause (human-like behavior)
        if self.request_count % 10 == 0:
            extra_pause = random.uniform(3.0, 8.0)
            logger.debug(f"Taking longer pause after {self.request_count} requests: {extra_pause:.2f}s")
            time.sleep(extra_pause)
    
    def increase_delay(self):
        """Increase delay on errors (exponential backoff)."""
        self.error_count += 1
        # Exponential backoff with cap
        self.current_delay = min(self.current_delay * 1.5, self.max_delay * 2)
        logger.warning(f"Rate limiter: Increased delay to {self.current_delay:.2f}s (error count: {self.error_count})")
    
    def reset_delay(self):
        """Reset delay after successful operation."""
        if self.error_count > 0:
            logger.info(f"Rate limiter: Resetting delay after {self.error_count} errors")
            self.error_count = 0
        self.current_delay = self.base_delay
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics."""
        return {
            'current_delay': self.current_delay,
            'request_count': self.request_count,
            'error_count': self.error_count,
            'last_request_time': self.last_request_time
        }


def retry_on_failure(max_retries=3, initial_delay=2.0):
    """Decorator for retry logic."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed after {max_retries} attempts: {str(e)}")
                        raise
                    logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
            return None
        return wrapper
    return decorator


class NZZScraper:
    """Scraper for NZZ articles."""
    
    def __init__(self, base_url='https://www.nzz.ch', articles_url='https://www.nzz.ch/neueste-artikel'):
        self.base_url = base_url
        self.articles_url = articles_url
        # Enhanced rate limiter with optimized delays to avoid anti-bot detection
        self.rate_limiter = RateLimiter(min_delay=1.0, max_delay=3.0, base_delay=1.5)
        # Database path is automatically set to NZZ folder by DatabaseManager
        self.db = DatabaseManager()
        self.driver = None  # Selenium WebDriver for infinite scroll
        self.session = requests.Session()  # Requests session for article scraping
        # Retry configuration for failed requests
        self.max_retries = 3  # Maximum number of retries for failed requests
        self.retry_delay = 2  # Initial delay between retries (seconds)
        # Rotate user agents to appear more human-like
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
        ]
        self._set_random_user_agent()
        
        # Threading for parallel processing
        self.scraping_queue = Queue()  # Queue for articles to be scraped
        self.scraping_threads = []  # List of threads for batch scraping
        self.scraping_active = False  # Flag to control scraping threads
        self.batch_size = 50  # Process every 50 articles
        self.num_worker_threads = 6  # Number of parallel scraping threads
    
    def setup_driver(self, headless: bool = True):
        """Setup Selenium WebDriver for infinite scroll."""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        # Set user agent
        chrome_options.add_argument(f'user-agent={random.choice(self.user_agents)}')
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.maximize_window()
        logger.info("Selenium WebDriver initialized successfully")
    
    def _set_random_user_agent(self):
        """Set a random user agent to appear more human-like."""
        user_agent = random.choice(self.user_agents)
        self.session.headers.update({
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })
        logger.debug(f"Set User-Agent: {user_agent[:50]}...")
    
    def _make_absolute_url(self, url: str) -> str:
        """Convert relative URL to absolute URL."""
        if url.startswith('http'):
            return url
        if url.startswith('/'):
            return f"{self.base_url}{url}"
        return f"{self.base_url}/{url}"
    
    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extract article ID from URL (pattern: ld.XXXXX).
        
        This ID is used to uniquely identify articles and compare them
        with articles already in the database.
        """
        # Primary pattern: ld.XXXXX (e.g., ld.1909637)
        match = re.search(r'ld\.(\d+)', url)
        if match:
            article_id = match.group(1)
            logger.debug(f"Extracted article ID '{article_id}' from URL: {url}")
            return article_id
        
        # Fallback: use last part of URL as ID
        parts = url.strip('/').split('/')
        if parts:
            fallback_id = parts[-1].replace('.html', '').replace('.htm', '')
            logger.debug(f"Using fallback ID '{fallback_id}' from URL: {url}")
            return fallback_id
        
        logger.warning(f"Could not extract article ID from URL: {url}")
        return None
    
    def _extract_category_from_url(self, url: str) -> Optional[str]:
        """Extract category from URL path (e.g., /zuerich/, /wirtschaft/)."""
        # URL pattern: https://www.nzz.ch/category/article-slug-ld.XXXXX
        parts = url.replace(self.base_url, '').strip('/').split('/')
        if len(parts) > 0:
            category = parts[0]
            # Filter out common non-category paths
            if category not in ['neueste-artikel', 'visuals', 'video', 'podcast']:
                return category
        return None
    
    def get_article_list_from_page(self, page_url: str) -> List[Dict]:
        """Get list of articles from a single page.
        
        Args:
            page_url: URL of the page to scrape
            
        Returns:
            List of article dictionaries with 'id', 'url', and 'title' keys.
        """
        try:
            logger.info(f"Fetching article list from {page_url}")
            # Wait with jitter for human-like behavior
            self.rate_limiter.wait(jitter=True)
            
            # Occasionally rotate user agent
            if random.random() < 0.1:  # 10% chance
                self._set_random_user_agent()
            
            r = self.session.get(page_url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            
            articles = []
            seen_urls = set()
            seen_ids = set()
            
            # Find all article elements
            article_elements = soup.find_all('article')
            logger.info(f"Found {len(article_elements)} article elements on page")
            
            if len(article_elements) == 0:
                logger.warning(f"No article elements found on page {page_url}")
                return articles
            
            for article_elem in article_elements:
                # Find link inside article
                link = article_elem.find('a', href=True)
                if not link:
                    continue
                
                href = link.get('href', '')
                if not href:
                    continue
                
                url = self._make_absolute_url(href)
                
                # Skip if already seen (duplicate URL)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                
                # Extract article ID
                article_id = self._extract_id_from_url(url)
                if not article_id:
                    logger.warning(f"Could not extract ID from URL: {url}")
                    continue
                
                # Skip if duplicate ID (different URL, same ID)
                if article_id in seen_ids:
                    logger.debug(f"Skipping duplicate article ID: {article_id} (URL: {url})")
                    continue
                seen_ids.add(article_id)
                
                # Extract title
                title = link.get_text(strip=True)
                if not title:
                    # Try to find title in article element
                    title_elem = article_elem.find(['h1', 'h2', 'h3'])
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                
                if title:
                    articles.append({
                        'id': article_id,
                        'url': url,
                        'title': title
                    })
                else:
                    logger.warning(f"Article {article_id} has no title, skipping")
            
            logger.info(f"Extracted {len(articles)} unique articles from page")
            return articles
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.info(f"Page {page_url} returned 404 (page does not exist)")
                return []
            else:
                logger.error(f"HTTP error fetching page {page_url}: {str(e)}")
                return []
        except Exception as e:
            logger.error(f"Error fetching article list from {page_url}: {str(e)}", exc_info=True)
            return []
    
    def _extract_articles_from_page_source(self, page_source: str) -> List[Dict]:
        """Extract articles from page HTML source, including dates if available."""
        soup = BeautifulSoup(page_source, 'html.parser')
        articles = []
        seen_urls = set()
        seen_ids = set()
        
        # Find all article elements
        article_elements = soup.find_all('article')
        
        for article_elem in article_elements:
            # Find link inside article
            link = article_elem.find('a', href=True)
            if not link:
                continue
            
            href = link.get('href', '')
            if not href:
                continue
            
            url = self._make_absolute_url(href)
            
            # Skip if already seen
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            # Extract article ID
            article_id = self._extract_id_from_url(url)
            if not article_id:
                continue
            
            # Skip if duplicate ID
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)
            
            # Extract title
            title = link.get_text(strip=True)
            if not title:
                title_elem = article_elem.find(['h1', 'h2', 'h3'])
                if title_elem:
                    title = title_elem.get_text(strip=True)
            
            # Try to extract date from list page
            article_date = None
            # Look for time element with datetime attribute
            time_elem = article_elem.find('time', {'datetime': True})
            if time_elem:
                try:
                    from dateutil import parser
                    date_str = time_elem.get('datetime', '')
                    if date_str:
                        article_date = parser.parse(date_str)
                except:
                    pass
            
            # If no date found, try to extract from text
            if not article_date:
                time_elem = article_elem.find('time')
                if time_elem:
                    try:
                        from dateutil import parser
                        date_text = time_elem.get_text(strip=True)
                        if date_text:
                            article_date = parser.parse(date_text, fuzzy=True)
                    except:
                        pass
            
            if title:
                articles.append({
                    'id': article_id,
                    'url': url,
                    'title': title,
                    'date': article_date  # May be None if not found on list page
                })
        
        return articles
    
    def get_article_list(self, max_articles: Optional[int] = None) -> List[Dict]:
        """Get list of articles using infinite scroll with weekly batch scraping.
        
        Scrolls down the page until 1 year of articles is reached.
        Scrapes articles in weekly batches while scrolling continues.
        
        Args:
            max_articles: Deprecated - not used anymore. Only stops when 1 year of data is reached.
        
        Returns:
            List of article dictionaries with 'id', 'url', 'title', and 'date' keys.
            The 'id' is extracted from the URL and used to compare with existing articles.
            Duplicate URLs and IDs are filtered out.
        """
        if self.driver is None:
            logger.info("Setting up Selenium WebDriver for infinite scroll...")
            self.setup_driver(headless=False)  # Open browser like ZEIT scraper
        
        all_articles = []
        seen_urls = set()
        seen_ids = set()
        
        # Make one_year_ago timezone-aware for comparison
        from datetime import timezone
        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        oldest_article_date = None
        one_year_limit_reached = False
        
        # Start multiple background scraping threads for parallel processing
        self.scraping_active = True
        self.scraping_threads = []
        for i in range(self.num_worker_threads):
            thread = threading.Thread(
                target=self._scraping_worker,
                daemon=True,
                name=f"scraping_worker_{i+1}"
            )
            thread.start()
            self.scraping_threads.append(thread)
        logger.info(f"Started {self.num_worker_threads} background scraping threads for parallel processing")
        
        try:
            logger.info(f"Loading page: {self.articles_url}")
            self.driver.get(self.articles_url)
            
            # Wait for initial page load
            time.sleep(1)
            self.rate_limiter.wait(jitter=True)
            
            logger.info("Starting infinite scroll with parallel batch scraping (every 50 articles)...")
            logger.info(f"Target: Articles from the last year (since {one_year_ago.date()})")
            logger.info("Stop condition: Only when 1 year of data is reached")
            
            while not one_year_limit_reached:
                # Scroll to bottom
                try:
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    # Minimal wait for content to load (faster scrolling)
                    time.sleep(0.1)  # Reduced from 0.5s for faster scrolling
                    
                    # Extract articles from current page source
                    page_source = self.driver.page_source
                except InvalidSessionIdException:
                    logger.error("Browser session was closed/disconnected. Stopping collection.")
                    break
                except Exception as e:
                    logger.error(f"Error during scrolling: {str(e)}")
                    break
                
                current_articles = self._extract_articles_from_page_source(page_source)
                
                # Add new articles and check dates
                new_articles_this_scroll = []
                for article in current_articles:
                    article_id = article.get('id')
                    article_url = article.get('url')
                    
                    if article_url not in seen_urls and article_id not in seen_ids:
                        # If article doesn't have date from list page, we'll need to scrape it
                        # For now, add it and we'll get the date when scraping
                        article_date = article.get('date')
                        
                        # Add article first, then check date
                        all_articles.append(article)
                        seen_urls.add(article_url)
                        seen_ids.add(article_id)
                        new_articles_this_scroll.append(article)
                        
                        # If we have a date and it's older than 1 year, stop collecting
                        if article_date:
                            # Make sure both dates are timezone-aware for comparison
                            if article_date.tzinfo is None:
                                # If article_date is naive, assume UTC
                                article_date = article_date.replace(tzinfo=timezone.utc)
                            
                            if article_date < one_year_ago:
                                logger.info(f"Reached 1 year limit. Oldest article: {article_date.date()}")
                                one_year_limit_reached = True
                                break
                            
                            if oldest_article_date is None or article_date < oldest_article_date:
                                oldest_article_date = article_date
                
                # Add new articles to scraping queue (parallel processing)
                if new_articles_this_scroll:
                    for article in new_articles_this_scroll:
                        self.scraping_queue.put(article)
                    logger.info(f"Found {len(all_articles)} articles so far. Added {len(new_articles_this_scroll)} to queue (queue size: {self.scraping_queue.qsize()})")
                
                # Break if 1 year limit reached
                if one_year_limit_reached:
                    break
            
            logger.info(f"Infinite scroll complete: Found {len(all_articles)} unique articles")
            
            # Wait for scraping queue to be processed
            logger.info(f"Waiting for scraping queue to be processed (queue size: {self.scraping_queue.qsize()})...")
            self.scraping_queue.join()  # Wait for all items to be processed
            logger.info("All articles in queue have been processed")
            
        except Exception as e:
            logger.error(f"Error during infinite scroll: {str(e)}", exc_info=True)
        finally:
            # Stop scraping threads
            self.scraping_active = False
            # Put sentinel values to wake up all threads
            for _ in range(self.num_worker_threads):
                self.scraping_queue.put(None)
            
            # Wait for all threads to complete
            for i, thread in enumerate(self.scraping_threads):
                if thread and thread.is_alive():
                    logger.info(f"Waiting for scraping thread {i+1}/{self.num_worker_threads} to complete...")
                    thread.join(timeout=30)  # Wait up to 30 seconds per thread
                    if thread.is_alive():
                        logger.warning(f"Scraping thread {i+1} did not complete within timeout")
                    else:
                        logger.info(f"Scraping thread {i+1} completed successfully")
            logger.info(f"All {self.num_worker_threads} background scraping threads stopped")
            # Don't close driver here - might be used for other operations
            pass
        
        return all_articles
    
    def _scraping_worker(self):
        """Background worker thread that processes articles from the queue in batches."""
        thread_name = threading.current_thread().name
        articles_batch = []
        batch_size = self.batch_size
        
        thread_short = thread_name.split('_')[-1] if '_' in thread_name else thread_name
        logger.info(f"[{thread_short}] Worker started")
        
        while self.scraping_active:
            try:
                # Get article from queue (with timeout to check if still active)
                try:
                    article = self.scraping_queue.get(timeout=1)
                except:
                    continue
                
                # Check for sentinel value (None) to stop
                if article is None:
                    break
                
                # Add to batch
                articles_batch.append(article)
                
                # If we have enough articles for a batch, scrape them
                if len(articles_batch) >= batch_size:
                    batch_to_scrape = articles_batch[:batch_size]
                    articles_batch = articles_batch[batch_size:]
                    thread_short = thread_name.split('_')[-1] if '_' in thread_name else thread_name
                    logger.info(f"[{thread_short}] Batch: {len(batch_to_scrape)} (queue: {self.scraping_queue.qsize()})")
                    self._scrape_article_batch(batch_to_scrape)
                    # Mark task as done
                    for _ in range(batch_size):
                        self.scraping_queue.task_done()
                
            except Exception as e:
                logger.error(f"[{thread_name}] Error in scraping worker: {str(e)}", exc_info=True)
        
        # Process any remaining articles in batch
        if articles_batch:
            thread_short = thread_name.split('_')[-1] if '_' in thread_name else thread_name
            logger.info(f"[{thread_short}] Final batch: {len(articles_batch)} articles")
            self._scrape_article_batch(articles_batch)
            # Mark remaining tasks as done
            for _ in range(len(articles_batch)):
                self.scraping_queue.task_done()
        
        thread_short = thread_name.split('_')[-1] if '_' in thread_name else thread_name
        logger.info(f"[{thread_short}] Worker stopped")
    
    def _scrape_article_batch(self, articles: List[Dict]) -> None:
        """Scrape a batch of articles (can run in parallel with scrolling)."""
        thread_name = threading.current_thread().name
        thread_short = thread_name.split('_')[-1] if '_' in thread_name else thread_name
        logger.info(f"[{thread_short}] Batch: {len(articles)} articles")
        
        successful = 0
        failed = 0
        # Make one_year_ago timezone-aware for comparison
        from datetime import timezone
        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        
        skipped = 0
        for article in articles:
            article_id = article.get('id')
            article_url = article.get('url')
            
            if not article_id:
                logger.warning(f"[{thread_short}] Missing ID: {article_url[:60]}...")
                skipped += 1
                continue
            
            # Skip if already in database
            if self.db.article_exists(article_id):
                skipped += 1
                logger.info(f"[{thread_short}] Skip {article_id} (exists)")
                continue
            
            try:
                article_data = self.scrape_article(article_url, article_id)
                if article_data and article_data.get('content'):
                    # Check date - if older than 1 year, stop
                    article_date = article_data.get('article_date')
                    if article_date:
                        # Make sure both dates are timezone-aware for comparison
                        if article_date.tzinfo is None:
                            # If article_date is naive, assume UTC
                            from datetime import timezone
                            article_date = article_date.replace(tzinfo=timezone.utc)
                        
                        if article_date < one_year_ago:
                            logger.info(f"[{thread_short}] 1yr limit reached: {article_date.date()}")
                            return
                    
                    # Final check before saving
                    if self.db.article_exists(article_id):
                        skipped += 1
                        continue
                    
                    # Save to database
                    self.db.save_article(
                        article_id=article_data['id'],
                        title=article_data['title'],
                        content=article_data['content'],
                        tags=article_data.get('tags', []),
                        article_url=article_data['url'],
                        article_date=article_data.get('article_date'),
                        article_updated=article_data.get('article_updated'),
                        author=article_data.get('author'),
                        description=article_data.get('description'),
                        category=article_data.get('category'),
                        scraped_at=article_data.get('scraped_at')
                    )
                    successful += 1
                    title_short = article_data.get('title', 'Untitled')[:40]
                    logger.info(f"[{thread_short}] ✓ {article_id}: {title_short}...")
                else:
                    failed += 1
                    logger.warning(f"[{thread_short}] ✗ {article_id}: No content")
            except Exception as e:
                failed += 1
                logger.error(f"[{thread_short}] ✗ {article_id}: {str(e)}", exc_info=True)
        
        logger.info(f"[{thread_short}] Done: {successful}✓ {failed}✗ {skipped}⊘")
    
    @retry_on_failure(max_retries=3, initial_delay=2.0)
    def scrape_article(self, article_url: str, article_id: str) -> Optional[Dict]:
        """Scrape a single article with retry logic.
        
        Note: This method does NOT check if the article exists in the database.
        The caller should verify article existence before calling this method.
        """
        try:
            # Wait with jitter for human-like behavior
            self.rate_limiter.wait(jitter=True)
            
            # Occasionally rotate user agent
            if random.random() < 0.1:  # 10% chance
                self._set_random_user_agent()
            
            # Retry logic for network/server errors
            r = None
            last_error = None
            for attempt in range(self.max_retries + 1):  # 0 to max_retries (inclusive)
                try:
                    r = self.session.get(article_url, timeout=30)
                    # Handle server errors gracefully
                    if r.status_code == 502:
                        if attempt < self.max_retries:
                            wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                            logger.warning(f"502 Bad Gateway for {article_id}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.warning(f"502 Bad Gateway for {article_id} after {self.max_retries + 1} attempts, skipping")
                            return None
                    if r.status_code == 504:
                        if attempt < self.max_retries:
                            wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                            logger.warning(f"504 Gateway Timeout for {article_id}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.warning(f"504 Gateway Timeout for {article_id} after {self.max_retries + 1} attempts, skipping")
                            return None
                    r.raise_for_status()
                    # Success - break out of retry loop
                    break
                except requests.exceptions.ChunkedEncodingError as e:
                    last_error = e
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"ChunkedEncodingError for {article_id} (response ended prematurely), retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"ChunkedEncodingError for {article_id} after {self.max_retries + 1} attempts, skipping: {str(e)}")
                        return None
                except requests.exceptions.Timeout as e:
                    last_error = e
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Timeout for {article_id}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"Timeout for {article_id} after {self.max_retries + 1} attempts, skipping: {str(e)}")
                        return None
                except requests.exceptions.ConnectionError as e:
                    last_error = e
                    if attempt < self.max_retries:
                        wait_time = self.retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"ConnectionError for {article_id}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries + 1})")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"ConnectionError for {article_id} after {self.max_retries + 1} attempts, skipping: {str(e)}")
                        return None
                except requests.exceptions.HTTPError as e:
                    # For other HTTP errors (not 502/504), don't retry
                    logger.error(f"HTTPError for {article_id}: {str(e)}", exc_info=True)
                    self.rate_limiter.increase_delay()
                    raise
            
            # If we get here and r is None, something went wrong
            if r is None:
                logger.error(f"Failed to get response for {article_id} after {self.max_retries + 1} attempts")
                return None
            
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Extract title
            title = self._extract_title(soup)
            
            # Extract content
            content = self._extract_content(soup)
            
            # Extract tags (Step 1: from news_keywords meta tag)
            tags = self._extract_tags(soup)
            
            # Extract category (Step 2: from URL path)
            category = self._extract_category_from_url(article_url)
            
            # Extract publication date
            article_date = self._extract_article_date(soup)
            
            # Extract updated date
            article_updated = self._extract_article_updated_date(soup)
            
            # Extract author
            author = self._extract_author(soup)
            
            # Extract description
            description = self._extract_description(soup)
            
            # Record exact scraped time (down to the second)
            scraped_at = datetime.utcnow().replace(microsecond=0)
            
            article_data = {
                'id': article_id,
                'title': title,
                'content': content,
                'tags': tags,
                'category': category,
                'url': article_url,
                'article_date': article_date,
                'article_updated': article_updated,
                'author': author,
                'description': description,
                'scraped_at': scraped_at
            }
            
            # Verify we got meaningful content
            if not content or len(content.strip()) < 50:
                logger.warning(f"Minimal content: {article_id}")
                return None
            self.rate_limiter.reset_delay()
            return article_data
            
        except Exception as e:
            logger.error(f"Error: {article_id} - {str(e)}", exc_info=True)
            self.rate_limiter.increase_delay()
            raise
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title."""
        # Try h1 first
        title = soup.find('h1')
        if title:
            title_text = title.get_text(strip=True)
            if title_text:
                return title_text
        
        # Try meta og:title
        og_title = soup.find('meta', {'property': 'og:title'})
        if og_title and og_title.get('content'):
            return og_title.get('content').strip()
        
        # Try meta title
        meta_title = soup.find('meta', {'name': 'title'})
        if meta_title and meta_title.get('content'):
            return meta_title.get('content').strip()
        
        return "Untitled"
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract article content."""
        content_selectors = [
            ('div', {'class': lambda x: x and 'article-content' in str(x).lower()}),
            ('div', {'class': lambda x: x and 'article-body' in str(x).lower()}),
            ('article', {'class': lambda x: x and 'content' in str(x).lower()}),
            ('div', {'class': lambda x: x and 'content' in str(x).lower() and 'article' in str(x).lower()}),
        ]
        
        for tag_name, attrs in content_selectors:
            element = soup.find(tag_name, attrs=attrs)
            if element:
                # Remove script and style elements
                for script in element(['script', 'style', 'nav', 'footer', 'header']):
                    script.decompose()
                text = element.get_text(separator='\n', strip=True)
                if len(text) > 100:  # Only if meaningful content
                    return text
        
        # Fallback: get all text
        return soup.get_text(separator='\n', strip=True)
    
    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract tags - Step 1: from news_keywords meta tag, Step 2: filter generic keywords."""
        tags = []
        
        # Step 1: Extract from news_keywords meta tag
        news_keywords = soup.find('meta', {'name': 'news_keywords'})
        if news_keywords and news_keywords.get('content'):
            keywords_str = news_keywords.get('content', '')
            # Split by comma
            keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
            tags.extend(keywords)
        
        # Step 2: Filter out generic keywords
        generic_keywords = ['Nachrichten', 'NZZ', 'News', 'Article']
        filtered_tags = [tag for tag in tags if tag not in generic_keywords]
        
        return filtered_tags
    
    def _extract_article_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract article publication date."""
        # Try time element with datetime attribute
        time_elem = soup.find('time', datetime=True)
        if time_elem:
            datetime_attr = time_elem.get('datetime')
            if datetime_attr:
                try:
                    date_obj = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                    return date_obj
                except Exception as e:
                    logger.debug(f"Error parsing datetime attribute: {str(e)}")
        
        # Try meta date tag
        meta_date = soup.find('meta', {'name': 'date'})
        if meta_date and meta_date.get('content'):
            try:
                date_str = meta_date.get('content', '').replace('Z', '+00:00')
                date_obj = datetime.fromisoformat(date_str)
                return date_obj
            except:
                pass
        
        return None
    
    def _extract_article_updated_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract article updated/modified date."""
        # Try meta last-modified tag
        meta_modified = soup.find('meta', {'name': 'last-modified'})
        if meta_modified and meta_modified.get('content'):
            try:
                date_str = meta_modified.get('content', '').replace('Z', '+00:00')
                date_obj = datetime.fromisoformat(date_str)
                logger.debug(f"Found updated date in meta tag: {date_obj}")
                return date_obj
            except:
                pass
        
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author."""
        # Try meta author tag
        meta_author = soup.find('meta', {'name': 'author'})
        if meta_author and meta_author.get('content'):
            author = meta_author.get('content', '').strip()
            if author:
                logger.debug(f"Found author in meta tag: {author}")
                return author
        
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article description."""
        # Try meta description tag
        meta_desc = soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc.get('content', '').strip()
            if desc:
                return desc
        
        # Try og:description
        og_desc = soup.find('meta', {'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            desc = og_desc.get('content', '').strip()
            if desc:
                return desc
        
        return None
    
    def run(self, headless: bool = False):
        """Main method to run the scraping process."""
        try:
            logger.info("Starting NZZ scraper...")
            
            # Get article list
            articles = self.get_article_list()
            if not articles:
                logger.warning("No articles found")
                return
            
            logger.info(f"Found {len(articles)} articles on the page")
            
            # Get already scraped article IDs from database
            scraped_ids = self.db.get_all_scraped_ids()
            logger.info(f"Found {len(scraped_ids)} articles already in database")
            
            # Filter out already scraped articles by comparing IDs
            new_articles = []
            skipped_articles = []
            
            for article in articles:
                article_id = article.get('id')
                if not article_id:
                    logger.warning(f"Skipping article without ID: {article.get('url', 'unknown')}")
                    continue
                
                # Check if article already exists in database
                if self.db.article_exists(article_id):
                    skipped_articles.append(article)
                    logger.debug(f"Skipping already scraped article: {article_id} - {article.get('title', 'Untitled')[:50]}")
                else:
                    new_articles.append(article)
            
            logger.info(f"Articles comparison complete:")
            logger.info(f"  - Total articles found: {len(articles)}")
            logger.info(f"  - Already in database: {len(skipped_articles)}")
            logger.info(f"  - New articles to scrape: {len(new_articles)}")
            
            if not new_articles:
                logger.info("No new articles to scrape. All articles are already in the database.")
                return
            
            # Scrape only new articles
            successful_scrapes = 0
            failed_scrapes = 0
            
            for idx, article in enumerate(new_articles, 1):
                article_id = article.get('id')
                article_url = article.get('url')
                article_title = article.get('title', 'Untitled')
                
                logger.info(f"Processing new article {idx}/{len(new_articles)}: {article_title[:60]}...")
                
                # Double-check that article doesn't exist (in case it was added during scraping)
                if self.db.article_exists(article_id):
                    logger.info(f"  → Article {article_id} was already scraped (skipping)")
                    skipped_articles.append(article)
                    continue
                
                try:
                    article_data = self.scrape_article(article_url, article_id)
                    if article_data and article_data.get('content'):
                        # Final check before saving (race condition protection)
                        if self.db.article_exists(article_id):
                            logger.warning(f"  → Article {article_id} was added to database during scraping (skipping save)")
                            skipped_articles.append(article)
                            continue
                        
                        # Save to database with all metadata
                        saved_article = self.db.save_article(
                            article_id=article_data['id'],
                            title=article_data['title'],
                            content=article_data['content'],
                            tags=article_data.get('tags', []),
                            article_url=article_data['url'],
                            article_date=article_data.get('article_date'),
                            article_updated=article_data.get('article_updated'),
                            author=article_data.get('author'),
                            description=article_data.get('description'),
                            category=article_data.get('category'),
                            scraped_at=article_data.get('scraped_at')
                        )
                        successful_scrapes += 1
                        logger.info(f"  ✓ Saved article {idx}/{len(new_articles)}: {article_data['title'][:50]}...")
                    else:
                        failed_scrapes += 1
                        logger.warning(f"  ✗ Failed to scrape article {idx}/{len(new_articles)}: {article_title[:50]}...")
                except Exception as e:
                    failed_scrapes += 1
                    logger.error(f"  ✗ Error scraping article {idx}/{len(new_articles)}: {str(e)}")
                    continue
            
            # Summary
            total_in_db = self.db.get_article_count()
            logger.info("="*80)
            logger.info("SCRAPING SUMMARY")
            logger.info("="*80)
            logger.info(f"Total articles found on page: {len(articles)}")
            logger.info(f"Already in database (skipped): {len(skipped_articles)}")
            logger.info(f"New articles processed: {len(new_articles)}")
            logger.info(f"Successfully scraped: {successful_scrapes}")
            logger.info(f"Failed to scrape: {failed_scrapes}")
            logger.info(f"Total articles in database now: {total_in_db}")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"Error in run method: {str(e)}", exc_info=True)
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Selenium WebDriver closed")
            except Exception as e:
                logger.warning(f"Error closing WebDriver: {str(e)}")
        self.db.close()
        self.session.close()

