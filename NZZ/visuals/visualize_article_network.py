"""Visualize Article Network

This script creates a network visualization of articles where:
- Each article is a node
- Edges connect articles based on the related_articles column
- No duplicate nodes (each article appears once)
"""
import os
import sys
import json
import logging
from sqlalchemy import create_engine, Column, String, Text, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Try to import visualization libraries
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    print("Warning: networkx not installed. Install with: pip install networkx")

# Try Pyvis (optimized for large networks, interactive HTML)
try:
    from pyvis.network import Network
    HAS_PYVIS = True
except ImportError:
    HAS_PYVIS = False
    print("Warning: pyvis not installed. Install with: pip install pyvis")

# Try Plotly (good for interactive visualizations)
try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    print("Warning: plotly not installed. Install with: pip install plotly")

# Fallback to matplotlib if needed
try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# Add parent directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('visualize_article_network')

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
    related_articles = Column(Text, nullable=True)  # JSON list of article IDs
    article_date = Column(DateTime, nullable=True)
    article_date_updated = Column(DateTime, nullable=True)


def load_articles_from_db(db_path):
    """Load articles from database.
    
    Args:
        db_path: Path to database file
        
    Returns:
        List of Article objects
    """
    engine = create_engine(f'sqlite:///{db_path}', echo=False, poolclass=NullPool)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        articles = session.query(Article).filter(
            Article.related_articles.isnot(None)
        ).all()
        logger.info(f"Loaded {len(articles)} articles with related articles")
        return articles
    finally:
        session.close()


def build_network(articles):
    """Build network graph from articles.
    
    Args:
        articles: List of Article objects
        
    Returns:
        networkx.Graph object
    """
    if not HAS_NETWORKX:
        raise ImportError("networkx is required for network visualization")
    
    G = nx.Graph()
    article_ids = set()
    related_ids_found = set()
    
    logger.info("Building network graph...")
    
    # First pass: collect all article IDs from the table and add them as nodes
    articles_by_id = {}
    for article in articles:
        article_id = article.article_id
        if article_id not in article_ids:
            G.add_node(article_id, 
                      title=article.title or '',
                      category=article.category or '',
                      article_date=str(article.article_date) if article.article_date else '',
                      in_table=True)
            article_ids.add(article_id)
            articles_by_id[article_id] = article
    
    logger.info(f"Added {len(article_ids)} article nodes from articles table")
    
    # Second pass: collect all related article IDs (including those not in table)
    for article in articles:
        if not article.related_articles:
            continue
        
        try:
            related_ids = json.loads(article.related_articles) if isinstance(article.related_articles, str) else article.related_articles
            if not isinstance(related_ids, list):
                continue
            
            for related_id in related_ids:
                # Convert to string if needed
                if isinstance(related_id, dict):
                    # If it's a dict, try to get 'id' key
                    related_id = related_id.get('id', str(related_id))
                related_id = str(related_id)
                
                if related_id:
                    related_ids_found.add(related_id)
        
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug(f"Error processing related_articles for article {article.article_id}: {str(e)}")
            continue
    
    # Third pass: add nodes for related article IDs that don't exist in the table
    orphan_nodes = related_ids_found - article_ids
    for related_id in orphan_nodes:
        G.add_node(related_id,
                  title='',
                  category='',
                  article_date='',
                  in_table=False)
    
    logger.info(f"Added {len(orphan_nodes)} orphan nodes (IDs in related_articles but not in table)")
    logger.info(f"Total nodes: {len(G.nodes())}")
    
    # Fourth pass: add edges based on related_articles
    edges_added = 0
    for article in articles:
        if not article.related_articles:
            continue
        
        try:
            related_ids = json.loads(article.related_articles) if isinstance(article.related_articles, str) else article.related_articles
            if not isinstance(related_ids, list):
                continue
            
            source_id = article.article_id
            
            for related_id in related_ids:
                # Convert to string if needed
                if isinstance(related_id, dict):
                    # If it's a dict, try to get 'id' key
                    related_id = related_id.get('id', str(related_id))
                related_id = str(related_id)
                
                # Add edge if both nodes exist (including orphan nodes) and they're different
                if related_id in G.nodes() and source_id != related_id:
                    if not G.has_edge(source_id, related_id):
                        G.add_edge(source_id, related_id)
                        edges_added += 1
        
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.debug(f"Error processing related_articles for article {article.article_id}: {str(e)}")
            continue
    
    logger.info(f"Added {edges_added} edges")
    logger.info(f"Network: {len(G.nodes())} nodes, {len(G.edges())} edges")
    
    return G


def visualize_network_pyvis(G, output_path, height='1000px', width='100%'):
    """Visualize network using Pyvis (optimized for large networks).
    
    Args:
        G: networkx.Graph object
        output_path: Path to save HTML file
        height: Height of visualization
        width: Width of visualization
    """
    if not HAS_PYVIS:
        raise ImportError("pyvis is required. Install with: pip install pyvis")
    
    logger.info("Creating interactive visualization with Pyvis...")
    
    # Create Pyvis network
    net = Network(height=height, width=width, bgcolor='#222222', font_color='white')
    net.set_options("""
    {
      "nodes": {
        "font": {
          "size": 12
        },
        "scaling": {
          "min": 10,
          "max": 50
        }
      },
      "edges": {
        "color": {
          "inherit": true
        },
        "smooth": {
          "type": "continuous"
        }
      },
      "physics": {
        "barnesHut": {
          "gravitationalConstant": -2000,
          "centralGravity": 0.1,
          "springLength": 200,
          "springConstant": 0.04,
          "damping": 0.09
        },
        "minVelocity": 0.75,
        "solver": "barnesHut"
      }
    }
    """)
    
    # Separate nodes
    nodes_in_table = [node for node in G.nodes() if G.nodes[node].get('in_table', True)]
    nodes_orphan = [node for node in G.nodes() if not G.nodes[node].get('in_table', True)]
    degrees = dict(G.degree())
    
    # Add nodes from table
    for node in nodes_in_table:
        title = G.nodes[node].get('title', '')[:50] or node
        degree = degrees.get(node, 0)
        net.add_node(node,
                    label=f"{node}\n{title}",
                    title=f"Article ID: {node}\nTitle: {G.nodes[node].get('title', 'N/A')}\nConnections: {degree}",
                    size=min(10 + degree * 2, 50),
                    color='#4A90E2',
                    shape='dot')
    
    # Add orphan nodes
    for node in nodes_orphan:
        degree = degrees.get(node, 0)
        net.add_node(node,
                    label=node,
                    title=f"Article ID: {node}\n(Not in articles table)\nConnections: {degree}",
                    size=min(5 + degree * 1.5, 30),
                    color='#E24A4A',
                    shape='dot')
    
    # Add edges
    for edge in G.edges():
        net.add_edge(edge[0], edge[1], width=0.5, color='#888888')
    
    # Save HTML
    net.save_graph(output_path)
    logger.info(f"Interactive visualization saved to: {output_path}")


def visualize_network_plotly(G, output_path):
    """Visualize network using Plotly (interactive, good for large networks).
    
    Args:
        G: networkx.Graph object
        output_path: Path to save HTML file
    """
    if not HAS_PLOTLY:
        raise ImportError("plotly is required. Install with: pip install plotly")
    
    logger.info("Creating interactive visualization with Plotly...")
    
    # Use spring layout for positioning
    pos = nx.spring_layout(G, k=1, iterations=50)
    
    # Separate nodes
    nodes_in_table = [node for node in G.nodes() if G.nodes[node].get('in_table', True)]
    nodes_orphan = [node for node in G.nodes() if not G.nodes[node].get('in_table', True)]
    degrees = dict(G.degree())
    
    # Prepare edge traces
    edge_x = []
    edge_y = []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
    
    edge_trace = go.Scatter(x=edge_x, y=edge_y,
                           line=dict(width=0.5, color='#888'),
                           hoverinfo='none',
                           mode='lines')
    
    # Prepare node traces
    node_x_table = [pos[node][0] for node in nodes_in_table]
    node_y_table = [pos[node][1] for node in nodes_in_table]
    node_text_table = [f"ID: {node}<br>Title: {G.nodes[node].get('title', 'N/A')[:50]}<br>Connections: {degrees.get(node, 0)}" 
                      for node in nodes_in_table]
    node_size_table = [min(10 + degrees.get(node, 0) * 2, 50) for node in nodes_in_table]
    
    node_trace_table = go.Scatter(x=node_x_table, y=node_y_table,
                                  mode='markers+text',
                                  name='Articles in table',
                                  marker=dict(size=node_size_table,
                                            color='#4A90E2',
                                            line=dict(width=1, color='white')),
                                  text=[node[:10] for node in nodes_in_table],
                                  textposition="middle center",
                                  hovertext=node_text_table,
                                  hoverinfo='text')
    
    if nodes_orphan:
        node_x_orphan = [pos[node][0] for node in nodes_orphan]
        node_y_orphan = [pos[node][1] for node in nodes_orphan]
        node_text_orphan = [f"ID: {node}<br>(Not in table)<br>Connections: {degrees.get(node, 0)}" 
                           for node in nodes_orphan]
        node_size_orphan = [min(5 + degrees.get(node, 0) * 1.5, 30) for node in nodes_orphan]
        
        node_trace_orphan = go.Scatter(x=node_x_orphan, y=node_y_orphan,
                                      mode='markers+text',
                                      name='Orphan nodes',
                                      marker=dict(size=node_size_orphan,
                                                color='#E24A4A',
                                                line=dict(width=1, color='white')),
                                      text=[node[:10] for node in nodes_orphan],
                                      textposition="middle center",
                                      hovertext=node_text_orphan,
                                      hoverinfo='text')
        
        fig = go.Figure(data=[edge_trace, node_trace_table, node_trace_orphan],
                       layout=go.Layout(
                           title=f'Article Network<br>{len(nodes_in_table)} articles, {len(nodes_orphan)} orphan nodes, {len(G.edges())} connections',
                           titlefont_size=16,
                           showlegend=True,
                           hovermode='closest',
                           margin=dict(b=20, l=5, r=5, t=40),
                           xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                           yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)))
    else:
        fig = go.Figure(data=[edge_trace, node_trace_table],
                       layout=go.Layout(
                           title=f'Article Network<br>{len(nodes_in_table)} articles, {len(G.edges())} connections',
                           titlefont_size=16,
                           showlegend=True,
                           hovermode='closest',
                           margin=dict(b=20, l=5, r=5, t=40),
                           xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                           yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)))
    
    # Save HTML
    fig.write_html(output_path)
    logger.info(f"Interactive visualization saved to: {output_path}")


def visualize_network(G, output_path=None, method='pyvis', layout='spring', figsize=(20, 20)):
    """Visualize the network graph using optimized libraries.
    
    Args:
        G: networkx.Graph object
        output_path: Path to save the visualization
        method: Visualization method ('pyvis', 'plotly', or 'matplotlib')
        layout: Layout algorithm (for matplotlib)
        figsize: Figure size tuple (for matplotlib)
    """
    if not HAS_NETWORKX:
        raise ImportError("networkx is required for network visualization")
    
    if output_path is None:
        output_path = 'article_network.html'
    
    # Determine file extension and method
    if output_path.endswith('.html'):
        # Use interactive method
        if method == 'pyvis' and HAS_PYVIS:
            visualize_network_pyvis(G, output_path)
            return
        elif method == 'plotly' and HAS_PLOTLY:
            visualize_network_plotly(G, output_path)
            return
        elif HAS_PYVIS:
            logger.warning("Requested method not available, using Pyvis")
            visualize_network_pyvis(G, output_path)
            return
        elif HAS_PLOTLY:
            logger.warning("Pyvis not available, using Plotly")
            visualize_network_plotly(G, output_path)
            return
    
    # Fallback to matplotlib for PNG/PDF
    if not HAS_MATPLOTLIB:
        raise ImportError("No visualization library available. Install pyvis, plotly, or matplotlib")
    
    logger.info(f"Creating visualization with matplotlib ({layout} layout)...")
    
    # Create figure
    plt.figure(figsize=figsize)
    
    # Choose layout
    if layout == 'spring':
        pos = nx.spring_layout(G, k=1, iterations=50)
    elif layout == 'circular':
        pos = nx.circular_layout(G)
    elif layout == 'kamada_kawai':
        try:
            pos = nx.kamada_kawai_layout(G)
        except Exception:
            logger.warning("Kamada-Kawai layout failed, using spring layout")
            pos = nx.spring_layout(G, k=1, iterations=50)
    else:
        pos = nx.spring_layout(G, k=1, iterations=50)
    
    # Calculate node sizes based on degree
    degrees = dict(G.degree())
    
    # Separate nodes by whether they're in the table or not
    nodes_in_table = [node for node in G.nodes() if G.nodes[node].get('in_table', True)]
    nodes_orphan = [node for node in G.nodes() if not G.nodes[node].get('in_table', True)]
    
    # Draw network - draw orphan nodes first (smaller, different color)
    if nodes_orphan:
        orphan_sizes = [degrees.get(node, 1) * 30 + 10 for node in nodes_orphan]
        orphan_pos = {node: pos[node] for node in nodes_orphan}
        nx.draw_networkx_nodes(G, orphan_pos,
                               nodelist=nodes_orphan,
                               node_size=orphan_sizes,
                               node_color='lightcoral',
                               alpha=0.5,
                               label='Orphan nodes')
    
    # Draw nodes from table
    if nodes_in_table:
        table_sizes = [degrees.get(node, 1) * 50 + 20 for node in nodes_in_table]
        table_pos = {node: pos[node] for node in nodes_in_table}
        nx.draw_networkx_nodes(G, table_pos,
                               nodelist=nodes_in_table,
                               node_size=table_sizes,
                               node_color='lightblue',
                               alpha=0.7,
                               label='Articles in table')
    
    nx.draw_networkx_edges(G, pos,
                           alpha=0.2,
                           width=0.5,
                           edge_color='gray')
    
    # Optionally add labels (only for nodes with high degree to avoid clutter)
    high_degree_nodes = {node: G.nodes[node].get('title', node)[:30] 
                         for node in nodes_in_table 
                         if degrees.get(node, 0) > 5 and G.nodes[node].get('title')}
    
    if high_degree_nodes:
        nx.draw_networkx_labels(G, pos,
                               labels=high_degree_nodes,
                               font_size=8,
                               font_weight='bold')
    
    # Add legend
    plt.legend(loc='upper right')
    
    nodes_in_table_count = len(nodes_in_table)
    orphan_count = len(nodes_orphan)
    plt.title(f'Article Network\n{nodes_in_table_count} articles in table, {orphan_count} orphan nodes, {len(G.edges())} connections', 
              fontsize=16, fontweight='bold')
    plt.axis('off')
    
    # Save
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    logger.info(f"Visualization saved to: {output_path}")
    plt.close()


def export_network_data(G, output_path):
    """Export network data to files (GEXF, GraphML, etc.).
    
    Args:
        G: networkx.Graph object
        output_path: Base path for output files (without extension)
    """
    if not HAS_NETWORKX:
        raise ImportError("networkx is required for export")
    
    # Export to GEXF (for Gephi)
    gexf_path = f"{output_path}.gexf"
    nx.write_gexf(G, gexf_path)
    logger.info(f"Network exported to GEXF: {gexf_path}")
    
    # Export to GraphML
    graphml_path = f"{output_path}.graphml"
    nx.write_graphml(G, graphml_path)
    logger.info(f"Network exported to GraphML: {graphml_path}")


def main():
    """Main function to create and visualize article network."""
    logger.info("="*80)
    logger.info("Article Network Visualization")
    logger.info("="*80)
    
    if not HAS_NETWORKX:
        logger.error("Required libraries not installed. Please install:")
        logger.error("  pip install networkx matplotlib")
        return
    
    # Database path
    db_path = os.path.join(PARENT_DIR, 'nzz_scraped_articles.db')
    
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return
    
    logger.info(f"Database path: {db_path}")
    
    # Load articles
    articles = load_articles_from_db(db_path)
    
    if not articles:
        logger.warning("No articles with related articles found!")
        return
    
    # Build network
    G = build_network(articles)
    
    if len(G.nodes()) == 0:
        logger.warning("No nodes in network!")
        return
    
    # Create output directory
    output_dir = SCRIPT_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    # Visualize - use Pyvis for interactive HTML (optimized for large networks)
    output_html = os.path.join(output_dir, 'article_network.html')
    try:
        if HAS_PYVIS:
            visualize_network(G, output_path=output_html, method='pyvis')
        elif HAS_PLOTLY:
            visualize_network(G, output_path=output_html, method='plotly')
        else:
            # Fallback to matplotlib PNG
            output_image = os.path.join(output_dir, 'article_network.png')
            visualize_network(G, output_path=output_image, method='matplotlib', layout='spring', figsize=(20, 20))
            output_html = output_image
    except Exception as e:
        logger.warning(f"Primary visualization method failed: {e}")
        # Fallback to matplotlib
        output_image = os.path.join(output_dir, 'article_network.png')
        visualize_network(G, output_path=output_image, method='matplotlib', layout='spring', figsize=(20, 20))
        output_html = output_image
    
    # Export network data
    output_base = os.path.join(output_dir, 'article_network')
    export_network_data(G, output_base)
    
    # Print statistics
    logger.info("\n" + "="*80)
    logger.info("Network Statistics")
    logger.info("="*80)
    nodes_in_table = [node for node in G.nodes() if G.nodes[node].get('in_table', True)]
    orphan_nodes = [node for node in G.nodes() if not G.nodes[node].get('in_table', True)]
    logger.info(f"Total nodes: {len(G.nodes())}")
    logger.info(f"  - Articles in table: {len(nodes_in_table)}")
    logger.info(f"  - Orphan nodes (only in related_articles): {len(orphan_nodes)}")
    logger.info(f"Edges (connections): {len(G.edges())}")
    if len(G.nodes()) > 0:
        logger.info(f"Average degree: {sum(dict(G.degree()).values()) / len(G.nodes()):.2f}")
    
    # Find most connected articles (only from table)
    degrees = dict(G.degree())
    top_connected = sorted([(node, deg) for node, deg in degrees.items() 
                            if G.nodes[node].get('in_table', True)], 
                           key=lambda x: x[1], reverse=True)[:10]
    logger.info("\nTop 10 most connected articles (from table):")
    for article_id, degree in top_connected:
        title = G.nodes[article_id].get('title', 'N/A')[:50]
        logger.info(f"  {article_id}: {degree} connections - {title}")
    
    logger.info("\n" + "="*80)
    logger.info("Visualization complete!")
    logger.info(f"Visualization saved to: {output_html}")
    logger.info(f"Network data exported to: {output_base}.gexf and {output_base}.graphml")
    if output_html.endswith('.html'):
        logger.info("Open the HTML file in a web browser for interactive visualization")
    logger.info("="*80)


if __name__ == '__main__':
    main()

