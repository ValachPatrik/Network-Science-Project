"""Database models for tracking scraped articles."""
from datetime import datetime
from typing import List, Dict
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Article(Base):
    """Model for storing scraped article data."""
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    tags = Column(String(1000), nullable=True)  # Store as comma-separated string
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    article_url = Column(String(500), nullable=False)
    article_date = Column(DateTime, nullable=True)  # Date from the article itself (published date)
    article_updated = Column(DateTime, nullable=True)  # Updated date if available
    source = Column(String(500), nullable=True)  # Source/Quelle of the article

    def __repr__(self):
        return f"<Article(article_id='{self.article_id}', title='{self.title[:50]}...')>"


class DatabaseManager:
    """Manages database connections and operations."""
    
    def __init__(self, db_path='scraped_articles.db'):
        """Initialize database connection."""
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
    
    def article_exists(self, article_id: str) -> bool:
        """Check if an article has already been scraped."""
        return self.session.query(Article).filter_by(article_id=article_id).first() is not None
    
    def save_article(self, article_id: str, title: str, content: str, 
                     tags: list, article_url: str, article_date: datetime = None,
                     article_updated: datetime = None, source: str = None,
                     scraped_at: datetime = None) -> Article:
        """Save a scraped article to the database."""
        tags_str = ','.join(tags) if tags else ''
        # Use provided scraped_at or default to current time (down to the second)
        if scraped_at is None:
            from datetime import datetime
            scraped_at = datetime.utcnow().replace(microsecond=0)
        
        article = Article(
            article_id=article_id,
            title=title,
            content=content,
            tags=tags_str,
            article_url=article_url,
            article_date=article_date,
            article_updated=article_updated,
            source=source,
            scraped_at=scraped_at
        )
        self.session.add(article)
        self.session.commit()
        return article
    
    def get_all_scraped_ids(self) -> set:
        """Get all scraped article IDs as a set."""
        articles = self.session.query(Article.article_id).all()
        return {article_id[0] for article_id in articles}
    
    def get_all_articles(self) -> List[Article]:
        """Get all scraped articles."""
        return self.session.query(Article).order_by(Article.scraped_at.desc()).all()
    
    def get_article_count(self) -> int:
        """Get total number of scraped articles."""
        return self.session.query(Article).count()
    
    def verify_article_format(self, article: Article) -> Dict[str, bool]:
        """Verify that an article has proper format."""
        checks = {
            'has_id': bool(article.article_id and article.article_id.strip()),
            'has_title': bool(article.title and article.title.strip()),
            'has_content': bool(article.content and len(article.content.strip()) > 50),
            'has_url': bool(article.article_url and article.article_url.strip()),
            'has_scraped_at': bool(article.scraped_at),
        }
        checks['all_valid'] = all(checks.values())
        return checks
    
    def close(self):
        """Close database session."""
        self.session.close()

