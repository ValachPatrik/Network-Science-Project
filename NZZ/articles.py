import os
import ast
import sys
import argparse
import pandas as pd
import networkx as nx
import logging
from dotenv import load_dotenv
from visualizer import GraphVisualizer
from authors import AuthorsBuilder
from centralities import CentralityAnalysis
from collections import Counter
import math


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
        self.cluster_counts = {}
        self.cluster_author_map = {}

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

        """Return a subgraph of the largest connected component."""

        if self.components_sorted is None:
            raise ValueError("Run analyze_components() first.")


        largest_component = self.components_sorted[0]

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
        #cluster_counts = {}
        for cluster_id in self.clusters.values():
            self.cluster_counts[cluster_id] = self.cluster_counts.get(cluster_id, 0) + 1

        print(f"\nClustering Results ({method}):")
        print(
            f"Number of clusters: {len([c for c in self.cluster_counts.keys() if c >= 0])}"
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
            [(cid, count) for cid, count in self.cluster_counts.items() if cid >= 0],
            key=lambda x: x[1],
            reverse=True,
        )
        
        sorted_clusters_10 = sorted_clusters[:10]
        self._create_cluster_to_author_map(sorted_clusters=sorted_clusters)


        print("\nTop 10 clusters by size:")
        for i, (cluster_id, count) in enumerate(sorted_clusters_10, 1):
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

        

        return self.clusters, self.cluster_counts
    

    def _create_cluster_to_author_map(self, sorted_clusters):
        """
        Creates a dictionary mapping each cluster ID to a list of author names belonging to that cluster. and sorted by cluster size.

        Args:
            sorted_clusters (list): A list of (cluster_id, count) tuples, typically sorted by count.

        Returns:
            dict: The self.cluster_author_map dictionary.
        """

        self.cluster_author_map = {}

        # Iterate through the cluster IDs (ignoring the count)
        for cluster_id, _ in sorted_clusters:
            
            # Filter self.clusters to find all authors assigned to the current cluster_id
            cluster_authors = [
                author_name
                for author_name, assigned_id in self.clusters.items()
                if assigned_id == cluster_id
            ]
            
            # Ask why do we want to decode it to ascii with replacement?

            # Sanitize author names: ensure they are strings and handle non-ASCII safely.
            # sanitized_author_names = [
            #     str(name).encode("ascii", "replace").decode("ascii")
            #     for name in cluster_authors
            # ]

            
            sanitized_author_names = [
                str(name)
                for name in cluster_authors
            ]
            
            # Store the list of sanitized names under the cluster_id
            self.cluster_author_map[cluster_id] = sanitized_author_names
        

        # Sort the cluster_author_map by cluster size in descending order

        self.cluster_author_map = dict(sorted(self.cluster_author_map.items(), key=lambda item: len(item[1]), reverse=True))

                
        return self.cluster_author_map

    
    def assign_clusters_to_dataframe(self, df_authors):
        """
        Assigns pre-computed cluster IDs to a DataFrame of authors and generates
        a summary of the clustering results.

        This method maps the 'self.clusters' dictionary (Author Name -> Cluster ID) 
        onto the input DataFrame using the 'name' column, handles unclustered
        entries, and triggers reporting functions.
        Args:
            df_authors (pd.DataFrame): DataFrame containing an 'name' and 'resort' column. 
                                       This DF will be modified in place with a new 'cluster' column.

        Returns:
            dict: The original cluster dictionary (Author Name resort-> Cluster ID), self.clusters.

        Raises:
            ValueError: If 'self.clusters' (the clustering result) has not been computed yet.
        """

        print(df_authors.head())
        if self.clusters is None:
            raise ValueError("Run compute_clusters() first.")
        
        #print(self.cluster_counts)
        
        # 1. Assign Clusters: Map cluster IDs to the DataFrame
        df_authors['cluster'] = df_authors['name'].map(self.clusters)

        # 2. Check Initial Cluster Count
        total_clusters_with_unassigned = df_authors['cluster'].nunique(dropna=False)
        print(f"Total unique clusters (including unassigned) found: {total_clusters_with_unassigned}")
        
        # 3. Handle Unclustered Authors
        unclustered_df = df_authors[df_authors['cluster'].isna()]
        unclustered_names = unclustered_df['name'].to_list()

        # External check/logging for authors that were not clustered
        self.check_unclustered_membership(unclustered_names=unclustered_names)

        # 4. Finalize Clustered DataFrame
        # Create a copy with only successfully clustered rows
        df_clustered = df_authors.dropna(subset=['cluster']).copy()
        
        # Convert cluster IDs from float (due to potential NaN/dropna) to integer
        # Note: 'cluster' column in df_authors remains float if NaN rows are present
        df_clustered['cluster'] = df_clustered['cluster'].astype(int)

        # 5. Final Cluster Metrics
        final_num_clusters = df_clustered['cluster'].nunique()
        print(f"Final number of unique clusters analyzed: {final_num_clusters}")

        num_clustered_authors = df_clustered['name'].nunique()
        print(f"Number of clustered unique authors: {num_clustered_authors}")
        print("\nClustered DataFrame Info:")
        print(df_clustered.info())

        # 6. Generate Summary and Reports
        # 'a' contains cluster summary data (e.g., counts per cluster/resort)
        cluster_summary_data = self.get_resort_counts_per_cluster(df_clustered=df_clustered)

        # Print/Format the results using internal methods
        self.format_cluster_summary(data=cluster_summary_data)
        self.print_detailed_counts(data=cluster_summary_data)

        #print(self.cluster_author_map)


        

        return self.clusters
    

    def get_resort_counts_per_cluster(self, df_clustered: pd.DataFrame) -> list[dict]:
        """
        Calculates the frequency of each unique resort within each cluster and 
        returns the result as a list of dictionaries.
        """
        
        # 1. Group by 'cluster' and then by 'resort' and count the occurrences
        # This results in a Series with a MultiIndex: (cluster, resort)
        counts_series = df_clustered.groupby(['cluster', 'resort'], dropna=True).size().sort_values(ascending=False)
        
        # 2. Convert the MultiIndex Series into a list of dictionaries
        cluster_resort_counts = []
        
        # Iterate through the unique cluster IDs
        for cluster_id, group in counts_series.groupby(level=0):
            
            # 'group' is a Series containing the counts for one cluster, 
            # indexed by the resort name.
            
            # Convert the Series (index=resort, value=count) into a dictionary
            resort_dict = group.droplevel(level=0).to_dict()
            
            # Create the final dictionary entry for this cluster
            cluster_entry = {
                'cluster_id': cluster_id,
                'resort_counts': resort_dict
            }
            
            cluster_resort_counts.append(cluster_entry)
            
        return cluster_resort_counts
    

    def get_most_frequent_resort(self, counts):
        """Finds the most common resort(s), excluding nan."""
        
        # Filter out the nan key first
        valid_counts = {k: v for k, v in counts.items() if not (isinstance(k, float) and math.isnan(k))}
        
        if not valid_counts:
            return "None Defined", 0
            
        counter = Counter(valid_counts)
        most_common = counter.most_common(2) # Get top 2 in case of ties
        
        display_parts = []
        max_count = most_common[0][1]
        
        for resort, count in most_common:
            if count == max_count:
                display_parts.append(f"{resort} ({count})")
            else:
                break
                
        return ", ".join(display_parts), max_count

    def format_cluster_summary(self, data: list[dict]):
        """Calculates summary statistics and prints a markdown table."""
        summary_data = []
        
        # Identify the correct key for NaN (the float NaN object)
        nan_key = float('nan')
        
        for entry in data:
            cluster_id = entry['cluster_id']
            counts = entry['resort_counts']
            
            # Calculate Total Authors (Sum all counts)
            total_authors = sum(counts.values())
            
            # Get count of authors with NO resort (NaN key)
            no_resort_count = counts.get(nan_key, 0)
            
            # Get most frequent defined resort
            most_frequent, max_count = self.get_most_frequent_resort(counts)

            resort_count_list = []
            
            for resort, count in counts.items():
                if isinstance(resort, float) and math.isnan(resort):
                    resort_name = "NO RESORT (NaN)"
                    continue
                resort_name = resort
                resort_count_list.append(f"{resort_name}: {count}")

            all_resort_counts_str = "; ".join(resort_count_list)

            summary_data.append({
                'Cluster ID': cluster_id,
                'Total Authors': total_authors,
                'Authors with No Resort (NaN)': no_resort_count,
                'Most Frequent Defined Resort (Count)': most_frequent,
                'Unique Defined Resorts': len(counts) - (1 if nan_key in counts else 0),
                #'All Defined Resorts (Count)': all_resort_counts_str
            })

        df_summary = pd.DataFrame(summary_data)
        
        print("## 📊 Cluster Resort Distribution Summary (n={:,})".format(df_summary['Total Authors'].sum()))
        print("----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------")
        print(df_summary.to_markdown(index=False))

    def print_detailed_counts(self, data: list[dict]):
        """Prints the full, detailed breakdown of resort counts per cluster."""
        
        print("\n## 📝 Detailed Resort Counts per Cluster")
        print("--------------------------------------")
        
        detailed_data = []
        nan_key = float('nan')
        
        for entry in data:
            cluster_id = entry['cluster_id']
            counts = entry['resort_counts']
            
            # Sort resorts within the cluster by count (descending), keeping nan last
            sorted_counts = sorted(
                counts.items(), 
                key=lambda item: (1 if (isinstance(item[0], float) and math.isnan(item[0])) else 0, -item[1])
            )
            
            for resort, count in sorted_counts:
                # Replace the float('nan') key with a readable string
                resort_name = "NO RESORT (NaN)" if (isinstance(resort, float) and math.isnan(resort)) else resort
                
                detailed_data.append({
                    'Cluster ID': cluster_id,
                    'Resort': resort_name,
                    'Count': count
                })

        df_detailed = pd.DataFrame(detailed_data)
        #print(df_detailed["Count"].sum())
        print(df_detailed.to_markdown(index=False))
    


    

    def check_unclustered_membership(self, unclustered_names):
        """Check the component membership of unclustered authors."""
        for name in unclustered_names:
            component = self.component_of_node(name)
            if component is not None:
                print(f"Author '{name}' is in a component of size {len(component)}")



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


  # Use centralities with different methods, default is graph is largest component
  python articles.py --centrality degree
  python articles.py --centrality betweenness
  python articles.py --centrality closeness
  python articles.py --centrality eigenvector

  # If clustering with different methods is used, we can caluculate centrality on different graphs, e.g., full_graph or top N clusters
  python articles.py --cluster louvain --centrality degree --graph full_graph
  python articles.py --cluster louvain --centrality degree --graph largest_cluster
  python articles.py --cluster louvain --centrality degree --graph 3

 
  
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
        "--centrality",
        type=str,
        nargs="?",
        default=None,
        const = "degree",
        choices=[
        "degree",
        "betweenness",
        "closeness",
        "eigenvector",
    ],
        help="Perform centrality analysis. Specify one or more measures (space-separated): degree, betweenness, closeness, eigenvector. By default, all are computed.",
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

    parser.add_argument(
        "--graph",
        type=str,
        nargs="?",
        default="full_graph",
        help="Specify which graph cluster to analyze. Options: 'full_graph', 'largest_cluster', or a **positive integer N** to analyze the top N largest clusters (e.g., '--graph 3'). Defaults to analyzing entire full graph.",
    )

    args = parser.parse_args()

    visualizer = GraphVisualizer()
    authors = AuthorsBuilder()
    


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
                #print(authors.df.head())
                builder.assign_clusters_to_dataframe(df_authors=authors.load_data(limit=10000))
                #print(builder.clusters)
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
        if args.centrality is not None:

            centrality_method = (
                args.centrality
            )
            print(f"\nPerforming centrality analysis using method: {centrality_method}")
            subgraphs = []
            if args.graph is not None:
                if args.graph == "full_graph" or args.cluster is None:
                    G_centrality = builder.get_largest_component_graph()
                    subgraphs.append(G_centrality)
                elif args.graph == "largest_cluster":
                    # G_centrality will be the subgraph of the authors in the largest cluster (list(values())[0])
                    G_centrality =  builder.G.subgraph(list(builder.cluster_author_map.values())[0]).copy()
                    subgraphs.append(G_centrality)
                else:
                    try:
                        n_clusters = int(args.graph)
                        if n_clusters <= 0:
                            raise ValueError
                        # Get top N clusters
                        for graph in list(builder.cluster_author_map.values())[:n_clusters]:
                            G_centrality = builder.G.subgraph(graph).copy()
                            subgraphs.append(G_centrality)
                    except ValueError:
                        print(f"Invalid value for --graph: {args.graph}. Must be 'full_graph', 'largest_cluster', or a positive integer.")
                        sys.exit(1)
            for G_centrality in subgraphs:
                centalities = CentralityAnalysis(G_centrality)
                try:
                    if centrality_method == "degree":
                        centalities.compute_degree_centrality()
                    elif centrality_method == "betweenness":
                        centalities.compute_betweenness_centrality()
                    elif centrality_method == "closeness":
                        centalities.compute_closeness_centrality()
                    elif centrality_method == "eigenvector":
                        centalities.compute_eigenvector_centrality()
                    else:
                        print(f"Unknown centrality method: {centrality_method}. Skipping.")
                        continue
                except Exception as e:
                    print(f"Error during centrality computation: {e}")
                    print("Skipping centrality computation.")

                for measure_name, measures in centalities.centrality_measures.items():
                    print(f"\nTop 10 nodes by {measure_name} centrality:")
                    sorted_measures = sorted(
                        measures.items(), key=lambda x: x[1], reverse=True
                    )[:10]
                    for node, value in sorted_measures:
                        print(f"  {node}: {value:.4f}")

                    # Visualize centrality
                    visualizer.visualize_existing_graph_interactive(
                        G_centrality,
                        show_names=True,
                        measure_name=measure_name,
                        centrality_measures=measures,
                    )
                
                


    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
