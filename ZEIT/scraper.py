"""Main scraping script for articles."""
import os
import time
import random
import logging
from datetime import datetime
from typing import List, Dict, Optional
from functools import wraps
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from database import DatabaseManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter with exponential backoff."""
    
    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, backoff_factor: float = 2.0):
        """
        Initialize rate limiter.
        
        Args:
            base_delay: Base delay in seconds between requests
            max_delay: Maximum delay in seconds
            backoff_factor: Factor to multiply delay on errors
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.current_delay = base_delay
        self.last_request_time = 0
    
    def wait(self):
        """Wait before making next request."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.current_delay:
            sleep_time = self.current_delay - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def increase_delay(self):
        """Increase delay due to error (exponential backoff)."""
        self.current_delay = min(self.current_delay * self.backoff_factor, self.max_delay)
        logger.info(f"Rate limit increased to {self.current_delay:.2f}s")
    
    def reset_delay(self):
        """Reset delay to base after successful request."""
        self.current_delay = self.base_delay


def retry_on_failure(max_retries: int = 3, initial_delay: float = 1.0, backoff_factor: float = 2.0):
    """Decorator for retrying failed operations."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {str(e)}")
            
            raise last_exception
        return wrapper
    return decorator


class ArticleScraper:
    """Main class for scraping articles from a website."""
    
    def __init__(self, base_url: str, login_url: str = None, 
                 request_delay: float = 2.0, max_retries: int = 3):
        """
        Initialize the scraper.
        
        Args:
            base_url: Base URL of the website
            login_url: URL for login page (defaults to base_url + '/login')
            request_delay: Delay between requests in seconds
            max_retries: Maximum number of retries for failed operations
        """
        self.base_url = base_url.rstrip('/')
        self.login_url = login_url or f"{self.base_url}/login"
        self.driver = None
        self.db = DatabaseManager()
        self.session = None
        self.rate_limiter = RateLimiter(base_delay=request_delay, max_delay=60.0)
        self.max_retries = max_retries
        self.is_logged_in = False
        
    def setup_driver(self, headless: bool = False):
        """Setup Selenium WebDriver."""
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.maximize_window()
        logger.info("WebDriver initialized successfully")
    
    def _handle_cookies(self):
        """Handle cookie consent dialogs."""
        try:
            logger.info("Checking for cookie consent dialogs...")
            # Wait a bit for page to fully load
            time.sleep(2)
            
            # Check if driver is still valid
            try:
                self.driver.current_url
            except:
                logger.error("Driver session invalid")
                return False
            
            wait = WebDriverWait(self.driver, 15)
            
            # Try to find cookie dialog in iframes first
            try:
                iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
                logger.info(f"Found {len(iframes)} iframes, checking for cookie dialog...")
                for iframe in iframes:
                    try:
                        self.driver.switch_to.frame(iframe)
                        # Zeit.de specific: "Agree and continue" button
                        cookie_button = self.driver.find_elements(By.XPATH, '//button[@title="Agree and continue"]')
                        if not cookie_button:
                            cookie_button = self.driver.find_elements(By.XPATH, '//button[@aria-label="Agree and continue"]')
                        if not cookie_button:
                            cookie_button = self.driver.find_elements(By.CSS_SELECTOR, 'button.btn-advisorycolumn.green')
                        
                        if cookie_button:
                            btn = cookie_button[0]
                            if btn.is_displayed():
                                logger.info(f"Found cookie button in iframe, clicking: {btn.text}")
                                self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                                time.sleep(0.5)
                                btn.click()
                                self.driver.switch_to.default_content()
                                time.sleep(3)
                                logger.info("Cookie consent accepted via iframe")
                                return True
                        self.driver.switch_to.default_content()
                    except Exception as e:
                        self.driver.switch_to.default_content()
                        continue
            except Exception as e:
                logger.debug(f"No iframes found or error checking iframes: {str(e)}")
            
            # Zeit.de specific cookie consent selectors (based on the actual dialog)
            cookie_selectors = [
                # Zeit.de specific: "Agree and continue" button - exact match
                (By.XPATH, '//button[@title="Agree and continue"]'),
                (By.XPATH, '//button[@aria-label="Agree and continue"]'),
                (By.XPATH, '//button[contains(@class, "btn-advisorycolumn") and contains(@class, "green")]'),
                (By.XPATH, '//button[contains(@class, "sp_choice_type_11")]'),
                (By.CSS_SELECTOR, 'button.btn-advisorycolumn.green'),
                (By.CSS_SELECTOR, 'button[title="Agree and continue"]'),
                (By.CSS_SELECTOR, 'button[aria-label="Agree and continue"]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "agree and continue")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "zustimmen und fortfahren")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "einverstanden und weiter")]'),
                # Common cookie consent selectors
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "akzeptieren")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "accept")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "zulassen")]'),
            ]
            
            for by, selector in cookie_selectors:
                try:
                    cookie_button = wait.until(EC.element_to_be_clickable((by, selector)))
                    if cookie_button and cookie_button.is_displayed():
                        logger.info(f"Found cookie consent dialog, clicking button with text: {cookie_button.text}")
                        # Scroll to button if needed
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cookie_button)
                        time.sleep(0.5)
                        # Try JavaScript click if regular click fails
                        try:
                            cookie_button.click()
                        except:
                            self.driver.execute_script("arguments[0].click();", cookie_button)
                        time.sleep(3)  # Wait for dialog to close
                        logger.info("Cookie consent accepted")
                        return True
                except (TimeoutException, NoSuchElementException):
                    continue
            
            logger.info("No cookie consent dialog found")
            return False
        except Exception as e:
            logger.warning(f"Error handling cookies: {str(e)}")
            return False
    
    def _navigate_to_login(self):
        """Navigate to login page, handling cookie dialogs and login button clicks."""
        try:
            logger.info(f"Navigating to base URL to find login page...")
            
            # Check if driver is valid
            try:
                self.driver.current_url
            except:
                logger.error("Driver session invalid before navigation")
                return False
            
            self.driver.get(self.base_url)
            self.rate_limiter.wait()
            time.sleep(3)  # Give page time to load
            
            # Handle cookies
            cookie_handled = self._handle_cookies()
            if cookie_handled:
                logger.info("Cookie consent handled successfully")
            time.sleep(2)
            
            # If we're already on login page, return
            current_url = self.driver.current_url.lower()
            if 'login' in current_url or 'anmeldung' in current_url or 'keycloak' in current_url:
                logger.info("Already on login page")
                return True
            
            # Try to find and click login/anmeldung link/button
            logger.info("Looking for login/anmeldung button...")
            wait = WebDriverWait(self.driver, 10)
            
            # Zeit.de specific: First click the account menu button, then click "Anmelden"
            try:
                # Step 1: Find and click the account menu button
                logger.info("Looking for account menu button...")
                account_menu_selectors = [
                    (By.CSS_SELECTOR, 'a.navigation__button--account'),
                    (By.CSS_SELECTOR, 'a[class*="navigation__button--account"]'),
                    (By.XPATH, '//a[contains(@class, "navigation__button--account")]'),
                    (By.XPATH, '//a[@aria-controls="navigation-content-account"]'),
                ]
                
                account_menu_button = None
                for by, selector in account_menu_selectors:
                    try:
                        account_menu_button = wait.until(EC.element_to_be_clickable((by, selector)))
                        if account_menu_button and account_menu_button.is_displayed():
                            logger.info("Found account menu button, clicking to open menu...")
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", account_menu_button)
                            time.sleep(0.5)
                            account_menu_button.click()
                            time.sleep(2)  # Wait for menu to open
                            logger.info("Account menu opened")
                            break
                    except (TimeoutException, NoSuchElementException):
                        continue
                
                # Step 2: Now find and click the "Anmelden" link inside the menu
                if account_menu_button:
                    logger.info("Looking for 'Anmelden' link in menu...")
                    time.sleep(1)  # Give menu time to fully open
                    
                    login_selectors = [
                        (By.CSS_SELECTOR, 'a.navigation-link--login'),
                        (By.CSS_SELECTOR, 'a[class*="navigation-link--login"]'),
                        (By.XPATH, '//a[contains(@class, "navigation-link--login")]'),
                        (By.XPATH, '//a[contains(@href, "anmelden")]'),
                        (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmelden")]'),
                        (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmeldung")]'),
                        (By.XPATH, '//span[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmelden")]/parent::a'),
                    ]
                    
                    for by, selector in login_selectors:
                        try:
                            login_element = wait.until(EC.element_to_be_clickable((by, selector)))
                            if login_element and login_element.is_displayed():
                                logger.info(f"Found 'Anmelden' link, clicking... (href: {login_element.get_attribute('href')})")
                                # Use JavaScript click to ensure it works even if menu is animating
                                self.driver.execute_script("arguments[0].click();", login_element)
                                time.sleep(3)  # Wait for navigation
                                
                                # Check if we're now on login page
                                current_url = self.driver.current_url.lower()
                                if 'anmelden' in current_url or 'login' in current_url or 'account' in current_url:
                                    logger.info(f"Successfully navigated to login page: {self.driver.current_url}")
                                    return True
                        except (TimeoutException, NoSuchElementException):
                            continue
                
                # Fallback: Try direct login selectors (in case menu is already open or link is visible)
                logger.info("Trying direct login selectors as fallback...")
                direct_login_selectors = [
                    (By.CSS_SELECTOR, 'a.navigation-link--login'),
                    (By.XPATH, '//a[contains(@href, "anmelden")]'),
                    (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmelden")]'),
                    (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmeldung")]'),
                    (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "login")]'),
                ]
                
                for by, selector in direct_login_selectors:
                    try:
                        login_element = wait.until(EC.element_to_be_clickable((by, selector)))
                        if login_element and login_element.is_displayed():
                            logger.info(f"Found direct login link, clicking... (href: {login_element.get_attribute('href')})")
                            self.driver.execute_script("arguments[0].click();", login_element)
                            time.sleep(3)
                            
                            current_url = self.driver.current_url.lower()
                            if 'anmelden' in current_url or 'login' in current_url:
                                logger.info(f"Successfully navigated to login page: {self.driver.current_url}")
                                return True
                    except (TimeoutException, NoSuchElementException):
                        continue
                        
            except Exception as e:
                logger.warning(f"Error with account menu approach: {str(e)}")
            
            # If not found, try going directly to login URL
            logger.info("Login button not found, navigating directly to login URL...")
            self.driver.get(self.login_url)
            self.rate_limiter.wait()
            time.sleep(2)
            self._handle_cookies()  # Handle cookies again in case they appear
            
            return True
        except Exception as e:
            logger.error(f"Error navigating to login: {str(e)}")
            return False
    
    @retry_on_failure(max_retries=3, initial_delay=2.0)
    def login(self) -> bool:
        """
        Login to the website using environment variables with retry logic.
        
        Returns:
            True if login successful, False otherwise
        """
        email = os.getenv('MAIL')
        password = os.getenv('PASS')
        
        if not email or not password:
            logger.error("MAIL and PASS environment variables must be set")
            return False
        
        try:
            # Navigate to login page (handles cookies and login button clicks)
            if not self._navigate_to_login():
                logger.error("Failed to navigate to login page")
                return False
            
            logger.info(f"On login page: {self.driver.current_url}")
            
            # Wait for login form to load
            wait = WebDriverWait(self.driver, 15)
            
            # Try common email input selectors (including Keycloak/OpenID Connect specific)
            email_selectors = [
                # Keycloak/OpenID Connect specific
                (By.ID, 'username'),
                (By.NAME, 'username'),
                (By.ID, 'username-input'),
                (By.CSS_SELECTOR, '#username'),
                (By.XPATH, '//input[@id="username"]'),
                # Standard email fields
                (By.ID, 'email'),
                (By.NAME, 'email'),
                (By.ID, 'mail'),
                (By.NAME, 'mail'),
                (By.ID, 'login-email'),
                (By.NAME, 'login-email'),
                (By.CSS_SELECTOR, 'input[type="email"]'),
                (By.XPATH, '//input[@type="email"]'),
                (By.XPATH, '//input[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "email")]'),
                (By.XPATH, '//input[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "mail")]'),
                (By.XPATH, '//input[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "e-mail")]'),
                (By.XPATH, '//input[contains(@placeholder, "E-Mail")]'),
                (By.XPATH, '//input[contains(@placeholder, "E-Mail-Adresse")]'),
                (By.XPATH, '//input[@name="email"]'),
                (By.XPATH, '//input[@id="email"]'),
            ]
            
            email_input = None
            for by, value in email_selectors:
                try:
                    email_input = wait.until(EC.presence_of_element_located((by, value)))
                    break
                except TimeoutException:
                    continue
            
            if not email_input:
                logger.error("Could not find email input field")
                return False
            
            # Try common password input selectors (including Keycloak/OpenID Connect specific)
            password_selectors = [
                # Keycloak/OpenID Connect specific
                (By.ID, 'password'),
                (By.NAME, 'password'),
                (By.ID, 'password-input'),
                (By.CSS_SELECTOR, '#password'),
                (By.XPATH, '//input[@id="password"]'),
                # Standard password fields
                (By.ID, 'pass'),
                (By.NAME, 'pass'),
                (By.ID, 'login-password'),
                (By.NAME, 'login-password'),
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.XPATH, '//input[@type="password"]'),
                (By.XPATH, '//input[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "password")]'),
                (By.XPATH, '//input[contains(@placeholder, "Passwort")]'),
                (By.XPATH, '//input[@name="password"]'),
            ]
            
            password_input = None
            for by, value in password_selectors:
                try:
                    password_input = wait.until(EC.presence_of_element_located((by, value)))
                    break
                except TimeoutException:
                    continue
            
            if not password_input:
                logger.error("Could not find password input field")
                return False
            
            # Re-find elements after page load (avoid stale element reference)
            email_input = None
            for by, value in email_selectors:
                try:
                    email_input = wait.until(EC.presence_of_element_located((by, value)))
                    break
                except TimeoutException:
                    continue
            
            if not email_input:
                logger.error("Could not find email input field after navigation")
                return False
            
            password_input = None
            for by, value in password_selectors:
                try:
                    password_input = wait.until(EC.presence_of_element_located((by, value)))
                    break
                except TimeoutException:
                    continue
            
            if not password_input:
                logger.error("Could not find password input field after navigation")
                return False
            
            # Fill in credentials with human-like typing
            email_input.clear()
            time.sleep(0.3)
            for char in email:
                email_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(0.5)
            
            password_input.clear()
            time.sleep(0.3)
            for char in password:
                password_input.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(1)
            
            # Try to find and click submit button (including Keycloak/OpenID Connect specific)
            submit_selectors = [
                # Keycloak/OpenID Connect specific
                (By.ID, 'kc-login'),
                (By.NAME, 'login'),
                (By.CSS_SELECTOR, '#kc-login'),
                (By.XPATH, '//input[@id="kc-login"]'),
                (By.XPATH, '//button[@id="kc-login"]'),
                # Standard submit buttons
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.XPATH, '//button[@type="submit"]'),
                (By.CSS_SELECTOR, 'input[type="submit"]'),
                (By.XPATH, '//input[@type="submit"]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "login")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "sign in")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmelden")]'),
                (By.XPATH, '//input[contains(translate(@value, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "anmelden")]'),
                (By.CSS_SELECTOR, 'button.btn-primary'),
                (By.CSS_SELECTOR, 'button[class*="submit"]'),
            ]
            
            submitted = False
            for by, value in submit_selectors:
                try:
                    submit_button = wait.until(EC.element_to_be_clickable((by, value)))
                    submit_button.click()
                    submitted = True
                    break
                except (NoSuchElementException, TimeoutException):
                    continue
            
            if not submitted:
                # Try pressing Enter on password field
                password_input.send_keys('\n')
            
            # Wait for navigation after login
            time.sleep(3)
            
            # Verify login was successful
            current_url = self.driver.current_url
            login_successful = self._verify_login()
            
            if login_successful:
                self.is_logged_in = True
                logger.info("Login successful and verified")
                self.rate_limiter.reset_delay()
                return True
            else:
                logger.warning("Login verification failed")
                self.rate_limiter.increase_delay()
                return False
                
        except Exception as e:
            logger.error(f"Error during login: {str(e)}", exc_info=True)
            self.rate_limiter.increase_delay()
            raise
    
    def _verify_login(self) -> bool:
        """Verify that login was successful by checking for common logged-in indicators."""
        try:
            # Check URL changed from login page
            current_url = self.driver.current_url.lower()
            if 'login' in current_url and current_url == self.login_url.lower():
                return False
            
            # Check for common logout buttons/links
            logout_indicators = [
                (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "log out")]'),
                (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "logout")]'),
                (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "log out")]'),
                (By.XPATH, '//*[contains(@class, "logout")]'),
                (By.XPATH, '//*[contains(@class, "user-menu")]'),
                (By.XPATH, '//*[contains(@class, "profile")]'),
            ]
            
            for by, selector in logout_indicators:
                try:
                    element = self.driver.find_element(by, selector)
                    if element and element.is_displayed():
                        return True
                except NoSuchElementException:
                    continue
            
            # Check for error messages
            error_indicators = [
                (By.XPATH, '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "invalid")]'),
                (By.XPATH, '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "incorrect")]'),
                (By.XPATH, '//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "failed")]'),
                (By.XPATH, '//*[contains(@class, "error")]'),
                (By.XPATH, '//*[contains(@class, "alert-danger")]'),
            ]
            
            for by, selector in error_indicators:
                try:
                    element = self.driver.find_element(by, selector)
                    if element and element.is_displayed():
                        error_text = element.text.lower()
                        if any(word in error_text for word in ['invalid', 'incorrect', 'failed', 'error']):
                            return False
                except NoSuchElementException:
                    continue
            
            # If URL changed and no error found, assume successful
            return current_url != self.login_url.lower()
            
        except Exception as e:
            logger.warning(f"Error verifying login: {str(e)}")
            # Default to checking URL change
            return self.driver.current_url.lower() != self.login_url.lower()
    
    def get_article_list(self, articles_url: str = None) -> List[Dict]:
        """
        Get list of ALL articles from the articles page, handling pagination and infinite scroll.
        
        Args:
            articles_url: URL of articles list page (defaults to base_url + '/articles')
            
        Returns:
            List of article dictionaries with 'id' and 'url' keys
        """
        if not articles_url:
            articles_url = f"{self.base_url}/articles"
        
        try:
            logger.info(f"Fetching article list from {articles_url}")
            self.rate_limiter.wait()
            self.driver.get(articles_url)
            time.sleep(3)  # Wait for page to load
            
            # Verify we're logged in and can access full content
            if not self.is_logged_in:
                logger.warning("Not logged in, attempting to login again...")
                if not self.login():
                    logger.error("Cannot access articles without login")
                    return []
            
            # After login, navigate to news index page if not already there
            current_url = self.driver.current_url.lower()
            if 'news/index' not in current_url and 'index' not in current_url:
                logger.info("Navigating to news index page after login...")
                self.rate_limiter.wait()
                self.driver.get(articles_url)
                time.sleep(3)
                # Handle cookies again in case they appear
                self._handle_cookies()
                time.sleep(2)
            
            # Handle infinite scroll first
            articles = []
            seen_urls = set()
            last_article_count = 0
            scroll_attempts = 0
            max_scroll_attempts = 50  # Prevent infinite loops
            
            logger.info("Handling infinite scroll...")
            while scroll_attempts < max_scroll_attempts:
                # Scroll to bottom
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self.rate_limiter.wait()
                time.sleep(2)  # Wait for content to load
                
                # Get current articles
                current_articles = self._extract_articles_from_page()
                for article in current_articles:
                    if article['url'] not in seen_urls:
                        articles.append(article)
                        seen_urls.add(article['url'])
                
                # Check if we got new articles
                if len(articles) == last_article_count:
                    scroll_attempts += 1
                    if scroll_attempts >= 3:  # If no new articles after 3 scrolls, try pagination
                        break
                else:
                    scroll_attempts = 0
                    last_article_count = len(articles)
                    logger.info(f"Found {len(articles)} articles so far...")
            
            # Handle pagination
            logger.info("Handling pagination...")
            page = 1
            max_pages = 1000  # Safety limit
            visited_urls = {articles_url}
            
            while page <= max_pages:
                # Extract articles from current page
                current_articles = self._extract_articles_from_page()
                for article in current_articles:
                    if article['url'] not in seen_urls:
                        articles.append(article)
                        seen_urls.add(article['url'])
                
                # Try to find and click "Next" button or link
                next_button = self._find_next_button()
                if next_button:
                    try:
                        next_url = next_button.get_attribute('href') or next_button.get_attribute('data-url')
                        if next_url and next_url not in visited_urls:
                            visited_urls.add(next_url)
                            self.rate_limiter.wait()
                            self.driver.get(next_url)
                            time.sleep(3)
                            page += 1
                            logger.info(f"Navigated to page {page}, found {len(articles)} articles so far...")
                            continue
                        elif next_button.is_enabled() and next_button.is_displayed():
                            self.rate_limiter.wait()
                            self.driver.execute_script("arguments[0].click();", next_button)
                            time.sleep(3)
                            page += 1
                            logger.info(f"Clicked next button, now on page {page}, found {len(articles)} articles so far...")
                            continue
                    except Exception as e:
                        logger.warning(f"Error clicking next button: {str(e)}")
                
                # Try to find pagination links
                pagination_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="page"], a[href*="p="], a[href*="/p/"]')
                next_page_url = None
                for link in pagination_links:
                    href = link.get_attribute('href') or ''
                    link_text = link.text.strip().lower()
                    if (('next' in link_text or '>' in link_text or str(page + 1) in link_text) and 
                        href not in visited_urls):
                        next_page_url = href
                        break
                
                if next_page_url:
                    visited_urls.add(next_page_url)
                    self.rate_limiter.wait()
                    self.driver.get(next_page_url)
                    time.sleep(3)
                    page += 1
                    logger.info(f"Navigated to page {page}, found {len(articles)} articles so far...")
                else:
                    # No more pages
                    break
            
            # Remove duplicates based on URL
            unique_articles = []
            seen = set()
            for article in articles:
                if article['url'] not in seen:
                    unique_articles.append(article)
                    seen.add(article['url'])
            
            logger.info(f"Found {len(unique_articles)} unique articles in total")
            return unique_articles
            
        except Exception as e:
            logger.error(f"Error fetching article list: {str(e)}", exc_info=True)
            return []
    
    def _extract_articles_from_page(self) -> List[Dict]:
        """Extract articles from the current page - optimized for zeit.de/news/index."""
        articles = []
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        seen_urls = set()
        
        logger.info("Extracting articles from zeit.de news index page...")
        
        # Strategy 1: Find all links that match zeit.de article URL patterns
        # Based on the website structure, articles are in headlines with links
        all_links = soup.find_all('a', href=True)
        logger.info(f"Found {len(all_links)} total links on page")
        
        # Zeit.de article URL patterns
        article_patterns = [
            '/news/', '/gesellschaft/', '/politik/', '/wirtschaft/', '/kultur/',
            '/wissen/', '/sport/', '/digital/', '/gesundheit/', '/familie/',
            '/campus/', '/feuilleton/', '/mobilität/', '/sinn/', '/hamburg/',
            '/leben/', '/arbeit/', '/schweiz/', '/österreich/', '/magazin/'
        ]
        
        # Exclude patterns
        exclude_patterns = [
            '/index', '/suche', '/impressum', '/datenschutz', '/agb',
            '/shop', '/abo', '/newsletter', '/login', '/anmelden',
            '/account', '/meine.zeit.de', '/kommentare', '/archiv',
            '/podcast', '/video', '/spiele', '/studiengänge', '/jobs'
        ]
        
        for link in all_links:
            href = link.get('href', '')
            if not href or href.startswith('#') or href.startswith('javascript:'):
                continue
            
            # Make absolute URL
            url = self._make_absolute_url(href)
            url_lower = url.lower()
            
            # Skip if already seen
            if url in seen_urls:
                continue
            
            # Check if it's a zeit.de article URL
            is_zeit_article = False
            if 'zeit.de' in url_lower:
                # Must contain at least one article pattern
                has_article_pattern = any(pattern in url_lower for pattern in article_patterns)
                # Must not contain exclude patterns
                has_exclude_pattern = any(exclude in url_lower for exclude in exclude_patterns)
                
                # Additional check: URL should have a meaningful path (not just domain)
                has_meaningful_path = len(url.replace('https://www.zeit.de', '').replace('https://zeit.de', '').strip('/')) > 3
                
                if has_article_pattern and not has_exclude_pattern and has_meaningful_path:
                    is_zeit_article = True
            
            if is_zeit_article:
                # Extract title
                title = link.get_text(strip=True)
                
                # If title is too short, try to get from parent or nearby elements
                if not title or len(title) < 10:
                    # Try parent element
                    parent = link.parent
                    if parent:
                        parent_text = parent.get_text(strip=True)
                        if len(parent_text) > len(title):
                            title = parent_text
                    
                    # Try previous sibling (often h2/h3 before link)
                    if not title or len(title) < 10:
                        prev_sibling = link.find_previous_sibling()
                        if prev_sibling:
                            sibling_text = prev_sibling.get_text(strip=True)
                            if len(sibling_text) > len(title):
                                title = sibling_text
                    
                    # Try finding h2/h3 in the same container
                    if not title or len(title) < 10:
                        container = link.find_parent(['article', 'div', 'li', 'section'])
                        if container:
                            heading = container.find(['h1', 'h2', 'h3', 'h4'])
                            if heading:
                                title = heading.get_text(strip=True)
                
                # Only add if we have a meaningful title
                if title and len(title) > 10:
                    article_id = self._extract_id_from_url(href) or str(hash(url))
                    articles.append({
                        'id': article_id,
                        'url': url,
                        'title': title[:200]  # Limit title length
                    })
                    seen_urls.add(url)
        
        # Strategy 2: Also look for article containers (as fallback)
        if len(articles) < 10:
            logger.info("Trying article container extraction as fallback...")
            article_containers = soup.find_all(['article', 'div', 'li'], class_=lambda x: x and any(
                keyword in str(x).lower() for keyword in ['article', 'teaser', 'news', 'story', 'item']
            ))
            
            for container in article_containers:
                # Find links inside container
                link = container.find('a', href=True)
                if link:
                    href = link.get('href', '')
                    url = self._make_absolute_url(href)
                    
                    if url not in seen_urls and any(pattern in url.lower() for pattern in article_patterns):
                        title = link.get_text(strip=True) or container.get_text(strip=True)[:200]
                        if title and len(title) > 10:
                            article_id = self._extract_id_from_url(href) or str(hash(url))
                            articles.append({
                                'id': article_id,
                                'url': url,
                                'title': title[:200]
                            })
                            seen_urls.add(url)
        
        logger.info(f"Extracted {len(articles)} unique articles from page")
        return articles
    
    def _find_next_button(self):
        """Find the next page button."""
        next_selectors = [
            (By.CSS_SELECTOR, 'a[aria-label*="next" i]'),
            (By.CSS_SELECTOR, 'a[title*="next" i]'),
            (By.CSS_SELECTOR, 'button[aria-label*="next" i]'),
            (By.CSS_SELECTOR, 'button[title*="next" i]'),
            (By.XPATH, '//a[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "next")]'),
            (By.XPATH, '//button[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "next")]'),
            (By.XPATH, '//a[contains(text(), ">")]'),
            (By.XPATH, '//a[contains(text(), "→")]'),
            (By.CSS_SELECTOR, '.pagination .next'),
            (By.CSS_SELECTOR, '.pagination-next'),
            (By.CSS_SELECTOR, '[class*="next"]'),
        ]
        
        for by, selector in next_selectors:
            try:
                elements = self.driver.find_elements(by, selector)
                for element in elements:
                    if element.is_displayed() and element.is_enabled():
                        return element
            except:
                continue
        
        return None
    
    def _extract_article_info(self, element) -> Optional[Dict]:
        """Extract article information from an HTML element."""
        try:
            # Try to find link
            link = element.find('a', href=True) if element.name != 'a' else element
            if not link:
                return None
            
            href = link.get('href', '')
            article_id = (
                element.get('id') or 
                link.get('id') or 
                element.get('data-id') or 
                self._extract_id_from_url(href) or 
                str(hash(href))
            )
            
            title = (
                element.get('title') or 
                link.get_text(strip=True) or 
                element.get_text(strip=True)
            )
            
            return {
                'id': str(article_id),
                'url': self._make_absolute_url(href),
                'title': title
            }
        except Exception as e:
            logger.warning(f"Error extracting article info: {str(e)}")
            return None
    
    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extract article ID from URL."""
        if not url:
            return None
        # Try to extract ID from URL (e.g., /articles/123 or /articles/article-slug)
        parts = url.strip('/').split('/')
        if len(parts) > 0:
            return parts[-1]
        return None
    
    def _make_absolute_url(self, url: str) -> str:
        """Convert relative URL to absolute URL."""
        if url.startswith('http'):
            return url
        if url.startswith('/'):
            return f"{self.base_url}{url}"
        return f"{self.base_url}/{url}"
    
    @retry_on_failure(max_retries=3, initial_delay=2.0)
    def scrape_article(self, article_url: str, article_id: str) -> Optional[Dict]:
        """
        Scrape a single article with retry logic.
        
        Args:
            article_url: URL of the article
            article_id: Unique identifier for the article
            
        Returns:
            Dictionary with article data or None if failed
        """
        try:
            logger.info(f"Scraping article: {article_url}")
            
            # Verify login before accessing article
            if not self.is_logged_in:
                logger.warning("Not logged in, attempting to login...")
                if not self.login():
                    logger.error(f"Cannot access article {article_url} without login")
                    return None
            
            self.rate_limiter.wait()
            self.driver.get(article_url)
            time.sleep(3)  # Wait for content to load
            
            # Check if we're being redirected to login or seeing paywall
            current_url = self.driver.current_url.lower()
            if 'login' in current_url or 'paywall' in current_url or 'subscribe' in current_url:
                logger.warning(f"Article {article_url} requires login/subscription. Attempting re-login...")
                if not self.login():
                    logger.error(f"Cannot access article {article_url} - login failed")
                    return None
                # Retry accessing the article
                self.rate_limiter.wait()
                self.driver.get(article_url)
                time.sleep(3)
            
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Extract title
            title = self._extract_title(soup)
            
            # Extract content
            content = self._extract_content(soup)
            
            # Extract tags (from article-tags__list structure)
            tags = self._extract_tags(soup)
            
            # Extract article publication date
            article_date = self._extract_article_date(soup)
            
            # Extract article updated date
            article_updated = self._extract_article_updated_date(soup)
            
            # Extract source/Quelle
            source = self._extract_source(soup)
            
            # Record exact scraped time (down to the second)
            scraped_at = datetime.utcnow().replace(microsecond=0)
            
            article_data = {
                'id': article_id,
                'title': title,
                'content': content,
                'tags': tags,
                'url': article_url,
                'article_date': article_date,
                'article_updated': article_updated,
                'source': source,
                'scraped_at': scraped_at
            }
            
            logger.info(f"Extracted metadata - Tags: {len(tags)}, Source: {source}, Published: {article_date}, Updated: {article_updated}")
            
            # Verify we got meaningful content
            if not content or len(content.strip()) < 50:
                logger.warning(f"Article {article_url} has minimal content, may be behind paywall or login")
                # Try to check if there's a paywall message
                paywall_indicators = soup.find_all(string=lambda text: text and any(
                    word in text.lower() for word in ['subscribe', 'paywall', 'premium', 'members only', 'sign in']
                ))
                if paywall_indicators:
                    logger.error(f"Article {article_url} is behind paywall")
                    self.rate_limiter.increase_delay()
                    return None
            
            logger.info(f"Successfully scraped article: {title[:50]}...")
            self.rate_limiter.reset_delay()
            return article_data
            
        except Exception as e:
            logger.error(f"Error scraping article {article_url}: {str(e)}", exc_info=True)
            self.rate_limiter.increase_delay()
            raise
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title and clean it."""
        title_selectors = [
            ('h1', {'class': 'title'}),
            ('h1', {'class': 'article-title'}),
            ('h1', {'class': 'post-title'}),
            ('title', None),
            ('h1', None)
        ]
        
        title = "Untitled"
        for tag_name, attrs in title_selectors:
            element = soup.find(tag_name, attrs=attrs)
            if element:
                title = element.get_text(strip=True)
                break
        
        # Clean up " | DIE ZEIT" suffix (case-insensitive, using regex)
        if title and title != "Untitled":
            import re
            original_title = title
            # Pattern to match " | DIE ZEIT" or "| DIE ZEIT" at the end (case-insensitive)
            # Handles variations in spacing
            title = re.sub(r'\s*\|\s*DIE\s+ZEIT\s*$', '', title, flags=re.IGNORECASE)
            title = title.strip()
            if original_title != title:
                logger.info(f"Cleaned title: '{original_title[:60]}...' -> '{title[:60]}...'")
        
        return title
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract article content."""
        content_selectors = [
            ('div', {'class': 'content'}),
            ('div', {'class': 'article-content'}),
            ('div', {'class': 'post-content'}),
            ('article', {'class': 'content'}),
            ('main', None),
            ('article', None)
        ]
        
        for tag_name, attrs in content_selectors:
            element = soup.find(tag_name, attrs=attrs)
            if element:
                # Remove script and style elements
                for script in element(['script', 'style', 'nav', 'footer', 'header']):
                    script.decompose()
                return element.get_text(separator='\n', strip=True)
        
        # Fallback: get all text
        return soup.get_text(separator='\n', strip=True)
    
    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract article tags - specifically targets zeit.de article-tags__list structure."""
        tags = []
        
        # Zeit.de specific: Look for <ul class="article-tags__list">
        tag_list = soup.find('ul', class_='article-tags__list')
        if tag_list:
            logger.info("Found article-tags__list, extracting tags...")
            # Find all <a> tags with class 'z-topic article-tags__link' inside the list
            # Also try with just 'article-tags__link' class
            tag_links = tag_list.find_all('a', class_=lambda x: x and ('article-tags__link' in x or 'z-topic' in x))
            if not tag_links:
                # Fallback: find any <a> tags inside <li> elements
                tag_links = tag_list.find_all('a')
            
            for link in tag_links:
                tag_text = link.get_text(strip=True)
                if tag_text and tag_text not in tags:
                    tags.append(tag_text)
                    logger.debug(f"Found tag: {tag_text}")
            
            if tags:
                logger.info(f"Extracted {len(tags)} tags from article-tags__list: {', '.join(tags)}")
                return list(set(tags))  # Remove duplicates
        
        # Fallback: Try other common tag structures
        tag_selectors = [
            ('ul', {'class': 'article-tags__list'}),  # Try again with different approach
            ('a', {'class': 'article-tags__link'}),
            ('a', {'class': 'tag'}),
            ('a', {'class': 'z-topic'}),
            ('span', {'class': 'tag'}),
            ('div', {'class': 'tags'}),
            ('ul', {'class': 'tags'}),
        ]
        
        for tag_name, attrs in tag_selectors:
            elements = soup.find_all(tag_name, attrs=attrs)
            if elements:
                for element in elements:
                    if tag_name == 'a':
                        tag_text = element.get_text(strip=True)
                        if tag_text and tag_text not in tags:
                            tags.append(tag_text)
                    elif tag_name in ['div', 'ul']:
                        tag_links = element.find_all('a')
                        for link in tag_links:
                            tag_text = link.get_text(strip=True)
                            if tag_text and tag_text not in tags:
                                tags.append(tag_text)
                    else:
                        tag_text = element.get_text(strip=True)
                        if tag_text and tag_text not in tags:
                            tags.append(tag_text)
                if tags:
                    break
        
        return list(set(tags))  # Remove duplicates
    
    def _extract_article_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract article publication date - specifically targets zeit.de metadata__date structure."""
        # Zeit.de specific: Look for <time class="metadata__date" datetime="...">
        time_element = soup.find('time', class_='metadata__date')
        if time_element:
            datetime_attr = time_element.get('datetime')
            if datetime_attr:
                try:
                    # Parse ISO format datetime (e.g., "2025-11-05T22:02:00+01:00")
                    date_obj = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                    logger.info(f"Found publication date in metadata__date: {date_obj}")
                    return date_obj
                except Exception as e:
                    logger.debug(f"Error parsing datetime attribute: {str(e)}")
        
        # Fallback: Try other common date structures
        date_selectors = [
            ('time', {'class': 'metadata__date'}),
            ('time', {'datetime': True}),
            ('time', None),
            ('span', {'class': 'date'}),
            ('div', {'class': 'date'}),
            ('meta', {'property': 'article:published_time'}),
            ('meta', {'name': 'article:published_time'}),
            ('meta', {'property': 'og:published_time'}),
        ]
        
        for tag_name, attrs in date_selectors:
            if tag_name == 'meta':
                element = soup.find(tag_name, attrs=attrs)
                if element and element.get('content'):
                    try:
                        date_obj = datetime.fromisoformat(element['content'].replace('Z', '+00:00'))
                        logger.debug(f"Found publication date in meta tag: {date_obj}")
                        return date_obj
                    except:
                        pass
            else:
                element = soup.find(tag_name, attrs=attrs)
                if element:
                    datetime_attr = element.get('datetime')
                    if datetime_attr:
                        try:
                            date_obj = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                            logger.debug(f"Found publication date: {date_obj}")
                            return date_obj
                        except:
                            pass
                    date_text = element.get_text(strip=True)
                    if date_text:
                        # Try to parse common date formats
                        try:
                            from dateutil.parser import parse as parse_date
                            date_obj = parse_date(date_text)
                            logger.debug(f"Found publication date via text parsing: {date_obj}")
                            return date_obj
                        except:
                            pass
        
        return None
    
    def _extract_article_updated_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract article updated/modified date - also checks zeit.de metadata__date structure."""
        # Check for updated/modified time elements
        updated_selectors = [
            ('meta', {'property': 'article:modified_time'}),
            ('meta', {'name': 'article:modified_time'}),
            ('meta', {'property': 'og:updated_time'}),
            ('time', {'class': 'updated'}),
            ('time', {'class': 'modified'}),
            ('time', {'class': 'metadata__date'}),  # Zeit.de might use same structure for updated
        ]
        
        for tag_name, attrs in updated_selectors:
            if tag_name == 'meta':
                element = soup.find(tag_name, attrs=attrs)
                if element and element.get('content'):
                    try:
                        date_str = element['content'].replace('Z', '+00:00')
                        date_obj = datetime.fromisoformat(date_str)
                        logger.debug(f"Found updated date in meta tag: {date_obj}")
                        return date_obj
                    except:
                        pass
            else:
                element = soup.find(tag_name, attrs=attrs)
                if element:
                    datetime_attr = element.get('datetime')
                    if datetime_attr:
                        try:
                            date_str = datetime_attr.replace('Z', '+00:00')
                            date_obj = datetime.fromisoformat(date_str)
                            logger.debug(f"Found updated date: {date_obj}")
                            return date_obj
                        except:
                            pass
        
        return None
    
    def _extract_source(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article source/Quelle - specifically targets zeit.de metadata__source structure."""
        # Zeit.de specific: Look for <span class="metadata__source">
        source_element = soup.find('span', class_='metadata__source')
        if source_element:
            source_text = source_element.get_text(strip=True)
            if source_text:
                logger.info(f"Found source in metadata__source: {source_text}")
                # Clean up "Quelle:" prefix if present
                source_text = source_text.replace('Quelle:', '').replace('quelle:', '').strip()
                if source_text:
                    return source_text[:200]  # Limit length
        
        # Fallback: Try other common source structures
        source_selectors = [
            ('span', {'class': 'metadata__source'}),  # Try again with different approach
            ('span', {'class': 'metadata-source'}),
            ('div', {'class': 'source'}),
            ('div', {'class': 'quelle'}),
            ('span', {'class': 'quelle'}),
            ('div', {'class': 'byline'}),
            ('span', {'class': 'byline'}),
            ('meta', {'name': 'author'}),
            ('meta', {'property': 'article:author'}),
        ]
        
        for tag_name, attrs in source_selectors:
            if tag_name == 'meta':
                element = soup.find(tag_name, attrs=attrs)
                if element and element.get('content'):
                    source = element['content'].strip()
                    if source:
                        logger.debug(f"Found source in meta tag: {source}")
                        return source
            else:
                element = soup.find(tag_name, attrs=attrs)
                if element:
                    source_text = element.get_text(strip=True)
                    if source_text and len(source_text) > 2:
                        # Clean up common patterns
                        source_text = source_text.replace('Von', '').replace('von', '').strip()
                        source_text = source_text.replace('Quelle:', '').replace('quelle:', '').strip()
                        if source_text:
                            logger.debug(f"Found source: {source_text}")
                            return source_text[:200]  # Limit length
        
        # Try to find source in common patterns like "dpa", "DIE ZEIT", etc.
        # Look for common source indicators in text
        page_text = soup.get_text()
        source_patterns = [
            r'(?:Von|von|Quelle|quelle|Source|source)[:\s]+([A-Z][^\.\n]{2,50})',
            r'(dpa|DIE ZEIT|ZEIT|AP|Reuters|AFP)',
        ]
        
        import re
        for pattern in source_patterns:
            matches = re.findall(pattern, page_text[:2000])  # Check first 2000 chars
            if matches:
                source = matches[0].strip()
                if source and len(source) > 2:
                    logger.debug(f"Found source via pattern matching: {source}")
                    return source[:200]
        
        return None
    
    def run(self, articles_url: str = None, headless: bool = False):
        """
        Main method to run the scraping process.
        
        Args:
            articles_url: URL of articles list page
            headless: Run browser in headless mode
        """
        try:
            # Setup driver
            self.setup_driver(headless=headless)
            
            # Login
            if not self.login():
                logger.error("Failed to login. Exiting.")
                return
            
            # Get article list
            articles = self.get_article_list(articles_url)
            if not articles:
                logger.warning("No articles found")
                return
            
            # Get already scraped article IDs
            scraped_ids = self.db.get_all_scraped_ids()
            logger.info(f"Found {len(scraped_ids)} already scraped articles")
            
            # Filter out already scraped articles
            new_articles = [a for a in articles if a['id'] not in scraped_ids]
            logger.info(f"Found {len(new_articles)} new articles to scrape")
            
            # Scrape new articles with retry logic
            successful_scrapes = 0
            failed_scrapes = 0
            
            for idx, article in enumerate(new_articles, 1):
                logger.info(f"Processing article {idx}/{len(new_articles)}: {article.get('title', article['url'])}")
                
                try:
                    article_data = self.scrape_article(article['url'], article['id'])
                    if article_data and article_data.get('content'):
                        # Save to database with all metadata
                        saved_article = self.db.save_article(
                            article_id=article_data['id'],
                            title=article_data['title'],
                            content=article_data['content'],
                            tags=article_data.get('tags', []),
                            article_url=article_data['url'],
                            article_date=article_data.get('article_date'),
                            article_updated=article_data.get('article_updated'),
                            source=article_data.get('source'),
                            scraped_at=article_data.get('scraped_at')
                        )
                        successful_scrapes += 1
                        logger.info(f"✓ Saved article {idx}/{len(new_articles)}: {article_data['title'][:50]}...")
                    else:
                        failed_scrapes += 1
                        logger.warning(f"✗ Failed to scrape article {idx}/{len(new_articles)}: {article.get('title', article['url'])}")
                except Exception as e:
                    failed_scrapes += 1
                    logger.error(f"✗ Error scraping article {idx}/{len(new_articles)}: {str(e)}")
                    # Continue with next article even if this one failed
                    continue
            
            logger.info(f"Scraping completed: {successful_scrapes} successful, {failed_scrapes} failed out of {len(new_articles)} total")
            
        except Exception as e:
            logger.error(f"Error in run method: {str(e)}", exc_info=True)
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources."""
        if self.driver:
            self.driver.quit()
            logger.info("WebDriver closed")
        if self.db:
            self.db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape articles from a website')
    parser.add_argument('--url', type=str, required=True, help='Base URL of the website')
    parser.add_argument('--login-url', type=str, help='Login URL (optional)')
    parser.add_argument('--articles-url', type=str, help='Articles list URL (optional)')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    
    args = parser.parse_args()
    
    scraper = ArticleScraper(base_url=args.url, login_url=args.login_url)
    scraper.run(articles_url=args.articles_url, headless=args.headless)

