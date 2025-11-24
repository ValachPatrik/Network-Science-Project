"""Analyze Article Network Connectivity

This script analyzes the connectivity of the article network where:
- Nodes are only articles that exist in the articles table
- Edges connect articles based on the related_articles column
- Calculates various network metrics: components, centrality, clustering, etc.
"""
import os
import sys
import json
import logging
from collections import Counter
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Try to import networkx
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    print("Error: networkx is required. Install with: pip install networkx")
    sys.exit(1)

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('analyze_article_network')

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
    authors = Column(Text, nullable=True)
    department = Column(String(200), nullable=True)
    location = Column(String(200), nullable=True)
    related_articles = Column(Text, nullable=True)
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)


def load_articles_from_db(db_path):
    """Load articles from database."""
    engine = create_engine(f'sqlite:///{db_path}', echo=False, poolclass=NullPool)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        articles = session.query(Article).all()
        logger.info(f"Loaded {len(articles)} articles from database")
        return articles
    finally:
        session.close()


def build_network(articles):
    """Build network graph from articles (only nodes in table, no orphans)."""
    G = nx.Graph()
    article_ids = set()
    
    logger.info("Building network graph...")
    
    # First pass: add all article nodes from the table
    for article in articles:
        article_id = article.article_id
        if article_id not in article_ids:
            G.add_node(article_id, 
                      title=article.title or '',
                      category=article.category or '',
                      article_date=str(article.article_date) if article.article_date else '')
            article_ids.add(article_id)
    
    logger.info(f"Added {len(article_ids)} article nodes")
    
    # Second pass: add edges (only if both nodes exist in table)
    edges_added = 0
    edges_skipped_orphan = 0
    
    for article in articles:
        if not article.related_articles:
            continue
        
        try:
            related_ids = json.loads(article.related_articles) if isinstance(article.related_articles, str) else article.related_articles
            if not isinstance(related_ids, list):
                continue
            
            source_id = article.article_id
            
            for related_id in related_ids:
                if isinstance(related_id, dict):
                    related_id = related_id.get('id', str(related_id))
                related_id = str(related_id)
                
                if related_id in article_ids and source_id != related_id:
                    if not G.has_edge(source_id, related_id):
                        G.add_edge(source_id, related_id)
                        edges_added += 1
                elif related_id not in article_ids and source_id != related_id:
                    edges_skipped_orphan += 1
        
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    
    logger.info(f"Added {edges_added} edges, skipped {edges_skipped_orphan} orphan edges")
    return G


def analyze_connectivity(G):
    """Analyze network connectivity and structure."""
    logger.info("="*80)
    logger.info("Network Connectivity Analysis")
    logger.info("="*80)
    
    # Basic statistics
    num_nodes = len(G.nodes())
    num_edges = len(G.edges())
    
    print("\n" + "="*80)
    print("BASIC STATISTICS")
    print("="*80)
    print(f"Nodes (articles): {num_nodes:,}")
    print(f"Edges (connections): {num_edges:,}")
    print(f"Average degree: {2 * num_edges / num_nodes if num_nodes > 0 else 0:.2f}")
    print(f"Density: {nx.density(G):.6f}")
    
    # Connected components
    components = list(nx.connected_components(G))
    component_sizes = [len(comp) for comp in components]
    component_sizes.sort(reverse=True)
    
    print("\n" + "="*80)
    print("CONNECTED COMPONENTS")
    print("="*80)
    print(f"Number of connected components: {len(components)}")
    print(f"Largest component size: {component_sizes[0] if component_sizes else 0:,} nodes")
    print(f"Percentage in largest component: {component_sizes[0] / num_nodes * 100 if num_nodes > 0 else 0:.2f}%")
    
    if len(component_sizes) > 1:
        print("\nComponent size distribution:")
        size_dist = Counter(component_sizes)
        for size, count in sorted(size_dist.items(), reverse=True)[:10]:
            print(f"  Size {size:,}: {count} component(s)")
    
    # Largest component analysis
    if components:
        largest_component = G.subgraph(components[0])
        print("\n" + "="*80)
        print("LARGEST COMPONENT ANALYSIS")
        print("="*80)
        print(f"Nodes: {len(largest_component.nodes()):,}")
        print(f"Edges: {len(largest_component.edges()):,}")
        print(f"Average degree: {2 * len(largest_component.edges()) / len(largest_component.nodes()) if len(largest_component.nodes()) > 0 else 0:.2f}")
        
        # Path length (if component is not too large)
        if len(largest_component.nodes()) <= 10000:
            try:
                avg_path_length = nx.average_shortest_path_length(largest_component)
                print(f"Average shortest path length: {avg_path_length:.2f}")
                diameter = nx.diameter(largest_component)
                print(f"Diameter (longest shortest path): {diameter}")
            except Exception as e:
                logger.warning(f"Could not calculate path length: {e}")
        else:
            print("Component too large for path length calculation (sampling instead)")
            # Sample for large components
            sample_nodes = list(largest_component.nodes())[:1000]
            sample_graph = largest_component.subgraph(sample_nodes)
            try:
                avg_path_length = nx.average_shortest_path_length(sample_graph)
                print(f"Average shortest path length (sample of 1000 nodes): {avg_path_length:.2f}")
            except Exception as e:
                logger.warning(f"Could not calculate path length on sample: {e}")
        
        # Clustering
        try:
            avg_clustering = nx.average_clustering(largest_component)
            print(f"Average clustering coefficient: {avg_clustering:.4f}")
        except Exception as e:
            logger.warning(f"Could not calculate clustering: {e}")
    
    # Degree distribution
    degrees = dict(G.degree())
    degree_values = list(degrees.values())
    
    print("\n" + "="*80)
    print("DEGREE DISTRIBUTION")
    print("="*80)
    print(f"Min degree: {min(degree_values) if degree_values else 0}")
    print(f"Max degree: {max(degree_values) if degree_values else 0}")
    print(f"Median degree: {sorted(degree_values)[len(degree_values)//2] if degree_values else 0}")
    
    degree_dist = Counter(degree_values)
    print("\nDegree distribution (top 20):")
    for degree, count in sorted(degree_dist.items(), reverse=True)[:20]:
        print(f"  Degree {degree}: {count:,} nodes ({count/num_nodes*100:.2f}%)")
    
    # Centrality measures (for largest component)
    if components and len(components[0]) > 0:
        largest_component = G.subgraph(components[0])
        
        print("\n" + "="*80)
        print("CENTRALITY MEASURES (Largest Component)")
        print("="*80)
        
        # Degree centrality
        degree_centrality = nx.degree_centrality(largest_component)
        top_degree = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:10]
        print("\nTop 10 by Degree Centrality:")
        for node, centrality in top_degree:
            title = G.nodes[node].get('title', 'N/A')[:50]
            degree = degrees[node]
            print(f"  {node}: {centrality:.4f} (degree: {degree}) - {title}")
        
        # Betweenness centrality (sample for large networks)
        if len(largest_component.nodes()) <= 5000:
            try:
                betweenness = nx.betweenness_centrality(largest_component)
                top_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:10]
                print("\nTop 10 by Betweenness Centrality:")
                for node, centrality in top_betweenness:
                    title = G.nodes[node].get('title', 'N/A')[:50]
                    print(f"  {node}: {centrality:.4f} - {title}")
            except Exception as e:
                logger.warning(f"Could not calculate betweenness centrality: {e}")
        else:
            print("\nBetweenness centrality: Skipped (component too large, >5000 nodes)")
        
        # Closeness centrality (sample for large networks)
        if len(largest_component.nodes()) <= 2000:
            try:
                closeness = nx.closeness_centrality(largest_component)
                top_closeness = sorted(closeness.items(), key=lambda x: x[1], reverse=True)[:10]
                print("\nTop 10 by Closeness Centrality:")
                for node, centrality in top_closeness:
                    title = G.nodes[node].get('title', 'N/A')[:50]
                    print(f"  {node}: {centrality:.4f} - {title}")
            except Exception as e:
                logger.warning(f"Could not calculate closeness centrality: {e}")
        else:
            print("\nCloseness centrality: Skipped (component too large, >2000 nodes)")
    
    # Isolated nodes
    isolated = list(nx.isolates(G))
    print("\n" + "="*80)
    print("ISOLATED NODES")
    print("="*80)
    print(f"Number of isolated nodes (degree 0): {len(isolated):,}")
    print(f"Percentage: {len(isolated)/num_nodes*100 if num_nodes > 0 else 0:.2f}%")
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total nodes: {num_nodes:,}")
    print(f"Total edges: {num_edges:,}")
    print(f"Connected components: {len(components)}")
    print(f"Largest component: {component_sizes[0] if component_sizes else 0:,} nodes ({component_sizes[0]/num_nodes*100 if num_nodes > 0 and component_sizes else 0:.2f}%)")
    print(f"Isolated nodes: {len(isolated):,} ({len(isolated)/num_nodes*100 if num_nodes > 0 else 0:.2f}%)")
    print(f"Average degree: {2 * num_edges / num_nodes if num_nodes > 0 else 0:.2f}")
    print(f"Network density: {nx.density(G):.6f}")
    print(f"{'='*80}\n")


def main():
    """Main function to analyze article network connectivity."""
    logger.info("="*80)
    logger.info("Article Network Connectivity Analysis")
    logger.info("="*80)
    
    # Database path
    db_path = os.path.join(PARENT_DIR, 'nzz_scraped_articles.db')
    
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return
    
    logger.info(f"Database path: {db_path}")
    
    # Load articles
    articles = load_articles_from_db(db_path)
    
    if not articles:
        logger.warning("No articles found!")
        return
    
    # Build network
    G = build_network(articles)
    
    if len(G.nodes()) == 0:
        logger.warning("No nodes in network!")
        return
    
    # Analyze connectivity
    analyze_connectivity(G)


if __name__ == '__main__':
    main()

