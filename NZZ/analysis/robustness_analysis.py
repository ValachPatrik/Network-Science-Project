"""Robustness analysis: simulate targeted hub removal and measure network impact.

This module implements targeted attack analysis to assess network vulnerability
when key hub authors are removed based on centrality measures.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Literal, Optional

import networkx as nx
from dotenv import load_dotenv

try:
    from .centralities import CentralityAnalysis
    from .article_graph_builder import ArticleGraphBuilder
    from .multilayer_network import MultiLayerAuthorGraph
except ImportError:
    from centralities import CentralityAnalysis
    from article_graph_builder import ArticleGraphBuilder
    from multilayer_network import MultiLayerAuthorGraph


CentralityMethod = Literal["degree", "betweenness", "closeness", "eigenvector"]


@dataclass
class NetworkMetrics:
    """Container for network metrics used in robustness analysis."""
    num_nodes: int
    num_edges: int
    num_components: int
    largest_component_size: int
    largest_component_fraction: float
    avg_path_length: float | None
    clustering_coefficient: float
    modularity: float | None

    def __str__(self) -> str:
        return (
            f"Nodes: {self.num_nodes}, Edges: {self.num_edges}, "
            f"Components: {self.num_components}, "
            f"Largest Component: {self.largest_component_size} ({self.largest_component_fraction:.1%}), "
            f"Avg Path Length: {self.avg_path_length or 'N/A':.3f}, "
            f"Clustering: {self.clustering_coefficient:.4f}, "
            f"Modularity: {self.modularity or 'N/A'}"
        )


def compute_metrics(G: nx.Graph) -> NetworkMetrics:
    """Compute all relevant network metrics for robustness analysis."""
    if G.number_of_nodes() == 0:
        return NetworkMetrics(
            num_nodes=0,
            num_edges=0,
            num_components=0,
            largest_component_size=0,
            largest_component_fraction=0.0,
            avg_path_length=None,
            clustering_coefficient=0.0,
            modularity=None,
        )

    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()
    
    # Connected components
    components = list(nx.connected_components(G))
    num_components = len(components)
    largest_component_size = max(len(c) for c in components) if components else 0
    largest_component_fraction = largest_component_size / num_nodes if num_nodes > 0 else 0.0

    # Average path length (only on largest component to avoid infinite distances)
    avg_path_length = None
    if largest_component_size > 1:
        largest_cc = G.subgraph(max(components, key=len)).copy()
        try:
            avg_path_length = nx.average_shortest_path_length(largest_cc)
        except nx.NetworkXError:
            avg_path_length = None

    # Clustering coefficient
    clustering_coefficient = nx.average_clustering(G)

    # Modularity (using greedy modularity communities)
    modularity = None
    if num_edges > 0:
        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = greedy_modularity_communities(G)
            modularity = nx.community.modularity(G, communities)
        except Exception:
            modularity = None

    return NetworkMetrics(
        num_nodes=num_nodes,
        num_edges=num_edges,
        num_components=num_components,
        largest_component_size=largest_component_size,
        largest_component_fraction=largest_component_fraction,
        avg_path_length=avg_path_length,
        clustering_coefficient=clustering_coefficient,
        modularity=modularity,
    )


def get_top_hubs(G: nx.Graph, method: CentralityMethod, top_k: int) -> list[tuple[str, float]]:
    """Get top-k hub nodes by the specified centrality measure."""
    analysis = CentralityAnalysis(G)

    if method == "degree":
        analysis.compute_degree_centrality()
    elif method == "betweenness":
        analysis.compute_betweenness_centrality()
    elif method == "closeness":
        analysis.compute_closeness_centrality()
    elif method == "eigenvector":
        analysis.compute_eigenvector_centrality()
    else:
        raise ValueError(f"Unsupported centrality method: {method}")

    if not analysis.centrality_measures:
        return []

    _, values = next(iter(analysis.centrality_measures.items()))
    sorted_nodes = sorted(values.items(), key=lambda x: x[1], reverse=True)
    return sorted_nodes[:top_k]


def simulate_removal(
    G: nx.Graph,
    method: CentralityMethod,
    top_k: int,
) -> tuple[NetworkMetrics, NetworkMetrics, list[tuple[str, float]]]:
    """
    Simulate removal of top-k hubs and return before/after metrics.
    
    Returns:
        Tuple of (metrics_before, metrics_after, removed_hubs)
    """
    # Compute metrics before removal
    metrics_before = compute_metrics(G)

    # Get top hubs to remove
    hubs_to_remove = get_top_hubs(G, method, top_k)
    hub_names = [name for name, _ in hubs_to_remove]

    # Create graph copy and remove hubs
    G_after = G.copy()
    G_after.remove_nodes_from(hub_names)

    # Compute metrics after removal
    metrics_after = compute_metrics(G_after)

    return metrics_before, metrics_after, hubs_to_remove


def print_comparison_table(
    method: CentralityMethod,
    top_k: int,
    metrics_before: NetworkMetrics,
    metrics_after: NetworkMetrics,
    removed_hubs: list[tuple[str, float]],
) -> None:
    """Print a formatted comparison table of before/after metrics."""
    print("\n" + "=" * 80)
    print(f"ROBUSTNESS ANALYSIS: Targeted Removal of Top {top_k} {method.upper()} Hubs")
    print("=" * 80)

    print(f"\nRemoved hubs ({method} centrality):")
    for i, (name, score) in enumerate(removed_hubs, 1):
        print(f"  {i:2d}. {name} ({score:.6f})")

    print("\n" + "-" * 80)
    print(f"{'Metric':<35} {'Before':>15} {'After':>15} {'Change':>15}")
    print("-" * 80)

    def fmt_change(before: float | int | None, after: float | int | None) -> str:
        if before is None or after is None:
            return "N/A"
        if isinstance(before, int):
            diff = after - before
            pct = (diff / before * 100) if before != 0 else 0
            return f"{diff:+d} ({pct:+.1f}%)"
        else:
            diff = after - before
            pct = (diff / before * 100) if before != 0 else 0
            return f"{diff:+.3f} ({pct:+.1f}%)"

    def fmt_val(val: float | int | None, is_pct: bool = False) -> str:
        if val is None:
            return "N/A"
        if isinstance(val, int):
            return str(val)
        if is_pct:
            return f"{val:.1%}"
        return f"{val:.4f}"

    rows = [
        ("Nodes", metrics_before.num_nodes, metrics_after.num_nodes),
        ("Edges", metrics_before.num_edges, metrics_after.num_edges),
        ("Connected Components", metrics_before.num_components, metrics_after.num_components),
        ("Largest Component Size", metrics_before.largest_component_size, metrics_after.largest_component_size),
        ("Largest Component Fraction", metrics_before.largest_component_fraction, metrics_after.largest_component_fraction),
        ("Avg Path Length (largest CC)", metrics_before.avg_path_length, metrics_after.avg_path_length),
        ("Clustering Coefficient", metrics_before.clustering_coefficient, metrics_after.clustering_coefficient),
        ("Modularity", metrics_before.modularity, metrics_after.modularity),
    ]

    for label, before, after in rows:
        is_pct = "Fraction" in label
        print(f"{label:<35} {fmt_val(before, is_pct):>15} {fmt_val(after, is_pct):>15} {fmt_change(before, after):>15}")

    print("-" * 80)

    # Generate summary statement
    print("\n📊 SUMMARY:")
    comp_change = metrics_after.num_components - metrics_before.num_components
    size_change_pct = (
        (metrics_after.largest_component_size - metrics_before.largest_component_size)
        / metrics_before.largest_component_size * 100
        if metrics_before.largest_component_size > 0 else 0
    )

    if comp_change > 0:
        print(f"  • Removing the top {top_k} {method} hubs increases connected components "
              f"from {metrics_before.num_components} to {metrics_after.num_components} (+{comp_change})")
    
    print(f"  • Largest component shrinks by {abs(size_change_pct):.1f}% "
          f"({metrics_before.largest_component_size} → {metrics_after.largest_component_size} nodes)")

    if metrics_before.avg_path_length and metrics_after.avg_path_length:
        path_change = metrics_after.avg_path_length - metrics_before.avg_path_length
        if path_change > 0:
            print(f"  • Average path length increases by {path_change:.3f}, "
                  "indicating harder communication across the network")
        else:
            print(f"  • Average path length decreases by {abs(path_change):.3f}")

    clust_change = metrics_after.clustering_coefficient - metrics_before.clustering_coefficient
    if abs(clust_change) > 0.001:
        direction = "increases" if clust_change > 0 else "decreases"
        print(f"  • Clustering coefficient {direction} by {abs(clust_change):.4f}")

    print()


def run_robustness_analysis(
    G: nx.Graph,
    method: CentralityMethod = "betweenness",
    top_k: int = 3,
    largest_component: bool = True,
) -> None:
    """Run the full robustness analysis on the given graph."""
    if G.number_of_nodes() == 0:
        print("Graph is empty; cannot perform robustness analysis.")
        return

    # Optionally restrict to largest component
    if largest_component:
        components = list(nx.connected_components(G))
        if components:
            largest = max(components, key=len)
            G = G.subgraph(largest).copy()
            print(f"Analyzing largest component: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    metrics_before, metrics_after, removed_hubs = simulate_removal(G, method, top_k)
    print_comparison_table(method, top_k, metrics_before, metrics_after, removed_hubs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Robustness analysis: simulate targeted hub removal and measure network impact."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit number of articles fetched from the database.",
    )
    parser.add_argument(
        "--method",
        choices=["degree", "betweenness", "closeness", "eigenvector"],
        default="betweenness",
        help="Centrality measure used to identify hubs for removal (default: betweenness).",
    )
    parser.add_argument(
        "--top-k", type=int, default=3,
        help="Number of top hubs to remove (default: 3).",
    )
    parser.add_argument(
        "--full-graph", action="store_true",
        help="Analyze full graph instead of largest connected component.",
    )
    parser.add_argument(
        "--compare-methods", action="store_true",
        help="Run analysis for both betweenness and eigenvector centrality.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()

    print("Building combined author network...")
    builder = ArticleGraphBuilder()
    builder.load_data(limit=args.limit)
    builder.build_author_map()

    multilayer = MultiLayerAuthorGraph()
    multilayer.add_layer("coauthor", builder.build_coauthor_layer())
    multilayer.add_layer("related", builder.build_related_layer())
    combined = multilayer.combine_layers(mode="sum")

    print(f"Combined graph: {combined.number_of_nodes()} nodes, {combined.number_of_edges()} edges")

    if args.compare_methods:
        # Run for both betweenness and eigenvector
        for method in ["betweenness", "eigenvector"]:
            run_robustness_analysis(
                combined.copy(),
                method=method,
                top_k=args.top_k,
                largest_component=not args.full_graph,
            )
    else:
        run_robustness_analysis(
            combined,
            method=args.method,
            top_k=args.top_k,
            largest_component=not args.full_graph,
        )


if __name__ == "__main__":
    main()
