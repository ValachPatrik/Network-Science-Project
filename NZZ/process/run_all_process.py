"""Run All Processing Scripts in Order

This script runs all processing scripts in the correct order:
1. 00_reset_to_preprocessing.py - Reset database to preprocessing state
   - Clears all processed tables, keeps raw tables intact
   - Handles database locks with force mode and journal cleanup
2. 01_process_impressum_authors.py - Process authors from authors_raw
   - Creates authors table with id, author_id, name, title, alt_name, alias, department, location, tags, bio, has_info
3. 02_process_articles.py - Process articles from articles_raw
   - Creates articles table with basic fields (title, content, description, tags, category, dates)
   - Leaves authors, department, location, related_articles empty for later processing
4. 03_process_related_articles.py - Extract related article IDs
   - Extracts IDs from articles_raw.related_articles JSON and stores as JSON list in articles.related_articles
5. 04_extract_author_info.py - Extract author names, locations, and departments
   - Uses AuthorNormalizer (geopy only, no LLM) to parse author strings from articles_raw.author
   - Populates articles.authors, articles.location, articles.department as JSON lists
6. 05_refine_extracted_data.py - Refine extracted data using parentheses
   - Uses parentheses as natural separators
   - Reclassifies parts using AuthorNormalizer and reassigns to correct columns
7. 06_clean_locations.py - Clean locations column
   - Removes non-location terms, moves specific terms to departments/authors
   - Translates country codes and cleans commas
8. 07_normalize_author_names.py - Normalize author names
   - Splits concatenated author names without commas (conservative approach)
   - Adds commas between multiple authors
   - Handles "und" (and) as separator
   - Moves "Bildredaktion NZZ" to departments
9. 09_clean_authors_final.py - Final cleanup of authors column
   - Moves department terms from authors to departments column
   - Removes non-author items (Text, Text Bilder)
   - Removes text labels from author names (Text:, Illustrationen:, etc.)
10. 10_clean_departments.py - Clean departments column
   - Removes "NZZ-" prefix from department names
   - Removes "NZZ " prefix from department names
   - Removes " NZZ" suffix from department names
   - Merges comma-separated and duplicate departments
   - Moves author names to authors column
11. 11_convert_unicode_escapes.py - Convert Unicode escape sequences
   - Converts \\u00fc -> ü, \\u00e4 -> ä, etc.
   - Ensures consistency with authors table format
12. 08_manual_fix_authors.py - Manual review and fix (run separately)
   - Interactive script to review suspicious author names
   - Allows manual editing, deletion, or moving to departments
   - Saves changes incrementally

Each script is run as a separate process to ensure clean execution.
The pipeline stops if any script fails.
Script 08 is for manual review and should be run separately.
"""
import sys
import subprocess
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('run_all_process')

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.absolute()

# Define processing scripts in order
PROCESSING_SCRIPTS = [
    '00_reset_to_preprocessing.py',
    '01_process_impressum_authors.py',
    '02_process_articles.py',
    '03_process_related_articles.py',
    '04_extract_author_info.py',
    '05_refine_extracted_data.py',
    '06_clean_locations.py',
    '07_normalize_author_names.py',
    '09_clean_authors_final.py',
    '10_clean_departments.py',
    '11_convert_unicode_escapes.py',
    # '08_manual_fix_authors.py'  # Manual review script - run separately
    # 'temp_find_unicode_escapes.py'  # Temporary diagnostic script
]


def run_script(script_name):
    """Run a processing script and return success status."""
    script_path = SCRIPT_DIR / script_name
    
    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return False
    
    logger.info("="*80)
    logger.info(f"Running: {script_name}")
    logger.info("="*80)
    
    try:
        # Run the script and capture output
        subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(SCRIPT_DIR),
            capture_output=False,  # Show output in real-time
            text=True,
            check=True
        )
        logger.info("="*80)
        logger.info(f"✓ Successfully completed: {script_name}")
        logger.info("="*80)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("="*80)
        logger.error(f"✗ Failed: {script_name}")
        logger.error(f"Exit code: {e.returncode}")
        logger.error("="*80)
        return False
    except Exception as e:
        logger.error("="*80)
        logger.error(f"✗ Error running {script_name}: {str(e)}")
        logger.error("="*80)
        return False


def main():
    """Run all processing scripts in order."""
    logger.info("="*80)
    logger.info("Processing Pipeline - Running All Scripts in Order")
    logger.info("="*80)
    logger.info(f"Working directory: {SCRIPT_DIR}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info("="*80)
    
    results = {}
    failed_scripts = []
    
    for script_name in PROCESSING_SCRIPTS:
        success = run_script(script_name)
        results[script_name] = success
        
        if not success:
            failed_scripts.append(script_name)
            logger.error("="*80)
            logger.error("STOPPING PIPELINE - Previous script failed!")
            logger.error("="*80)
            break
    
    # Summary
    logger.info("="*80)
    logger.info("Processing Pipeline Summary")
    logger.info("="*80)
    
    for script_name, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        logger.info(f"{script_name}: {status}")
    
    logger.info("="*80)
    
    if failed_scripts:
        logger.error(f"Pipeline failed at: {', '.join(failed_scripts)}")
        logger.error("Please fix the errors and rerun the pipeline.")
        sys.exit(1)
    else:
        logger.info("All processing scripts completed successfully!")
        logger.info("="*80)
        sys.exit(0)


if __name__ == '__main__':
    main()

