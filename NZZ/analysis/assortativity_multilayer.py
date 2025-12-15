import logging

import networkx as nx


logger = logging.getLogger("assortativity_multilayer")


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


def compute_assortativity_for_multilayer(
    layers: dict[str, nx.Graph],
    combined: nx.Graph,
    *,
    largest_component: bool = True,
) -> None:
    """Compute degree assortativity for all layers and the combined graph.

    Parameters
    ----------
    layers : dict[str, nx.Graph]
        Mapping from layer name (e.g. "coauthor", "related") to its graph.
    combined : nx.Graph
        Combined multilayer graph.
    largest_component : bool, optional
        If True, compute assortativity on the largest connected component
        of each graph. If False, use the full graph.
    """

    if not layers and combined is None:
        logger.info("No graphs provided for assortativity computation; skipping.")
        return

    logger.info("\n=== Assortativity on empirical multilayer ===")

    for name, G in layers.items():
        if G is None:
            continue
        target = largest_component_subgraph(G) if largest_component else G
        suffix = " (largest component)" if largest_component else " (full graph)"
        compute_assortativity_for_graph(name + suffix, target)

    if combined is not None:
        target_combined = largest_component_subgraph(combined) if largest_component else combined
        suffix_combined = " (largest component)" if largest_component else " (full graph)"
        compute_assortativity_for_graph("combined" + suffix_combined, target_combined)

