import argparse
from articles import ArticleGraphBuilder
import networkx as nx

# python3 assortativity.py --largest-component --limit 10000


def build_graph(limit: int | None = None) -> ArticleGraphBuilder:
    """Build the author graph using the existing ArticleGraphBuilder.

    Parameters
    ----------
    limit : int | None
        Optional row limit forwarded to `load_data`.

    Returns
    -------
    ArticleGraphBuilder
        The builder instance with `G` populated.
    """
    builder = ArticleGraphBuilder()
    builder.load_data(limit=limit)
    builder.build_authors_graph()
    builder.build_graph()
    builder.analyze_components()
    return builder


def compute_assortativity(G: nx.Graph) -> None:
    """Compute and print assortativity measures for a given graph.

    Currently reports:
    - Degree assortativity (unweighted)
    - Degree assortativity (weighted by the edge attribute ``weight``)
    """
    if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
        print("Graph is empty; cannot compute assortativity.")
        return

    print("Nodes:", G.number_of_nodes())
    print("Edges:", G.number_of_edges())

    # Unweighted degree assortativity
    r_unweighted = nx.degree_assortativity_coefficient(G)
    print(f"Unweighted degree assortativity: {r_unweighted:.4f}")

    # Weighted degree assortativity, if edge weights are present
    try:
        r_weighted = nx.degree_assortativity_coefficient(G, weight="weight")
        print(f"Weighted degree assortativity:  {r_weighted:.4f}")
    except Exception as e:  # e.g. if weights are missing or invalid
        print(f"Could not compute weighted assortativity: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute assortativity of the NZZ author graph.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles to load (forwarded to ArticleGraphBuilder).",
    )

    parser.add_argument(
        "--largest-component",
        action="store_true",
        help="Compute assortativity only on the largest connected component.",
    )

    args = parser.parse_args()

    builder = build_graph(limit=args.limit)

    if args.largest_component:
        print("Using largest connected component for assortativity computation.")
        G_target = builder.get_largest_component_graph()
    else:
        print("Using full author graph for assortativity computation.")
        G_target = builder.G

    compute_assortativity(G_target)


if __name__ == "__main__":
    main()
