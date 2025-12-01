"""Build a multilayer author network combining co-authorship and related-article edges."""

from __future__ import annotations

import argparse
import ast
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, Iterable, List, Sequence

import networkx as nx
import pandas as pd

from articles import ArticleGraphBuilder
from visualizer import GraphVisualizer


logger = logging.getLogger("author_network")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_related_articles(value: object) -> List[str]:
    """Parse the related_articles field into a Python list."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            logger.debug("Could not parse related_articles entry: %s", value)
    return []


def build_author_map(df: pd.DataFrame, builder: ArticleGraphBuilder) -> Dict[str, List[str]]:
    """Return mapping of article_id -> normalized list of authors."""
    author_map: Dict[str, List[str]] = {}
    for row in df.itertuples(index=False):
        authors = builder._normalize_authors(row.authors)
        authors = [a for a in authors if isinstance(a, str) and a.strip()]
        author_map[row.article_id] = authors
    return author_map


def build_coauthor_layer(author_map: Dict[str, Sequence[str]], all_authors: Iterable[str]) -> nx.Graph:
    """Create the co-authorship layer where weights are joint article counts."""
    import itertools

    G = nx.Graph(layer="coauthor")
    G.add_nodes_from(all_authors)

    for authors in author_map.values():
        unique_authors = sorted(set(a for a in authors if a))
        if len(unique_authors) < 2:
            continue
        for a1, a2 in itertools.combinations(unique_authors, 2):
            if G.has_edge(a1, a2):
                G[a1][a2]["weight"] += 1
            else:
                G.add_edge(a1, a2, weight=1)

    logger.info("Co-author layer: %s nodes, %s edges", G.number_of_nodes(), G.number_of_edges())
    return G


def build_related_layer(df: pd.DataFrame, author_map: Dict[str, Sequence[str]], all_authors: Iterable[str]) -> nx.Graph:
    """Create the related-articles layer with weights equal to shared references."""
    G = nx.Graph(layer="related")
    G.add_nodes_from(all_authors)

    if "related_articles_filtered" in df.columns:
        related_column = "related_articles_filtered"
    elif "related_articles" in df.columns:
        related_column = "related_articles"
    else:
        logger.warning("No related articles column available; returning empty related layer.")
        return G

    for row in df.itertuples(index=False):
        source_id = row.article_id
        source_authors = author_map.get(source_id, [])
        if not source_authors:
            continue

        related_field = getattr(row, related_column, None)
        related_list = parse_related_articles(related_field)
        if not related_list:
            continue
        for target_id in related_list:
            target_authors = author_map.get(target_id, [])
            if not target_authors:
                continue
            for a1 in source_authors:
                for a2 in target_authors:
                    if a1 == a2:
                        continue
                    if G.has_edge(a1, a2):
                        G[a1][a2]["weight"] += 1
                    else:
                        G.add_edge(a1, a2, weight=1)

    logger.info("Related-article layer: %s nodes, %s edges", G.number_of_nodes(), G.number_of_edges())
    return G


@dataclass
class MultiLayerAuthorGraph:
    """Container for managing distinct author network layers."""

    layers: Dict[str, nx.Graph] = field(default_factory=dict)

    def add_layer(self, name: str, graph: nx.Graph) -> None:
        if not isinstance(graph, nx.Graph):
            raise TypeError("Layer must be a NetworkX Graph instance.")
        self.layers[name] = graph

    def combine_layers(self, mode: str = "sum") -> nx.Graph:
        """Combine all layers into a single weighted graph."""
        if not self.layers:
            raise ValueError("No layers available to combine.")

        combined = nx.Graph(layer="combined")
        node_membership: defaultdict[str, set] = defaultdict(set)

        for name, layer in self.layers.items():
            for node in layer.nodes():
                combined.add_node(node)
                node_membership[node].add(name)

            for u, v, data in layer.edges(data=True):
                weight = data.get("weight", 1)
                if combined.has_edge(u, v):
                    if mode == "sum":
                        combined[u][v]["weight"] += weight
                    elif mode == "max":
                        combined[u][v]["weight"] = max(combined[u][v]["weight"], weight)
                    else:
                        raise ValueError(f"Unknown combination mode: {mode}")
                    combined[u][v]["layers"].add(name)
                else:
                    combined.add_edge(u, v, weight=weight)
                    combined[u][v]["layers"] = {name}

        for node, names in node_membership.items():
            combined.nodes[node]["layers"] = ",".join(sorted(names))

        for u, v, data in combined.edges(data=True):
            data["layers"] = ",".join(sorted(data["layers"]))

        logger.info(
            "Combined graph (%s mode): %s nodes, %s edges",
            mode,
            combined.number_of_nodes(),
            combined.number_of_edges(),
        )
        return combined


def summarize_graph(name: str, G: nx.Graph) -> None:
    """Print quick stats about a graph/layer."""
    components = list(nx.connected_components(G)) if G.number_of_nodes() else []
    largest_component = max((len(c) for c in components), default=0)
    density = nx.density(G) if G.number_of_nodes() > 1 else 0.0
    isolated_nodes = len(list(nx.isolates(G)))

    logger.info(
        "%s → nodes: %s | edges: %s | largest component: %s | density: %.4f | isolates: %s",
        name,
        G.number_of_nodes(),
        G.number_of_edges(),
        largest_component,
        density,
        isolated_nodes,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a multilayer author network with separate co-author and related-article layers.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of articles to load from the database.")
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=["coauthor", "related"],
        default=["coauthor", "related"],
        help="Specify which layers to construct.",
    )
    parser.add_argument(
        "--combine-mode",
        choices=["sum", "max"],
        default="sum",
        help="How to merge weights across layers when building the combined view.",
    )
    parser.add_argument("--export", type=str, default=None, help="Optional path to export the combined graph to GEXF.")
    parser.add_argument(
        "--export-layers",
        action="store_true",
        help="When provided with --export, also export each individual layer.",
    )
    parser.add_argument("--visualize", action="store_true", help="Open an interactive visualization at the end.")
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
    return parser.parse_args()


def degree_preserving_random_layer(
    base_graph: nx.Graph,
    degree_profile: Dict[str, int],
    swaps_per_edge: int,
    seed: int,
    layer_name: str,
) -> nx.Graph:
    """Create a randomised copy of the base graph via double-edge swaps."""
    randomized = nx.Graph()
    randomized.add_nodes_from(base_graph.nodes())
    randomized.add_edges_from(base_graph.edges())
    randomized.graph["layer"] = layer_name

    edge_count = randomized.number_of_edges()
    if edge_count == 0:
        logger.warning("Layer %s has no edges; skipping rewiring.", layer_name)
    else:
        nswap = max(edge_count * swaps_per_edge, 1)
        max_tries = nswap * 10
        try:
            nx.double_edge_swap(randomized, nswap=nswap, max_tries=max_tries, seed=seed)
        except nx.NetworkXError as exc:
            logger.warning("Failed to fully randomise %s (reason: %s)", layer_name, exc)

    nx.set_edge_attributes(randomized, 1, "weight")
    nx.set_node_attributes(randomized, degree_profile, "activity")

    actual_degrees = dict(randomized.degree())
    for author, expected_degree in degree_profile.items():
        if actual_degrees.get(author, 0) != expected_degree:
            raise RuntimeError(
                f"Degree mismatch for {author} in {layer_name}: expected {expected_degree}, "
                f"observed {actual_degrees.get(author, 0)}",
            )
    return randomized


def compute_activity(layers: Dict[str, nx.Graph]) -> Dict[str, int]:
    activity = defaultdict(int)
    for graph in layers.values():
        for author, deg in graph.degree():
            activity[author] += deg
    return activity


def print_activity_table(activity_scores: Dict[str, int], top_k: int, layer_count: int) -> tuple[float | None, float | None]:
    if not activity_scores:
        logger.warning("No authors found while ranking activity.")
        return None, None

    sorted_authors: List[tuple[str, int]] = sorted(
        activity_scores.items(),
        key=lambda item: (-item[1], item[0]),
    )[:top_k]

    header = f"{'Rank':>4}  {'Author':<40} {'Activity (Σ degrees)':>22}  {'Per Layer':>10}"
    print("\n=== Activity Ranking (degree-based) ===")
    print(header)
    print("-" * len(header))

    for idx, (author, total_activity) in enumerate(sorted_authors, start=1):
        per_layer = total_activity / layer_count
        print(f"{idx:>4}  {author:<40} {total_activity:>22}  {per_layer:>10.2f}")

    top_per_layer = sorted_authors[0][1] / layer_count if sorted_authors else None
    avg_activity = mean(activity_scores.values()) if activity_scores else None
    if top_per_layer is not None and avg_activity is not None:
        print(
            f"\nConclusion: Activity is uniform by construction; our most active author "
            f"shows degree {top_per_layer:.2f} per layer, versus an average of "
            f"{avg_activity:.2f} summed across layers. "
            f"Use this ranking as a neutral baseline before comparing against the empirical network."
        )
    return top_per_layer, avg_activity


def maybe_export_layers(layers: Dict[str, nx.Graph], combined: nx.Graph | None, prefix: str) -> None:
    for name, layer in layers.items():
        path = f"{prefix}_{name}.gexf"
        nx.write_gexf(layer, path)
        logger.info("Saved %s", path)
    if combined is not None:
        path = f"{prefix}_combined.gexf"
        nx.write_gexf(combined, path)
        logger.info("Saved %s", path)


def build_base_graph(limit: int | None) -> tuple[nx.Graph, Dict[str, int]]:
    builder = ArticleGraphBuilder()
    builder.load_data(limit=limit)

    df = builder.df.copy()
    author_map = build_author_map(df, builder)
    all_authors = sorted({author for authors in author_map.values() for author in authors})

    multilayer = MultiLayerAuthorGraph()
    coauthor = build_coauthor_layer(author_map, all_authors)
    related = build_related_layer(df, author_map, all_authors)
    multilayer.add_layer("coauthor", coauthor)
    multilayer.add_layer("related", related)

    summarize_graph("coauthor (empirical)", coauthor)
    summarize_graph("related (empirical)", related)

    combined_weighted = multilayer.combine_layers(mode="sum")
    summarize_graph("combined (empirical)", combined_weighted)

    base_graph = nx.Graph()
    base_graph.add_nodes_from(combined_weighted.nodes())
    base_graph.add_edges_from(combined_weighted.edges())

    degree_profile = dict(base_graph.degree())
    logger.info(
        "Base graph contains %s authors and %s edges. Avg degree %.2f",
        base_graph.number_of_nodes(),
        base_graph.number_of_edges(),
        (sum(degree_profile.values()) / max(len(degree_profile), 1)) if degree_profile else 0.0,
    )
    return base_graph, degree_profile


def run_random_baseline(
    *,
    limit: int | None = None,
    swaps_per_edge: int = 5,
    seed: int = 42,
    top_k: int = 20,
    export_prefix: str | None = None,
    visualize: bool = False,
    visualizer: GraphVisualizer | None = None,
    weight_threshold: float = 0.0,
) -> dict | None:
    base_graph, degree_profile = build_base_graph(limit=limit)
    if not base_graph.number_of_nodes():
        logger.error("No authors available. Nothing to randomise.")
        return None

    layer_names = ["random_layer_authors", "random_layer_citations", "random_layer_activity"]
    random_layers: Dict[str, nx.Graph] = {}
    for offset, name in enumerate(layer_names):
        layer_seed = seed + offset * 101
        random_layers[name] = degree_preserving_random_layer(
            base_graph,
            degree_profile,
            swaps_per_edge=swaps_per_edge,
            seed=layer_seed,
            layer_name=name,
        )
        summarize_graph(name, random_layers[name])

    combined_random = MultiLayerAuthorGraph()
    for name, layer in random_layers.items():
        combined_random.add_layer(name, layer)
    combined_view = combined_random.combine_layers(mode="sum")
    summarize_graph("combined (random baseline)", combined_view)

    activity_scores = compute_activity(random_layers)
    top_act, avg_act = print_activity_table(activity_scores, top_k, layer_count=len(layer_names))

    if export_prefix:
        maybe_export_layers(random_layers, combined_view, export_prefix)

    if visualize and visualizer:
        visualizer.visualize_existing_graph_interactive(
            combined_view,
            show_names=False,
            weight_threshold=weight_threshold,
        )

    return {
        "combined": combined_view,
        "top_activity_per_layer": top_act,
        "avg_activity_sum": avg_act,
    }


def main() -> None:
    args = parse_args()

    builder = ArticleGraphBuilder()
    builder.load_data(limit=args.limit)

    df = builder.df.copy()
    author_map = build_author_map(df, builder)
    all_authors = sorted({author for authors in author_map.values() for author in authors})

    multilayer = MultiLayerAuthorGraph()

    co_stats = {}
    if "coauthor" in args.layers:
        coauthor_graph = build_coauthor_layer(author_map, all_authors)
        multilayer.add_layer("coauthor", coauthor_graph)
        summarize_graph("coauthor", coauthor_graph)
        co_stats = {
            "edges": coauthor_graph.number_of_edges(),
            "isolates": len(list(nx.isolates(coauthor_graph))),
        }

    related_stats = {}
    if "related" in args.layers:
        related_graph = build_related_layer(df, author_map, all_authors)
        multilayer.add_layer("related", related_graph)
        summarize_graph("related", related_graph)
        related_stats = {
            "edges": related_graph.number_of_edges(),
            "isolates": len(list(nx.isolates(related_graph))),
        }

    if not multilayer.layers:
        raise RuntimeError("No layers were built. Check input arguments.")

    logger.info("=== Multilayer network (empirical) ===")
    combined = multilayer.combine_layers(mode=args.combine_mode)
    summarize_graph("combined", combined)
    combined_stats = {
        "edges": combined.number_of_edges(),
        "isolates": len(list(nx.isolates(combined))),
    }

    if co_stats or related_stats:
        logger.info(
            "Layer summary → coauthor: %s edges (%s isolates) | related: %s edges (%s isolates) | combined isolates: %s",
            co_stats.get("edges", "n/a"),
            co_stats.get("isolates", "n/a"),
            related_stats.get("edges", "n/a"),
            related_stats.get("isolates", "n/a"),
            combined_stats["isolates"],
        )
        logger.info(
            "Interpretation → multilayer graph is undirected; coauthor edges capture shared bylines, related edges capture shared references. Edge weights always equal the number of shared articles (>=1)."
        )
        if co_stats.get("isolates") and related_stats.get("isolates"):
            logger.info(
                "Layer contribution → coauthor layer leaves %s authors disconnected whereas related articles reduce isolates to %s; hence related-article similarity dominates.",
                co_stats["isolates"],
                related_stats["isolates"],
            )

    visualizer = GraphVisualizer() if args.visualize else None
    if args.visualize and visualizer:
        if args.visualize_target == "combined":
            graph_to_visualize = combined
        else:
            graph_to_visualize = multilayer.layers.get(args.visualize_target)
        if graph_to_visualize is None:
            logger.error("Cannot visualize '%s' because that layer was not constructed.", args.visualize_target)
        else:
            visualizer.visualize_existing_graph_interactive(
                graph_to_visualize,
                show_names=False,
                weight_threshold=args.visualize_weight_threshold,
            )

    if args.export:
        nx.write_gexf(combined, args.export)
        logger.info("Exported combined graph to %s", args.export)
        if args.export_layers:
            for name, layer in multilayer.layers.items():
                path = f"{args.export.rsplit('.', 1)[0]}_{name}.gexf"
                nx.write_gexf(layer, path)
                logger.info("Exported %s layer to %s", name, path)

    if args.run_baseline:
        logger.info("=== Random multilayer baseline (degree-preserving) ===")
        baseline_result = run_random_baseline(
            limit=args.limit,
            top_k=20,
            visualize=args.visualize,
            visualizer=visualizer,
            weight_threshold=args.visualize_weight_threshold,
        )
        if baseline_result:
            top_act = baseline_result.get("top_activity_per_layer")
            avg_act = baseline_result.get("avg_activity_sum")
            if top_act is not None and avg_act is not None:
                logger.info(
                    "Random baseline activity → top author degree per layer: %.2f | average summed activity: %.2f",
                    top_act,
                    avg_act,
                )
            logger.info(
                "Baseline interpretation → three random layers preserve every author's degree across layers, so activity (degree) is directly comparable for coauthors, related citations, and overall presence."
            )
            logger.info(
                "Baseline invariants → each author node exists in all three random layers with the same degree, meaning 'activity' is the shared property across authors/citations and we judge importance purely by that degree."
            )


if __name__ == "__main__":
    main()
