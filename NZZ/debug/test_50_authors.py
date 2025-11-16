"""Test Author Normalizer on first 50 articles by scraping from website (like the scraper does)."""
import sys
import os
import json
from datetime import datetime

# Add NZZ to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper_v2 import NZZScraperV2
from scraper import logger
from bs4 import BeautifulSoup
import time

def main():
    # Initialize
    print("=" * 80)
    print("Testing Author Normalizer on First 50 Articles (Scraping from Website)")
    print("=" * 80)
    print()
    
    # Initialize scraper (which includes the author normalizer)
    print("Initializing NZZ Scraper V2 (includes Author Normalizer)...")
    scraper = NZZScraperV2()
    
    if not scraper.author_normalizer.llm_classifier or not scraper.author_normalizer.llm_classifier.use_llm:
        print("WARNING: LLM classifier not available. Will use geopy/heuristics only.")
    else:
        print("OK: Author Normalizer initialized with LLM support\n")
    
    # Get article list from website using scraper's same logic (with page 2000)
    print("=" * 80)
    print("Step 1: Getting article list from website using scraper's logic...")
    print("Note: This will use infinite scroll (like the scraper) and stop after 50 articles")
    print("=" * 80)
    print()
    
    max_articles = 50
    
    def limited_get_article_list():
        """Wrapper that stops after collecting max_articles."""
        all_articles = []
        seen_ids = set()
        
        # Use the scraper's setup
        if scraper.driver is None:
            scraper.setup_driver(headless=False)
        
        try:
            logger.info(f"Loading page: {scraper.articles_url}")
            scraper.driver.get(scraper.articles_url)
            
            # Wait for initial page load
            time.sleep(1)
            scraper.rate_limiter.wait(jitter=True)
            
            print(f"Scrolling to collect {max_articles} articles...")
            
            scroll_count = 0
            while len(all_articles) < max_articles:
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
                        
                        if len(all_articles) >= max_articles:
                            break
                
                scroll_count += 1
                if scroll_count % 5 == 0:
                    print(f"  Scrolled {scroll_count} times, found {len(all_articles)} articles so far...")
                
                if len(all_articles) >= max_articles:
                    break
                
                # Safety limit - don't scroll forever
                if scroll_count > 100:
                    print(f"  Reached safety limit of 100 scrolls, stopping with {len(all_articles)} articles")
                    break
        
        except Exception as e:
            logger.error(f"Error in limited_get_article_list: {str(e)}")
        
        return all_articles[:max_articles]
    
    # Use the limited version
    articles = limited_get_article_list()
    
    if not articles:
        print("ERROR: No articles found from website!")
        return
    
    print(f"\nFound {len(articles)} articles from website\n")
    
    print("=" * 80)
    print("Step 2: Processing articles and extracting authors (this may take a few minutes)...")
    print("=" * 80)
    print()
    
    # Track results
    results = []
    articles_with_authors = 0
    articles_without_authors = 0
    total_author_strings = 0
    total_parsed_authors = 0
    errors = []
    
    for i, article in enumerate(articles, 1):
        article_id = article.get('id', 'N/A')
        article_url = article.get('url', '')
        article_title = article.get('title', 'N/A')
        
        if not article_url:
            articles_without_authors += 1
            continue
        
        print(f"[{i:2d}/{len(articles)}] Article {article_id}: {article_title[:50]}...", end=' ... ', flush=True)
        
        try:
            # Fetch article page (like the scraper does)
            r = scraper.session.get(article_url, timeout=30)
            if r.status_code == 404:
                print("404 - Article not found")
                articles_without_authors += 1
                continue
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Extract authors using scraper's method (like it does during scraping)
            authors = scraper._extract_authors_from_article(soup)
            
            if not authors:
                print("No authors found")
                articles_without_authors += 1
                continue
            
            articles_with_authors += 1
            
            # Process authors like the scraper does
            normalized_author_names = []
            article_locations = []
            parsed_authors_list = []
            author_processing_details = []  # Track each author string processing
            
            for author in authors:
                author_name = author.get('name', '')
                if not author_name:
                    continue
                
                total_author_strings += 1
                
                # Track processing for this author string
                processing_detail = {
                    'extracted_string': author_name,
                    'parsed_results': []
                }
                
                # Use normalizer to parse and normalize the author name (like scraper does)
                parsed_authors = scraper.author_normalizer.parse_author_string(author_name)
                
                if parsed_authors:
                    for parsed in parsed_authors:
                        normalized_author_names.append(parsed.normalized_name)
                        parsed_authors_list.append(parsed)
                        
                        # Collect location if present
                        if parsed.location and parsed.location not in article_locations:
                            article_locations.append(parsed.location)
                        
                        # Add to processing detail
                        processing_detail['parsed_results'].append({
                            'normalized_name': parsed.normalized_name,
                            'first_name': parsed.first_name,
                            'last_name': parsed.last_name,
                            'middle_name': parsed.middle_name,
                            'location': parsed.location,
                            'department': parsed.department
                        })
                else:
                    # Empty result - check if it's a standalone location (should be filtered out)
                    # If it's a single capitalized word, it's likely a location that was correctly filtered
                    if len(author_name.split()) == 1 and author_name[0].isupper() and len(author_name) >= 3:
                        # This is a standalone location - correctly filtered, not a failure
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
                        # Fallback to original name (actual parsing failure)
                        normalized_author_names.append(author_name)
                        processing_detail['parsed_results'].append({
                            'normalized_name': author_name,
                            'first_name': author_name.split()[0] if author_name.split() else "",
                            'last_name': " ".join(author_name.split()[1:]) if len(author_name.split()) > 1 else author_name,
                            'middle_name': None,
                            'location': None,
                            'department': None,
                            'note': 'Failed to parse - using original'
                        })
                
                author_processing_details.append(processing_detail)
            
            total_parsed_authors += len(parsed_authors_list)
            
            result_entry = {
                'article_id': article_id,
                'article_title': article_title,
                'article_url': article_url,
                'author_processing': author_processing_details,  # New: detailed processing info
                'extracted_authors': authors,
                'parsed_authors': [
                    {
                        'normalized_name': p.normalized_name,
                        'first_name': p.first_name,
                        'last_name': p.last_name,
                        'middle_name': p.middle_name,
                        'location': p.location,
                        'department': p.department
                    } for p in parsed_authors_list
                ],
                'normalized_names': normalized_author_names,
                'num_extracted': len(authors),
                'num_parsed': len(parsed_authors_list),
                'locations': article_locations,
                'departments': []
            }
            
            # Extract departments
            for parsed in parsed_authors_list:
                if parsed.department:
                    if parsed.department not in result_entry['departments']:
                        result_entry['departments'].append(parsed.department)
            
            results.append(result_entry)
            
            # Print summary
            names_str = ", ".join(normalized_author_names)
            location_str = f" [Loc: {', '.join(article_locations)}]" if article_locations else ""
            dept_str = f" [Dept: {', '.join(result_entry['departments'])}]" if result_entry['departments'] else ""
            print(f"OK: {len(authors)} extracted, {len(parsed_authors_list)} parsed: {names_str[:40]}{location_str}{dept_str}")
        
        except Exception as e:
            print(f"ERROR: {str(e)}")
            errors.append({
                'article_id': article_id,
                'article_url': article_url if article_url else 'N/A',
                'error': str(e)
            })
    
    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total articles tested: {len(articles)}")
    print(f"Articles with authors: {articles_with_authors}")
    print(f"Articles without authors: {articles_without_authors}")
    print(f"Total author strings extracted: {total_author_strings}")
    print(f"Total parsed authors: {total_parsed_authors}")
    print(f"Errors: {len(errors)}")
    print()
    
    # Show detailed results
    print("=" * 80)
    print("DETAILED RESULTS")
    print("=" * 80)
    print()
    
    for result in results:
        print(f"Article ID: {result['article_id']}")
        print(f"  URL: {result['article_url']}")
        print(f"  Extracted {result['num_extracted']} author(s) from HTML:")
        for author in result['extracted_authors']:
            author_info = f"    - {author.get('name', 'N/A')}"
            if author.get('id'):
                author_info += f" [ID: {author['id']}]"
            if author.get('url'):
                author_info += f" [URL: {author['url'][:50]}...]"
            print(author_info)
        print(f"  Parsed {result['num_parsed']} normalized author(s):")
        for parsed in result['parsed_authors']:
            # Handle both dict and ParsedAuthor object
            if isinstance(parsed, dict):
                normalized_name = parsed.get('normalized_name', 'N/A')
                location = parsed.get('location')
                department = parsed.get('department')
            else:
                normalized_name = parsed.normalized_name
                location = parsed.location
                department = parsed.department
            print(f"    - {normalized_name}", end="")
            if location:
                print(f" (Location: {location})", end="")
            if department:
                print(f" (Department: {department})", end="")
            print()
        if result['locations']:
            print(f"  Locations found: {', '.join(result['locations'])}")
        if result['departments']:
            print(f"  Departments found: {', '.join(result['departments'])}")
        print()
    
    # Show errors
    if errors:
        print("=" * 80)
        print("ERRORS:")
        print("=" * 80)
        for entry in errors:
            print(f"  Article {entry['article_id']}: {entry['article_url'][:60]}...")
            print(f"    Error: {entry['error']}")
        print()
    
    # Statistics
    print("=" * 80)
    print("STATISTICS")
    print("=" * 80)
    
    all_locations = []
    all_departments = []
    all_names = []
    
    for result in results:
        all_locations.extend(result['locations'])
        all_departments.extend(result['departments'])
        # Handle both dict and ParsedAuthor object
        for p in result['parsed_authors']:
            if isinstance(p, dict):
                all_names.append(p.get('normalized_name', ''))
            else:
                all_names.append(p.normalized_name)
    
    print(f"Unique locations found: {len(set(all_locations))}")
    if all_locations:
        print(f"  Locations: {', '.join(sorted(set(all_locations)))}")
    
    print(f"Unique departments found: {len(set(all_departments))}")
    if all_departments:
        print(f"  Departments: {', '.join(sorted(set(all_departments)))}")
    
    print(f"Unique author names found: {len(set(all_names))}")
    print(f"  Sample names: {', '.join(sorted(set(all_names))[:10])}")
    if len(set(all_names)) > 10:
        print(f"  ... and {len(set(all_names)) - 10} more")
    
    print()
    print("=" * 80)
    print("Test Complete")
    print("=" * 80)
    
    # Create JSON output
    json_output = {
        'test_metadata': {
            'test_date': datetime.now().isoformat(),
            'total_articles_tested': len(articles),
            'articles_with_authors': articles_with_authors,
            'articles_without_authors': articles_without_authors,
            'total_author_strings_extracted': total_author_strings,
            'total_parsed_authors': total_parsed_authors,
            'success_rate': f"{(total_parsed_authors / total_author_strings * 100):.1f}%" if total_author_strings > 0 else "0%",
            'errors_count': len(errors)
        },
        'test_results': results,
        'errors': errors,
        'statistics': {
            'unique_locations': sorted(set(all_locations)) if all_locations else [],
            'unique_departments': sorted(set(all_departments)) if all_departments else [],
            'unique_author_names': sorted(set(all_names)) if all_names else []
        }
    }
    
    # Save JSON to file
    json_filename = f"author_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_path = os.path.join(os.path.dirname(__file__), json_filename)
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    
    print(f"\nJSON results saved to: {json_filename}")
    print(f"Full path: {json_path}")

if __name__ == "__main__":
    main()

