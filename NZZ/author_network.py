"""Build a multilayer author network combining co-authorship and related-article edges."""

from __future__ import annotations

import argparse
import ast
import logging
from collections import defaultdict
from dataclasses import dataclass, field
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

    logger.info(
        "Co-author layer: %s nodes, %s edges",
        G.number_of_nodes(),
        G.number_of_edges(),
    )
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

    logger.info(
        "Related-article layer: %s nodes, %s edges",
        G.number_of_nodes(),
        G.number_of_edges(),
    )
    return G


@dataclass
class MultiLayerAuthorGraph:
    """Container for managing distinct author network layers."""

    layers: Dict[str, nx.Graph] = field(default_factory=dict)

    def add_layer(self, name: str, graph: nx.Graph) -> None:
        # Basic safety check: only allow proper NetworkX graphs
        if not isinstance(graph, nx.Graph):
            raise TypeError("Layer must be a NetworkX Graph instance.")
        self.layers[name] = graph

    def combine_layers(self, mode: str = "sum") -> nx.Graph:
        """Combine all layers into a single weighted graph."""
        if not self.layers:
            raise ValueError("No layers available to combine.")

        combined = nx.Graph(layer="combined")
        node_membership: defaultdict[str, set] = defaultdict(set)
        # Copy nodes and keep track of which node appears in which layer

        for name, layer in self.layers.items():
            for node in layer.nodes():
                combined.add_node(node)
                node_membership[node].add(name)

            # Merge edges, either sum weights or take the maximum across layers
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

        # Store layer membership info for nodes and edges
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles to load from the database.",
    )
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
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="Optional path to export the combined graph to GEXF.",
    )
    parser.add_argument(
        "--export-layers",
        action="store_true",
        help="When provided with --export, also export each individual layer.",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Open an interactive visualization (ForceAtlas2) at the end.",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    builder = ArticleGraphBuilder()
    builder.load_data(limit=args.limit)

    df = builder.df.copy()
    # Precompute (article -> authors) mapping for reuse
    author_map = build_author_map(df, builder)
    all_authors = sorted({author for authors in author_map.values() for author in authors})

    multilayer = MultiLayerAuthorGraph()

    # Build coauthor layer if selected
    if "coauthor" in args.layers:
        coauthor_graph = build_coauthor_layer(author_map, all_authors)
        multilayer.add_layer("coauthor", coauthor_graph)
        summarize_graph("coauthor", coauthor_graph)

    # Build related layer if selected
    if "related" in args.layers:
        related_graph = build_related_layer(df, author_map, all_authors)
        multilayer.add_layer("related", related_graph)
        summarize_graph("related", related_graph)

    if not multilayer.layers:
        raise RuntimeError("No layers were built. Check input arguments.")

    combined = multilayer.combine_layers(mode=args.combine_mode)
    summarize_graph("combined", combined)

    if args.visualize:
        visualizer = GraphVisualizer()
        if args.visualize_target == "combined":
            graph_to_visualize = combined
        else:
            graph_to_visualize = multilayer.layers.get(args.visualize_target)
        if graph_to_visualize is None:
            logger.error(
                "Cannot visualize '%s' because that layer was not constructed.",
                args.visualize_target,
            )
        else:
            visualizer.visualize_existing_graph_interactive(
                graph_to_visualize,
                show_names=False,
                weight_threshold=args.visualize_weight_threshold,
            )

    # Export combined and optionally individual layers
    if args.export:
        nx.write_gexf(combined, args.export)
        logger.info("Exported combined graph to %s", args.export)
        if args.export_layers:
            for name, layer in multilayer.layers.items():
                path = f"{args.export.rsplit('.', 1)[0]}_{name}.gexf"
                nx.write_gexf(layer, path)
                logger.info("Exported %s layer to %s", name, path)


if __name__ == "__main__":
    main()
