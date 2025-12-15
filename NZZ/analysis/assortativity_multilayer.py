"""python NZZ/analysis/assortativity_multilayer.py --limit 2000 --combine-mode sum --largest-component"""

import argparse
import logging

import networkx as nx
import numpy as np
from dotenv import load_dotenv

from article_graph_builder import ArticleGraphBuilder


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


def compute_assortativity_for_graph(name: str, G: nx.Graph) -> dict[str, float | int | None]:
    """Compute and log degree assortativity for a graph if it is non-trivial."""
    n, m = G.number_of_nodes(), G.number_of_edges()
    if n < 2 or m == 0:
        logger.info("%s: too small for assortativity (nodes=%s, edges=%s)", name, n, m)
        return {"name": name, "nodes": n, "edges": m, "r_unweighted": None, "r_weighted": None}

    logger.info("%s: nodes=%s, edges=%s", name, n, m)

    r_unweighted = nx.degree_assortativity_coefficient(G)
    logger.info("%s: unweighted degree assortativity r = %.4f", name, r_unweighted)

    r_weighted: float | None = None
    try:
        r_weighted = nx.degree_assortativity_coefficient(G, weight="weight")
        logger.info("%s: weighted degree assortativity r = %.4f", name, r_weighted)
    except Exception as exc:
        logger.info("%s: could not compute weighted assortativity (%s)", name, exc)
    return {"name": name, "nodes": n, "edges": m, "r_unweighted": r_unweighted, "r_weighted": r_weighted}


def compute_cross_layer_degree_correlation(
    layers: dict[str, nx.Graph],
    nodes: list[str],
) -> dict[tuple[str, str], float]:
    """Compute Pearson correlation between degree sequences of every pair of layers."""
    layer_names = list(layers.keys())
    if len(layer_names) < 2:
        return {}

    degree_matrix = []
    for name in layer_names:
        G = layers[name]
        degree_matrix.append([G.degree(node) for node in nodes])
    matrix = np.array(degree_matrix, dtype=float)

    correlations: dict[tuple[str, str], float] = {}
    for i in range(len(layer_names)):
        for j in range(i + 1, len(layer_names)):
            a = matrix[i]
            b = matrix[j]
            if np.std(a) == 0 or np.std(b) == 0:
                corr = float("nan")
            else:
                corr = float(np.corrcoef(a, b)[0, 1])
            correlations[(layer_names[i], layer_names[j])] = corr
    return correlations


def print_correlation_summary(correlations: dict[tuple[str, str], float], scope: str) -> None:
    if not correlations:
        return
    print(f"\n=== Cross-layer degree correlations ({scope}) ===")
    for (layer_a, layer_b), corr in correlations.items():
        if np.isnan(corr):
            print(f"{layer_a} vs {layer_b}: n/a (zero variance)")
        else:
            print(f"{layer_a} vs {layer_b}: Pearson r = {corr:.4f}")


def build_multilayer(limit: int | None, combine_mode: str = "sum") -> tuple[dict[str, nx.Graph], nx.Graph]:
    """Build coauthor, related, and combined layers using the multilayer pipeline."""
    logger.info("=== Building empirical multilayer for assortativity analysis ===")
    load_dotenv()
    builder = ArticleGraphBuilder()
    layers, combined = builder.build_empirical_multilayer(limit=limit, combine_mode=combine_mode)
    return layers, combined


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

    results: list[dict[str, float | int | None]] = []
    for name, G in layers.items():
        target = largest_component_subgraph(G) if args.largest_component else G
        suffix = " (largest component)" if args.largest_component else " (full graph)"
        results.append(compute_assortativity_for_graph(name + suffix, target))

    target_combined = largest_component_subgraph(combined) if args.largest_component else combined
    suffix_combined = " (largest component)" if args.largest_component else " (full graph)"
    combined_result = compute_assortativity_for_graph("combined" + suffix_combined, target_combined)
    results.append(combined_result)

    # Cross-layer degree correlations (overall)
    reference_nodes = sorted(combined.nodes())
    overall_correlations = compute_cross_layer_degree_correlation(layers, reference_nodes)
    print_correlation_summary(overall_correlations, scope="all nodes")

    # Cross-layer correlations (largest component of combined graph)
    largest = largest_component_subgraph(combined)
    component_correlations = compute_cross_layer_degree_correlation(layers, sorted(largest.nodes()))
    print_correlation_summary(component_correlations, scope="largest component")

    print("\n=== Summary ===")
    for entry in results:
        if entry["r_unweighted"] is None:
            continue
        logger.info(
            "%s → r_unweighted=%.4f | r_weighted=%s",
            entry["name"],
            entry["r_unweighted"],
            f"{entry['r_weighted']:.4f}" if entry["r_weighted"] is not None else "n/a",
        )


if __name__ == "__main__":
    main()

