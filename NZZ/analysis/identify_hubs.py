import argparse
from typing import Literal

import networkx as nx
from dotenv import load_dotenv

CentralityMethod = Literal["degree", "betweenness", "closeness", "eigenvector"]

try:
    from .centralities import CentralityAnalysis
    from .article_graph_builder import ArticleGraphBuilder
    from .multilayer_network import MultiLayerAuthorGraph
except ImportError:
    from centralities import CentralityAnalysis
    from article_graph_builder import ArticleGraphBuilder
    from multilayer_network import MultiLayerAuthorGraph


def _get_target_graph(G_combined: nx.Graph, largest_component: bool) -> nx.Graph:
    """
    Return either the full combined graph or its largest connected component.
    """
    if not largest_component:
        return G_combined

    if G_combined.number_of_nodes() == 0:
        return G_combined

    components = list(nx.connected_components(G_combined))
    if not components:
        return G_combined

    largest = max(components, key=len)
    return G_combined.subgraph(largest).copy()


def _compute_centrality(G: nx.Graph, method: CentralityMethod) -> dict[str, float]:
    """
    Compute a single centrality measure using the existing CentralityAnalysis helper.
    """
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
        return {}

    # Take the first (and only) measure dict that was filled
    _, values = next(iter(analysis.centrality_measures.items()))
    return values


def identify_hubs(
    G_combined: nx.Graph,
    method: CentralityMethod = "degree",
    top_k: int = 20,
    largest_component: bool = True,
) -> None:
    """
    Build the combined author network and print the top-k hubs.

    Parameters
    ----------
    limit : int | None
        Optional limit on number of articles loaded from the database.
    method : {"degree", "betweenness", "closeness", "eigenvector"}
        Centrality measure used to rank hubs.
    top_k : int
        Number of top nodes to display.
    largest_component : bool
        If True, restrict to the largest connected component of the
        combined graph; otherwise use the full combined graph.
    """
    if G_combined.number_of_nodes() == 0:
        print("Combined graph is empty; cannot identify hubs.")
        return

    G_target = _get_target_graph(G_combined, largest_component=largest_component)

    print("=== Hub Identification ===")
    print(
        f"Base combined graph: {G_combined.number_of_nodes()} nodes, "
        f"{G_combined.number_of_edges()} edges"
    )
    if largest_component:
        print(
            "Analyzing largest component: "
            f"{G_target.number_of_nodes()} nodes, {G_target.number_of_edges()} edges"
        )
    else:
        print("Analyzing full combined graph.")

    centrality_values = _compute_centrality(G_target, method=method)
    if not centrality_values:
        print("No centrality values computed; check graph size and method.")
        return

    # Sort nodes by centrality descending
    sorted_nodes = sorted(
        centrality_values.items(), key=lambda item: item[1], reverse=True
    )
    top_k = max(1, top_k)
    top_nodes = sorted_nodes[:top_k]

    print(f"\nTop {len(top_nodes)} hubs by {method} centrality:")
    for rank, (node, score) in enumerate(top_nodes, start=1):
        print(f"{rank:2d}. {node}  ({score:.6f})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Identify hub authors in the combined author network."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit number of articles fetched from the database.",
    )
    parser.add_argument(
        "--method",
        choices=["degree", "betweenness", "closeness", "eigenvector"],
        default="degree",
        help="Centrality measure used to rank hubs (default: degree).",
    )
    parser.add_argument(
        "--top-k", type=int, default=20,
        help="Number of top hubs to display (default: 20).",
    )
    parser.add_argument(
        "--full-graph", action="store_true",
        help="Analyze full graph instead of largest connected component.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()

    builder = ArticleGraphBuilder()
    builder.load_data(limit=args.limit)
    builder.build_author_map()

    multilayer = MultiLayerAuthorGraph()
    multilayer.add_layer("coauthor", builder.build_coauthor_layer())
    multilayer.add_layer("related", builder.build_related_layer())
    combined = multilayer.combine_layers(mode="sum")

    identify_hubs(
        combined,
        method=args.method,
        top_k=args.top_k,
        largest_component=not args.full_graph,
    )


if __name__ == "__main__":
    main()
