"""Test author normalization on 1000 articles with detailed step-by-step analysis."""
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Any
import logging

# Setup logging - save logs in log/ subfolder
script_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(script_dir, 'log')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f'nzz_scraper_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
error_log_file = os.path.join(log_dir, f'nzz_scraper_errors_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

error_logger = logging.getLogger('nzz_scraper_errors')
error_handler = logging.FileHandler(error_log_file, encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_logger.addHandler(error_handler)

logger = logging.getLogger('nzz_scraper')
logger.info(f"Logging initialized - Main log: {log_file}")
logger.info(f"Error log: {error_log_file}")

from scraper_v2 import NZZScraperV2

def analyze_article(article_id: str, article_title: str, article_url: str, 
                   authors: List[Dict], scraper: NZZScraperV2) -> Dict[str, Any]:
    """Analyze a single article's authors step by step.
    
    Returns detailed analysis including:
    - Each author string extracted
    - Parsing steps and decisions
    - Final parsed results
    - Any issues or edge cases
    """
    analysis = {
        'article_id': article_id,
        'article_title': article_title,
        'article_url': article_url,
        'step_by_step_analysis': [],
        'author_processing': [],
        'extracted_authors': authors,
        'parsed_authors': [],
        'normalized_names': [],
        'locations': [],
        'departments': [],
        'issues': [],
        'num_extracted': len(authors),
        'num_parsed': 0
    }
    
    normalized_author_names = []
    article_locations = []
    parsed_authors_list = []
    
    for idx, author in enumerate(authors):
        author_name = author.get('name', '')
        if not author_name:
            continue
        
        step_analysis = {
            'step': idx + 1,
            'author_string': author_name,
            'steps': [],
            'final_result': None,
            'issues': []
        }
        
        # Step 1: Check if it's a standalone location
        step_analysis['steps'].append({
            'step_name': 'Check standalone location',
            'input': author_name,
            'check': f'len("{author_name}".split()) == 1 and "{author_name}"[0].isupper()',
            'result': len(author_name.split()) == 1 and author_name[0].isupper() if author_name else False
        })
        
        # Step 2: Parse with normalizer
        parsed_authors = scraper.author_normalizer.parse_author_string(author_name)
        
        step_analysis['steps'].append({
            'step_name': 'Parse with AuthorNormalizer',
            'input': author_name,
            'result_count': len(parsed_authors) if parsed_authors else 0,
            'result': [p.__dict__ for p in parsed_authors] if parsed_authors else []
        })
        
        # Step 3: Analyze result
        if parsed_authors:
            for parsed in parsed_authors:
                normalized_author_names.append(parsed.normalized_name)
                parsed_authors_list.append(parsed)
                
                if parsed.location and parsed.location not in article_locations:
                    article_locations.append(parsed.location)
                
                step_analysis['final_result'] = {
                    'normalized_name': parsed.normalized_name,
                    'first_name': parsed.first_name,
                    'last_name': parsed.last_name,
                    'middle_name': parsed.middle_name,
                    'location': parsed.location,
                    'department': parsed.department
                }
        else:
            # Empty result - check if it's a standalone location (single OR multi-word)
            # Use the same logic as parse_author_string to determine if it's a location
            is_standalone_location = False
            
            # Check if it's a location using the normalizer's method
            if scraper.author_normalizer.is_location(author_name, context=author_name):
                is_standalone_location = True
            else:
                # Also check heuristic patterns for multi-word locations
                words = author_name.split()
                if len(words) >= 2:
                    # Check for location patterns
                    location_keywords = ['gazastreifen', 'gaza', 'valley', 'city', 'town', 'nördlicher', 'südlicher', 'östlicher', 'westlicher']
                    has_location_keyword = any(kw in author_name.lower() for kw in location_keywords)
                    has_location_connector = any(conn in author_name.lower() for conn in [' de ', ' am ', ' on ', ' in ', ' bei ', ' an ', ' al-', ' al '])
                    is_capitalized = all(w[0].isupper() if w else False for w in words)
                    
                    # If it has location indicators, it's likely a location
                    if has_location_keyword or (has_location_connector and is_capitalized):
                        is_standalone_location = True
            
            if is_standalone_location:
                step_analysis['final_result'] = {
                    'note': 'Standalone location - correctly filtered out',
                    'location': author_name
                }
                step_analysis['steps'].append({
                    'step_name': 'Identify as standalone location',
                    'result': 'Correctly filtered - not a parsing failure'
                })
            else:
                step_analysis['final_result'] = {
                    'note': 'Failed to parse - using original',
                    'normalized_name': author_name,
                    'first_name': author_name.split()[0] if author_name.split() else "",
                    'last_name': " ".join(author_name.split()[1:]) if len(author_name.split()) > 1 else author_name,
                    'middle_name': None,
                    'location': None,
                    'department': None
                }
                step_analysis['issues'].append('Parsing returned empty result - fallback used')
                analysis['issues'].append(f'Author "{author_name}" failed to parse')
                normalized_author_names.append(author_name)
        
        analysis['step_by_step_analysis'].append(step_analysis)
        
        # Add to author_processing for compatibility
        processing_detail = {
            'extracted_string': author_name,
            'parsed_results': []
        }
        
        if parsed_authors:
            for parsed in parsed_authors:
                processing_detail['parsed_results'].append({
                    'normalized_name': parsed.normalized_name,
                    'first_name': parsed.first_name,
                    'last_name': parsed.last_name,
                    'middle_name': parsed.middle_name,
                    'location': parsed.location,
                    'department': parsed.department
                })
        else:
            # Check if it's a standalone location (single OR multi-word)
            is_standalone_location = False
            
            # Check if it's a location using the normalizer's method
            if scraper.author_normalizer.is_location(author_name, context=author_name):
                is_standalone_location = True
            else:
                # Also check heuristic patterns for multi-word locations
                words = author_name.split()
                if len(words) >= 2:
                    # Check for location patterns
                    location_keywords = ['gazastreifen', 'gaza', 'valley', 'city', 'town', 'nördlicher', 'südlicher', 'östlicher', 'westlicher']
                    has_location_keyword = any(kw in author_name.lower() for kw in location_keywords)
                    has_location_connector = any(conn in author_name.lower() for conn in [' de ', ' am ', ' on ', ' in ', ' bei ', ' an ', ' al-', ' al '])
                    is_capitalized = all(w[0].isupper() if w else False for w in words)
                    
                    # If it has location indicators, it's likely a location
                    if has_location_keyword or (has_location_connector and is_capitalized):
                        is_standalone_location = True
            
            if is_standalone_location:
                processing_detail['parsed_results'].append({
                    'normalized_name': None,
                    'first_name': None,
                    'last_name': None,
                    'middle_name': None,
                    'location': author_name,
                    'department': None,
                    'note': 'Standalone location - correctly filtered out'
                })
            else:
                processing_detail['parsed_results'].append({
                    'normalized_name': author_name,
                    'first_name': author_name.split()[0] if author_name.split() else "",
                    'last_name': " ".join(author_name.split()[1:]) if len(author_name.split()) > 1 else author_name,
                    'middle_name': None,
                    'location': None,
                    'department': None,
                    'note': 'Failed to parse - using original'
                })
        
        analysis['author_processing'].append(processing_detail)
    
    analysis['parsed_authors'] = [
        {
            'normalized_name': p.normalized_name,
            'first_name': p.first_name,
            'last_name': p.last_name,
            'middle_name': p.middle_name,
            'location': p.location,
            'department': p.department
        } for p in parsed_authors_list
    ]
    analysis['normalized_names'] = normalized_author_names
    analysis['num_parsed'] = len(parsed_authors_list)
    analysis['locations'] = article_locations
    
    # Extract departments
    for parsed in parsed_authors_list:
        if parsed.department:
            if parsed.department not in analysis['departments']:
                analysis['departments'].append(parsed.department)
    
    return analysis

def main():
    """Test author normalization on 1000 articles."""
    print("=" * 70)
    print("AUTHOR NORMALIZATION TEST - 1000 ARTICLES")
    print("=" * 70)
    print()
    
    # Initialize scraper
    scraper = NZZScraperV2()
    
    # Get article list starting from page 2000
    # The scraper uses articles_url with page=2000 parameter set in __init__
    print("Fetching article list (starting from page 2000, max 1000 articles)...")
    print("Note: Using infinite scroll to collect articles...")
    
    # Use the scraper's method but limit to 1000 articles
    all_articles = []
    seen_ids = set()
    
    # Setup driver if needed
    if scraper.driver is None:
        scraper.setup_driver(headless=True)
    
    try:
        import time
        logger.info(f"Loading page: {scraper.articles_url}")
        scraper.driver.get(scraper.articles_url)
        
        # Wait for initial page load
        time.sleep(2)
        scraper.rate_limiter.wait(jitter=True)
        
        print(f"Scrolling to collect 1000 articles...")
        
        scroll_count = 0
        while len(all_articles) < 1000:
            # Scroll to bottom
            try:
                scraper.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)  # Wait for content to load
                
                # Extract articles from current page source
                page_source = scraper.driver.page_source
            except Exception as e:
                logger.error(f"Error during scrolling: {str(e)}")
                break
            
            # Extract articles using scraper's method
            current_articles = scraper._extract_articles_from_page_source(page_source)
            
            # Add new articles
            for article in current_articles:
                article_id = article.get('id')
                
                if article_id and article_id not in seen_ids:
                    all_articles.append(article)
                    seen_ids.add(article_id)
                    
                    if len(all_articles) >= 1000:
                        break
            
            scroll_count += 1
            if scroll_count % 10 == 0:
                print(f"  Scrolled {scroll_count} times, found {len(all_articles)} articles so far...")
            
            if len(all_articles) >= 1000:
                break
            
            # Safety limit - don't scroll forever
            if scroll_count > 500:
                print(f"  Reached safety limit of 500 scrolls, stopping with {len(all_articles)} articles")
                break
        
        articles = all_articles[:1000]
    except Exception as e:
        logger.error(f"Error getting article list: {str(e)}")
        print(f"ERROR: Failed to get article list: {str(e)}")
        articles = []
    
    if not articles:
        print("No articles found!")
        return
    
    print(f"Found {len(articles)} articles")
    print()
    
    results = []
    total_author_strings = 0
    total_parsed_authors = 0
    articles_with_authors = 0
    articles_without_authors = 0
    all_issues = []
    all_locations = set()
    all_departments = set()
    all_author_names = set()
    
    # Process each article
    print("=" * 70)
    print("PROCESSING ARTICLES - STEP BY STEP ANALYSIS")
    print("=" * 70)
    print()
    
    for idx, article in enumerate(articles, 1):
        article_id = article.get('id', '')
        article_title = article.get('title', '')
        article_url = article.get('url', '')
        
        print(f"[{idx:4d}/{len(articles)}] Article {article_id}")
        print(f"         Title: {article_title[:70]}...")
        print(f"         URL: {article_url}")
        
        # Extract authors from article
        try:
            # Fetch article page directly (like test_50_authors.py does)
            # We don't need the full scrape_article method which requires article_id
            r = scraper.session.get(article_url, timeout=30)
            if r.status_code == 404:
                print(f"         -> 404 - Article not found")
                articles_without_authors += 1
                continue
            r.raise_for_status()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, 'html.parser')
            
            authors = scraper._extract_authors_from_article(soup)
            
            if not authors:
                print(f"  -> No authors found")
                articles_without_authors += 1
                continue
            
            articles_with_authors += 1
            total_author_strings += len(authors)
            
            print(f"  -> Extracted {len(authors)} author(s) from HTML")
            
            # Analyze article step by step
            analysis = analyze_article(article_id, article_title, article_url, authors, scraper)
            results.append(analysis)
            
            total_parsed_authors += analysis['num_parsed']
            
            # Collect statistics
            for loc in analysis['locations']:
                all_locations.add(loc)
            for dept in analysis['departments']:
                all_departments.add(dept)
            for name in analysis['normalized_names']:
                all_author_names.add(name)
            
            if analysis['issues']:
                all_issues.extend([(article_id, issue) for issue in analysis['issues']])
                print(f"  -> WARNING: {len(analysis['issues'])} issue(s) found")
            else:
                print(f"  -> OK: {len(authors)} extracted, {analysis['num_parsed']} parsed")
            
            # Print detailed info for first 10 articles
            if idx <= 10:
                print(f"    Parsed {len(analysis['parsed_authors'])} normalized author(s):")
                for parsed in analysis['parsed_authors']:
                    loc_str = f" (Location: {parsed['location']})" if parsed['location'] else ""
                    dept_str = f" [Dept: {parsed['department']}]" if parsed['department'] else ""
                    print(f"      - {parsed['normalized_name']}{loc_str}{dept_str}")
                if analysis['locations']:
                    print(f"    Locations found: {', '.join(analysis['locations'])}")
            
        except Exception as e:
            logger.error(f"Error processing article {article_id}: {str(e)}")
            print(f"         -> ERROR: {str(e)}")
            articles_without_authors += 1
            all_issues.append((article_id, f"Error: {str(e)}"))
        
        print()
    
    # Generate summary
    print("=" * 70)
    print("STATISTICS")
    print("=" * 70)
    print(f"Total articles tested: {len(articles)}")
    print(f"Articles with authors: {articles_with_authors}")
    print(f"Articles without authors: {articles_without_authors}")
    print(f"Total author strings extracted: {total_author_strings}")
    print(f"Total author strings parsed: {total_parsed_authors}")
    print()
    print(f"Unique locations found: {len(all_locations)}")
    print(f"  Locations: {', '.join(sorted(all_locations))}")
    print()
    print(f"Unique departments found: {len(all_departments)}")
    print(f"  Departments: {', '.join(sorted(all_departments))}")
    print()
    print(f"Unique author names found: {len(all_author_names)}")
    print(f"  Sample names: {', '.join(sorted(list(all_author_names))[:20])}")
    if len(all_author_names) > 20:
        print(f"  ... and {len(all_author_names) - 20} more")
    print()
    
    if all_issues:
        print(f"Total issues found: {len(all_issues)}")
        print("Sample issues:")
        for art_id, issue in all_issues[:10]:
            print(f"  - Article {art_id}: {issue}")
        if len(all_issues) > 10:
            print(f"  ... and {len(all_issues) - 10} more")
    else:
        print("No issues found - all articles correctly parsed!")
    
    print()
    print("=" * 70)
    print("Test Complete")
    print("=" * 70)
    
    # Save results to JSON
    output_file = f"author_test_results_1000_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_file)
    
    test_metadata = {
        'test_date': datetime.now().isoformat(),
        'total_articles_tested': len(articles),
        'articles_with_authors': articles_with_authors,
        'articles_without_authors': articles_without_authors,
        'total_author_strings_extracted': total_author_strings,
        'total_parsed_authors': total_parsed_authors,
        'success_rate': f"{(total_parsed_authors / total_author_strings * 100) if total_author_strings > 0 else 0:.1f}%",
        'errors_count': len(all_issues),
        'unique_locations': sorted(list(all_locations)),
        'unique_departments': sorted(list(all_departments)),
        'unique_author_names': sorted(list(all_author_names))
    }
    
    output_data = {
        'test_metadata': test_metadata,
        'test_results': results,
        'errors': all_issues,
        'statistics': {
            'unique_locations': sorted(list(all_locations)),
            'unique_departments': sorted(list(all_departments)),
            'unique_author_names': sorted(list(all_author_names))
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nJSON results saved to: {output_file}")
    print(f"Full path: {output_path}")
    print()

if __name__ == '__main__':
    main()

