import argparse
import sys
from typing import List, Optional, Dict, Any
import networkx as nx
import logging

# Assuming these classes are implemented in separate files as suggested by the imports
from visualizer import GraphVisualizer
from centralities import CentralityAnalysis
from article_graph_builder import ArticleGraphBuilder
from analyser import ArticleAnalyser
from authors import AuthorsBuilder



class NetworkAnalysisCLI:
    """
    Command Line Interface for building and analyzing a multilayer article-author network.
    
    It combines arguments for multilayer construction (layers, combine, export) 
    with traditional graph analysis (cluster, centrality, component analysis) applied 
    to the combined graph.
    """

    def __init__(self):
        self.parser = self._setup_parser()
        self.visualizer = GraphVisualizer()
        self.article_builder = ArticleGraphBuilder()
        self.authors_builder = AuthorsBuilder()
        self.analyser = None # Initialized after graph is built

    def _setup_parser(self):
        """
        Sets up the unified argument parser containing both single-layer and 
        multilayer options.
        """
        parser = argparse.ArgumentParser(
            description="Build a multilayer author network with separate co-author and related-article layers, and perform graph analysis.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Build default multilayer network and analyze the combined view (default)
  python main.py --limit 1000
  
  # Build only the related-article layer and visualize it
  python main.py --layers related --visualize --visualize-target related
  
  # Combine layers using 'max' weight, export all layers, then cluster and run centrality on the combined graph
  python main.py --combine-mode max --export network.gexf --export-layers --cluster leiden --centrality betweenness
  
  # Analyze a specific author's component in the combined graph
  python main.py --author "Eric Gujer"
            """,
        )

        # --- Multilayer Arguments ---
        
        parser.add_argument("--limit", type=int, default=None, help="Limit number of articles to load from the database.")
        
        parser.add_argument(
            "--layers",
            nargs="+",
            choices=["coauthor", "related"],
            default=["coauthor", "related"],
            help="Specify which multilayer structure layers to construct (coauthor, related).",
        )
        
        parser.add_argument(
            "--combine-mode",
            choices=["sum", "max"],
            default="sum",
            help="How to merge weights across layers when building the combined view (if both layers exist).",
        )
        
        parser.add_argument("--export", type=str, default=None, help="Optional path to export the combined graph to GEXF.")
        
        parser.add_argument(
            "--export-layers",
            action="store_true",
            help="When provided with --export, also export each individual layer.",
        )
        
        parser.add_argument(
            "--visualize-target",
            choices=["coauthor", "related", "combined"],
            default="combined",
            help="Which layer/graph to visualize when --visualize is enabled.",
        )
        
        parser.add_argument(
            "--visualize-weight-threshold",
            type=float,
            default=0.0,
            help="Minimum edge weight required to display an edge in the visualization.",
        )
        
        parser.add_argument(
            "--run-baseline",
            action="store_true",
            help="Also generate the three-layer degree-preserving random baseline.",
        )
        
        # --- Single-Layer/Analysis Arguments (Applied to Combined Graph) ---
        
        # Handle --visualize / --no-visualize
        visualize_group = parser.add_mutually_exclusive_group()
        visualize_group.add_argument(
            "--visualize", action="store_true", default=False, help="Show interactive visualization."
        )
        visualize_group.add_argument(
            "--no-visualize", dest="visualize", action="store_false", help="Skip interactive visualization"
        )
        
        # Handle --analyze / --no-analyze
        analyze_group = parser.add_mutually_exclusive_group()
        analyze_group.add_argument(
            "--analyze", action="store_true", default=True, help="Run general graph analysis (components, degree, etc.) (default: True)",
        )
        analyze_group.add_argument(
            "--no-analyze", dest="analyze", action="store_false", help="Skip general graph analysis"
        )

        parser.add_argument("--author", type=str, default=None, help="Analyze specific author.")
        
        parser.add_argument(
            "--centrality", nargs="?", default=None, const="degree",
            choices=["degree", "betweenness", "closeness", "eigenvector"],
            help="Perform centrality analysis on the target graph (default: degree).",
        )

        parser.add_argument(
            "--cluster", nargs="?", const="louvain", default=None,
            choices=["louvain", "leiden", "greedy_modularity", "label_propagation", "asyn_lpa"],
            help="Perform community clustering analysis on the target graph (default: louvain).",
        )

        parser.add_argument(
            "--graph", nargs="?", default="largest_component", 
            help="Which graph component to analyze for centrality/clustering (e.g., 'largest_cluster' or integer N). Defaults to 'largest_component' of the combined view.",
        )
        
        # Note: The original `--save` argument is merged into the `--export` argument for file saving consistency.
        
        return parser

    def parse_args(self) -> argparse.Namespace:
        """Parses the arguments and returns the resulting namespace."""
        return self.parser.parse_args()

    # --- Analysis Helpers (Adapted from single-layer logic) ---
    
    def _get_analysis_graph(self, args):
        """Returns the appropriate graph object for clustering/centrality analysis."""
        # When clustering or centrality is run, it should apply to the combined view,
        # but the logic for which subgraph to analyze still comes from the old CLI.
        
        # 1. Use the Analyser based on the Combined Graph
        G_target = self.analyser.G # This should be the combined graph or its largest component
        
        # 2. Apply subgraph logic
        subgraphs = []
        graph_target = args.graph
        print(graph_target)
        
        if graph_target == "largest_component" or args.cluster is None:
            subgraphs.append(self.analyser.get_largest_component_graph())
        elif graph_target == "largest_cluster" and self.analyser.cluster_author_map:
            largest_cluster_nodes = list(self.analyser.cluster_author_map.values())[0]
            # Mock subgraph extraction
            print(len(largest_cluster_nodes))
            G_centrality = {'name': 'largest_cluster', 'is_mock': True, 'G': G_target}
            subgraphs.append(G_centrality)
        else:
            try:
                n_clusters = int(graph_target)
                if n_clusters > 0 and self.analyser.cluster_author_map:
                    for i in range(min(n_clusters, len(self.analyser.cluster_author_map))):
                        # Mock subgraph extraction
                        G_centrality = {'name': f'top_{i+1}_cluster', 'is_mock': True, 'G': G_target}
                        subgraphs.append(G_centrality)
            except ValueError:
                print(f"Invalid value for --graph: {args.graph}. Must be 'largest_component', 'largest_cluster', or a positive integer.")
                sys.exit(1)
                
        return subgraphs

    def _get_graph_label(self, args, index):
        """Generates a descriptive label for the analyzed subgraph."""
        if args.graph == "largest_component" or args.cluster is None: return "Largest Component"
        if args.graph == "largest_cluster": return "Largest Cluster"
        if args.graph.isdigit(): return f"Top {index + 1} Cluster"
        return "Unknown Subgraph"

    def _run_clustering(self, args, G_base):
        """Computes community clusters on the base graph."""
        cluster_method = args.cluster
        print(f"\nPerforming clustering using method: {cluster_method} on the combined graph.")
        try:
            self.analyser.compute_clusters(method=cluster_method)
            df_authors = self.authors_builder.load_data(limit=10000) 
            self.analyser.assign_clusters_to_dataframe(df_authors=df_authors)
        except Exception as e:
            print(f"Error during clustering: {e}\nSkipping clustering.")
        
        return self.analyser.clusters
    
    def _run_centrality(self, args, cluster_colors):
        """Computes and visualizes centrality measures."""
        centrality_method = args.centrality
        print(f"\nPerforming centrality analysis using method: {centrality_method}")
        
        subgraphs_to_analyze = self._get_analysis_graph(args)
        
        for i, G_centrality_package in enumerate(subgraphs_to_analyze): # Renamed to G_centrality_package
            graph_label = self._get_graph_label(args, i)
            print(f"\n--- Analyzing Graph: {graph_label} ---")
            
            # **FIX: Extract the actual NetworkX graph object**
            G_centrality_nx = G_centrality_package.get('G', G_centrality_package)
            
            # 1. Run Centrality Analysis (requires NX graph)
            centalities = CentralityAnalysis(G_centrality_nx) 
            
            # ... (Centrality calculation logic) ...
            try:
                if centrality_method == "degree": centalities.compute_degree_centrality()
                # ... (other methods) ...
            except Exception as e:
                print(f"Error during centrality computation on {graph_label}: {e}")
                continue

            for measure_name, measures in centalities.centrality_measures.items():
                print(f"\nTop nodes by {measure_name} centrality on {graph_label}: {list(measures.keys())[:2]}...")
                
                # 2. Visualize centrality (requires NX graph)
                # If your visualizer is simple, it expects the NX graph.
                # If it's complex and needs metadata (like name/is_mock) from the package, 
                # you must adapt the visualizer OR ensure you pass the NX object.
                
                # Assuming your visualizer expects a NetworkX graph for plotting (G_centrality_nx):
                self.visualizer.visualize_existing_graph_interactive(
                    G_centrality_nx,  # <-- Pass the extracted NetworkX graph
                    show_names=True, 
                    cluster_colors=cluster_colors,
                    measure_name=measure_name, 
                    centrality_measures=measures,
                )

    def run(self):
        """
        Parses arguments and runs the network analysis workflow.
        """
        args = self.parse_args()
        
        try:
            print("=" * 80)
            print("Starting Network Analysis (Multilayer Build + Analysis)")
            print("=" * 80)

            # 1. Load Data
            self.article_builder.load_data(limit=args.limit)

            # 2. Build Multilayer Structure and Combined Graph
            # Check if all required layers are specified
            all_layers_required = len(args.layers) == 2 and "coauthor" in args.layers and "related" in args.layers
            
            # The builder's method combines loading, mapping, building layers, and combining.
            # We call it once to get the necessary graphs.
            print("\n--- Building Empirical Multilayer Network ---")
            
            # Check if the MultiLayerAuthorGraph dependency is satisfied
            try:
                # Assuming MultiLayerAuthorGraph is a class used internally by ArticleGraphBuilder
                layers, G_combined_weighted = self.article_builder.build_empirical_multilayer(
                    limit=args.limit, # Limit is passed but self.article_builder should handle data only once
                    combine_mode=args.combine_mode, 
                    run_load_data=False # Data is already loaded by self.article_builder.load_data()
                )
                
                # Store the built layers on the builder for export/visualization purposes
                self.article_builder.graphs = layers
                self.article_builder.combined_graph = G_combined_weighted

            except NameError as e:
                print(f"FATAL ERROR: {e}. Cannot proceed with multilayer analysis.")
                return

            # If only a subset of layers was requested, the combined graph might not be the right target.
            # We need a unified graph (unweighted) for centrality/clustering.
            # The 'G_combined_weighted' from the builder is the combined weighted graph.
            # We need to explicitly create an unweighted base graph for component analysis.

            # Get the base graph (unweighted) for component analysis
            # We assume ArticleAnalyser works best on the largest component of an UNWEIGHTED combined graph.
            # We'll use the combined weighted graph and create an unweighted version for the analyser.
            G_combined = nx.Graph(G_combined_weighted) # Removes edge weights if passed to Analyser

            # Initialize Analyser with the combined/base graph
            self.analyser = ArticleAnalyser(G_combined)
            
            # Store necessary state for helpers/analyser
            self.analyser.G = G_combined
            self.analyser.cluster_author_map = self.article_builder.cluster_author_map # Used by _get_analysis_graph

            # 4. Run Baseline
            if args.run_baseline:
                self.article_builder.run_baseline()
            
            # 5. Export Graphs
            if args.export:
                # Export combined graph
                if G_combined:
                    self.analyser.save_graph_to_gexf(args.export, G_combined_weighted) # Export weighted graph
                
                if args.export_layers:
                    # Export individual layers
                    for name, graph in self.article_builder.graphs.items():
                        layer_path = args.export.replace(".gexf", f"_{name}.gexf")
                        self.analyser.save_graph_to_gexf(layer_path, graph)

            # 6. Run General Analysis (on the unweighted combined graph)
            if args.analyze:
                self.analyser.analyze_components()
                self.analyser.highest_degree_node()
                G_largest_component = self.analyser.get_largest_component_graph()
                
                # df is stored on the builder, pass it to the analyser's method
                print(self.analyser.authors_to_category_mapping(G=G_largest_component, df=self.article_builder.df))
                
                author_to_analyze = args.author if args.author else "Eric Gujer"
                self.analyser.component_of_node(author_to_analyze)
                self.analyser.degree_of_author(author_to_analyze)
                self.analyser.nodes_not_in_largest()
            
            # 7. Clustering
            cluster_colors = None
            if args.cluster is not None:
                cluster_colors = self._run_clustering(args, G_combined) # Run clustering on the unweighted combined graph

            # 8. Centrality
            if args.centrality is not None:
                self._run_centrality(args, cluster_colors)

            # 9. Visualization (Final step)
            if args.visualize:
                # Use the appropriate graph object (weighted or unweighted is determined by the Visualizer/Target choice)
                G_target = self.article_builder.graphs.get(args.visualize_target) or self.article_builder.combined_graph
                
                if not G_target:
                    print(f"Warning: Cannot visualize target '{args.visualize_target}'. Graph not built.")
                    return
                
                # If visualizing the combined graph after clustering, use cluster colors
                vis_cluster_colors = cluster_colors if args.visualize_target == "combined" else None
                
                self.visualizer.visualize_existing_graph_interactive(
                    G_target, show_names=True, 
                    weight_threshold=args.visualize_weight_threshold,
                    cluster_colors=vis_cluster_colors,
                )

        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            sys.exit(0)
        except Exception as e:
            print(f"\n\nAn unexpected error occurred: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    cli = NetworkAnalysisCLI()
    cli.run()