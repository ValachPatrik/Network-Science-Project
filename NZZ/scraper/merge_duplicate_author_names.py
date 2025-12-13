"""Merge duplicate authors with the same name, prioritizing authors with has_info=1.

This script:
1. Loads all authors from the authors table
2. Groups authors by name (case-insensitive)
3. For each group of duplicates:
   - Selects the primary author (prioritizing has_info=1)
   - Merges data from all duplicates, prioritizing has_info=1 authors
   - Deletes duplicate records
4. Provides statistics on the merge process
"""
import os
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
logger = logging.getLogger('merge_duplicate_author_names')

# Load environment variables
load_dotenv()


class AuthorMerger:
    """Merge duplicate authors with the same name."""
    
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
    
    def load_authors(self):
        """Load all authors from the database."""
        logger.info("Loading authors from database...")
        
        query = """
            SELECT id, author_id, name, title, alt_name, alias, 
                   department, location, tags, bio, has_info
            FROM authors
            ORDER BY name, has_info DESC
        """
        
        df = pd.read_sql(query, self.engine)
        logger.info(f"Loaded {len(df):,} authors")
        return df
    
    def find_duplicates(self, df):
        """Find duplicate authors grouped by name (case-insensitive)."""
        logger.info("Finding duplicate authors by name...")
        
        # Group by normalized name (case-insensitive, stripped)
        df['name_normalized'] = df['name'].str.strip().str.lower()
        
        # Group by normalized name
        groups = defaultdict(list)
        for idx, row in df.iterrows():
            groups[row['name_normalized']].append(idx)
        
        # Find groups with duplicates (more than 1 author)
        duplicates = {name: indices for name, indices in groups.items() if len(indices) > 1}
        
        logger.info(f"Found {len(duplicates):,} groups of duplicate authors")
        total_duplicates = sum(len(indices) - 1 for indices in duplicates.values())
        logger.info(f"Total duplicate records to merge: {total_duplicates:,}")
        
        return duplicates, df
    
    def _merge_string_list(self, *values, delimiter=','):
        """Merge multiple string values, treating them as comma-separated lists.
        
        Args:
            *values: Variable number of string values (can be None/NaN)
            delimiter: Delimiter to split/join (default: comma)
            
        Returns:
            str: Merged string with unique values, or None if all values are empty
        """
        all_items = []
        for val in values:
            if pd.notna(val) and val:
                val_str = str(val).strip()
                if val_str:
                    # Split by delimiter and add each item
                    items = [item.strip() for item in val_str.split(delimiter) if item.strip()]
                    all_items.extend(items)
        
        if not all_items:
            return None
        
        # Remove duplicates while preserving order
        seen = set()
        unique_items = []
        for item in all_items:
            if item.lower() not in seen:  # Case-insensitive deduplication
                seen.add(item.lower())
                unique_items.append(item)
        
        return delimiter.join(unique_items) if unique_items else None
    
    def _merge_string_field(self, primary_val, other_vals, prioritize_has_info=True):
        """Merge string fields, combining different values.
        
        Args:
            primary_val: Primary value (from has_info=1 author if available)
            other_vals: List of other values to merge
            prioritize_has_info: If True, prioritize values from has_info=1 authors
            
        Returns:
            str: Merged string value
        """
        all_values = []
        if pd.notna(primary_val) and primary_val:
            all_values.append(str(primary_val).strip())
        
        for val in other_vals:
            if pd.notna(val) and val:
                val_str = str(val).strip()
                if val_str and val_str not in all_values:
                    all_values.append(val_str)
        
        if not all_values:
            return None
        
        # If all values are the same, return the first one
        if len(set(v.lower() for v in all_values)) == 1:
            return all_values[0]
        
        # If different values, combine them (prioritize primary)
        # For fields like title, department, location - keep primary if it exists
        if primary_val and pd.notna(primary_val):
            return str(primary_val).strip()
        
        # If primary is empty, use first non-empty value
        return all_values[0] if all_values else None
    
    def _merge_bio(self, *bios):
        """Merge bio fields, keeping the longest/most complete one.
        
        Args:
            *bios: Variable number of bio strings
            
        Returns:
            str: Longest bio, or None if all are empty
        """
        valid_bios = [str(bio).strip() for bio in bios if pd.notna(bio) and str(bio).strip()]
        if not valid_bios:
            return None
        
        # Return the longest bio (most complete)
        return max(valid_bios, key=len)
    
    def merge_author_data(self, author_rows):
        """Merge data from multiple author rows, preserving most data.
        
        Combines lists, keeps unique values, and prioritizes has_info=1 authors.
        
        Args:
            author_rows: List of DataFrame rows representing duplicate authors
            
        Returns:
            dict: Merged author data
        """
        # Sort by has_info descending (1 first, then 0), then by id ascending (keep lowest id as primary)
        sorted_authors = sorted(author_rows, key=lambda x: (-x['has_info'], x['id']))
        
        # Primary author is the one with has_info=1, or first one if none have has_info=1
        primary = sorted_authors[0]
        
        # Collect all values for each field, grouped by has_info
        has_info_1_authors = [a for a in sorted_authors if a['has_info'] == 1]
        has_info_0_authors = [a for a in sorted_authors if a['has_info'] == 0]
        
        # Merge tags (comma-separated list)
        all_tags = []
        if pd.notna(primary['tags']) and primary['tags']:
            all_tags.append(primary['tags'])
        for author in sorted_authors[1:]:
            if pd.notna(author['tags']) and author['tags']:
                all_tags.append(author['tags'])
        merged_tags = self._merge_string_list(*all_tags) if all_tags else None
        
        # Merge bio (keep longest)
        all_bios = [a['bio'] for a in sorted_authors if pd.notna(a['bio']) and a['bio']]
        merged_bio = self._merge_bio(*all_bios) if all_bios else None
        
        # For string fields, prioritize has_info=1, but combine if different
        # Title: prioritize has_info=1, but keep primary if exists
        title_vals = [a['title'] for a in has_info_1_authors if pd.notna(a['title']) and a['title']]
        if not title_vals:
            title_vals = [a['title'] for a in has_info_0_authors if pd.notna(a['title']) and a['title']]
        merged_title = title_vals[0] if title_vals else primary['title']
        
        # Alt_name: prioritize has_info=1, otherwise first non-empty
        alt_name_vals_1 = [a['alt_name'] for a in has_info_1_authors if pd.notna(a['alt_name']) and a['alt_name']]
        alt_name_vals_0 = [a['alt_name'] for a in has_info_0_authors if pd.notna(a['alt_name']) and a['alt_name']]
        merged_alt_name = (alt_name_vals_1[0] if alt_name_vals_1 
                          else (alt_name_vals_0[0] if alt_name_vals_0 else primary['alt_name']))
        
        # Alias: prioritize has_info=1, otherwise first non-empty
        alias_vals_1 = [a['alias'] for a in has_info_1_authors if pd.notna(a['alias']) and a['alias']]
        alias_vals_0 = [a['alias'] for a in has_info_0_authors if pd.notna(a['alias']) and a['alias']]
        merged_alias = (alias_vals_1[0] if alias_vals_1 
                       else (alias_vals_0[0] if alias_vals_0 else primary['alias']))
        
        # Department: prioritize has_info=1
        dept_vals_1 = [a['department'] for a in has_info_1_authors if pd.notna(a['department']) and a['department']]
        dept_vals_0 = [a['department'] for a in has_info_0_authors if pd.notna(a['department']) and a['department']]
        merged_department = dept_vals_1[0] if dept_vals_1 else (dept_vals_0[0] if dept_vals_0 else primary['department'])
        
        # Location: prioritize has_info=1, but combine if different
        loc_vals_1 = [a['location'] for a in has_info_1_authors if pd.notna(a['location']) and a['location']]
        loc_vals_0 = [a['location'] for a in has_info_0_authors if pd.notna(a['location']) and a['location']]
        merged_location = loc_vals_1[0] if loc_vals_1 else (loc_vals_0[0] if loc_vals_0 else primary['location'])
        
        # Author_id: Always keep primary author's original author_id to avoid conflicts
        # Only change if primary has no author_id and we can safely use one from duplicates
        # (Conflict checking will be done in update_author method)
        if pd.notna(primary['author_id']) and primary['author_id']:
            merged_author_id = primary['author_id']
        else:
            # Primary has no author_id, try to get one from has_info=1 authors first
            author_id_vals_1 = [a['author_id'] for a in has_info_1_authors if pd.notna(a['author_id']) and a['author_id']]
            author_id_vals_0 = [a['author_id'] for a in has_info_0_authors if pd.notna(a['author_id']) and a['author_id']]
            merged_author_id = (author_id_vals_1[0] if author_id_vals_1
                               else (author_id_vals_0[0] if author_id_vals_0 else None))
        
        # Has_info: 1 if any author has it
        merged_has_info = 1 if any(a['has_info'] == 1 for a in sorted_authors) else 0
        
        merged = {
            'id': primary['id'],
            'author_id': merged_author_id,
            'name': primary['name'],  # Keep original case from primary
            'title': merged_title,
            'alt_name': merged_alt_name,
            'alias': merged_alias,
            'department': merged_department,
            'location': merged_location,
            'tags': merged_tags,
            'bio': merged_bio,
            'has_info': merged_has_info
        }
        
        return merged
    
    def check_author_id_conflict(self, conn, author_id, current_author_id, duplicate_ids=None):
        """Check if author_id already exists for a different author.
        
        Args:
            conn: Database connection
            author_id: The author_id to check
            current_author_id: The ID of the author we're updating (to exclude from check)
            duplicate_ids: List of duplicate author IDs that will be deleted (to exclude from check)
            
        Returns:
            bool: True if author_id already exists for a different author (outside our duplicate group)
        """
        if not author_id or pd.isna(author_id):
            return False
        
        # Build query to exclude current author and duplicates we're about to delete
        exclude_ids = [int(current_author_id)]
        if duplicate_ids:
            exclude_ids.extend([int(did) for did in duplicate_ids])
        
        # Use NOT IN clause to exclude all relevant IDs
        placeholders = ', '.join([f':id{i}' for i in range(len(exclude_ids))])
        params = {'author_id': author_id}
        params.update({f'id{i}': did for i, did in enumerate(exclude_ids)})
        
        check_query = text(f"""
            SELECT COUNT(*) FROM authors 
            WHERE author_id = :author_id AND id NOT IN ({placeholders})
        """)
        result = conn.execute(check_query, params)
        count = result.fetchone()[0]
        return count > 0
    
    def update_author(self, merged_data, conn=None, duplicate_ids=None):
        """Update the primary author record with merged data.
        
        Args:
            merged_data: Merged author data dictionary
            conn: Optional database connection to check for author_id conflicts
            duplicate_ids: List of duplicate author IDs that will be deleted (to exclude from conflict check)
            
        Returns:
            tuple: (update_query, update_params)
        """
        author_id = merged_data['author_id']
        current_id = int(merged_data['id'])
        
        # Check for author_id conflict if connection is provided
        if conn is not None and author_id and pd.notna(author_id):
            if self.check_author_id_conflict(conn, author_id, current_id, duplicate_ids):
                # Conflict detected - keep the primary author's original author_id or set to None
                # Get the original author_id from the database
                get_original_query = text("SELECT author_id FROM authors WHERE id = :id")
                result = conn.execute(get_original_query, {'id': current_id})
                original_author_id = result.fetchone()[0]
                
                # Use original if it exists, otherwise set to None
                if original_author_id and pd.notna(original_author_id):
                    author_id = original_author_id
                    logger.warning(f"Author ID conflict detected for author {current_id}. "
                                 f"Keeping original author_id: {author_id}")
                else:
                    author_id = None
                    logger.warning(f"Author ID conflict detected for author {current_id}. "
                                 f"Setting author_id to NULL")
        
        update_query = text("""
            UPDATE authors
            SET author_id = :author_id,
                title = :title,
                alt_name = :alt_name,
                alias = :alias,
                department = :department,
                location = :location,
                tags = :tags,
                bio = :bio,
                has_info = :has_info
            WHERE id = :id
        """)
        
        return update_query, {
            'id': current_id,
            'author_id': author_id,
            'title': merged_data['title'],
            'alt_name': merged_data['alt_name'],
            'alias': merged_data['alias'],
            'department': merged_data['department'],
            'location': merged_data['location'],
            'tags': merged_data['tags'],
            'bio': merged_data['bio'],
            'has_info': int(merged_data['has_info'])
        }
    
    def delete_author(self, author_id):
        """Delete an author record by id."""
        delete_query = text("DELETE FROM authors WHERE id = :id")
        return delete_query, {'id': int(author_id)}
    
    def process_duplicates(self, duplicates, df, batch_size=100):
        """Process all duplicate groups and merge them."""
        logger.info("Processing duplicate authors...")
        
        total_groups = len(duplicates)
        processed = 0
        total_merged = 0
        total_deleted = 0
        
        try:
            with self.engine.begin() as conn:  # Use transaction
                for name_normalized, indices in duplicates.items():
                    # Get author rows
                    author_rows = [df.loc[idx] for idx in indices]
                    
                    # Merge data
                    merged_data = self.merge_author_data(author_rows)
                    
                    # Get duplicate IDs before deletion
                    duplicate_ids = [int(row['id']) for row in author_rows[1:]]
                    
                    # Update primary author (pass conn and duplicate_ids to check for author_id conflicts)
                    update_query, update_params = self.update_author(merged_data, conn=conn, duplicate_ids=duplicate_ids)
                    conn.execute(update_query, update_params)
                    
                    # Delete duplicate authors (all except primary)
                    for dup_id in duplicate_ids:
                        delete_query, delete_params = self.delete_author(dup_id)
                        conn.execute(delete_query, delete_params)
                        total_deleted += 1
                    
                    total_merged += len(author_rows) - 1
                    processed += 1
                    
                    if processed % batch_size == 0:
                        logger.info(f"Processed {processed:,} / {total_groups:,} groups "
                                  f"({processed/total_groups*100:.1f}%)")
                
                logger.info(f"Successfully processed {processed:,} groups")
                logger.info(f"  Merged {total_merged:,} duplicate authors")
                logger.info(f"  Deleted {total_deleted:,} duplicate records")
                
        except Exception as e:
            logger.error(f"Error processing duplicates: {e}")
            raise
        
        return total_merged, total_deleted
    
    def run(self, dry_run=False):
        """Run the complete merge process.
        
        Args:
            dry_run (bool): If True, only show what would be merged without making changes
        """
        logger.info("="*80)
        logger.info("Starting duplicate author merge process")
        if dry_run:
            logger.info("DRY RUN MODE - No changes will be made")
        logger.info("="*80)
        
        try:
            # Load authors
            df = self.load_authors()
            
            # Find duplicates
            duplicates, df = self.find_duplicates(df)
            
            if len(duplicates) == 0:
                logger.info("No duplicate authors found. Nothing to merge.")
                return
            
            if dry_run:
                # Show what would be merged
                logger.info("\nDuplicate groups that would be merged:")
                for name_normalized, indices in list(duplicates.items())[:10]:  # Show first 10
                    author_rows = [df.loc[idx] for idx in indices]
                    logger.info(f"\n  Name: '{author_rows[0]['name']}' ({len(author_rows)} duplicates)")
                    for row in author_rows:
                        logger.info(f"    ID: {row['id']}, has_info: {row['has_info']}, "
                                  f"author_id: {row['author_id']}")
                if len(duplicates) > 10:
                    logger.info(f"  ... and {len(duplicates) - 10} more groups")
                logger.info("\nRun without --dry-run to perform the merge.")
                return
            
            # Process duplicates
            total_merged, total_deleted = self.process_duplicates(duplicates, df)
            
            logger.info("="*80)
            logger.info("Merge process completed successfully!")
            logger.info(f"  Total groups processed: {len(duplicates):,}")
            logger.info(f"  Total authors merged: {total_merged:,}")
            logger.info(f"  Total records deleted: {total_deleted:,}")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"Process failed: {e}")
            raise


if __name__ == "__main__":
    import sys
    
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv
    
    merger = AuthorMerger()
    merger.run(dry_run=dry_run)

