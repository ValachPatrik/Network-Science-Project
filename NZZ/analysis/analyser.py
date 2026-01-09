import os
import ast
import sys
import argparse
import pandas as pd
import networkx as nx
import logging
from difflib import get_close_matches
from collections import defaultdict, Counter
from dotenv import load_dotenv
import math


    # when executed as scripts without package context (assuming local files)
from visualizer import GraphVisualizer
from authors import AuthorsBuilder
from centralities import CentralityAnalysis
from article_graph_builder import ArticleGraphBuilder
from multilayer_network import MultiLayerAuthorGraph
from impressum_parser import NZZParser

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ArticleAnalyser")


# External library checks (Kept as is, they are crucial for functionality)
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

class ArticleReporter:
    """Handles the creation and formatting of analysis reports, 
    especially for cluster and article section/category distribution."""

    def __init__(self, clusters: dict = None):
        """Initializes the reporter with clustering results."""
        self.clusters = clusters
        self.nan_key = float("nan")

    def _get_most_frequent_section(self, counts: dict):
        """Finds the most common section(s), excluding the NaN key."""

        # Filter out the nan key first
        valid_counts = {
            k: v
            for k, v in counts.items()
            if not (isinstance(k, float) and math.isnan(k))
        }

        if not valid_counts:
            return "None Defined", 0

        counter = Counter(valid_counts)
        most_common = counter.most_common(2)  # Get top 2 in case of ties

        display_parts = []
        max_count = most_common[0][1]

        for section, count in most_common:
            if count == max_count:
                display_parts.append(f"{section} ({count})")
            else:
                break

        return ", ".join(display_parts), max_count

    def get_section_counts_per_cluster(self, df_clustered: pd.DataFrame) -> list[dict]:
        """
        Calculates the frequency of each unique article section within each cluster and
        returns the result as a list of dictionaries.
        """
        # Ensure 'cluster' column is present and valid
        if 'cluster' not in df_clustered.columns:
            logger.error("DataFrame must contain a 'cluster' column.")
            return []
        
        # 1. Group by 'cluster' and then by 'Resort' (renamed to 'Section') and count the occurrences
        # This results in a Series with a MultiIndex: (cluster, Section)
        counts_series = (
            df_clustered.groupby(["cluster", "Resort"], dropna=True)
            .size()
            .sort_values(ascending=False)
        )

        # 2. Convert the MultiIndex Series into a list of dictionaries
        cluster_section_counts = []

        # Iterate through the unique cluster IDs
        for cluster_id, group in counts_series.groupby(level=0):

            # 'group' is a Series containing the counts for one cluster,
            # indexed by the section name.
            
            # Convert the Series (index=Section, value=count) into a dictionary
            section_dict = group.droplevel(level=0).to_dict()

            # Create the final dictionary entry for this cluster
            cluster_entry = {"cluster_id": cluster_id, "section_counts": section_dict}

            cluster_section_counts.append(cluster_entry)

        return cluster_section_counts

    def format_cluster_summary(self, cluster_section_data: list[dict]):
        """Calculates summary statistics and prints a markdown table."""
        summary_data = []

        for entry in cluster_section_data:
            cluster_id = entry["cluster_id"]
            counts = entry["section_counts"]

            # Calculate Total Authors (Sum all counts)
            total_authors = sum(counts.values())

            # Get count of authors with NO section (NaN key)
            no_section_count = counts.get(self.nan_key, 0)

            # Get most frequent defined section
            most_frequent, max_count = self._get_most_frequent_section(counts)

            summary_data.append(
                {
                    "Cluster ID": cluster_id,
                    "Total Authors": total_authors,
                    "Authors with No Section (NaN)": no_section_count,
                    "Most Frequent Defined Section (Count)": most_frequent,
                    "Unique Defined Sections": len(counts)
                    - (1 if self.nan_key in counts else 0),
                }
            )

        df_summary = pd.DataFrame(summary_data)
        print("\n")
        print(
            "## 📊 Cluster Section Distribution Summary (n={:,})".format(
                df_summary["Total Authors"].sum()
            )
        )
        print("-" * 150)
        print(df_summary.to_markdown(index=False))

        return df_summary

    def print_detailed_counts(self, cluster_section_data: list[dict]) -> pd.DataFrame:
        """Full, detailed breakdown of section counts per cluster and returns the DataFrame."""


        detailed_data = []

        for entry in cluster_section_data:
            cluster_id = entry["cluster_id"]
            counts = entry["section_counts"]

            # Sort sections within the cluster by count (descending), keeping nan last
            sorted_counts = sorted(
                counts.items(),
                key=lambda item: (
                    1 if (isinstance(item[0], float) and math.isnan(item[0])) else 0,
                    -item[1],
                ),
            )

            for section, count in sorted_counts:
                # Replace the float('nan') key with a readable string
                section_name = (
                    "NO RESORT (NaN)"
                    if (isinstance(section, float) and math.isnan(section))
                    else section
                )

                detailed_data.append(
                    {"Cluster ID": cluster_id, "Resort": section_name, "Count": count}
                )

        df_detailed = pd.DataFrame(detailed_data)
        return df_detailed


class ArticleAnalyser:
    """Loads NZZ article data, builds a graph, and performs graph analysis."""

    def __init__(self, G: nx.Graph = nx.Graph()):
        """Initialize ArticleGraphBuilder with a NetworkX graph."""

        self.df = None
        self.G = G
        self.components_sorted = None
        self.clusters = None  # Mapping: Node -> Cluster ID
        self.cluster_counts = {} # Mapping: Cluster ID -> Node Count
        self.cluster_author_map = {} # Mapping: Cluster ID -> List[Author Names]

        self.raw_data_categories = {} # Mapping: Author -> {Category: Count}
        self.reporter = ArticleReporter() # Initialize the new reporter

    def _normalize_authors(self, author_field):
        """
        Convert author field into a list of authors.
        Handles your format: '["Alain Zucker", "Martin Berz"]'
        """
        if pd.isna(author_field):
            return []

        if isinstance(author_field, list):
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

    # === 3. Analyze connected components ===
    def analyze_components(self):
        """Compute connected components sorted by size."""
        if not self.G.nodes:
            logger.warning("Graph is empty. Cannot analyze components.")
            return []

        components = list(nx.connected_components(self.G))
        self.components_sorted = sorted(components, key=len, reverse=True)

        print("Graph connected?", nx.is_connected(self.G))
        print("Number of components:", len(self.components_sorted))
        for i, comp in enumerate(self.components_sorted, 1):
            comp_size = len(comp)
            # Use safe string conversion for display
            sample_nodes = [str(node) for node in list(comp)[:5]]
            sample_str = ", ".join(sample_nodes)
            if comp_size > 5:
                sample_str += f", ... ({comp_size - 5} more)"
            print(f"Component {i} (size {comp_size}): {sample_str}")
        
        return self.components_sorted

    def highest_degree_node(self):
        """Return node with the most edges."""
        if not self.G.degree:
            return None, 0
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

    def nodes_not_in_largest(self):
        """Return all nodes not in the largest connected component."""
        if self.components_sorted is None:
            raise ValueError("Run analyze_components() first.")

        largest = self.components_sorted[0]
        all_nodes = set(self.G.nodes)

        excluded = all_nodes - largest
        print(f"Nodes not in largest component: {len(excluded)}")
        return excluded

    def save_graph_to_gexf(
        self, filename="authors_graph.gexf", graph: nx.Graph | None = None
    ):
        """Save a NetworkX graph to a GEXF file."""
        target = graph if graph is not None else self.G
        nx.write_gexf(target, filename)
        print(f"Graph successfully saved to {filename}")

    def get_largest_component_graph(self):
        """Return a subgraph of the largest connected component."""
        if self.components_sorted is None:
            self.analyze_components() # Ensure components are computed
        
        if not self.components_sorted:
            return nx.Graph()

        largest_component = self.components_sorted[0]
        G_largest = self.G.subgraph(largest_component).copy()
        return G_largest

    def compute_clusters(self, method="louvain"):
        """Compute community clusters using specified algorithm.
        
        This method is cleaned up and only focuses on the graph algorithm.
        """
        if len(self.G.nodes()) == 0:
            logger.warning("Graph is empty. Cannot compute clusters.")
            return {}, {}

        # Use the largest component for clustering if graph is disconnected
        if not nx.is_connected(self.G):
            print("Graph is disconnected. Computing clusters on largest component...")
            G_cluster = self.get_largest_component_graph()
        else:
            G_cluster = self.G
        
        if len(G_cluster.nodes) < 2:
            logger.warning("Largest component is too small for clustering.")
            return {}, {}

        print(f"\nComputing clusters using {method} algorithm...")

        partition = {}

        if method == "louvain":
            if not HAS_COMMUNITY:
                raise ImportError(
                    "python-louvain is required for Louvain clustering. Install with: pip install python-louvain"
                )
            partition = community_louvain.best_partition(G_cluster, weight="weight", random_state=42)

        elif method == "leiden":
            if not HAS_IGRAPH:
                print(
                    "Warning: igraph not available. Falling back to Louvain algorithm."
                )
                if not HAS_COMMUNITY:
                    raise ImportError(
                        "Neither igraph nor python-louvain available. Install with: pip install python-igraph or pip install python-louvain"
                    )
                partition = community_louvain.best_partition(G_cluster, weight="weight", random_state=42)
            else:
                # Igrah conversion logic (kept as is, it's efficient)
                node_list = list(G_cluster.nodes())
                node_to_idx = {node: idx for idx, node in enumerate(node_list)}
                edges = [(node_to_idx[u], node_to_idx[v]) for u, v in G_cluster.edges()]
                weights = [
                    G_cluster[u][v].get("weight", 1) for u, v in G_cluster.edges()
                ]
                g_ig = ig.Graph(edges, edge_attrs={"weight": weights})
                leiden_partition = g_ig.community_leiden(
                    weights="weight", resolution_parameter=1.0
                )
                for idx, cluster_id in enumerate(leiden_partition.membership):
                    partition[node_list[idx]] = cluster_id

        elif method == "greedy_modularity":
            communities = nx.community.greedy_modularity_communities(
                G_cluster, weight="weight", random_state=42
            )
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id

        elif method == "label_propagation":
            communities = nx.community.label_propagation_communities(G_cluster)
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id

        elif method == "asyn_lpa":
            communities = nx.community.asyn_lpa_communities(G_cluster, weight="weight")
            for cluster_id, community in enumerate(communities):
                for node in community:
                    partition[node] = cluster_id

        else:
            raise ValueError(
                f"Unknown clustering method: {method}."
            )

        # Extend partition to all nodes (nodes not in largest component get cluster -1)
        self.clusters = {}
        self.cluster_counts = {}
        for node in self.G.nodes():
            cluster_id = partition.get(node, -1)
            self.clusters[node] = cluster_id
            self.cluster_counts[cluster_id] = self.cluster_counts.get(cluster_id, 0) + 1


        # Print cluster statistics
        print(f"\nClustering Results ({method}):")
        # Filter for actual clusters (ID >= 0)
        actual_clusters = {cid: count for cid, count in self.cluster_counts.items() if cid >= 0}

        print(
            f"Number of clusters: {len(actual_clusters)}"
        )
        print(
            f"Nodes in largest component: {sum(actual_clusters.values())}"
        )

        # Calculate modularity if possible
        try:
            if method in ["louvain", "leiden", "greedy_modularity"]:
                communities_list = [
                    [n for n, c in self.clusters.items() if c == cid]
                    for cid in actual_clusters.keys()
                ]

                if communities_list:
                    # Note: Modularity should be calculated on the graph that was clustered (G_cluster)
                    modularity = nx.community.modularity(
                        G_cluster, communities_list, weight="weight"
                    )
                    print(f"Modularity: {modularity:.4f}")
        except Exception as e:
            logger.error(f"Could not calculate modularity: {e}")

        # Show top clusters by size and build the map
        sorted_clusters = sorted(
            [(cid, count) for cid, count in actual_clusters.items()],
            key=lambda x: x[1],
            reverse=True,
        )

        self._build_cluster_author_map(sorted_clusters=sorted_clusters)

        print("\nTop 10 clusters by size:")
        for i, (cluster_id, count) in enumerate(sorted_clusters[:10], 1):
            sample_names = [str(n) for n in self.cluster_author_map[cluster_id][:3]]
            sample_str = ", ".join(sample_names)
            if count > 3:
                sample_str += f", ... ({count - 3} more)"
            print(f"  Cluster {cluster_id} (size {count}): {sample_str}")

        return self.clusters, self.cluster_counts

    def _build_cluster_author_map(self, sorted_clusters: list):
        """
        Creates a dictionary mapping each cluster ID to a list of author names belonging to that cluster, 
        using the provided sorted list to ensure the map is ordered by size.
        (Renamed and simplified)
        """
        self.cluster_author_map = {}
        
        for cluster_id, _ in sorted_clusters:
            # Filter self.clusters to find all authors assigned to the current cluster_id
            cluster_authors = [
                author_name
                for author_name, assigned_id in self.clusters.items()
                if assigned_id == cluster_id
            ]

            # Store the list of names (no unnecessary encoding/decoding)
            self.cluster_author_map[cluster_id] = [str(name) for name in cluster_authors]

        # Since sorted_clusters is already sorted by size, the dictionary iteration order 
        # (in modern Python) will maintain this. No need for re-sorting here.
        return self.cluster_author_map


    def assign_clusters_to_dataframe(self, df_authors: pd.DataFrame):
        """Main entry point to assign clusters and generate reports."""
        if self.clusters is None:
            raise ValueError("Run compute_clusters() first.")
        
        # 1. Map data
        df_clustered = self._prepare_clustered_dataframe(df_authors)

        # 2. Log Metrics
        self._log_cluster_metrics(df_authors, df_clustered)

        # 3. Delegate to Reporter
        return self._generate_cluster_reports(df_clustered)

    def _prepare_clustered_dataframe(self, df_authors: pd.DataFrame) -> pd.DataFrame:
        """Handles the mapping and type conversion of the cluster data."""
        df_authors["cluster"] = df_authors["Author"].map(self.clusters)
        
        # Drop unassigned authors and convert cluster ID to int
        df_clustered = df_authors.dropna(subset=["cluster"]).copy()
        df_clustered["cluster"] = df_clustered["cluster"].astype(int)
        
        return df_clustered

    def _log_cluster_metrics(self, df_original: pd.DataFrame, df_clustered: pd.DataFrame):
        """Handles all print and logger statements regarding data shape."""
        total_initial = df_original["cluster"].nunique(dropna=False)
        final_clusters = df_clustered["cluster"].nunique()
        num_authors = df_clustered["Author"].nunique()

        print(f"Total unique clusters (including unassigned) found: {total_initial}")
        print(f"Final number of unique clusters analyzed: {final_clusters}")
        print(f"Number of clustered unique authors: {num_authors}")
        

    def _generate_cluster_reports(self, df_clustered: pd.DataFrame):
        """Delegates the heavy lifting to the ArticleReporter."""
        self.reporter.clusters = self.clusters
        
        cluster_section_data = self.reporter.get_section_counts_per_cluster(
            df_clustered=df_clustered
        )

        self.reporter.format_cluster_summary(cluster_section_data)
        
        return cluster_section_data
    
    def authors_to_category_mapping(self, G: nx.Graph, df: pd.DataFrame) -> dict:
        """
        Creates a mapping of authors to their article sections/categories based on the provided DataFrame.
        """
        author_category_counts = defaultdict(lambda: defaultdict(int))

        for _, row in df.iterrows():
            author_name_list = self._normalize_authors(row["authors"])
            category = row["category"]

            for author_name in author_name_list:

                if author_name in G.nodes:
                    author_category_counts[author_name][category] += 1
        
        self.raw_data_categories = dict(author_category_counts)
        return self.raw_data_categories

    def create_author_section_table(self, sort_by: list = ['Author', 'Count'], ascending: list = [True, False]) -> pd.DataFrame:
        """
        Flattens the nested data, creates a DataFrame, sorts it, and returns the result.
        (Renamed 'Resort' to 'Section' in the logic, but the DF column name 'Resort' is maintained 
         to match the input expectation of `assign_clusters_to_dataframe` from `df_table`).
        """
        records = []
        for author, sections in self.raw_data_categories.items():
            for section, count in sections.items():
                section_name = 'Unspecified' if section is None else section
                # Note: Keeping 'Resort' as column name here to match original usage pattern with assign_clusters_to_dataframe
                records.append({'Author': author, 'Resort': section_name, 'Count': count}) 

        df = pd.DataFrame(records)
        df_sorted = df.sort_values(by=sort_by, ascending=ascending).reset_index(drop=True)
        return df_sorted
    
    def highest_count_section_per_author(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Finds the section with the highest count for each author.
        """
        if df.empty:
            return pd.DataFrame()
            
        # Find the index of the row with the maximum 'Count' for each 'Author'
        idx_max = df.groupby(['Author'])['Count'].idxmax()
        
        # Select the corresponding rows and sort by 'Author'
        result_df = df.loc[idx_max].sort_values(by='Author').reset_index(drop=True)
        
        return result_df

    def _get_role_from_map(self, name, role_map):
        if not role_map:
            return "Unknown"
        if name in role_map:
            if isinstance(role_map[name], list):
                return ", ".join(role_map[name])
            return role_map[name]
        match = get_close_matches(name, role_map.keys(), n=1, cutoff=0.85)
        return ", ".join(role_map[match[0]]) if match else "Unknown"

    def add_team_roles(self, df: pd.DataFrame, role_map: dict) -> pd.DataFrame:
        """
        Adds a 'Role' column to the DataFrame based on the provided role mapping.
        """
        if df.empty:
            return df

        df['Role'] = df['Author'].apply(lambda name: self._get_role_from_map(name, role_map))
        return df
    
def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build and analyze article-author networks from NZZ database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    Examples:
  # Build and analyze the graph
  python analyser.py
  
  # Limit to 1000 articles and save to GEXF
  python analyser.py --limit 1000 --save graph.gexf
  
  # Visualize the graph interactively
  python analyser.py --visualize
  
  # Use clustering with different methods
  python analyser.py --cluster louvain
  python analyser.py --cluster leiden
  python analyser.py --cluster greedy_modularity
  python analyser.py --cluster label_propagation
  python analyser.py --cluster asyn_lpa


  # Use centralities with different methods, default is graph is largest component
  python analyser.py --centrality degree
  python analyser.py --centrality betweenness
  python analyser.py --centrality closeness
  python analyser.py --centrality eigenvector

  # If clustering with different methods is used, we can caluculate centrality on different graphs, e.g., full_graph or top N clusters
  python analyser.py --cluster louvain --centrality degree --graph full_graph
  python analyser.py --cluster louvain --centrality degree --graph largest_cluster
  python analyser.py --cluster louvain --centrality degree --graph 3

 
  
  # Combine clustering with visualization
  python analyser.py --cluster leiden --visualize
  
  # Analyze specific author
  python analyser.py --author "Eric Gujer"
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
        "--largest-component",
        action="store_true",
        default =True,
        help="Restrict analysis to the largest connected component.",
    )

    parser.add_argument(
        "--no-largest-component",
        dest="largest_component",
        action="store_false",
        help="Use the full graph for analysis.",)
    

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
        nargs="+",
        default=None,
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

    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of top authors to display per measure.",
    )

    parser.add_argument(
        "--impressum",
        type=str,
        default="NZZ/analysis/nzz_impressum.csv",
        help="Path to the NZZ Impressum CSV file.",
    )

    parser.add_argument(
        "--show-names",
        action="store_true",
        default=True,
        help="Show node labels in the visualization viewport.",
    )
    

    

    parser.add_argument(
        "--no-show-names",
        dest="show_names",
        action="store_false",
        help="Hide node labels in the visualization viewport.",
    )

    return parser.parse_args()

def main():

    args = parse_args()

    # Assuming these classes exist as per imports
    visualizer = GraphVisualizer()
    impressum_parser = NZZParser(args.impressum)


    try:
        print("=" * 80)
        print("Using ArticleGraphBuilder")
        print("=" * 80)

        data_builder = ArticleGraphBuilder()
        data_builder.load_data(limit=args.limit)
        data_builder.build_author_map()

        multilayer = MultiLayerAuthorGraph()
        coauthor_graph = data_builder.build_coauthor_layer()
        multilayer.add_layer("coauthor", coauthor_graph)
        related_graph = data_builder.build_related_layer()
        multilayer.add_layer("related", related_graph)
        combined_graph = multilayer.combine_layers(mode="sum")

        builder = ArticleAnalyser(G=combined_graph)
        builder.df = data_builder.df
        df_table = pd.DataFrame()
        G = builder.G.copy()
        if args.largest_component:
            G = builder.get_largest_component_graph()
        if args.analyze:
            if not args.largest_component:
                builder.analyze_components()
            
            builder.authors_to_category_mapping(
                    G=G, df=builder.df)
            
            df_table = builder.create_author_section_table()
            df_table.to_csv('author_section_counts.csv', index=False)

            # Filter to highest count section per author for summary
            df_filtered = builder.highest_count_section_per_author(df=df_table.copy())

            builder.add_team_roles(df_filtered, impressum_parser.get_dict()).to_csv('author_section_counts_with_roles.csv', index=False)



            if args.author:
                builder.component_of_node(args.author)
                builder.degree_of_author(args.author)

            builder.nodes_not_in_largest()

        # Compute clusters if requested
        cluster_colors = None
        if args.cluster is not None:
            cluster_method = args.cluster
            try:
                builder.compute_clusters(method=cluster_method)
                
                if args.analyze:


                    cluster_summary_data_filtered = builder.assign_clusters_to_dataframe(df_authors=df_filtered.copy())

                    (builder._prepare_clustered_dataframe(df_filtered)).to_csv('filtered_clustered_authors.csv', index=False)
        

                    builder.reporter.print_detailed_counts(cluster_section_data=cluster_summary_data_filtered).to_csv('filtered_cluster_resort_counts.csv', index=False)

                # Use the clusters for visualization
                cluster_colors = builder.clusters
            except ImportError as e:
                print(f"Warning: {e}")
                print("Skipping clustering.")
            except Exception as e:
                print(f"Error during clustering: {e}")
                import traceback
                traceback.print_exc()
                print("Skipping clustering.")

        if args.save:
            builder.save_graph_to_gexf(filename=args.save)

        if args.visualize:
            # Visualize the largest component by default
            if G.nodes:
                visualizer.visualize_existing_graph_interactive(
                    G,
                    show_names=args.show_names,
                    cluster_colors=cluster_colors,
                )

        # Centrality Analysis
        if args.centrality is not None:
            centrality_method = args.centrality
            print(f"\nPerforming centrality analysis using method: {centrality_method}")
            subgraphs = []
            
            # Logic to determine which subgraph(s) to analyze (based on --graph argument)
            if args.graph is not None:
                if args.graph == "full_graph" or args.cluster is None:
                    # Analyze the Largest Component
                    subgraphs.append(builder.get_largest_component_graph())
                    graph_names = ["Largest Component"]
                elif builder.clusters is None:
                    print("Clustering required for '--graph largest_cluster' or integer N.")
                    sys.exit(1)
                elif args.graph == "largest_cluster":
                    # Analyze the Largest Cluster
                    if not builder.cluster_author_map: 
                         print("Cluster map is empty. Cannot analyze largest cluster.")
                         sys.exit(1)
                    largest_cluster_nodes = list(builder.cluster_author_map.values())[0]
                    G_centrality = builder.G.subgraph(largest_cluster_nodes).copy()
                    subgraphs.append(G_centrality)
                    graph_names = ["Largest Cluster"]
                else:
                    try:
                        # Analyze top N clusters
                        n_clusters = int(args.graph)
                        if n_clusters <= 0:
                            raise ValueError
                        
                        cluster_list = list(builder.cluster_author_map.items())
                        graph_names = []
                        for cluster_id, nodes in cluster_list[:n_clusters]:
                            G_centrality = builder.G.subgraph(nodes).copy()
                            subgraphs.append(G_centrality)
                            graph_names.append(f"Cluster {cluster_id}")
                            
                    except ValueError:
                        print(
                            f"Invalid value for --graph: {args.graph}. Must be 'full_graph', 'largest_cluster', or a positive integer."
                        )
                        sys.exit(1)
            
            # Perform Centrality Calculation and Visualization
            for G_centrality, name in zip(subgraphs, graph_names):
                
                if not G_centrality.nodes:
                    print(f"Skipping centrality for '{name}': Graph is empty.")
                    continue

                centalities = CentralityAnalysis(G_centrality)
                print(f"\n--- Centrality for {name} ---")
                
                centrality_values = centalities.compute_measures(list(args.centrality))
                if not centrality_values:
                    logger.error("No centrality measures were computed; exiting.")
                    sys.exit(1)


                top_rows= {}

                for name, values in centrality_values.items():
                    
                    rows = centalities.build_rankings(values, args.top_k, impressum_parser.get_dict())
                    top_rows[name] = rows
                    centalities.print_table(name, rows)

                    if args.visualize:
                        visualizer.visualize_existing_graph_interactive(
                        G_centrality,
                        show_names=args.show_names,
                        measure_name=name,
                        centrality_measures=values,
                    )
        
                        

                centalities.summarize_hubs(top_rows, None)

                    # Visualize centrality
                    
                

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()