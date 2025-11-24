"""Sync department and location between articles and authors tables.

This script:
1. Loads articles (with authors as JSON list) and authors (with name as text)
2. Matches authors by name (case-insensitive)
3. Copies department and location both ways:
   - From articles to authors (for each author in article's author list)
   - From authors to articles (for each article that contains the author)
4. Appends values uniquely (avoids duplicates)
5. Updates both tables
"""
import os
import ast
import json
import re
import html
import pandas as pd
import logging
from collections import defaultdict
from dotenv import load_dotenv

try:
    from sqlalchemy import create_engine, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    print("Error: SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('sync_author_article_data')

# Load environment variables
load_dotenv()


class AuthorArticleDataSyncer:
    """Sync department and location data between articles and authors."""
    
    def __init__(self):
        """Initialize with Supabase PostgreSQL connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError("SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")
        
        # PostgreSQL connection parameters from environment
        self.user = os.getenv("user")
        self.password = os.getenv("password")
        self.host = os.getenv("host")
        self.port = os.getenv("port", "5432")
        self.dbname = os.getenv("dbname")
        
        # Validate connection parameters
        if not all([self.user, self.password, self.host, self.dbname]):
            missing = []
            if not self.user:
                missing.append("user")
            if not self.password:
                missing.append("password")
            if not self.host:
                missing.append("host")
            if not self.dbname:
                missing.append("dbname")
            raise ValueError(
                f"Missing required database connection parameters: {', '.join(missing)}\n"
                "Set the following in your .env file:\n"
                "  user=postgres.[PROJECT-REF]\n"
                "  password=[YOUR-PASSWORD]\n"
                "  host=aws-0-[REGION].pooler.supabase.com\n"
                "  port=6543 (Session mode) or 5432 (Transaction mode)\n"
                "  dbname=postgres"
            )
        
        # Create SQLAlchemy engine
        self.engine = self._create_engine()
    
    def _create_engine(self):
        """Create SQLAlchemy engine for PostgreSQL (Supabase) connection."""
        try:
            connection_string = (
                f"postgresql://{self.user}:{self.password}@"
                f"{self.host}:{self.port}/{self.dbname}"
            )
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": 30,
                    "options": "-c statement_timeout=300000"  # 5 minutes
                }
            )
            return engine
        except Exception as e:
            raise ConnectionError(f"Failed to create database engine: {e}")
    
    def _normalize_name(self, name):
        """Normalize author name for matching (case-insensitive, trimmed, cleaned)."""
        if pd.isna(name) or not name:
            return None
        # Clean HTML entities and unicode escapes before normalizing
        cleaned = self._clean_text(str(name))
        return cleaned.lower() if cleaned else None
    
    def _parse_authors_list(self, authors_field):
        """Parse authors field from articles (can be JSON string or list).
        Also cleans HTML entities and converts unicode escapes.
        """
        if pd.isna(authors_field):
            return []
        
        try:
            # Try json.loads first to handle unicode escapes properly
            if isinstance(authors_field, str):
                try:
                    parsed = json.loads(authors_field)
                except (json.JSONDecodeError, ValueError):
                    parsed = ast.literal_eval(authors_field)
            elif isinstance(authors_field, list):
                parsed = authors_field
            else:
                return []
            
            if isinstance(parsed, list):
                # Clean each author name
                cleaned_authors = []
                for a in parsed:
                    if a:
                        cleaned = self._clean_text(str(a))
                        if cleaned:
                            cleaned_authors.append(cleaned)
                return cleaned_authors
            return []
        except Exception:
            return []
    
    def _clean_text(self, text):
        """Clean HTML entities and convert unicode escapes in text.
        
        Args:
            text: Text string that may contain HTML entities or unicode escapes
            
        Returns:
            Cleaned text with HTML entities decoded and unicode escapes converted
        """
        if not text or not isinstance(text, str):
            return text
        
        # First, normalize HTML entities that might be missing semicolons
        common_entities = ['nbsp', 'amp', 'lt', 'gt', 'quot', 'apos']
        cleaned = text
        for entity in common_entities:
            # Match &entity at word boundary (not followed by semicolon or alphanumeric)
            cleaned = re.sub(rf'&{entity}(?![#\w;])', f'&{entity};', cleaned)
        
        # Decode HTML entities (e.g., &nbsp; -> space, &amp; -> &, etc.)
        cleaned = html.unescape(cleaned)
        
        # Also handle numeric entities (e.g., &#160; for non-breaking space)
        cleaned = re.sub(r'&#(\d+);?', lambda m: chr(int(m.group(1))), cleaned)
        cleaned = re.sub(r'&#x([0-9a-fA-F]+);?', lambda m: chr(int(m.group(1), 16)), cleaned)
        
        # Convert unicode escape sequences (e.g., \u00fc -> ü)
        # Try to decode as JSON string first (handles \u escapes)
        try:
            # If it looks like it might have unicode escapes, try json.loads
            if '\\u' in cleaned:
                # Try to decode as JSON string
                decoded = json.loads(f'"{cleaned}"')
                cleaned = decoded
        except (json.JSONDecodeError, ValueError):
            # If JSON decoding fails, try manual unicode escape conversion
            try:
                cleaned = cleaned.encode().decode('unicode_escape')
            except (UnicodeDecodeError, ValueError):
                pass
        
        # Normalize whitespace (replace all whitespace sequences with single space)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Remove leading/trailing whitespace
        cleaned = cleaned.strip()
        
        return cleaned
    
    def _parse_list_value(self, value):
        """Parse a value that might be a JSON list, comma-separated string, or single value.
        Also cleans HTML entities and converts unicode escapes.
        
        Args:
            value: Value that could be a JSON list string, comma-separated string, or single value
            
        Returns:
            list: List of cleaned items, or empty list if value is empty/None
        """
        if pd.isna(value) or not value:
            return []
        
        val_str = str(value).strip()
        if not val_str:
            return []
        
        # Try to parse as JSON list first (this automatically converts \u escapes)
        try:
            # Check if it looks like a JSON list
            if val_str.startswith('[') and val_str.endswith(']'):
                # Use json.loads to properly handle unicode escapes
                parsed = json.loads(val_str)
                if isinstance(parsed, list):
                    # Clean each item
                    cleaned_items = []
                    for item in parsed:
                        if item:
                            cleaned = self._clean_text(str(item))
                            if cleaned:
                                cleaned_items.append(cleaned)
                    return cleaned_items
        except (json.JSONDecodeError, ValueError):
            # If json.loads fails, try ast.literal_eval as fallback
            try:
                if val_str.startswith('[') and val_str.endswith(']'):
                    parsed = ast.literal_eval(val_str)
                    if isinstance(parsed, list):
                        cleaned_items = []
                        for item in parsed:
                            if item:
                                cleaned = self._clean_text(str(item))
                                if cleaned:
                                    cleaned_items.append(cleaned)
                        return cleaned_items
            except Exception:
                pass
        
        # Try parsing as comma-separated string
        if ',' in val_str:
            items = [item.strip() for item in val_str.split(',') if item.strip()]
            # Check if any item is a JSON list itself
            result = []
            for item in items:
                item = item.strip()
                # Remove surrounding quotes if present
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                # Try to parse as JSON list
                if item.startswith('[') and item.endswith(']'):
                    try:
                        parsed = json.loads(item)
                        if isinstance(parsed, list):
                            for i in parsed:
                                if i:
                                    cleaned = self._clean_text(str(i))
                                    if cleaned:
                                        result.append(cleaned)
                        else:
                            cleaned = self._clean_text(item)
                            if cleaned:
                                result.append(cleaned)
                    except (json.JSONDecodeError, ValueError):
                        cleaned = self._clean_text(item)
                        if cleaned:
                            result.append(cleaned)
                else:
                    cleaned = self._clean_text(item)
                    if cleaned:
                        result.append(cleaned)
            return result
        
        # Single value - clean it
        cleaned = self._clean_text(val_str)
        return [cleaned] if cleaned else []
    
    def _merge_list_values(self, *values):
        """Merge multiple values (JSON lists, comma-separated strings, or single values) into a single list.
        
        Args:
            *values: Variable number of values (can be None/NaN, JSON lists, comma-separated strings, or single values)
            
        Returns:
            str: JSON string representation of merged list with unique values, or None if all values are empty
        """
        all_items = []
        
        for val in values:
            if pd.notna(val) and val:
                items = self._parse_list_value(val)
                all_items.extend(items)
        
        if not all_items:
            return None
        
        # Remove duplicates while preserving order (case-insensitive)
        seen = set()
        unique_items = []
        for item in all_items:
            item_lower = item.lower()
            if item_lower not in seen:
                seen.add(item_lower)
                unique_items.append(item)
        
        # Return as JSON string (list format) with ensure_ascii=False to preserve unicode characters
        # This ensures ü is stored as ü, not as \u00fc
        return json.dumps(unique_items, ensure_ascii=False) if unique_items else None
    
    def load_data(self):
        """Load articles and authors from database."""
        logger.info("Loading articles and authors from database...")
        
        # Load articles
        articles_query = """
            SELECT article_id, authors, department, location
            FROM articles
            WHERE authors IS NOT NULL
        """
        articles_df = pd.read_sql(articles_query, self.engine)
        logger.info(f"Loaded {len(articles_df):,} articles")
        
        # Load authors
        authors_query = """
            SELECT id, name, department, location
            FROM authors
        """
        authors_df = pd.read_sql(authors_query, self.engine)
        logger.info(f"Loaded {len(authors_df):,} authors")
        
        return articles_df, authors_df
    
    def build_name_mapping(self, authors_df):
        """Build mapping from normalized author name to author records."""
        name_to_authors = defaultdict(list)
        
        for _, author in authors_df.iterrows():
            normalized_name = self._normalize_name(author['name'])
            if normalized_name:
                name_to_authors[normalized_name].append(author)
        
        logger.info(f"Built name mapping for {len(name_to_authors):,} unique author names")
        return name_to_authors
    
    def sync_data(self, articles_df, authors_df, name_to_authors):
        """Sync department and location between articles and authors.
        
        Returns:
            tuple: (articles_updates, authors_updates)
                articles_updates: dict mapping article_id to {department, location}
                authors_updates: dict mapping author_id to {department, location}
        """
        logger.info("Syncing department and location data...")
        
        # Initialize update dictionaries
        articles_updates = {}
        authors_updates = defaultdict(lambda: {'department': None, 'location': None})
        
        # Process each article
        for _, article in articles_df.iterrows():
            article_id = article['article_id']
            article_dept = article['department']
            article_loc = article['location']
            
            # Parse authors list
            author_names = self._parse_authors_list(article['authors'])
            
            if not author_names:
                continue
            
            # For each author in the article, copy article's dept/loc to author
            for author_name in author_names:
                normalized_name = self._normalize_name(author_name)
                if normalized_name and normalized_name in name_to_authors:
                    # Found matching author(s) - there might be duplicates
                    for author_record in name_to_authors[normalized_name]:
                        author_id = author_record['id']
                        
                        # Merge department (as list)
                        existing_dept = authors_updates[author_id]['department']
                        authors_updates[author_id]['department'] = self._merge_list_values(
                            existing_dept, article_dept
                        )
                        
                        # Merge location (as list)
                        existing_loc = authors_updates[author_id]['location']
                        authors_updates[author_id]['location'] = self._merge_list_values(
                            existing_loc, article_loc
                        )
            
            # For each author in the article, copy author's dept/loc to article
            article_depts = []
            article_locs = []
            
            for author_name in author_names:
                normalized_name = self._normalize_name(author_name)
                if normalized_name and normalized_name in name_to_authors:
                    for author_record in name_to_authors[normalized_name]:
                        if pd.notna(author_record['department']) and author_record['department']:
                            article_depts.append(author_record['department'])
                        if pd.notna(author_record['location']) and author_record['location']:
                            article_locs.append(author_record['location'])
            
            # Merge all departments and locations for this article (as lists)
            merged_dept = self._merge_list_values(article_dept, *article_depts)
            merged_loc = self._merge_list_values(article_loc, *article_locs)
            
            # Compare by parsing and normalizing JSON strings
            article_dept_parsed = self._parse_list_value(article_dept) if pd.notna(article_dept) else []
            merged_dept_parsed = self._parse_list_value(merged_dept) if merged_dept else []
            article_loc_parsed = self._parse_list_value(article_loc) if pd.notna(article_loc) else []
            merged_loc_parsed = self._parse_list_value(merged_loc) if merged_loc else []
            
            # Check if values changed (compare normalized lists)
            dept_changed = sorted([x.lower() for x in article_dept_parsed]) != sorted([x.lower() for x in merged_dept_parsed])
            loc_changed = sorted([x.lower() for x in article_loc_parsed]) != sorted([x.lower() for x in merged_loc_parsed])
            
            if dept_changed or loc_changed:
                articles_updates[article_id] = {
                    'department': merged_dept,
                    'location': merged_loc
                }
        
        # Also add existing author data to updates (merge with what we collected)
        for _, author in authors_df.iterrows():
            author_id = author['id']
            existing_dept = author['department']
            existing_loc = author['location']
            
            # Merge with any updates we collected
            updated_dept = authors_updates[author_id]['department']
            updated_loc = authors_updates[author_id]['location']
            
            final_dept = self._merge_list_values(existing_dept, updated_dept)
            final_loc = self._merge_list_values(existing_loc, updated_loc)
            
            # Compare by parsing and normalizing JSON strings
            existing_dept_parsed = self._parse_list_value(existing_dept) if pd.notna(existing_dept) else []
            final_dept_parsed = self._parse_list_value(final_dept) if final_dept else []
            existing_loc_parsed = self._parse_list_value(existing_loc) if pd.notna(existing_loc) else []
            final_loc_parsed = self._parse_list_value(final_loc) if final_loc else []
            
            # Check if values changed (compare normalized lists)
            dept_changed = sorted([x.lower() for x in existing_dept_parsed]) != sorted([x.lower() for x in final_dept_parsed])
            loc_changed = sorted([x.lower() for x in existing_loc_parsed]) != sorted([x.lower() for x in final_loc_parsed])
            
            if dept_changed or loc_changed:
                authors_updates[author_id] = {
                    'department': final_dept,
                    'location': final_loc
                }
            elif updated_dept is None and updated_loc is None:
                # No updates for this author, remove from dict
                del authors_updates[author_id]
        
        logger.info(f"Prepared updates for {len(articles_updates):,} articles")
        logger.info(f"Prepared updates for {len(authors_updates):,} authors")
        
        # Store original values for comparison in dry-run
        articles_original = {}
        authors_original = {}
        
        for article_id in articles_updates.keys():
            article_row = articles_df[articles_df['article_id'] == article_id].iloc[0]
            articles_original[article_id] = {
                'department': article_row['department'],
                'location': article_row['location']
            }
        
        for author_id in authors_updates.keys():
            author_row = authors_df[authors_df['id'] == author_id].iloc[0]
            authors_original[author_id] = {
                'department': author_row['department'],
                'location': author_row['location'],
                'name': author_row['name']
            }
        
        return articles_updates, authors_updates, articles_original, authors_original
    
    def update_database(self, articles_updates, authors_updates, batch_size=1000):
        """Update database with synced data."""
        logger.info("Updating database...")
        
        try:
            with self.engine.begin() as conn:  # Use transaction
                # Update articles
                articles_updated = 0
                for article_id, data in articles_updates.items():
                    update_query = text("""
                        UPDATE articles
                        SET department = :department,
                            location = :location
                        WHERE article_id = :article_id
                    """)
                    conn.execute(update_query, {
                        'article_id': article_id,
                        'department': data['department'],
                        'location': data['location']
                    })
                    articles_updated += 1
                    
                    if articles_updated % batch_size == 0:
                        logger.info(f"Updated {articles_updated:,} / {len(articles_updates):,} articles")
                
                logger.info(f"Updated {articles_updated:,} articles")
                
                # Update authors
                authors_updated = 0
                for author_id, data in authors_updates.items():
                    update_query = text("""
                        UPDATE authors
                        SET department = :department,
                            location = :location
                        WHERE id = :id
                    """)
                    conn.execute(update_query, {
                        'id': int(author_id),
                        'department': data['department'],
                        'location': data['location']
                    })
                    authors_updated += 1
                    
                    if authors_updated % batch_size == 0:
                        logger.info(f"Updated {authors_updated:,} / {len(authors_updates):,} authors")
                
                logger.info(f"Updated {authors_updated:,} authors")
                
        except Exception as e:
            logger.error(f"Error updating database: {e}")
            raise
    
    def run(self, dry_run=False):
        """Run the complete sync process.
        
        Args:
            dry_run (bool): If True, only show what would be updated without making changes
        """
        logger.info("="*80)
        logger.info("Starting author-article data sync process")
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made")
        logger.info("="*80)
        
        try:
            # Load data
            articles_df, authors_df = self.load_data()
            
            # Build name mapping
            name_to_authors = self.build_name_mapping(authors_df)
            
            # Sync data
            articles_updates, authors_updates, articles_original, authors_original = self.sync_data(
                articles_df, authors_df, name_to_authors
            )
            
            if dry_run:
                # Show what would be updated with before/after comparison
                logger.info("\n" + "="*80)
                logger.info("ARTICLES TABLE - Changes Preview")
                logger.info("="*80)
                
                if len(articles_updates) == 0:
                    logger.info("No articles would be updated.")
                else:
                    logger.info(f"\n{len(articles_updates):,} articles would be updated:\n")
                    for i, (article_id, data) in enumerate(list(articles_updates.items())[:20]):
                        original = articles_original[article_id]
                        logger.info(f"Article ID: {article_id}")
                        logger.info("  Department:")
                        logger.info(f"    BEFORE: {original['department']}")
                        logger.info(f"    AFTER:  {data['department']}")
                        logger.info("  Location:")
                        logger.info(f"    BEFORE: {original['location']}")
                        logger.info(f"    AFTER:  {data['location']}")
                        logger.info("")
                    if len(articles_updates) > 20:
                        logger.info(f"  ... and {len(articles_updates) - 20} more articles")
                
                logger.info("\n" + "="*80)
                logger.info("AUTHORS TABLE - Changes Preview")
                logger.info("="*80)
                
                if len(authors_updates) == 0:
                    logger.info("No authors would be updated.")
                else:
                    logger.info(f"\n{len(authors_updates):,} authors would be updated:\n")
                    for i, (author_id, data) in enumerate(list(authors_updates.items())[:20]):
                        original = authors_original[author_id]
                        logger.info(f"Author ID: {author_id} (Name: {original['name']})")
                        logger.info("  Department:")
                        logger.info(f"    BEFORE: {original['department']}")
                        logger.info(f"    AFTER:  {data['department']}")
                        logger.info("  Location:")
                        logger.info(f"    BEFORE: {original['location']}")
                        logger.info(f"    AFTER:  {data['location']}")
                        logger.info("")
                    if len(authors_updates) > 20:
                        logger.info(f"  ... and {len(authors_updates) - 20} more authors")
                
                logger.info("\n" + "="*80)
                logger.info("Run without --dry-run to perform the updates.")
                logger.info("="*80)
                return
            
            # Update database
            self.update_database(articles_updates, authors_updates)
            
            logger.info("="*80)
            logger.info("Sync process completed successfully!")
            logger.info(f"  Articles updated: {len(articles_updates):,}")
            logger.info(f"  Authors updated: {len(authors_updates):,}")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"Process failed: {e}")
            raise


if __name__ == "__main__":
    import sys
    
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv
    
    syncer = AuthorArticleDataSyncer()
    syncer.run(dry_run=dry_run)

