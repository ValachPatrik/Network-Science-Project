import os
import ast
import sys
import argparse
import pandas as pd
import networkx as nx
import logging
from dotenv import load_dotenv
from visualizer import GraphVisualizer


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("articles")

try:
    from sqlalchemy import create_engine

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    print(
        "Error: SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv"
    )

try:
    import community.community_louvain as community_louvain

    HAS_COMMUNITY = True
except ImportError:
    HAS_COMMUNITY = False
    print(
        "Warning: python-louvain not available. Louvain/Leiden clustering will be disabled. Install with: pip install python-louvain"
    )

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
            raise ImportError(
                "SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv"
            )

        self.df = None
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
                    "options": "-c statement_timeout=300000",  # 5 minutes in milliseconds
                },
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
                    print(
                        f"Loading chunk: rows {offset:,} to {offset + current_chunk_size:,}..."
                    )
                    chunk_df = pd.read_sql(query, self.engine)
                    if len(chunk_df) == 0:
                        break
                    chunks.append(chunk_df)
                    offset += len(chunk_df)
                    print(
                        f"  Loaded {len(chunk_df):,} rows (total: {sum(len(c) for c in chunks):,})"
                    )

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
            if (
                "statement timeout" in error_msg.lower()
                or "querycanceled" in error_msg.lower()
            ):
                print("Warning: Query timed out. This might be due to a large dataset.")
                print(
                    "Consider using load_data(limit=N) to load a subset of data first."
                )
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
                    print(
                        f"Error parsing related_articles_filtered for {source_authors}: {e}"
                    )

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
            sample_str = ", ".join(
                [
                    str(node).encode("ascii", "replace").decode("ascii")
                    for node in sample_nodes
                ]
            )
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

    def compute_clusters(self, method="louvain"):
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

        if method == "louvain":
            if not HAS_COMMUNITY:
                raise ImportError(
                    "python-louvain is required for Louvain clustering. Install with: pip install python-louvain"
                )
            partition = community_louvain.best_partition(G_cluster, weight="weight")

        elif method == "leiden":
            if not HAS_IGRAPH:
                print(
                    "Warning: igraph not available. Falling back to Louvain algorithm."
                )
                if not HAS_COMMUNITY:
                    raise ImportError(
                        "Neither igraph nor python-louvain available. Install with: pip install python-igraph or pip install python-louvain"
                    )
                partition = community_louvain.best_partition(G_cluster, weight="weight")
            else:
                # Convert NetworkX graph to igraph
                # Create mapping from node names to indices
                node_list = list(G_cluster.nodes())
                node_to_idx = {node: idx for idx, node in enumerate(node_list)}

                # Create igraph graph
                edges = [(node_to_idx[u], node_to_idx[v]) for u, v in G_cluster.edges()]
                weights = [
                    G_cluster[u][v].get("weight", 1) for u, v in G_cluster.edges()
                ]
                g_ig = ig.Graph(edges, edge_attrs={"weight": weights})

                # Run Leiden algorithm
                leiden_partition = g_ig.community_leiden(
                    weights="weight", resolution_parameter=1.0
                )

                # Convert back to node->cluster_id mapping
                for idx, cluster_id in enumerate(leiden_partition.membership):
                    partition[node_list[idx]] = cluster_id

        elif method == "greedy_modularity":
            # NetworkX greedy modularity communities
            communities = nx.community.greedy_modularity_communities(
                G_cluster, weight="weight"
            )
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id

        elif method == "label_propagation":
            # NetworkX label propagation
            communities = nx.community.label_propagation_communities(G_cluster)
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id

        elif method == "asyn_lpa":
            # NetworkX asynchronous label propagation
            communities = nx.community.asyn_lpa_communities(G_cluster, weight="weight")
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id

        else:
            raise ValueError(
                f"Unknown clustering method: {method}. Available methods: louvain, leiden, greedy_modularity, label_propagation, asyn_lpa"
            )

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
        print(
            f"Number of clusters: {len([c for c in cluster_counts.keys() if c >= 0])}"
        )
        print(
            f"Nodes in largest component: {len([n for n, c in self.clusters.items() if c >= 0])}"
        )

        # Calculate modularity if possible
        try:
            if method in ["louvain", "leiden", "greedy_modularity"]:
                # Create communities list for modularity calculation
                communities_list = []
                for cluster_id in set(self.clusters.values()):
                    if cluster_id >= 0:
                        community = [
                            n for n, c in self.clusters.items() if c == cluster_id
                        ]
                        communities_list.append(community)

                if communities_list:
                    modularity = nx.community.modularity(
                        G_cluster, communities_list, weight="weight"
                    )
                    print(f"Modularity: {modularity:.4f}")
        except Exception as e:
            print(f"Could not calculate modularity: {e}")

        # Show top clusters by size
        sorted_clusters = sorted(
            [(cid, count) for cid, count in cluster_counts.items() if cid >= 0],
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        print("\nTop 10 clusters by size:")
        for i, (cluster_id, count) in enumerate(sorted_clusters, 1):
            # Get sample nodes from this cluster
            cluster_nodes = [n for n, c in self.clusters.items() if c == cluster_id]
            sample_names = []
            for node in cluster_nodes[:3]:
                # In V1, nodes are author names directly
                sample_names.append(str(node))
            sample_str = ", ".join(
                [
                    str(n).encode("ascii", "replace").decode("ascii")
                    for n in sample_names
                ]
            )
            if count > 3:
                sample_str += f", ... ({count - 3} more)"
            print(f"  Cluster {cluster_id} (size {count}): {sample_str}")

        return self.clusters




# === Example Usage ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build and analyze article-author networks from NZZ database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build and analyze the graph
  python articles.py
  
  # Limit to 1000 articles and save to GEXF
  python articles.py --limit 1000 --save graph.gexf
  
  # Visualize the graph interactively
  python articles.py --visualize
  
  # Use clustering with different methods
  python articles.py --cluster louvain
  python articles.py --cluster leiden
  python articles.py --cluster greedy_modularity
  python articles.py --cluster label_propagation
  python articles.py --cluster asyn_lpa
  
  # Combine clustering with visualization
  python articles.py --cluster leiden --visualize
  
  # Analyze specific author
  python articles.py --author "Eric Gujer"
        """,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles to load (default: all)",
    )

    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Save graph to GEXF file (e.g., --save graph.gexf)",
    )

    parser.add_argument(
        "--visualize",
        action="store_true",
        default=True,
        help="Show interactive visualization of the graph (default: True)",
    )

    parser.add_argument(
        "--no-visualize",
        dest="visualize",
        action="store_false",
        help="Skip interactive visualization",
    )

    parser.add_argument(
        "--analyze",
        action="store_true",
        default=True,
        help="Run graph analysis (components, highest degree, etc.) (default: True)",
    )

    parser.add_argument(
        "--no-analyze", dest="analyze", action="store_false", help="Skip graph analysis"
    )

    parser.add_argument(
        "--author",
        type=str,
        default=None,
        help="Analyze specific author",
    )

    parser.add_argument(
        "--cluster",
        type=str,
        nargs="?",
        const="louvain",
        default=None,
        choices=[
            "louvain",
            "leiden",
            "greedy_modularity",
            "label_propagation",
            "asyn_lpa",
        ],
        help="Perform community clustering analysis. Methods: louvain (default), leiden, greedy_modularity, label_propagation, asyn_lpa",
    )

    args = parser.parse_args()

    visualizer = GraphVisualizer()

    try:
        print("=" * 80)
        print("Using ArticleGraphBuilder")
        print("=" * 80)

        builder = ArticleGraphBuilder()
        builder.load_data(limit=args.limit)

        # Build the graph (co-authorship + related articles)
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

        # Compute clusters if requested
        cluster_colors = None
        if args.cluster is not None:
            cluster_method = (
                args.cluster
            )  # args.cluster is already the method name or 'louvain' if const
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
            visualizer.visualize_existing_graph_interactive(
                builder.get_largest_component_graph(),
                show_names=True,
                cluster_colors=cluster_colors,
            )

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
