import os
import ast
import sys
import math
import argparse
import pandas as pd
import networkx as nx
from pyvis.network import Network
import matplotlib.pyplot as plt
import numpy as np
import logging
from fa2_modified import ForceAtlas2
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('articles')

try:
    from sqlalchemy import create_engine
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    print("Error: SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")

try:
    import community.community_louvain as community_louvain
    HAS_COMMUNITY = True
except ImportError:
    HAS_COMMUNITY = False
    print("Warning: python-louvain not available. Louvain/Leiden clustering will be disabled. Install with: pip install python-louvain")

try:
    import igraph as ig
    HAS_IGRAPH = True
except ImportError:
    HAS_IGRAPH = False
    # igraph is optional, only needed for Infomap and Leiden

# Load environment variables
load_dotenv()


class ArticleGraphBuilder:
    """Loads NZZ article data, builds a graph, and performs graph analysis."""

    def __init__(self):
        """Initialize ArticleGraphBuilder with Supabase PostgreSQL connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError("SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")
        
        self.df = None
        self.G = nx.Graph()
        self.components_sorted = None
        
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
        
        # Create SQLAlchemy engine for pandas compatibility
        self.engine = self._create_engine()
    
    def _create_engine(self):
        """Create SQLAlchemy engine for PostgreSQL (Supabase) connection.
        
        Returns:
            sqlalchemy.engine.Engine: SQLAlchemy engine object
        """
        try:
            # Build connection string for SQLAlchemy
            connection_string = (
                f"postgresql://{self.user}:{self.password}@"
                f"{self.host}:{self.port}/{self.dbname}"
            )
            # Add connect_args to increase statement timeout (in milliseconds)
            # Supabase default is often 20 seconds, we'll set it higher
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": 30,
                    "options": "-c statement_timeout=300000"  # 5 minutes in milliseconds
                }
            )
            return engine
        except Exception as e:
            raise ConnectionError(f"Failed to create database engine: {e}")

    # === 1. Load data ===
    def load_data(self, limit=None, chunk_size=10000):
        """Load articles from Supabase PostgreSQL into a DataFrame.
        
        Args:
            limit (int, optional): Maximum number of rows to load. If None, loads all rows.
            chunk_size (int): Number of rows to fetch per chunk when loading large datasets.
        
        Returns:
            pd.DataFrame: DataFrame containing articles
        """
        try:
            # First, try to get total count
            count_query = "SELECT COUNT(*) FROM articles"
            total_count = pd.read_sql(count_query, self.engine).iloc[0, 0]
            print(f"Total articles in database: {total_count:,}")
            
            if limit:
                total_to_load = min(limit, total_count)
            else:
                total_to_load = total_count
            
            # Only select columns we actually use: article_id, authors, related_articles_filtered
            # Use related_articles_filtered (filtered to only include valid article_ids)
            # COALESCE provides fallback to related_articles if filtered column doesn't exist
            # This significantly reduces data transfer, especially avoiding large 'content' field
            columns = "article_id, authors, COALESCE(related_articles_filtered, related_articles) as related_articles_filtered"
            
            # If dataset is large, load in chunks
            if total_to_load > chunk_size:
                print(f"Loading {total_to_load:,} rows in chunks of {chunk_size:,}...")
                chunks = []
                offset = 0
                
                while offset < total_to_load:
                    current_chunk_size = min(chunk_size, total_to_load - offset)
                    query = (
                        f"SELECT {columns} FROM articles "
                        f"ORDER BY article_date DESC "
                        f"LIMIT {current_chunk_size} OFFSET {offset}"
                    )
                    print(f"Loading chunk: rows {offset:,} to {offset + current_chunk_size:,}...")
                    chunk_df = pd.read_sql(query, self.engine)
                    if len(chunk_df) == 0:
                        break
                    chunks.append(chunk_df)
                    offset += len(chunk_df)
                    print(f"  Loaded {len(chunk_df):,} rows (total: {sum(len(c) for c in chunks):,})")
                
                self.df = pd.concat(chunks, ignore_index=True)
            else:
                # Small dataset, load all at once
                query = f"SELECT {columns} FROM articles ORDER BY article_date DESC"
                if limit:
                    query += f" LIMIT {limit}"
                print("Loading data from Supabase...")
                self.df = pd.read_sql(query, self.engine)
            
            print("Columns found:", self.df.columns.tolist())
            print(f"Loaded {len(self.df)} rows.")
            return self.df
        except Exception as e:
            error_msg = str(e)
            if "statement timeout" in error_msg.lower() or "querycanceled" in error_msg.lower():
                print("Warning: Query timed out. This might be due to a large dataset.")
                print("Consider using load_data(limit=N) to load a subset of data first.")
            raise ConnectionError(f"Failed to load data from database: {e}")

    def _normalize_authors(self, author_field):
        """
        Convert author field into a list of authors.
        Handles your format:
        '["Alain Zucker", "Martin Berz"]'
        '["Alain Zucker"]'
        """
        if pd.isna(author_field):
            return []

        if isinstance(author_field, list):
            # Already a list
            return [a.strip() for a in author_field]

        if isinstance(author_field, str):
            try:
                parsed = ast.literal_eval(author_field)
                if isinstance(parsed, list):
                    return [a.strip() for a in parsed]
            except Exception:
                pass

        # fallback: single author
        return [str(author_field).strip()]

    def build_authors_graph(self):

        for author_group in self.df["authors"]:
            if pd.isna(author_group):
                continue

            # Convert string like '["Albert Steck", "Jürg Meier"]' into a Python list
            try:
                author_group = ast.literal_eval(author_group)
            except Exception as e:
                print(f"Error parsing related_articles for {author_group}: {e}")

            for i in range(len(author_group)):
                for j in range(i + 1, len(author_group)):
                    # Add edge between author_group[i] and author_group[j]

                    if self.G.has_edge(author_group[i], author_group[j]):
                        self.G[author_group[i]][author_group[j]]["weight"] += 10
                    else:
                        self.G.add_edge(author_group[i], author_group[j], weight=10)

    # === 2. Build graph ===
    def build_graph(self):
        """Build graph of articles and their related articles."""
        if self.df is None:
            raise ValueError("Data not loaded. Call load_data() first.")

        author_map = {
            row["article_id"]: self._normalize_authors(row["authors"])
            for _, row in self.df.iterrows()
        }

        # Add all authors as nodes
        all_authors = {a for authors in author_map.values() for a in authors}
        self.G.add_nodes_from(all_authors)

        for _, row in self.df.iterrows():
            source_id = row["article_id"]
            source_authors = author_map[source_id]
            # self.G.add_node(article)

            # Use related_articles_filtered (which should contain only valid article_ids)
            related_articles_field = row.get("related_articles_filtered")
            
            if pd.notnull(related_articles_field):
                try:
                    related_list = ast.literal_eval(related_articles_field)
                    for target_id in related_list:

                        if target_id not in author_map:
                            continue

                        target_authors = author_map[target_id]

                        # print(target_authors)

                        for a1 in source_authors:
                            for a2 in target_authors:
                                if a1 == a2:
                                    continue

                                if self.G.has_edge(a1, a2):
                                    self.G[a1][a2]["weight"] += 1
                                else:
                                    self.G.add_edge(a1, a2, weight=1)

                except Exception as e:
                    print(f"Error parsing related_articles_filtered for {source_authors}: {e}")

        print(
            "Graph built with",
            len(self.G.nodes),
            "nodes and",
            len(self.G.edges),
            "edges.",
        )

    # === 3. Analyze connected components ===
    def analyze_components(self):
        """Compute connected components sorted by size."""
        components = list(nx.connected_components(self.G))
        self.components_sorted = sorted(components, key=len, reverse=True)

        print("Graph connected?", nx.is_connected(self.G))
        print("Number of components:", len(self.components_sorted))

        for i, comp in enumerate(self.components_sorted, 1):
            # Safely print component info, handling Unicode characters
            comp_size = len(comp)
            # Show first few nodes as sample (with safe encoding)
            sample_nodes = list(comp)[:5]
            sample_str = ", ".join([str(node).encode('ascii', 'replace').decode('ascii') for node in sample_nodes])
            if comp_size > 5:
                sample_str += f", ... ({comp_size - 5} more)"
            print(f"Component {i} (size {comp_size}): {sample_str}")

        return self.components_sorted

    # === 4. Find node with highest degree ===
    def highest_degree_node(self):
        """Return node with the most edges."""
        node, degree = max(self.G.degree, key=lambda x: x[1])
        print(f"Highest-degree node: {node} (degree {degree})")
        return node, degree

    def degree_of_author(self, author_name: str):
        if author_name not in self.G:
            print(f"Author '{author_name}' not found in graph.")
            return None

        deg = self.G.degree[author_name]
        print(f"Degree of '{author_name}': {deg}")
        return deg

    # === 5. Find the component containing a specific node ===
    def component_of_node(self, node_id: str):
        """Return component containing the given node."""
        if self.components_sorted is None:
            raise ValueError("Run analyze_components() first.")

        for comp in self.components_sorted:
            if node_id in comp:
                print(f"Node {node_id} is in a component of size {len(comp)}")
                return comp

        print(f"Node {node_id} not found.")
        return None

    # === 6. Get nodes not in the largest component ===
    def nodes_not_in_largest(self):
        """Return all nodes not in the largest connected component."""
        if self.components_sorted is None:
            raise ValueError("Run analyze_components() first.")

        largest = self.components_sorted[0]
        all_nodes = set(self.G.nodes)

        excluded = all_nodes - largest
        print(f"Nodes not in largest component: {len(excluded)}")
        return excluded

    def save_graph_to_gexf(self, filename="authors_graph.gexf"):
        """
        Save a NetworkX graph to a GEXF file.

        Parameters:
        -----------
        filename : str
            The name of the output GEXF file.
        """
        nx.write_gexf(self.G, filename)
        print(f"Graph successfully saved to {filename}")

    def get_largest_component_graph(self):

        largest_component = self.analyze_components()[0]

        G_largest = self.G.subgraph(largest_component).copy()

        return G_largest


def visualize_interactive(G, filename="authors_graph_weighted.html"):
    net = Network(
        notebook=False,
        height="800px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#000000",
    )

    print(G.nodes())
    # Add nodes with size proportional to weighted degree
    for node in G.nodes():
        strength = G.degree(node, weight="weight")
        size = 5 + strength * 1.5
        net.add_node(
            node,
            label=node,
            size=size,  # node size
            title=f"Autor: {size}",
            shape="dot",  # ensures label is inside the node
            font={
                "size": 14,  # fixed font size
                "align": "center",  # center label over the circle
                "vadjust": 0,  # vertical adjustment (keeps text centered)
            },
        )

    # Add edges with weights
    for u, v, data in G.edges(data=True):
        w = data.get("weight", 1)
        net.add_edge(
            u,
            v,
            value=w,  # PyVis: used for physics weight
            title=f"Weight: {w}",
        )

    # ---- ForceAtlas2 with edge weights ----
    net.set_options(
        """
    {
        "configure": {
            "enabled": true,
            "filter": ["physics"]
        },
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -50,
                "centralGravity": 0.01,
                "springConstant": 0.2,
                "springLength": 80,
                "damping": 0.4,
                "avoidOverlap": 20
                },
            "solver": "forceAtlas2Based",
            "timestep": 0.4
        },
        "edges": {
            "scaling": {
            "min": 1,
            "max": 20
            }
        },
        "nodes": {
            "shape": "dots",
            "scaling": {
                "min": 5,
                "max": 50
            }
        }
    }
    """
    )
    # net.show_buttons(filter_=['physics'])
    net.write_html(filename, open_browser=True)
    print(f"Interactive visualization saved as: {filename}")


def normalize_node_sizes(values, new_min=5, new_max=100):
    """
    Normalize a list of numeric values into a given range [new_min, new_max].

    Parameters:
        values (list of float/int): Original values to normalize
        new_min (float): Lower bound of target range (default = 5)
        new_max (float): Upper bound of target range (default = 100)

    Returns:
        list of float: Normalized values
    """
    if not values or len(values) == 0:
        return []
    
    old_min = min(values)
    old_max = max(values)

    # Avoid division by zero if all values are the same
    if old_min == old_max:
        return [new_min for _ in values]

    return [
        new_min + (val - old_min) * (new_max - new_min) / (old_max - old_min)
        for val in values
    ]



def visualize_existing_graph_interactive(
    G,
    node_scale=5,
    figsize=(24, 16),
    weight_threshold=0,
    label_top_n=50,
    iterations=1000,
    show_names=False,
    cluster_colors=None,
):
    # Filter edges by weight
    filtered_edges = [
        (u, v) for u, v, w in G.edges(data="weight") if w > weight_threshold
    ]
    H = G.edge_subgraph(filtered_edges).copy()
    
    # Check if graph has any edges
    if len(H.edges()) == 0:
        print("Warning: Graph has no edges after filtering. Cannot visualize.")
        return
    
    if len(H.nodes()) == 0:
        print("Warning: Graph has no nodes. Cannot visualize.")
        return

    # Compute node weights
    node_weights = {node: 0 for node in H.nodes()}
    #print(node_weights)
    for u, v, w in H.edges(data="weight"):
        node_weights[u] += w
        node_weights[v] += w

    node_sizes = [node_weights[n] * node_scale for n in H.nodes()]
    # pos = nx.spring_layout(H, weight='weight',scale=500, center=(0,0),seed=layout_seed, k=2)

    node_sizes = normalize_node_sizes(values=node_sizes)
    
    if not node_sizes:
        print("Warning: No valid node sizes computed. Cannot visualize.")
        return
    

    # Adapt layout and visualization based on clustering
    if cluster_colors is not None:
        # When clustering is enabled, use a better initial layout that groups clusters
        print("Adapting visualization for cluster display...")
        
        # Group nodes by cluster
        cluster_groups = {}
        for node in H.nodes():
            cluster_id = cluster_colors.get(node, -1)
            if cluster_id not in cluster_groups:
                cluster_groups[cluster_id] = []
            cluster_groups[cluster_id].append(node)
        
        # Create initial positions that separate clusters spatially
        # Use a circular layout for each cluster, then position clusters in a larger circle
        initial_pos = {}
        num_clusters = len([c for c in cluster_groups.keys() if c >= 0])
        
        if num_clusters > 0:
            # Position clusters in a circle
            cluster_centers = {}
            angle_step = 2 * math.pi / num_clusters if num_clusters > 1 else 0
            cluster_idx = 0
            
            for cluster_id, nodes in cluster_groups.items():
                if cluster_id >= 0 and len(nodes) > 0:
                    # Center of cluster
                    angle = cluster_idx * angle_step
                    center_x = 100 * math.cos(angle)
                    center_y = 100 * math.sin(angle)
                    cluster_centers[cluster_id] = (center_x, center_y)
                    
                    # Position nodes in a small circle around cluster center
                    node_angle_step = 2 * math.pi / len(nodes) if len(nodes) > 1 else 0
                    radius = min(30, 5 * math.sqrt(len(nodes)))
                    
                    for i, node in enumerate(nodes):
                        node_angle = i * node_angle_step
                        initial_pos[node] = (
                            center_x + radius * math.cos(node_angle),
                            center_y + radius * math.sin(node_angle)
                        )
                    cluster_idx += 1
            
            # Position nodes without clusters (cluster_id = -1) in center
            if -1 in cluster_groups:
                for node in cluster_groups[-1]:
                    initial_pos[node] = (0, 0)
        else:
            initial_pos = None
        
        # Configure ForceAtlas2 with adjusted parameters for better cluster visualization
        forceatlas2 = ForceAtlas2(
            outboundAttractionDistribution=False,
            linLogMode=False,
            adjustSizes=True,
            edgeWeightInfluence=1.2,  # Slightly higher to emphasize strong connections
            jitterTolerance=1.0,
            barnesHutOptimize=True,
            barnesHutTheta=1.2,
            scalingRatio=120.0,  # Slightly higher to give more space
            strongGravityMode=False,
            gravity=0.15,  # Slightly higher gravity to keep clusters together
            verbose=True,
        )
        
        # Use initial positions if available
        pos = forceatlas2.forceatlas2_networkx_layout(H, pos=initial_pos, iterations=iterations)
    else:
        # Standard configuration when no clustering
        forceatlas2 = ForceAtlas2(
            outboundAttractionDistribution=False,
            linLogMode=False,
            adjustSizes=True,
            edgeWeightInfluence=1,
            jitterTolerance=1.0,
            barnesHutOptimize=True,
            barnesHutTheta=1.2,
            scalingRatio=100.0,
            strongGravityMode=False,
            gravity=0.1,
            verbose=True,
        )
        
        # Compute layout
        pos = forceatlas2.forceatlas2_networkx_layout(H, pos=None, iterations=iterations)


    # Draw
    fig, ax = plt.subplots(figsize=figsize)

    # Determine node colors (by cluster if provided, otherwise default)
    if cluster_colors is not None:
        node_colors = [cluster_colors.get(node, 0) for node in H.nodes()]
        # Use a colormap for clusters
        import matplotlib.cm as cm
        cmap = cm.get_cmap('tab20')  # Use tab20 for distinct colors
        node_colors_mapped = [cmap(c % 20) for c in node_colors]
    else:
        node_colors_mapped = "skyblue"

    # Draw edges first (so nodes appear on top)
    if cluster_colors is not None:
        # Separate intra-cluster and inter-cluster edges for better visualization
        intra_cluster_edges = []
        inter_cluster_edges = []
        
        for u, v in H.edges():
            u_cluster = cluster_colors.get(u, -1)
            v_cluster = cluster_colors.get(v, -1)
            
            if u_cluster == v_cluster and u_cluster >= 0:
                intra_cluster_edges.append((u, v))
            else:
                inter_cluster_edges.append((u, v))
        
        # Draw inter-cluster edges (lighter, thinner)
        if inter_cluster_edges:
            nx.draw_networkx_edges(
                H, pos, 
                edgelist=inter_cluster_edges,
                edge_color="lightgray",
                width=0.15,
                alpha=0.3,
                ax=ax,
                style='dashed'
            )
        
        # Draw intra-cluster edges (darker, thicker)
        if intra_cluster_edges:
            nx.draw_networkx_edges(
                H, pos,
                edgelist=intra_cluster_edges,
                edge_color="gray",
                width=0.3,
                alpha=0.6,
                ax=ax
            )
        
        title = "Weighted Network Graph (Clustered)"
    else:
        # Standard edge drawing
        nx.draw_networkx_edges(H, pos, edge_color="gray", width=0.2, alpha=0.5, ax=ax)
        title = "Weighted Network Graph"
    
    # Draw nodes on top
    nx.draw_networkx_nodes(
        H, pos, node_size=node_sizes, node_color=node_colors_mapped, alpha=0.7, ax=ax
    )

    ax.set_title(title, fontsize=14)
    ax.axis("off")
    plt.tight_layout()

    # --- Helper: update labels dynamically ---
    def update_labels():
        # Clear old labels
        for artist in ax.texts:
            artist.remove()
        # Show labels only for nodes currently visible
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        visible_nodes = []
        for node, (x, y) in pos.items():
            if xlim[0] <= x <= xlim[1] and ylim[0] <= y <= ylim[1]:
                visible_nodes.append(node)
        # Limit to top-N by weight
        top_nodes = sorted(
            [(n, node_weights[n]) for n in visible_nodes],
            key=lambda x: x[1],
            reverse=True,
        )[:label_top_n]
        
        # Extract labels: use name if show_names=True and node has name attribute, otherwise use node ID
        labels = {}
        for node, _ in top_nodes:
            if show_names:
                node_data = H.nodes[node]
                # Try to get name from node data
                label = node_data.get('name', node)
                # If node is like "author_123", try to extract name from data
                if label == node and node.startswith('author_'):
                    label = node_data.get('name', node.replace('author_', ''))
            else:
                label = node
            labels[node] = label
        
        nx.draw_networkx_labels(H, pos, labels=labels, font_size=8, ax=ax)

    # --- Add scroll zoom and pan ---
    def zoom(event):
        base_scale = 1.1
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        xdata = event.xdata
        ydata = event.ydata
        if xdata is None or ydata is None:
            return
        if event.button == "up":  # zoom in
            scale_factor = 1 / base_scale
        elif event.button == "down":  # zoom out
            scale_factor = base_scale
        else:
            scale_factor = 1
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
        ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
        update_labels()  # refresh labels after zoom
        fig.canvas.draw_idle()

    def pan(event):
        if event.button == 1 and event.inaxes == ax:  # left mouse drag
            dx = -event.xdata + pan.prev_x
            dy = -event.ydata + pan.prev_y
            cur_xlim = ax.get_xlim()
            cur_ylim = ax.get_ylim()
            ax.set_xlim(cur_xlim + dx)
            ax.set_ylim(cur_ylim + dy)
            update_labels()  # refresh labels after pan
            fig.canvas.draw_idle()
        pan.prev_x, pan.prev_y = event.xdata, event.ydata

    pan.prev_x, pan.prev_y = None, None
    fig.canvas.mpl_connect("scroll_event", zoom)
    fig.canvas.mpl_connect("motion_notify_event", pan)

    update_labels()

    plt.show(block=True)


class ArticleGraphBuilderV2:
    """Loads NZZ article and author data, builds a graph with authors as nodes connected to articles.
    
    This version:
    - Uses authors from the authors table as nodes (with author IDs)
    - Connects authors to articles they wrote
    - Can also build author-author co-authorship network
    """
    
    def __init__(self):
        """Initialize ArticleGraphBuilderV2 with Supabase PostgreSQL connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError("SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")
        
        self.articles_df = None
        self.authors_df = None
        self.G = nx.Graph()
        self.components_sorted = None
        self.clusters = None  # Store clustering results
        
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
    
    def load_data(self, limit=None, chunk_size=10000):
        """Load articles and authors from Supabase PostgreSQL.
        
        Args:
            limit (int, optional): Maximum number of articles to load. If None, loads all.
            chunk_size (int): Number of rows to fetch per chunk when loading large datasets.
        
        Returns:
            tuple: (articles_df, authors_df)
        """
        try:
            # Load authors from authors table
            logger.info("Loading authors from database...")
            authors_query = "SELECT id, name, author_id, department, location, has_info FROM authors"
            self.authors_df = pd.read_sql(authors_query, self.engine)
            logger.info(f"Loaded {len(self.authors_df):,} authors")
            
            # Load articles
            count_query = "SELECT COUNT(*) FROM articles"
            total_count = pd.read_sql(count_query, self.engine).iloc[0, 0]
            logger.info(f"Total articles in database: {total_count:,}")
            
            if limit:
                total_to_load = min(limit, total_count)
            else:
                total_to_load = total_count
            
            columns = "article_id, authors, COALESCE(related_articles_filtered, related_articles) as related_articles_filtered"
            
            if total_to_load > chunk_size:
                logger.info(f"Loading {total_to_load:,} articles in chunks of {chunk_size:,}...")
                chunks = []
                offset = 0
                
                while offset < total_to_load:
                    current_chunk_size = min(chunk_size, total_to_load - offset)
                    query = (
                        f"SELECT {columns} FROM articles "
                        f"ORDER BY article_date DESC "
                        f"LIMIT {current_chunk_size} OFFSET {offset}"
                    )
                    logger.info(f"Loading chunk: rows {offset:,} to {offset + current_chunk_size:,}...")
                    chunk_df = pd.read_sql(query, self.engine)
                    if len(chunk_df) == 0:
                        break
                    chunks.append(chunk_df)
                    offset += len(chunk_df)
                    logger.info(f"  Loaded {len(chunk_df):,} rows (total: {sum(len(c) for c in chunks):,})")
                
                self.articles_df = pd.concat(chunks, ignore_index=True)
            else:
                query = f"SELECT {columns} FROM articles ORDER BY article_date DESC"
                if limit:
                    query += f" LIMIT {limit}"
                logger.info("Loading articles from Supabase...")
                self.articles_df = pd.read_sql(query, self.engine)
            
            logger.info(f"Loaded {len(self.articles_df):,} articles")
            return self.articles_df, self.authors_df
            
        except Exception as e:
            raise ConnectionError(f"Failed to load data from database: {e}")
    
    def _normalize_name(self, name):
        """Normalize author name for matching (case-insensitive, trimmed)."""
        if pd.isna(name) or not name:
            return None
        return str(name).strip().lower()
    
    def _parse_authors_list(self, authors_field):
        """Parse authors field from articles (can be JSON string or list)."""
        if pd.isna(authors_field):
            return []
        
        try:
            if isinstance(authors_field, str):
                parsed = ast.literal_eval(authors_field)
            elif isinstance(authors_field, list):
                parsed = authors_field
            else:
                return []
            
            if isinstance(parsed, list):
                return [str(a).strip() for a in parsed if a and str(a).strip()]
            return []
        except Exception:
            return []
    
    def build_author_article_graph(self):
        """Build graph with authors as nodes connected to articles.
        
        Creates a bipartite-like graph where:
        - Author nodes are from the authors table (using author ID as node ID)
        - Articles are represented as edges or can be added as nodes too
        - Edges connect authors to articles they wrote
        """
        if self.articles_df is None or self.authors_df is None:
            raise ValueError("Data not loaded. Call load_data() first.")
        
        # Create mapping from author name (normalized) to author records
        name_to_author = {}
        for _, author in self.authors_df.iterrows():
            normalized_name = self._normalize_name(author['name'])
            if normalized_name:
                # Store multiple authors with same name (list)
                if normalized_name not in name_to_author:
                    name_to_author[normalized_name] = []
                name_to_author[normalized_name].append(author)
        
        # Add all authors as nodes (use author ID if available, otherwise use name)
        for _, author in self.authors_df.iterrows():
            # Use author ID as node identifier, fallback to name
            node_id = f"author_{author['id']}" if pd.notna(author['id']) else f"author_{author['name']}"
            self.G.add_node(
                node_id,
                node_type='author',
                name=author['name'],
                author_id=author['id'] if pd.notna(author['id']) else None,
                author_db_id=author['id'],
                department=author['department'] if pd.notna(author['department']) else None,
                location=author['location'] if pd.notna(author['location']) else None,
                has_info=author['has_info'] if pd.notna(author['has_info']) else 0
            )
        
        # Process articles and connect authors to articles
        article_count = 0
        for _, article in self.articles_df.iterrows():
            article_id = article['article_id']
            author_names = self._parse_authors_list(article['authors'])
            
            if not author_names:
                continue
            
            # Add article as node
            article_node_id = f"article_{article_id}"
            self.G.add_node(
                article_node_id,
                node_type='article',
                article_id=article_id
            )
            
            # Connect each author to this article
            for author_name in author_names:
                normalized_name = self._normalize_name(author_name)
                if normalized_name and normalized_name in name_to_author:
                    # Connect to all matching authors (in case of duplicates)
                    for author_record in name_to_author[normalized_name]:
                        author_node_id = f"author_{author_record['id']}" if pd.notna(author_record['id']) else f"author_{author_record['name']}"
                        
                        if self.G.has_edge(author_node_id, article_node_id):
                            self.G[author_node_id][article_node_id]["weight"] += 1
                        else:
                            self.G.add_edge(author_node_id, article_node_id, weight=1)
            
            article_count += 1
        
        print(f"Graph built with {len(self.G.nodes)} nodes ({len([n for n, d in self.G.nodes(data=True) if d.get('node_type') == 'author'])} authors, "
              f"{len([n for n, d in self.G.nodes(data=True) if d.get('node_type') == 'article'])} articles) and {len(self.G.edges)} edges.")
        
        return self.G
    
    def build_coauthorship_graph(self):
        """Build author-author co-authorship graph based on articles.
        
        Creates edges between authors who co-authored articles together.
        """
        if self.articles_df is None or self.authors_df is None:
            raise ValueError("Data not loaded. Call load_data() first.")
        
        # Create mapping from author name (normalized) to author records
        name_to_author = {}
        for _, author in self.authors_df.iterrows():
            normalized_name = self._normalize_name(author['name'])
            if normalized_name:
                if normalized_name not in name_to_author:
                    name_to_author[normalized_name] = []
                name_to_author[normalized_name].append(author)
        
        # Add all authors as nodes
        for _, author in self.authors_df.iterrows():
            node_id = f"author_{author['id']}" if pd.notna(author['id']) else f"author_{author['name']}"
            self.G.add_node(
                node_id,
                node_type='author',
                name=author['name'],
                author_id=author['id'] if pd.notna(author['id']) else None,
                author_db_id=author['id'],
                department=author['department'] if pd.notna(author['department']) else None,
                location=author['location'] if pd.notna(author['location']) else None,
                has_info=author['has_info'] if pd.notna(author['has_info']) else 0
            )
        
        # Process articles and create co-authorship edges
        for _, article in self.articles_df.iterrows():
            author_names = self._parse_authors_list(article['authors'])
            
            if len(author_names) < 2:
                continue  # Need at least 2 authors for co-authorship
            
            # Get all author nodes for this article
            article_author_nodes = []
            for author_name in author_names:
                normalized_name = self._normalize_name(author_name)
                if normalized_name and normalized_name in name_to_author:
                    for author_record in name_to_author[normalized_name]:
                        node_id = f"author_{author_record['id']}" if pd.notna(author_record['id']) else f"author_{author_record['name']}"
                        article_author_nodes.append(node_id)
            
            # Create edges between all pairs of co-authors
            for i in range(len(article_author_nodes)):
                for j in range(i + 1, len(article_author_nodes)):
                    a1 = article_author_nodes[i]
                    a2 = article_author_nodes[j]
                    
                    if self.G.has_edge(a1, a2):
                        self.G[a1][a2]["weight"] += 1
                    else:
                        self.G.add_edge(a1, a2, weight=1)
        
        print(f"Co-authorship graph built with {len(self.G.nodes)} author nodes and {len(self.G.edges)} edges.")
        
        return self.G
    
    def build_related_graph(self):
        """Build author-author graph based on related articles (similar to V1 but using authors table).
        
        Creates edges between authors when their articles are related:
        - If article A is related to article B, connect all authors of A to all authors of B
        - Also connects co-authors within the same article (higher weight)
        - Uses author IDs from the authors table as node identifiers
        """
        if self.articles_df is None or self.authors_df is None:
            raise ValueError("Data not loaded. Call load_data() first.")
        
        # Create mapping from author name (normalized) to author records
        name_to_author = {}
        for _, author in self.authors_df.iterrows():
            normalized_name = self._normalize_name(author['name'])
            if normalized_name:
                if normalized_name not in name_to_author:
                    name_to_author[normalized_name] = []
                name_to_author[normalized_name].append(author)
        
        # Create mapping from article_id to list of author node IDs
        article_to_authors = {}
        for _, article in self.articles_df.iterrows():
            article_id = article['article_id']
            author_names = self._parse_authors_list(article['authors'])
            
            author_nodes = []
            seen_nodes = set()  # Track seen nodes to avoid duplicates
            for author_name in author_names:
                normalized_name = self._normalize_name(author_name)
                if normalized_name and normalized_name in name_to_author:
                    for author_record in name_to_author[normalized_name]:
                        node_id = f"author_{author_record['id']}" if pd.notna(author_record['id']) else f"author_{author_record['name']}"
                        if node_id not in seen_nodes:
                            author_nodes.append(node_id)
                            seen_nodes.add(node_id)
            
            article_to_authors[article_id] = author_nodes
        
        # Add all authors as nodes
        for _, author in self.authors_df.iterrows():
            node_id = f"author_{author['id']}" if pd.notna(author['id']) else f"author_{author['name']}"
            self.G.add_node(
                node_id,
                node_type='author',
                name=author['name'],
                author_id=author['id'] if pd.notna(author['id']) else None,
                author_db_id=author['id'],
                department=author['department'] if pd.notna(author['department']) else None,
                location=author['location'] if pd.notna(author['location']) else None,
                has_info=author['has_info'] if pd.notna(author['has_info']) else 0
            )
        
        # First, connect co-authors within the same article (weight = 10, like V1)
        for article_id, author_nodes in article_to_authors.items():
            if len(author_nodes) < 2:
                continue
            
            # Connect all pairs of co-authors
            for i in range(len(author_nodes)):
                for j in range(i + 1, len(author_nodes)):
                    a1 = author_nodes[i]
                    a2 = author_nodes[j]
                    
                    if self.G.has_edge(a1, a2):
                        self.G[a1][a2]["weight"] += 10
                    else:
                        self.G.add_edge(a1, a2, weight=10)
        
        # Then, connect authors based on related articles (weight = 1, like V1)
        for _, article in self.articles_df.iterrows():
            source_id = article['article_id']
            source_authors = article_to_authors.get(source_id, [])
            
            if not source_authors:
                continue
            
            # Parse related articles
            related_articles_field = article.get('related_articles_filtered')
            
            if pd.notnull(related_articles_field):
                try:
                    related_list = ast.literal_eval(related_articles_field)
                    for target_id in related_list:
                        if target_id not in article_to_authors:
                            continue
                        
                        target_authors = article_to_authors[target_id]
                        
                        # Connect all authors of source article to all authors of target article
                        for a1 in source_authors:
                            for a2 in target_authors:
                                if a1 == a2:
                                    continue
                                
                                if self.G.has_edge(a1, a2):
                                    self.G[a1][a2]["weight"] += 1
                                else:
                                    self.G.add_edge(a1, a2, weight=1)
                
                except Exception as e:
                    print(f"Error parsing related_articles_filtered for article {source_id}: {e}")
        
        print(f"Related articles graph built with {len(self.G.nodes)} author nodes and {len(self.G.edges)} edges.")
        
        return self.G
    
    def analyze_components(self):
        """Compute connected components sorted by size."""
        components = list(nx.connected_components(self.G))
        self.components_sorted = sorted(components, key=len, reverse=True)
        
        print("Graph connected?", nx.is_connected(self.G))
        print("Number of components:", len(self.components_sorted))
        
        for i, comp in enumerate(self.components_sorted, 1):
            comp_size = len(comp)
            sample_nodes = list(comp)[:5]
            sample_str = ", ".join([str(node).encode('ascii', 'replace').decode('ascii') for node in sample_nodes])
            if comp_size > 5:
                sample_str += f", ... ({comp_size - 5} more)"
            print(f"Component {i} (size {comp_size}): {sample_str}")
        
        return self.components_sorted
    
    def highest_degree_node(self):
        """Return node with the most edges."""
        node, degree = max(self.G.degree, key=lambda x: x[1])
        node_data = self.G.nodes[node]
        node_name = node_data.get('name', node)
        print(f"Highest-degree node: {node_name} ({node}) (degree {degree})")
        return node, degree
    
    def get_largest_component_graph(self):
        """Get the largest connected component as a subgraph."""
        if self.components_sorted is None:
            self.analyze_components()
        
        largest_component = self.components_sorted[0]
        G_largest = self.G.subgraph(largest_component).copy()
        
        return G_largest
    
    def compute_clusters(self, method='louvain'):
        """Compute community clusters using specified algorithm.
        
        Available methods:
        - 'louvain': Louvain algorithm (modularity optimization)
        - 'leiden': Leiden algorithm (improved Louvain, requires igraph)
        - 'greedy_modularity': Greedy modularity communities (NetworkX)
        - 'label_propagation': Label propagation algorithm (NetworkX)
        - 'asyn_lpa': Asynchronous label propagation (NetworkX)
        
        Args:
            method (str): Clustering algorithm to use (default: 'louvain')
        
        Returns:
            dict: Mapping of node -> cluster_id
        """
        if len(self.G.nodes()) == 0:
            print("Warning: Graph is empty. Cannot compute clusters.")
            return {}
        
        # Use the largest component for clustering if graph is disconnected
        if not nx.is_connected(self.G):
            print("Graph is disconnected. Computing clusters on largest component...")
            G_cluster = self.get_largest_component_graph()
        else:
            G_cluster = self.G
        
        print(f"\nComputing clusters using {method} algorithm...")
        
        # Compute partition based on method
        partition = {}
        
        if method == 'louvain':
            if not HAS_COMMUNITY:
                raise ImportError("python-louvain is required for Louvain clustering. Install with: pip install python-louvain")
            partition = community_louvain.best_partition(G_cluster, weight='weight')
        
        elif method == 'leiden':
            if not HAS_IGRAPH:
                print("Warning: igraph not available. Falling back to Louvain algorithm.")
                if not HAS_COMMUNITY:
                    raise ImportError("Neither igraph nor python-louvain available. Install with: pip install python-igraph or pip install python-louvain")
                partition = community_louvain.best_partition(G_cluster, weight='weight')
            else:
                # Convert NetworkX graph to igraph
                # Create mapping from node names to indices
                node_list = list(G_cluster.nodes())
                node_to_idx = {node: idx for idx, node in enumerate(node_list)}
                
                # Create igraph graph
                edges = [(node_to_idx[u], node_to_idx[v]) for u, v in G_cluster.edges()]
                weights = [G_cluster[u][v].get('weight', 1) for u, v in G_cluster.edges()]
                g_ig = ig.Graph(edges, edge_attrs={'weight': weights})
                
                # Run Leiden algorithm
                leiden_partition = g_ig.community_leiden(weights='weight', resolution_parameter=1.0)
                
                # Convert back to node->cluster_id mapping
                for idx, cluster_id in enumerate(leiden_partition.membership):
                    partition[node_list[idx]] = cluster_id
        
        elif method == 'greedy_modularity':
            # NetworkX greedy modularity communities
            communities = nx.community.greedy_modularity_communities(G_cluster, weight='weight')
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id
        
        elif method == 'label_propagation':
            # NetworkX label propagation
            communities = nx.community.label_propagation_communities(G_cluster)
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id
        
        elif method == 'asyn_lpa':
            # NetworkX asynchronous label propagation
            communities = nx.community.asyn_lpa_communities(G_cluster, weight='weight')
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id
        
        else:
            raise ValueError(f"Unknown clustering method: {method}. Available methods: louvain, leiden, greedy_modularity, label_propagation, asyn_lpa")
        
        # Extend partition to all nodes (nodes not in largest component get cluster -1)
        self.clusters = {}
        for node in self.G.nodes():
            if node in partition:
                self.clusters[node] = partition[node]
            else:
                self.clusters[node] = -1
        
        # Print cluster statistics
        cluster_counts = {}
        for cluster_id in self.clusters.values():
            cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1
        
        print(f"\nClustering Results ({method}):")
        print(f"Number of clusters: {len([c for c in cluster_counts.keys() if c >= 0])}")
        print(f"Nodes in largest component: {len([n for n, c in self.clusters.items() if c >= 0])}")
        
        # Calculate modularity if possible
        try:
            if method in ['louvain', 'leiden', 'greedy_modularity']:
                # Create communities list for modularity calculation
                communities_list = []
                for cluster_id in set(self.clusters.values()):
                    if cluster_id >= 0:
                        community = [n for n, c in self.clusters.items() if c == cluster_id]
                        communities_list.append(community)
                
                if communities_list:
                    modularity = nx.community.modularity(G_cluster, communities_list, weight='weight')
                    print(f"Modularity: {modularity:.4f}")
        except Exception as e:
            print(f"Could not calculate modularity: {e}")
        
        # Show top clusters by size
        sorted_clusters = sorted(
            [(cid, count) for cid, count in cluster_counts.items() if cid >= 0],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        print("\nTop 10 clusters by size:")
        for i, (cluster_id, count) in enumerate(sorted_clusters, 1):
            # Get sample nodes from this cluster
            cluster_nodes = [n for n, c in self.clusters.items() if c == cluster_id]
            sample_names = []
            for node in cluster_nodes[:3]:
                node_data = self.G.nodes[node]
                name = node_data.get('name', str(node))
                sample_names.append(name)
            sample_str = ", ".join([str(n).encode('ascii', 'replace').decode('ascii') for n in sample_names])
            if count > 3:
                sample_str += f", ... ({count - 3} more)"
            print(f"  Cluster {cluster_id} (size {count}): {sample_str}")
        
        return self.clusters
    
    def save_graph_to_gexf(self, filename="authors_articles_graph.gexf"):
        """Save the graph to a GEXF file."""
        nx.write_gexf(self.G, filename)
        print(f"Graph successfully saved to {filename}")


# === Example Usage ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Build and analyze article-author networks from NZZ database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use original builder (author-author network)
  python articles.py --builder v1
  
  # Use V2 builder with author-article graph
  python articles.py --builder v2 --graph-type author-article
  
  # Use V2 builder with co-authorship graph
  python articles.py --builder v2 --graph-type coauthorship
  
  # Limit to 1000 articles and save to GEXF
  python articles.py --builder v2 --graph-type author-article --limit 1000 --save authors_v2.gexf
  
  # Visualize the graph interactively
  python articles.py --builder v2 --graph-type author-article --visualize
  
  # Use clustering with different methods
  python articles.py --builder v2 --cluster louvain
  python articles.py --builder v2 --cluster leiden
  python articles.py --builder v2 --cluster greedy_modularity
  python articles.py --builder v2 --cluster label_propagation
  python articles.py --builder v2 --cluster asyn_lpa
  
  # Combine clustering with visualization
  python articles.py --builder v2 --cluster leiden --visualize
        """
    )
    
    parser.add_argument(
        '--builder',
        choices=['v1', 'v2'],
        default='v1',
        help='Graph builder version: v1 (original author-author) or v2 (authors table based) (default: v1)'
    )
    
    parser.add_argument(
        '--graph-type',
        choices=['author-article', 'coauthorship', 'related'],
        default='related',
        help='Graph type: related (author-author via related articles, default for V2), author-article (bipartite, V2 only), coauthorship (author-author, V2 only)'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of articles to load (default: all)'
    )
    
    parser.add_argument(
        '--save',
        type=str,
        default=None,
        help='Save graph to GEXF file (e.g., --save graph.gexf)'
    )
    
    parser.add_argument(
        '--visualize',
        action='store_true',
        default=True,
        help='Show interactive visualization of the graph (default: True)'
    )
    
    parser.add_argument(
        '--no-visualize',
        dest='visualize',
        action='store_false',
        help='Skip interactive visualization'
    )
    
    parser.add_argument(
        '--analyze',
        action='store_true',
        default=True,
        help='Run graph analysis (components, highest degree, etc.) (default: True)'
    )
    
    parser.add_argument(
        '--no-analyze',
        dest='analyze',
        action='store_false',
        help='Skip graph analysis'
    )
    
    parser.add_argument(
        '--author',
        type=str,
        default=None,
        help='Analyze specific author (for V1 builder only)'
    )
    
    parser.add_argument(
        '--cluster',
        type=str,
        nargs='?',
        const='louvain',
        default=None,
        choices=['louvain', 'leiden', 'greedy_modularity', 'label_propagation', 'asyn_lpa'],
        help='Perform community clustering analysis (V2 only). Methods: louvain (default), leiden, greedy_modularity, label_propagation, asyn_lpa'
    )
    
    args = parser.parse_args()
    
    try:
        if args.builder == 'v1':
            # Original ArticleGraphBuilder
            print("="*80)
            print("Using ArticleGraphBuilder (V1)")
            print("="*80)
            
            builder = ArticleGraphBuilder()
            builder.load_data(limit=args.limit)
            
            if args.graph_type == 'related':
                builder.build_authors_graph()
                builder.build_graph()
            else:
                print(f"Warning: Graph type '{args.graph_type}' not available for V1 builder.")
                print("Using default 'related' graph type.")
                builder.build_authors_graph()
                builder.build_graph()
            
            if args.analyze:
                builder.analyze_components()
                builder.highest_degree_node()
                
                if args.author:
                    builder.component_of_node(args.author)
                    builder.degree_of_author(args.author)
                else:
                    builder.component_of_node("Eric Gujer")
                    builder.degree_of_author("Eric Gujer")
                
                builder.nodes_not_in_largest()
            
            if args.save:
                builder.save_graph_to_gexf(filename=args.save)
            
            if args.visualize:
                visualize_existing_graph_interactive(builder.get_largest_component_graph())
        
        elif args.builder == 'v2':
            # New ArticleGraphBuilderV2
            print("="*80)
            print("Using ArticleGraphBuilderV2 (V2)")
            print("="*80)
            
            builder = ArticleGraphBuilderV2()
            builder.load_data(limit=args.limit)
            
            if args.graph_type == 'related':
                print("Building related articles graph (author-author via related articles)...")
                builder.build_related_graph()
            elif args.graph_type == 'author-article':
                print("Building author-article graph...")
                builder.build_author_article_graph()
            elif args.graph_type == 'coauthorship':
                print("Building co-authorship graph...")
                builder.build_coauthorship_graph()
            else:
                print(f"Warning: Graph type '{args.graph_type}' not available for V2 builder.")
                print("Using default 'related' graph type.")
                builder.build_related_graph()
            
            if args.analyze:
                builder.analyze_components()
                builder.highest_degree_node()
            
            # Compute clusters if requested
            cluster_colors = None
            if args.cluster is not None:
                cluster_method = args.cluster  # args.cluster is already the method name or 'louvain' if const
                try:
                    builder.compute_clusters(method=cluster_method)
                    cluster_colors = builder.clusters
                except ImportError as e:
                    print(f"Warning: {e}")
                    print("Skipping clustering.")
                except Exception as e:
                    print(f"Error during clustering: {e}")
                    print("Skipping clustering.")
            
            if args.save:
                builder.save_graph_to_gexf(filename=args.save)
            
            if args.visualize:
                # For V2, show author names and optionally color by cluster
                if args.graph_type == 'author-article':
                    # For author-article graph, create co-authorship projection for visualization
                    # (connect authors who wrote articles together)
                    print("Creating co-authorship projection for visualization...")
                    G_vis = nx.Graph()
                    
                    # Add all author nodes
                    for node, data in builder.G.nodes(data=True):
                        if data.get('node_type') == 'author':
                            G_vis.add_node(node, **data)
                    
                    # Find articles and connect their authors
                    article_nodes = [n for n, d in builder.G.nodes(data=True) if d.get('node_type') == 'article']
                    for article_node in article_nodes:
                        # Get all authors connected to this article
                        article_authors = [n for n in builder.G.neighbors(article_node) 
                                         if builder.G.nodes[n].get('node_type') == 'author']
                        
                        # Connect all pairs of co-authors
                        for i in range(len(article_authors)):
                            for j in range(i + 1, len(article_authors)):
                                a1 = article_authors[i]
                                a2 = article_authors[j]
                                if G_vis.has_edge(a1, a2):
                                    G_vis[a1][a2]["weight"] += 1
                                else:
                                    G_vis.add_edge(a1, a2, weight=1)
                    
                    if len(G_vis.edges()) == 0:
                        print("Warning: Co-authorship projection has no edges. Showing full graph instead.")
                        G_vis = builder.get_largest_component_graph()
                    
                    # Use cluster colors from original graph if available
                    vis_cluster_colors = None
                    if cluster_colors:
                        vis_cluster_colors = {node: cluster_colors.get(node, -1) for node in G_vis.nodes()}
                    
                    visualize_existing_graph_interactive(
                        G_vis, 
                        show_names=True, 
                        cluster_colors=vis_cluster_colors
                    )
                else:
                    # For related and coauthorship graphs, use the graph directly
                    visualize_existing_graph_interactive(
                        builder.get_largest_component_graph(),
                        show_names=True,
                        cluster_colors=cluster_colors
                    )
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
