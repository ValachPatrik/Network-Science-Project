"""08 - Manual Fix Author Names (Interactive Review)

This script allows manual review and fixing of suspicious author names.
It identifies potentially concatenated author names (no commas, multiple words)
and allows you to review and fix them interactively.

Usage:
    python 08_manual_fix_authors.py
    
The script will:
1. Find articles with suspicious author names
2. Show them for review
3. Allow you to edit and save changes
4. Track what was changed
"""
import os
import sys
import json
import logging
import platform

# Try to import readline (works on Unix/Linux/Mac)
READLINE_AVAILABLE = False
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    # On Windows, try pyreadline3 (needs to be installed: pip install pyreadline3)
    if platform.system() == 'Windows':
        try:
            import pyreadline3 as readline
            READLINE_AVAILABLE = True
        except ImportError:
            READLINE_AVAILABLE = False
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('manual_fix_authors')

Base = declarative_base()


class Article(Base):
    """Processed article data."""
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String(1000), nullable=True)
    category = Column(String(200), nullable=True)
    authors = Column(Text, nullable=True)  # JSON list of author names
    department = Column(String(200), nullable=True)  # JSON list of departments
    location = Column(String(200), nullable=True)  # JSON list of locations
    related_articles = Column(Text, nullable=True)
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


class ProcessedDatabaseManager:
    """Manages database connection for processed tables."""
    
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(PARENT_DIR, 'nzz_scraped_articles.db')
        
        db_path = os.path.normpath(db_path)
        logger.info(f"Database path: {db_path}")
        
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            poolclass=NullPool,
            connect_args={'check_same_thread': False}
        )
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.db_path = db_path
    
    def close(self):
        """Close database connections."""
        try:
            if hasattr(self, 'Session') and self.Session:
                self.Session.remove()
            if hasattr(self, 'engine') and self.engine:
                self.engine.dispose()
        except Exception as e:
            logger.warning(f"Error closing database connections: {str(e)}")


# Terms to move to departments (case-insensitive)
TERMS_TO_DEPARTMENTS = {
    "bildredaktion nzz": "Bildredaktion NZZ"
}


def is_suspicious_author(author_string):
    """Check if an author string looks suspicious (might need splitting).
    
    Args:
        author_string: Author string to check
        
    Returns:
        True if suspicious (no commas, 4+ words, no "und")
    """
    if not author_string or not isinstance(author_string, str):
        return False
    
    author_string = author_string.strip()
    
    # Already has commas - probably fine
    if ',' in author_string:
        return False
    
    # Has "und" - probably fine (will be handled by other script)
    if ' und ' in author_string.lower():
        return False
    
    # Check if it's a department term
    if author_string.lower() in TERMS_TO_DEPARTMENTS:
        return False
    
    # Multiple words (4+) without commas - suspicious
    # 3-word names are common (first middle last) so not suspicious
    words = author_string.split()
    if len(words) >= 4:
        return True
    
    return False


def parse_author_list(author_string):
    """Parse author string into list, handling JSON or comma-separated.
    
    Args:
        author_string: Author string (JSON list or comma-separated)
        
    Returns:
        List of author strings
    """
    if not author_string:
        return []
    
    # Try JSON first
    if isinstance(author_string, str):
        try:
            parsed = json.loads(author_string)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Try comma-separated
        if ',' in author_string:
            return [a.strip() for a in author_string.split(',') if a.strip()]
        
        # Single author
        return [author_string.strip()] if author_string.strip() else []
    
    if isinstance(author_string, list):
        return author_string
    
    return []


def format_author_list(authors):
    """Format author list as JSON string.
    
    Args:
        authors: List of author strings
        
    Returns:
        JSON string or None if empty
    """
    if not authors:
        return None
    return json.dumps(authors)


def manual_fix_authors():
    """Interactive script to manually review and fix author names."""
    logger.info("="*80)
    logger.info("08 - Manual Fix Author Names (Interactive Review)")
    logger.info("="*80)
    logger.info("This script helps you review and fix suspicious author names.")
    logger.info("="*80)
    
    # Initialize database manager
    processed_db = ProcessedDatabaseManager()
    
    try:
        # Create tables if they don't exist
        Base.metadata.create_all(processed_db.engine)
        
        processed_session = processed_db.Session()
        
        try:
            # Get all articles with author data
            logger.info("Loading articles with author data...")
            all_articles = processed_session.query(Article).filter(
                Article.authors.isnot(None)
            ).all()
            
            total_articles = len(all_articles)
            logger.info(f"Found {total_articles} articles with author data")
            
            if total_articles == 0:
                logger.info("No articles with author data found. Exiting.")
                return
            
            # Find suspicious authors and track all instances
            suspicious_items = []
            suspicious_author_to_articles = {}  # Map author -> list of (article, all_authors, author_index)
            
            for article in all_articles:
                try:
                    authors = parse_author_list(article.authors)
                    
                    for idx, author in enumerate(authors):
                        if is_suspicious_author(author):
                            # Track all instances of this suspicious author
                            if author not in suspicious_author_to_articles:
                                suspicious_author_to_articles[author] = []
                            
                            suspicious_author_to_articles[author].append({
                                'article': article,
                                'all_authors': authors,
                                'author_index': idx,
                                'article_id': article.article_id,
                                'title': article.title[:80] if article.title else 'No title'
                            })
                except Exception as e:
                    logger.debug(f"Error processing article {article.article_id}: {str(e)}")
                    continue
            
            # Create unique suspicious items (one per unique author)
            for author, instances in suspicious_author_to_articles.items():
                suspicious_items.append({
                    'author': author,
                    'instances': instances,  # All articles with this suspicious author
                    'count': len(instances)  # How many times it appears
                })
            
            total_suspicious = len(suspicious_items)
            total_instances = sum(item['count'] for item in suspicious_items)
            logger.info(f"Found {total_suspicious} unique suspicious author names ({total_instances} total instances)")
            
            if total_suspicious == 0:
                logger.info("No suspicious author names found. Exiting.")
                return
            
            # Interactive review
            logger.info("="*80)
            logger.info("Starting interactive review...")
            logger.info("="*80)
            logger.info("Commands:")
            logger.info("  - Enter comma-separated names for authors (e.g., 'Name1, Name2')")
            logger.info("  - Use 'dept:Name' to move parts to departments (e.g., 'dept:Bildredaktion NZZ')")
            logger.info("  - Use 'loc:Name' to move parts to locations (e.g., 'loc:Berlin')")
            logger.info("  - You can mix: 'Name1, Name2, dept:Dept1, loc:Location1'")
            logger.info("  - Enter 'skip' or 's' to skip this item")
            logger.info("  - Enter 'delete' or 'd' to remove this author completely")
            logger.info("  - Enter 'quit' or 'q' to save and exit")
            logger.info("="*80)
            
            fixed_count = 0
            skipped_count = 0
            deleted_count = 0
            moved_to_dept_count = 0
            moved_to_loc_count = 0
            
            for idx, item in enumerate(suspicious_items, 1):
                author = item['author']
                instances = item['instances']
                instance_count = item['count']
                
                # Show first instance as example
                first_instance = instances[0]
                
                print("\n" + "="*80)
                print(f"Item {idx}/{total_suspicious} (appears in {instance_count} article(s))")
                print("="*80)
                print(f"Current author: {author}")
                if instance_count > 1:
                    print(f"\nThis author appears in {instance_count} articles:")
                    for inst in instances[:5]:  # Show first 5
                        print(f"  - {inst['article_id']}: {inst['title']}")
                    if instance_count > 5:
                        print(f"  ... and {instance_count - 5} more")
                else:
                    print(f"\nArticle: {first_instance['article_id']} - {first_instance['title']}")
                print(f"Example - All authors in first article: {json.dumps(first_instance['all_authors'], ensure_ascii=False)}")
                print("="*80)
                print("NOTE: Your fix will be applied to ALL instances of this author!")
                print("="*80)
                
                while True:
                    try:
                        # Show current value prominently for easy copy-paste editing
                        print(f"\n{'='*80}")
                        print("CURRENT VALUE (copy this and edit):")
                        print(f"{'='*80}")
                        print(f"  {author}")
                        print(f"{'='*80}")
                        print("\nQuick shortcuts:")
                        print("  - Type comma-separated names to replace (e.g., 'Name1, Name2')")
                        print("  - Type '2' to automatically split every 2 words with commas")
                        print("  - Use 'dept:Name' or 'loc:Name' to move parts")
                        print("  - Use pattern 's/old/new/' to replace (e.g., 's/ /, /' adds commas)")
                        print("  - Type 'skip' or 's' to skip")
                        print("  - Type 'delete' or 'd' to remove")
                        print("  - Type 'quit' or 'q' to save and exit")
                        print(f"\n{'='*80}")
                        
                        # Try readline if available (Unix/Mac)
                        use_readline = READLINE_AVAILABLE
                        if use_readline:
                            try:
                                readline.set_startup_hook(lambda: readline.insert_text(author))
                                prompt = "Your input: "
                            except Exception:
                                use_readline = False
                                prompt = "Your input: "
                        else:
                            prompt = "Your input: "
                        
                        try:
                            user_input = input(prompt).strip()
                        finally:
                            if use_readline:
                                try:
                                    readline.set_startup_hook()
                                except Exception:
                                    pass
                        
                        if not user_input:
                            continue
                        
                        user_input_lower = user_input.lower()
                        
                        # Quick split every 2 words
                        if user_input_lower == '2':
                            words = author.split()
                            if len(words) >= 2:
                                # Split into pairs of words
                                split_authors = []
                                for i in range(0, len(words), 2):
                                    if i + 1 < len(words):
                                        split_authors.append(f"{words[i]} {words[i+1]}")
                                    else:
                                        # Odd number of words - last word alone
                                        split_authors.append(words[i])
                                user_input = ', '.join(split_authors)
                                print(f"Auto-split result: {user_input}")
                            else:
                                print("Not enough words to split (need at least 2 words).")
                                continue
                        
                        # Check for pattern replacement (s/old/new/)
                        elif user_input.startswith('s/') and user_input.count('/') >= 3:
                            # Pattern replacement: s/old/new/
                            parts = user_input.split('/')
                            if len(parts) >= 3:
                                old_text = parts[1]
                                new_text = parts[2]
                                # Apply replacement
                                modified_author = author.replace(old_text, new_text)
                                if modified_author != author:
                                    user_input = modified_author
                                    print(f"Applied pattern: '{old_text}' -> '{new_text}'")
                                    print(f"Result: {modified_author}")
                                else:
                                    print(f"Pattern '{old_text}' not found in current value.")
                                    continue
                        
                        # Re-check user_input_lower after potential modifications
                        user_input_lower = user_input.lower()
                        
                        if user_input_lower in ['quit', 'q']:
                            logger.info("Saving changes and exiting...")
                            processed_session.commit()
                            logger.info("="*80)
                            logger.info("Summary:")
                            logger.info(f"  Fixed: {fixed_count}")
                            logger.info(f"  Skipped: {skipped_count}")
                            logger.info(f"  Deleted: {deleted_count}")
                            logger.info(f"  Moved to departments: {moved_to_dept_count}")
                            logger.info(f"  Moved to locations: {moved_to_loc_count}")
                            logger.info(f"  Remaining: {total_suspicious - idx + 1}")
                            logger.info("="*80)
                            return
                        
                        if user_input_lower in ['skip', 's']:
                            skipped_count += 1
                            logger.info("Skipped")
                            break
                        
                        if user_input_lower in ['delete', 'd']:
                            # Remove this author from ALL instances
                            for inst in instances:
                                article = inst['article']
                                all_authors = inst['all_authors']
                                updated_authors = [a for a in all_authors if a != author]
                                article.authors = format_author_list(updated_authors)
                            
                            deleted_count += instance_count
                            logger.info(f"Deleted from {instance_count} article(s)")
                            fixed_count += instance_count
                            break
                        
                        if user_input_lower == 'dept':
                            # Quick move to departments (legacy shortcut) - apply to ALL instances
                            dept_name = TERMS_TO_DEPARTMENTS.get(author.lower(), author)
                            
                            for inst in instances:
                                article = inst['article']
                                all_authors = inst['all_authors']
                                
                                # Update departments
                                current_departments = []
                                if article.department:
                                    try:
                                        current_departments = json.loads(article.department) if isinstance(article.department, str) else article.department
                                    except (json.JSONDecodeError, TypeError):
                                        current_departments = []
                                
                                if dept_name not in current_departments:
                                    current_departments.append(dept_name)
                                
                                article.department = format_author_list(current_departments)
                                
                                # Remove from authors
                                updated_authors = [a for a in all_authors if a != author]
                                article.authors = format_author_list(updated_authors)
                            
                            moved_to_dept_count += instance_count
                            logger.info(f"Moved to departments in {instance_count} article(s)")
                            fixed_count += instance_count
                            break
                        
                        # Parse the input - can contain authors, dept:..., loc:...
                        parts = [p.strip() for p in user_input.split(',') if p.strip()]
                        
                        if not parts:
                            print("Error: No valid input entered. Please try again.")
                            continue
                        
                        # Separate into authors, departments, and locations
                        new_authors = []
                        new_departments = []
                        new_locations = []
                        
                        for part in parts:
                            part_lower = part.lower()
                            
                            if part_lower.startswith('dept:'):
                                # Department
                                dept_name = part[5:].strip()  # Remove 'dept:' prefix
                                if dept_name:
                                    new_departments.append(dept_name)
                            elif part_lower.startswith('loc:'):
                                # Location
                                loc_name = part[4:].strip()  # Remove 'loc:' prefix
                                if loc_name:
                                    new_locations.append(loc_name)
                            else:
                                # Regular author
                                new_authors.append(part)
                        
                        # Apply fix to ALL instances
                        for inst in instances:
                            article = inst['article']
                            all_authors = inst['all_authors']
                            author_index = inst['author_index']
                            
                            # Update authors
                            updated_authors = all_authors[:author_index] + new_authors + all_authors[author_index + 1:]
                            article.authors = format_author_list(updated_authors)
                            
                            # Update departments if any
                            if new_departments:
                                current_departments = []
                                if article.department:
                                    try:
                                        current_departments = json.loads(article.department) if isinstance(article.department, str) else article.department
                                    except (json.JSONDecodeError, TypeError):
                                        current_departments = []
                                
                                for dept in new_departments:
                                    # Use standardized name if available
                                    dept_name = TERMS_TO_DEPARTMENTS.get(dept.lower(), dept)
                                    if dept_name not in current_departments:
                                        current_departments.append(dept_name)
                                
                                article.department = format_author_list(current_departments)
                            
                            # Update locations if any
                            if new_locations:
                                current_locations = []
                                if article.location:
                                    try:
                                        current_locations = json.loads(article.location) if isinstance(article.location, str) else article.location
                                    except (json.JSONDecodeError, TypeError):
                                        current_locations = []
                                
                                for loc in new_locations:
                                    if loc not in current_locations:
                                        current_locations.append(loc)
                                
                                article.location = format_author_list(current_locations)
                        
                        fixed_count += instance_count
                        moved_to_dept_count += len(new_departments) * instance_count if new_departments else 0
                        moved_to_loc_count += len(new_locations) * instance_count if new_locations else 0
                        
                        logger.info(f"Fixed in {instance_count} article(s).")
                        if new_authors:
                            logger.info(f"  Authors: {json.dumps(new_authors, ensure_ascii=False)}")
                        if new_departments:
                            logger.info(f"  Departments: {json.dumps(new_departments, ensure_ascii=False)}")
                        if new_locations:
                            logger.info(f"  Locations: {json.dumps(new_locations, ensure_ascii=False)}")
                        break
                    
                    except KeyboardInterrupt:
                        print("\n\nInterrupted. Saving changes...")
                        processed_session.commit()
                        logger.info("Changes saved. Exiting.")
                        return
                    except Exception as e:
                        print(f"Error: {str(e)}. Please try again.")
                        continue
                
                # Commit every 10 unique items
                if idx % 10 == 0:
                    try:
                        processed_session.commit()
                        logger.info(f"Progress saved (processed {idx}/{total_suspicious} unique authors)")
                    except Exception as commit_error:
                        processed_session.rollback()
                        logger.warning(f"Commit error: {str(commit_error)}")
            
            # Final commit
            try:
                processed_session.commit()
            except Exception as commit_error:
                processed_session.rollback()
                logger.error(f"Final commit error: {str(commit_error)}")
                raise
            
            logger.info("="*80)
            logger.info("Review complete!")
            logger.info("="*80)
            logger.info(f"Total suspicious items: {total_suspicious}")
            logger.info(f"Fixed: {fixed_count}")
            logger.info(f"Skipped: {skipped_count}")
            logger.info(f"Deleted: {deleted_count}")
            logger.info(f"Moved to departments: {moved_to_dept_count}")
            logger.info(f"Moved to locations: {moved_to_loc_count}")
            logger.info("="*80)
            
        finally:
            processed_session.close()
    
    finally:
        processed_db.close()


if __name__ == '__main__':
    manual_fix_authors()

