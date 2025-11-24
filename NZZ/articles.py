import os
import ast
import pandas as pd
import networkx as nx
from pyvis.network import Network
import matplotlib.pyplot as plt
import numpy as np
from fa2_modified import ForceAtlas2
from dotenv import load_dotenv

try:
    from sqlalchemy import create_engine
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    print("Error: SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv")

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
):
    # Filter edges by weight
    filtered_edges = [
        (u, v) for u, v, w in G.edges(data="weight") if w > weight_threshold
    ]
    H = G.edge_subgraph(filtered_edges).copy()

    # Compute node weights
    node_weights = {node: 0 for node in H.nodes()}
    #print(node_weights)
    for u, v, w in H.edges(data="weight"):
        node_weights[u] += w
        node_weights[v] += w

    node_sizes = [node_weights[n] * node_scale for n in H.nodes()]
    # pos = nx.spring_layout(H, weight='weight',scale=500, center=(0,0),seed=layout_seed, k=2)

    node_sizes = normalize_node_sizes(values=node_sizes)
    

    # Configure ForceAtlas2
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


    nx.draw_networkx_nodes(
        H, pos, node_size=node_sizes, node_color="skyblue", alpha=0.7, ax=ax
    )
    # nx.draw_networkx_edges(H, pos, width=[H[u][v]['weight'] for u, v in H.edges()],
    #                        edge_color='gray', alpha=0.5, ax=ax)

    nx.draw_networkx_edges(H, pos, edge_color="gray",width=0.2, alpha=0.5, ax=ax)

    ax.set_title("Weighted Network Graph", fontsize=14)
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
        labels = {node: node for node, _ in top_nodes}
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

# === Example Usage ===
if __name__ == "__main__":
    builder = ArticleGraphBuilder()

    builder.load_data()
    builder.build_authors_graph()
    builder.build_graph()
    builder.analyze_components()

    builder.highest_degree_node()
    builder.component_of_node("Eric Gujer")
    builder.degree_of_author("Eric Gujer")
    builder.nodes_not_in_largest()
    # builder.save_graph_to_gexf(filename="authors_graph_100.gexf")

    # visualize_gephi_style(builder.G)

    # visualize_interactive(builder.G, filename="authors_graph_weighted.html")

    # visualize_gephi_style_no_overlap(builder.G)

    # visualize_existing_graph(builder.G)
    visualize_existing_graph_interactive(builder.get_largest_component_graph())
