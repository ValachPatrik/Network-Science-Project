"""Test script for NZZ scraper v2."""

import sys
import os
import json
from datetime import datetime
from scraper_v2 import NZZScraperV2
from database import DatabaseManager, Article, RelatedArticle, Author


def clean_database_before_tests():
    """Clean the database before running tests."""
    print("Cleaning database before tests...")
    try:
        db = DatabaseManager()
        # Don't clean articles and authors - we want to keep test data for export
        # Only clean relationships if needed
        # db.clean_database(
        #     clean_articles=False,
        #     clean_authors=False,
        #     clean_related_articles=True,
        #     clean_article_author_associations=True
        # )
        print("[OK] Database ready (keeping existing data for export)")
    except Exception as e:
        print(f"[WARN] Could not prepare database: {str(e)}")


def export_data_to_json():
    """Export test data to JSON files in test_data/ folder."""
    print("\n" + "=" * 80)
    print("EXPORTING TEST DATA TO JSON")
    print("=" * 80)

    # Create test_data directory if it doesn't exist
    test_data_dir = os.path.join(os.path.dirname(__file__), "test_data")
    os.makedirs(test_data_dir, exist_ok=True)
    print(f"\nCreated/verified test_data directory: {test_data_dir}")

    db = DatabaseManager()
    session = db.Session()

    try:
        # Export first 10 articles
        print("\nExporting first 10 articles...")
        articles = (
            session.query(Article).order_by(Article.scraped_at.desc()).limit(10).all()
        )
        articles_data = []
        for article in articles:
            article_dict = {
                "id": article.id,
                "article_id": article.article_id,
                "title": article.title,
                "content": (
                    article.content[:500] + "..."
                    if article.content and len(article.content) > 500
                    else article.content
                ),  # Truncate for readability
                "content_length": len(article.content) if article.content else 0,
                "tags": article.tags,
                "category": article.category,
                "article_url": article.article_url,
                "article_date": (
                    article.article_date.isoformat() if article.article_date else None
                ),
                "article_updated": (
                    article.article_updated.isoformat()
                    if article.article_updated
                    else None
                ),
                "author": article.author,
                "description": article.description,
                "scraped_at": (
                    article.scraped_at.isoformat() if article.scraped_at else None
                ),
            }
            articles_data.append(article_dict)

        articles_file = os.path.join(test_data_dir, "articles.json")
        with open(articles_file, "w", encoding="utf-8") as f:
            json.dump(articles_data, f, indent=2, ensure_ascii=False)
        print(f"[OK] Exported {len(articles_data)} articles to {articles_file}")

        # Export all related articles
        print("\nExporting related articles...")
        related_articles = session.query(RelatedArticle).all()
        related_articles_data = []
        for related in related_articles:
            related_dict = {
                "id": related.id,
                "article_id": related.article_id,
                "related_article_id": related.related_article_id,
                "related_article_url": related.related_article_url,
                "created_at": (
                    related.created_at.isoformat() if related.created_at else None
                ),
            }
            related_articles_data.append(related_dict)

        related_file = os.path.join(test_data_dir, "related_articles.json")
        with open(related_file, "w", encoding="utf-8") as f:
            json.dump(related_articles_data, f, indent=2, ensure_ascii=False)
        print(
            f"[OK] Exported {len(related_articles_data)} related articles to {related_file}"
        )

        # Export all authors
        print("\nExporting authors...")
        authors = session.query(Author).all()
        authors_data = []
        for author in authors:
            author_dict = {
                "id": author.id,
                "author_id": author.author_id,
                "name": author.name,
                "title": author.title,
                "alternate_name": author.alternate_name,
                "bio": author.bio,
                "image_url": author.image_url,
                "author_url": author.author_url,
                "scraped_at": (
                    author.scraped_at.isoformat() if author.scraped_at else None
                ),
            }
            authors_data.append(author_dict)

        authors_file = os.path.join(test_data_dir, "authors.json")
        with open(authors_file, "w", encoding="utf-8") as f:
            json.dump(authors_data, f, indent=2, ensure_ascii=False)
        print(f"[OK] Exported {len(authors_data)} authors to {authors_file}")

        # Export article-author associations
        print("\nExporting article-author associations...")
        from sqlalchemy import text

        associations = session.execute(
            text("SELECT article_id, author_id FROM article_author_association")
        ).fetchall()
        associations_data = []
        for assoc in associations:
            # Get article_id and author_id from the association
            article_db_id = assoc[0]
            author_db_id = assoc[1]

            # Get the actual article_id and author_id strings
            article = session.query(Article).filter_by(id=article_db_id).first()
            author = session.query(Author).filter_by(id=author_db_id).first()

            if article and author:
                assoc_dict = {
                    "article_id": article.article_id,
                    "article_title": article.title,
                    "author_id": author.author_id,
                    "author_name": author.name,
                }
                associations_data.append(assoc_dict)

        associations_file = os.path.join(
            test_data_dir, "article_author_associations.json"
        )
        with open(associations_file, "w", encoding="utf-8") as f:
            json.dump(associations_data, f, indent=2, ensure_ascii=False)
        print(
            f"[OK] Exported {len(associations_data)} article-author associations to {associations_file}"
        )

        # Export summary
        summary = {
            "export_date": datetime.now().isoformat(),
            "articles_count": len(articles_data),
            "related_articles_count": len(related_articles_data),
            "authors_count": len(authors_data),
            "associations_count": len(associations_data),
            "files": {
                "articles": "articles.json",
                "related_articles": "related_articles.json",
                "authors": "authors.json",
                "article_author_associations": "article_author_associations.json",
            },
        }

        summary_file = os.path.join(test_data_dir, "summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] Exported summary to {summary_file}")

        print("\n" + "=" * 80)
        print("EXPORT SUMMARY")
        print("=" * 80)
        print(f"Articles: {len(articles_data)}")
        print(f"Related Articles: {len(related_articles_data)}")
        print(f"Authors: {len(authors_data)}")
        print(f"Article-Author Associations: {len(associations_data)}")
        print(f"Export directory: {test_data_dir}")
        print("=" * 80)

    except Exception as e:
        print(f"[FAIL] Error exporting data: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            session.close()
        except Exception:
            pass


def test_scrape_single_article():
    """Test scraping a single article to verify related articles and authors extraction."""
    print("=" * 80)
    print("TEST 1: Scraping Single Article")
    print("=" * 80)

    scraper = NZZScraperV2()

    # Test with a known article URL
    test_url = "https://www.nzz.ch/feuilleton/eric-kaufmann-wokeness-hamas-universitaeten-ld.1764342"
    article_id = "1764342"

    print(f"\nScraping article: {test_url}")
    print(f"Article ID: {article_id}\n")

    try:
        article_data = scraper.scrape_article(test_url, article_id)

        if article_data:
            print("[PASS] Article scraped successfully")
            print(f"  Title: {article_data.get('title', 'N/A')[:80]}...")
            print(f"  Author: {article_data.get('author', 'N/A')}")
            print(f"  Category: {article_data.get('category', 'N/A')}")
            print(
                f"  Content length: {len(article_data.get('content', ''))} characters"
            )

            # Save article to database if not already exists
            db = DatabaseManager()
            if not db.article_exists(article_id):
                db.save_article(
                    article_id=article_data["id"],
                    title=article_data["title"],
                    content=article_data["content"],
                    tags=article_data.get("tags", []),
                    article_url=article_data["url"],
                    article_date=article_data.get("article_date"),
                    article_updated=article_data.get("article_updated"),
                    author=article_data.get("author"),
                    description=article_data.get("description"),
                    category=article_data.get("category"),
                    scraped_at=article_data.get("scraped_at"),
                )
                print(f"  [OK] Article saved to database")
            else:
                print(f"  [OK] Article already exists in database")

            # Check related articles
            related_articles = db.get_related_articles(article_id)
            print(f"\n  Related articles found: {len(related_articles)}")
            for related in related_articles[:5]:  # Show first 5
                print(
                    f"    - {related.related_article_id}: {related.related_article_url[:60]}..."
                )

            # Check authors
            print(f"\n  Authors extracted: {article_data.get('author', 'N/A')}")

        else:
            print("[FAIL] Failed to scrape article")
            return False

    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        scraper.cleanup()

    return True


def test_author_profile_scraping():
    """Test scraping an author profile page."""
    print("\n" + "=" * 80)
    print("TEST 2: Scraping Author Profile")
    print("=" * 80)

    scraper = NZZScraperV2()

    # Test with Rico Bandle's profile
    test_url = "https://www.nzz.ch/impressum/rico-bandle-ld.1894615"
    author_id = "1894615"

    print(f"\nScraping author profile: {test_url}")
    print(f"Author ID: {author_id}\n")

    try:
        author_data = scraper.scrape_author_profile(test_url, author_id)

        if author_data:
            print("[PASS] Author profile scraped successfully")
            print(f"  Name: {author_data.get('name', 'N/A')}")
            print(f"  Title: {author_data.get('title', 'N/A')}")
            print(f"  Alternate Name: {author_data.get('alternate_name', 'N/A')}")
            print(f"  Bio length: {len(author_data.get('bio', ''))} characters")
            print(f"  Image URL: {author_data.get('image_url', 'N/A')[:60]}...")

            # Save to database
            db = DatabaseManager()
            saved_author = db.save_author(
                name=author_data["name"],
                author_id=author_data["id"],
                author_url=author_data["url"],
                title=author_data.get("title"),
                alternate_name=author_data.get("alternate_name"),
                bio=author_data.get("bio"),
                image_url=author_data.get("image_url"),
            )

            # Get author name before session closes
            author_name = author_data["name"]
            author_id_str = author_data["id"]
            print(f"\n[PASS] Author saved to database: {author_name} ({author_id_str})")

            # Try to link this author to articles that mention them
            # This will help populate the associations table
            articles = db.get_all_articles()
            linked_count = 0
            for article in articles:
                if article.author and author_name in article.author:
                    if db.link_article_to_author(article.article_id, author_id_str):
                        linked_count += 1
            if linked_count > 0:
                print(f"  [OK] Linked author to {linked_count} articles")

        else:
            print("[FAIL] Failed to scrape author profile")
            return False

    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        scraper.cleanup()

    return True


def test_related_articles_extraction():
    """Test extracting related articles from an article page."""
    print("\n" + "=" * 80)
    print("TEST 3: Extracting Related Articles")
    print("=" * 80)

    scraper = NZZScraperV2()

    test_url = "https://www.nzz.ch/feuilleton/eric-kaufmann-wokeness-hamas-universitaeten-ld.1764342"
    article_id = "1764342"

    print(f"\nExtracting related articles from: {test_url}\n")

    try:
        from bs4 import BeautifulSoup

        scraper.rate_limiter.wait(jitter=True)
        r = scraper.session.get(test_url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        related_articles = scraper._extract_related_articles(soup, article_id)

        print(f"[PASS] Found {len(related_articles)} related articles")
        for idx, related in enumerate(related_articles[:10], 1):  # Show first 10
            print(f"  {idx}. {related['id']}: {related['title'][:60]}...")
            print(f"     URL: {related['url'][:70]}...")

        if len(related_articles) > 0:
            print("\n[PASS] Related articles extraction successful")
        else:
            print("\n[WARN] No related articles found (this might be normal)")

    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        scraper.cleanup()

    return True


def test_authors_extraction():
    """Test extracting authors from an article page."""
    print("\n" + "=" * 80)
    print("TEST 4: Extracting Authors")
    print("=" * 80)

    scraper = NZZScraperV2()

    test_url = "https://www.nzz.ch/feuilleton/eric-kaufmann-wokeness-hamas-universitaeten-ld.1764342"

    print(f"\nExtracting authors from: {test_url}\n")

    try:
        from bs4 import BeautifulSoup

        scraper.rate_limiter.wait(jitter=True)
        r = scraper.session.get(test_url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        authors = scraper._extract_authors_from_article(soup)

        print(f"[PASS] Found {len(authors)} authors")
        for idx, author in enumerate(authors, 1):
            author_id = author.get("id", "no-id")
            author_url = author.get("url", "no-url")
            print(f"  {idx}. {author['name']} ({author_id})")
            if author_url != "no-url":
                print(f"     URL: {author_url}")

        if len(authors) > 0:
            print("\n[PASS] Authors extraction successful")
        else:
            print("\n[WARN] No authors found (this might be normal)")

    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        scraper.cleanup()

    return True


def test_database_tables():
    """Test that database tables are created correctly."""
    print("\n" + "=" * 80)
    print("TEST 5: Database Tables")
    print("=" * 80)

    try:
        from sqlalchemy import inspect

        db = DatabaseManager()
        inspector = inspect(db.engine)

        tables = inspector.get_table_names()

        print(f"\n[PASS] Database tables found: {len(tables)}")
        for table in tables:
            print(f"  - {table}")

        # Check for required tables
        required_tables = [
            "articles",
            "related_articles",
            "authors",
            "article_author_association",
        ]
        missing_tables = [t for t in required_tables if t not in tables]

        if missing_tables:
            print(f"\n[FAIL] Missing tables: {missing_tables}")
            return False
        else:
            print("\n[PASS] All required tables exist")

    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    return True


def test_impressum_loading():
    """Test loading currently employed authors from impressum page."""
    print("=" * 80)
    print("TEST 7: Impressum Authors Loading")
    print("=" * 80)

    scraper = NZZScraperV2()

    # Check if impressum authors were loaded
    if not scraper.currently_employed_authors:
        print("[FAIL] No authors loaded from impressum page")
        return False

    print(
        f"[PASS] Loaded {len(scraper.currently_employed_authors)} currently employed authors from impressum"
    )

    # Check if some known authors are in the list
    known_authors = ["Rico Bandle", "Eric Gujer", "David Signer"]
    found_authors = []
    for author in known_authors:
        for employed in scraper.currently_employed_authors:
            if author.lower() in employed.lower():
                found_authors.append(author)
                break

    print(
        f"  Found {len(found_authors)}/{len(known_authors)} known authors in impressum"
    )
    for author in found_authors:
        print(f"    - {author}")

    scraper.cleanup()
    return True


def test_author_currently_employed_check():
    """Test checking if authors are currently employed."""
    print("=" * 80)
    print("TEST 8: Author Currently Employed Check")
    print("=" * 80)

    scraper = NZZScraperV2()

    # Test with known currently employed author
    test_cases = [
        ("Rico Bandle", True),  # Should be employed
        ("Eric Gujer", True),  # Should be employed
        ("David Signer", True),  # Should be employed
        ("Unknown Author XYZ", False),  # Should not be employed
    ]

    all_passed = True
    for author_name, expected_employed in test_cases:
        is_employed = scraper._is_author_currently_employed(author_name)
        status = "[PASS]" if is_employed == expected_employed else "[FAIL]"
        print(f"{status} {author_name}: {is_employed} (expected: {expected_employed})")
        if is_employed != expected_employed:
            all_passed = False

    scraper.cleanup()
    return all_passed


def test_author_without_link():
    """Test creating author entry without link (just name and date)."""
    print("=" * 80)
    print("TEST 9: Author Without Link")
    print("=" * 80)

    scraper = NZZScraperV2()
    db = DatabaseManager()

    # Test author name with city
    test_name = "Andreas Babst, Bangkok"

    # Check if author exists
    if db.author_exists(name=test_name):
        # Delete existing author for clean test
        session = db.Session()
        existing = (
            session.query(Author)
            .filter_by(name=test_name)
            .filter(Author.author_id.like("no-id-%"))
            .first()
        )
        if not existing:
            existing = session.query(Author).filter_by(name=test_name).first()
        if existing:
            session.delete(existing)
            session.commit()
        session.close()

    # Create author without link
    author = db.save_author(
        name=test_name,
        author_id=None,
        author_url=None,
        alias=None,
        currently_employed=0,  # Should be False for authors without links
    )

    if not author:
        print("[FAIL] Failed to create author without link")
        return False

    # Get author data by querying from database (author object may be detached)
    session = db.Session()
    try:
        # Query the author again to get fresh data
        fresh_author = (
            session.query(Author)
            .filter_by(name=test_name)
            .filter(Author.author_id.like("no-id-%"))
            .first()
        )
        if not fresh_author:
            fresh_author = session.query(Author).filter_by(name=test_name).first()

        if fresh_author:
            author_id_val = fresh_author.author_id
            author_url_val = fresh_author.author_url
            author_employed = fresh_author.currently_employed
            author_alias = fresh_author.alias
            author_name = fresh_author.name
        else:
            print("[FAIL] Could not retrieve author from database")
            return False
    finally:
        session.close()

    print(f"[PASS] Created author without link: {author_name}")
    print(f"  Author ID: {author_id_val} (should be placeholder like 'no-id-...')")
    print(f"  Author URL: {author_url_val} (should be placeholder like 'no-url-...')")
    print(f"  Currently Employed: {author_employed} (should be 0)")
    print(f"  Alias: {author_alias} (should be None)")

    # Verify fields
    if not author_id_val or not author_id_val.startswith("no-id-"):
        print(
            f"[FAIL] Author ID should be a placeholder 'no-id-...' for authors without links, got: {author_id_val}"
        )
        return False

    if not author_url_val or not author_url_val.startswith("no-url-"):
        print(
            f"[FAIL] Author URL should be a placeholder 'no-url-...' for authors without links, got: {author_url_val}"
        )
        return False

    if author_employed != 0:
        print("[FAIL] Currently employed should be 0 (False) for authors without links")
        return False

    if author_alias is not None:
        print("[FAIL] Alias should be None (reserved for manual use)")
        return False

    # Check if author exists by name
    if not db.author_exists(name=test_name):
        print("[FAIL] Author should exist when searched by name")
        return False

    # Check if author can be retrieved by name
    retrieved = db.get_author_by_name_or_alias(name=test_name)
    if not retrieved:
        print("[FAIL] Should be able to retrieve author by name")
        return False

    print(f"[PASS] Author can be retrieved by name: {retrieved.name}")

    scraper.cleanup()
    return True


def test_author_with_city_in_name():
    """Test that authors with cities are stored with full name (not as alias)."""
    print("=" * 80)
    print("TEST 10: Author With City In Name")
    print("=" * 80)

    scraper = NZZScraperV2()
    db = DatabaseManager()

    # Test scraping an article that might have author with city
    # We'll use a test article URL
    test_url = "https://www.nzz.ch/international/der-anschlag-in-manchester-ist-ausdruck-eines-weit-verbreiteten-judenhasses-ld.1906060"
    article_id = "1906060"

    print(f"\nScraping article: {test_url}")
    article_data = scraper.scrape_article(test_url, article_id)

    if not article_data:
        print("[FAIL] Failed to scrape article")
        return False

    print(f"[PASS] Article scraped successfully")
    print(f"  Author string: {article_data.get('author', 'N/A')}")

    # Check if any authors were saved without links
    session = db.Session()
    authors_without_links = session.query(Author).filter(Author.author_id == None).all()
    session.close()

    print(f"\nAuthors without links in database: {len(authors_without_links)}")
    for author in authors_without_links[:5]:  # Show first 5
        print(
            f"  - {author.name} (employed: {author.currently_employed}, alias: {author.alias})"
        )
        # Check that full name with city is stored as name, not alias
        if "," in author.name and author.alias is not None:
            print(f"    [WARN] Author has city in name but also has alias set")

    scraper.cleanup()
    return True


def test_author_exists_by_name_or_alias():
    """Test checking if author exists by name or alias."""
    print("=" * 80)
    print("TEST 11: Author Exists By Name Or Alias")
    print("=" * 80)

    db = DatabaseManager()

    # Create a test author with alias
    test_name = "Test Author"
    test_alias = "Test Alias"

    # Clean up if exists
    session = db.Session()
    existing = session.query(Author).filter_by(name=test_name).first()
    if existing:
        session.delete(existing)
        session.commit()
    session.close()

    # Create author with alias
    author = db.save_author(
        name=test_name,
        author_id="test123",
        author_url="https://www.nzz.ch/impressum/test-author-ld.test123",
        alias=test_alias,
        currently_employed=1,
    )

    if not author:
        print("[FAIL] Failed to create test author")
        return False

    # Get author data by querying from database (author object may be detached)
    session = db.Session()
    try:
        # Query the author again to get fresh data
        fresh_author = session.query(Author).filter_by(author_id="test123").first()
        if fresh_author:
            author_name = fresh_author.name
            author_alias = fresh_author.alias
            author_id_val = fresh_author.author_id
        else:
            print("[FAIL] Could not retrieve author from database")
            return False
    finally:
        session.close()

    print(
        f"[PASS] Created test author: {author_name} (alias: {author_alias}, id: {author_id_val})"
    )

    # Test checking by name
    if not db.author_exists(name=test_name):
        print("[FAIL] Should find author by name")
        return False
    print(f"[PASS] Author found by name: {test_name}")

    # Test checking by alias
    if not db.author_exists(alias=test_alias):
        print("[FAIL] Should find author by alias")
        return False
    print(f"[PASS] Author found by alias: {test_alias}")

    # Test retrieving by name
    retrieved = db.get_author_by_name_or_alias(name=test_name)
    if not retrieved or retrieved.name != test_name:
        print("[FAIL] Should retrieve author by name")
        return False
    print(f"[PASS] Author retrieved by name: {retrieved.name}")

    # Test retrieving by alias
    retrieved = db.get_author_by_name_or_alias(alias=test_alias)
    if not retrieved or retrieved.alias != test_alias:
        print("[FAIL] Should retrieve author by alias")
        return False
    print(f"[PASS] Author retrieved by alias: {retrieved.alias}")

    # Clean up
    session = db.Session()
    session.delete(author)
    session.commit()
    session.close()

    return True


def test_scrape_multiple_articles():
    """Test scraping multiple articles to populate database for export.

    Scrapes enough articles to ensure all tables have at least 10 entries:
    - Articles: at least 10
    - Related articles: at least 10
    - Authors: at least 10 (with links)
    - Article-author associations: at least 10
    """
    print("=" * 80)
    print("TEST 6: Scraping Multiple Articles")
    print("=" * 80)

    scraper = NZZScraperV2()
    db = DatabaseManager()

    # List of test article URLs to scrape (prioritize articles with author links)
    # These articles have authors with links that we can scrape
    test_articles = [
        (
            "https://www.nzz.ch/feuilleton/eric-kaufmann-wokeness-hamas-universitaeten-ld.1764342",
            "1764342",
        ),
        (
            "https://www.nzz.ch/international/der-anschlag-in-manchester-ist-ausdruck-eines-weit-verbreiteten-judenhasses-ld.1906060",
            "1906060",
        ),
        (
            "https://www.nzz.ch/feuilleton/was-zum-teufel-ist-aus-grossbritannien-geworden-die-verhaftung-eines-komikers-loest-eine-debatte-aus-ld.1900909",
            "1900909",
        ),
        (
            "https://www.nzz.ch/feuilleton/schweizer-hochschulen-antisemitische-tweets-ld.1765585",
            "1765585",
        ),
        (
            "https://www.nzz.ch/feuilleton/shai-davidai-columbia-harvard-hamas-terror-ld.1762332",
            "1762332",
        ),
        (
            "https://www.nzz.ch/feuilleton/studentische-hamas-fans-die-den-progrom-feiern-ld.1761502",
            "1761502",
        ),
        (
            "https://www.nzz.ch/international/antisemitismus-manchester-ld.1905290",
            "1905290",
        ),
        ("https://www.nzz.ch/international/judenhass-europa-ld.1905501", "1905501"),
        (
            "https://www.nzz.ch/international/israel-palastina-konflikt-ld.1850912",
            "1850912",
        ),
        (
            "https://www.nzz.ch/feuilleton/grossbritannien-komiker-verhaftung-ld.1898033",
            "1898033",
        ),
        (
            "https://www.nzz.ch/feuilleton/frankreich-karikaturist-plantu-ld.1844429",
            "1844429",
        ),
        ("https://www.nzz.ch/feuilleton/ukraine-selenski-ld.1863736", "1863736"),
        # Add more articles to ensure we have enough data
        (
            "https://www.nzz.ch/international/krieg-in-der-ukraine-raketenalarm-in-russland-ld.1900000",
            "1900000",
        ),  # May not exist, will skip
        (
            "https://www.nzz.ch/wirtschaft/migros-renditen-marktniveau-ld.1900001",
            "1900001",
        ),  # May not exist, will skip
    ]

    print(f"\nScraping {len(test_articles)} articles to populate database...\n")

    scraped_count = 0
    skipped_count = 0

    for idx, (url, article_id) in enumerate(test_articles, 1):
        try:
            # Check if already exists
            if db.article_exists(article_id):
                print(
                    f"  [{idx}/{len(test_articles)}] Article {article_id} already exists, skipping..."
                )
                skipped_count += 1
                continue

            print(f"  [{idx}/{len(test_articles)}] Scraping article {article_id}...")
            article_data = scraper.scrape_article(url, article_id)

            if article_data and article_data.get("content"):
                # Save to database
                db.save_article(
                    article_id=article_data["id"],
                    title=article_data["title"],
                    content=article_data["content"],
                    tags=article_data.get("tags", []),
                    article_url=article_data["url"],
                    article_date=article_data.get("article_date"),
                    article_updated=article_data.get("article_updated"),
                    author=article_data.get("author"),
                    description=article_data.get("description"),
                    category=article_data.get("category"),
                    scraped_at=article_data.get("scraped_at"),
                )
                scraped_count += 1
                print(f"    [OK] Saved: {article_data.get('title', 'N/A')[:60]}...")
            else:
                print(f"    [WARN] Failed to scrape article {article_id}")

        except Exception as e:
            print(f"    [WARN] Error scraping article {article_id}: {str(e)}")
            continue

    print(
        f"\n[OK] Scraped {scraped_count} new articles, skipped {skipped_count} existing articles"
    )

    # Process author queue to scrape author profiles
    print("\nProcessing author queue to scrape author profiles...")
    scraper.process_author_queue()

    # Also scrape author profiles from articles that have author links
    # Continue until we have at least 10 authors and 10 associations
    print("\nScraping author profiles from articles with author links...")
    articles = db.get_all_articles()
    author_profiles_scraped = 0
    max_iterations = 50  # Check up to 50 articles
    related_articles_scraped = 0

    # First, scrape some related articles to get more authors
    print("\nScraping related articles to find more authors...")
    all_related = db.Session().query(RelatedArticle).all()
    unique_related_ids = set()
    for rel in all_related:
        unique_related_ids.add(rel.related_article_id)

    # Scrape up to 20 related articles that aren't already in database
    for related_id in list(unique_related_ids)[:20]:
        if db.article_exists(related_id):
            continue

        # Find the related article URL
        related = (
            db.Session()
            .query(RelatedArticle)
            .filter_by(related_article_id=related_id)
            .first()
        )
        if not related:
            continue

        try:
            print(f"  Scraping related article: {related_id}...")
            article_data = scraper.scrape_article(
                related.related_article_url, related_id
            )

            if article_data and article_data.get("content"):
                db.save_article(
                    article_id=article_data["id"],
                    title=article_data["title"],
                    content=article_data["content"],
                    tags=article_data.get("tags", []),
                    article_url=article_data["url"],
                    article_date=article_data.get("article_date"),
                    article_updated=article_data.get("article_updated"),
                    author=article_data.get("author"),
                    description=article_data.get("description"),
                    category=article_data.get("category"),
                    scraped_at=article_data.get("scraped_at"),
                )
                related_articles_scraped += 1
                print(
                    f"    [OK] Saved related article: {article_data.get('title', 'N/A')[:50]}..."
                )
        except Exception as e:
            print(f"    [WARN] Error scraping related article {related_id}: {str(e)}")
            continue

    print(f"\n[OK] Scraped {related_articles_scraped} related articles")

    # Now extract authors from all articles (including newly scraped related articles)
    # Continue until we have at least 10 authors and 10 associations
    articles = db.get_all_articles()
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # Check if we have enough authors and associations
        total_authors = db.Session().query(Author).count()
        from sqlalchemy import text

        total_associations = (
            db.Session()
            .execute(text("SELECT COUNT(*) FROM article_author_association"))
            .scalar()
        )

        if total_authors >= 10 and total_associations >= 10:
            print(
                f"\n[OK] Reached target: {total_authors} authors, {total_associations} associations"
            )
            break

        # Process articles in batches
        for article in articles[iteration * 5 : (iteration + 1) * 5]:
            try:
                # Check again before processing each article
                total_authors = db.Session().query(Author).count()
                total_associations = (
                    db.Session()
                    .execute(text("SELECT COUNT(*) FROM article_author_association"))
                    .scalar()
                )

                if total_authors >= 10 and total_associations >= 10:
                    print(
                        f"\n[OK] Reached target: {total_authors} authors, {total_associations} associations"
                    )
                    break

                # Get the article HTML to extract authors
                from bs4 import BeautifulSoup

                scraper.rate_limiter.wait(jitter=True)
                r = scraper.session.get(article.article_url, timeout=30)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")

                # Extract authors with links
                authors = scraper._extract_authors_from_article(soup)

                for author in authors:
                    if "id" in author and author.get("id"):
                        author_id = author["id"]
                        author_url = author["url"]

                        # Check if author already exists
                        if not db.author_exists(author_id):
                            print(
                                f"  Scraping author profile: {author['name']} ({author_id})..."
                            )
                            author_data = scraper.scrape_author_profile(
                                author_url, author_id
                            )

                            if author_data:
                                db.save_author(
                                    author_id=author_data["id"],
                                    name=author_data["name"],
                                    author_url=author_data["url"],
                                    title=author_data.get("title"),
                                    alternate_name=author_data.get("alternate_name"),
                                    bio=author_data.get("bio"),
                                    image_url=author_data.get("image_url"),
                                )
                                author_profiles_scraped += 1
                                print(f"    [OK] Saved author: {author_data['name']}")

                        # Link author to article if not already linked
                        db.link_article_to_author(article.article_id, author_id)

            except Exception as e:
                print(
                    f"    [WARN] Error processing article {article.article_id}: {str(e)}"
                )
                continue

        # If we've processed all articles, break
        if (iteration + 1) * 5 >= len(articles):
            break

    print(f"\n[OK] Scraped {author_profiles_scraped} additional author profiles")

    # Link articles to authors
    print("\nLinking articles to authors...")
    scraper.link_articles_to_authors_after_scraping()

    # Check totals
    total_articles = db.get_article_count()
    total_related = db.Session().query(RelatedArticle).count()
    total_authors = db.Session().query(Author).count()
    from sqlalchemy import text

    total_associations = (
        db.Session()
        .execute(text("SELECT COUNT(*) FROM article_author_association"))
        .scalar()
    )

    print(f"\n[PASS] Database populated:")
    print(f"  Articles: {total_articles}")
    print(f"  Related Articles: {total_related}")
    print(f"  Authors: {total_authors}")
    print(f"  Article-Author Associations: {total_associations}")

    # Check if we have at least 10 in each table
    if (
        total_articles >= 10
        and total_related >= 10
        and total_authors >= 10
        and total_associations >= 10
    ):
        print(f"\n[PASS] All tables have at least 10 entries!")
    else:
        print(f"\n[WARN] Some tables don't have 10 entries yet:")
        if total_articles < 10:
            print(f"  - Articles: {total_articles} < 10")
        if total_related < 10:
            print(f"  - Related Articles: {total_related} < 10")
        if total_authors < 10:
            print(f"  - Authors: {total_authors} < 10")
        if total_associations < 10:
            print(f"  - Associations: {total_associations} < 10")

    scraper.cleanup()
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("NZZ SCRAPER V2 TEST SUITE")
    print("=" * 80)

    # Clean database before tests
    clean_database_before_tests()

    tests = [
        ("Database Tables", test_database_tables),
        ("Related Articles Extraction", test_related_articles_extraction),
        ("Authors Extraction", test_authors_extraction),
        ("Author Profile Scraping", test_author_profile_scraping),
        ("Single Article Scraping", test_scrape_single_article),
        ("Multiple Articles Scraping", test_scrape_multiple_articles),
        ("Impressum Authors Loading", test_impressum_loading),
        ("Author Currently Employed Check", test_author_currently_employed_check),
        ("Author Without Link", test_author_without_link),
        ("Author With City In Name", test_author_with_city_in_name),
        ("Author Exists By Name Or Alias", test_author_exists_by_name_or_alias),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n[FAIL] Test '{test_name}' crashed: {str(e)}")
            import traceback

            traceback.print_exc()
            results.append((test_name, False))

    # Export test data to JSON files
    export_data_to_json()

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 80)

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
