import argparse
import logging

import networkx as nx

from articles import ArticleGraphBuilder
from author_network import (
    MultiLayerAuthorGraph,
    build_author_map,
    build_coauthor_layer,
    build_related_layer,
    summarize_graph,
)


logger = logging.getLogger("assortativity_multilayer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def largest_component_subgraph(G: nx.Graph) -> nx.Graph:
    """Return the subgraph induced by the largest connected component."""
    if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
        return G
    components = list(nx.connected_components(G))
    if not components:
        return G
    largest = max(components, key=len)
    return G.subgraph(largest).copy()


def compute_assortativity_for_graph(name: str, G: nx.Graph) -> None:
    """Compute and log degree assortativity for a graph if it is non-trivial."""
    n, m = G.number_of_nodes(), G.number_of_edges()
    if n < 2 or m == 0:
        logger.info("%s: too small for assortativity (nodes=%s, edges=%s)", name, n, m)
        return

    logger.info("%s: nodes=%s, edges=%s", name, n, m)

    r_unweighted = nx.degree_assortativity_coefficient(G)
    logger.info("%s: unweighted degree assortativity r = %.4f", name, r_unweighted)

    try:
        r_weighted = nx.degree_assortativity_coefficient(G, weight="weight")
        logger.info("%s: weighted degree assortativity r = %.4f", name, r_weighted)
    except Exception as exc:
        logger.info("%s: could not compute weighted assortativity (%s)", name, exc)


def build_multilayer(limit: int | None, combine_mode: str = "sum") -> tuple[dict[str, nx.Graph], nx.Graph]:
    """Build coauthor, related, and combined layers using the existing pipeline."""
    builder = ArticleGraphBuilder()
    builder.load_data(limit=limit)

    df = builder.df.copy()
    author_map = build_author_map(df, builder)
    all_authors = sorted({author for authors in author_map.values() for author in authors})

    multilayer = MultiLayerAuthorGraph()

    coauthor = build_coauthor_layer(author_map, all_authors)
    summarize_graph("coauthor (empirical)", coauthor)
    multilayer.add_layer("coauthor", coauthor)

    related = build_related_layer(df, author_map, all_authors)
    summarize_graph("related (empirical)", related)
    multilayer.add_layer("related", related)

    logger.info("=== Multilayer network (empirical) ===")
    combined = multilayer.combine_layers(mode=combine_mode)
    summarize_graph("combined (empirical)", combined)

    return {"coauthor": coauthor, "related": related}, combined


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute assortativity measures on the multilayer author network (coauthor, related, combined).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of articles loaded from the database.")
    parser.add_argument(
        "--combine-mode",
        choices=["sum", "max"],
        default="sum",
        help="How to merge edge weights across layers for the combined graph.",
    )
    parser.add_argument(
        "--largest-component",
        action="store_true",
        help="Compute assortativity only on the largest connected component of each graph.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    layers, combined = build_multilayer(limit=args.limit, combine_mode=args.combine_mode)

    logger.info("\n=== Assortativity on empirical multilayer ===")

    for name, G in layers.items():
        target = largest_component_subgraph(G) if args.largest_component else G
        suffix = " (largest component)" if args.largest_component else " (full graph)"
        compute_assortativity_for_graph(name + suffix, target)

    target_combined = largest_component_subgraph(combined) if args.largest_component else combined
    suffix_combined = " (largest component)" if args.largest_component else " (full graph)"
    compute_assortativity_for_graph("combined" + suffix_combined, target_combined)


if __name__ == "__main__":
    main()
