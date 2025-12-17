"""Centrality computation and reporting for the multilayer author network."""

from __future__ import annotations

import argparse
import logging
import os
from collections import Counter
from difflib import get_close_matches
from typing import Dict, Iterable, List, Tuple

import networkx as nx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from article_graph_builder import ArticleGraphBuilder
from visualizer import GraphVisualizer


logger = logging.getLogger("centralities")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

MEASURE_CHOICES = ["betweenness", "degree", "closeness", "eigenvector"]


class CentralityAnalysis:
    """Performs centrality analysis on a given graph."""

    def __init__(self, graph: nx.Graph):
        """Initialize with a NetworkX graph."""
        self.graph = graph
        self.centrality_measures: Dict[str, Dict[str, float]] = {}

    def compute_degree_centrality(self) -> Dict[str, float]:
        self.centrality_measures["degree"] = nx.degree_centrality(self.graph)
        return self.centrality_measures["degree"]

    def compute_betweenness_centrality(self) -> Dict[str, float]:
        self.centrality_measures["betweenness"] = nx.betweenness_centrality(self.graph)
        return self.centrality_measures["betweenness"]

    def compute_closeness_centrality(self) -> Dict[str, float]:
        self.centrality_measures["closeness"] = nx.closeness_centrality(self.graph)
        return self.centrality_measures["closeness"]

    def compute_eigenvector_centrality(self) -> Dict[str, float]:
        self.centrality_measures["eigenvector"] = nx.eigenvector_centrality(
            self.graph, max_iter=1000
        )
        return self.centrality_measures["eigenvector"]

    def compute_measures(
        self, measures: Iterable[str]
    ) -> Dict[str, Dict[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        print(measures)
        print(self.graph)

        for name in measures:
            method = getattr(self, f"compute_{name}_centrality", None)
            if not method:
                logger.warning("Unsupported centrality measure: %s", name)
                continue
            try:
                result[name] = method()
            except Exception as exc:
                logger.error("Failed to compute %s centrality: %s", name, exc)
        return result


    def build_rankings(self, values: Dict[str, float], top_k: int, role_map: Dict[str, str]) -> List[Tuple[int, str, float, str]]:
        sorted_nodes = sorted(values.items(), key=lambda item: item[1], reverse=True)[
            :top_k
        ]
        rows: List[Tuple[int, str, float, str]] = []
        for rank, (name, score) in enumerate(sorted_nodes, start=1):
            rows.append((rank, name, score, lookup_role(name, role_map)))
        return rows

    def print_table(self,measure_name: str, rows: List[Tuple[int, str, float, str]]) -> None:
        if not rows:
            logger.warning("No centrality data available for %s", measure_name)
            return

        print(f"\n=== {measure_name.title()} centrality (top {len(rows)}) ===")
        header = f"{'Rank':>4}  {'Author':<35}  {'Score':>10}  {'Role from Impressum'}"
        print(header)
        print("-" * len(header))
        for rank, author, value, role in rows:
            print(f"{rank:>4}  {author:<35}  {value:>10.4f}  {role}")
    
    def summarize_hubs(self, 
        top_rows: Dict[str, List[Tuple[int, str, float, str]]], role_map: Dict[str, str]
    ) -> None:
        frequency: Counter[str] = Counter()
        for rows in top_rows.values():
            for _, author, _, _ in rows:
                frequency[author] += 1

        if not frequency:
            return

        hubs = [name for name, count in frequency.items() if count >= 2]
        specialists = [name for name, count in frequency.items() if count == 1]

        if hubs:
            print("\n=== Central hubs (appear in multiple measures) ===")
            for name in sorted(hubs, key=lambda x: frequency[x], reverse=True):
                print(
                    f"- {name} ({lookup_role(name, role_map)}) → {frequency[name]} measures"
                )

        if specialists:
            print("\n=== Peripheral specialists (single measure appearance) ===")
            for name in sorted(specialists):
                print(f"- {name} ({lookup_role(name, role_map)})")



def parse_impressum(html_path: str) -> Dict[str, str]:
    """Extract author roles from the NZZ Impressum."""
    if not html_path:
        return {}
    if not os.path.exists(html_path):
        logger.warning("Impressum not found at %s", html_path)
        return {}

    with open(html_path, "r", encoding="utf-8") as handle:
        soup = BeautifulSoup(handle.read(), "html.parser")

    role_map: Dict[str, str] = {}
    current_section: str | None = None

    for tag in soup.find_all(["h2", "h3", "strong", "b", "p"]):
        text = tag.get_text(" ", strip=True)
        if not text:
            continue

        if len(text.split()) <= 4 and text.endswith(":"):
            current_section = text[:-1]
            continue

        separators = ["–", "-", ","]
        parts: List[str] = []
        for sep in separators:
            if sep in text:
                parts = [chunk.strip() for chunk in text.split(sep, 1)]
                break
        if len(parts) != 2:
            continue

        name, role = parts
        if len(name.split()) < 2:
            continue
        role_map[name] = f"{role} ({current_section})" if current_section else role

    logger.info("[Impressum] Extracted %s names with roles.", len(role_map))
    return role_map


def lookup_role(name: str, role_map: Dict[str, str]) -> str:
    if not role_map:
        return "Unknown"
    if name in role_map:
        return role_map[name]
    match = get_close_matches(name, role_map.keys(), n=1, cutoff=0.85)
    return role_map[match[0]] if match else "Unknown"


def largest_component_subgraph(graph: nx.Graph) -> nx.Graph:
    if graph.number_of_nodes() == 0:
        return nx.Graph()
    if nx.is_connected(graph):
        return graph.copy()
    nodes = max(nx.connected_components(graph), key=len)
    return graph.subgraph(nodes).copy()


def build_graph(limit: int | None, combine_mode: str, target: str) -> nx.Graph:
    builder = ArticleGraphBuilder()
    layers, combined = builder.build_empirical_multilayer(
        limit=limit, combine_mode=combine_mode
    )
    mapping = {
        "coauthor": layers["coauthor"],
        "related": layers["related"],
        "combined": combined,
    }
    return mapping[target]


def visualize_measure(
    graph: nx.Graph,
    measure_name: str,
    values: Dict[str, float],
    args: argparse.Namespace,
) -> None:
    visualizer = GraphVisualizer()
    visualizer.visualize_existing_graph_interactive(
        graph,
        weight_threshold=args.visualize_weight_threshold,
        label_top_n=args.label_top_n,
        show_names=args.show_names,
        measure_name=f"{measure_name.title()} centrality",
        centrality_measures=values,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute and visualize centralities for the author network."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles loaded from Supabase.",
    )
    parser.add_argument(
        "--graph",
        choices=["coauthor", "related", "combined"],
        default="combined",
        help="Which layer to analyze.",
    )
    parser.add_argument(
        "--combine-mode",
        choices=["sum", "max"],
        default="sum",
        help="Combination method for the multilayer graph.",
    )
    parser.add_argument(
        "--measures",
        nargs="+",
        choices=MEASURE_CHOICES,
        default=MEASURE_CHOICES,
        help="Centrality measures to compute.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of top authors to display per measure.",
    )
    parser.add_argument(
        "--largest-component",
        action="store_true",
        help="Restrict analysis to the largest connected component.",
    )
    parser.add_argument(
        "--impressum",
        type=str,
        default="NZZ/impressum.html",
        help="Path to the NZZ Impressum HTML file.",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Visualize the selected graph colored by a centrality measure.",
    )
    parser.add_argument(
        "--visualize-measure",
        choices=MEASURE_CHOICES,
        default="betweenness",
        help="Centrality metric to use for visualization.",
    )
    parser.add_argument(
        "--visualize-weight-threshold",
        type=float,
        default=0.0,
        help="Minimum edge weight when visualizing.",
    )
    parser.add_argument(
        "--label-top-n",
        type=int,
        default=40,
        help="Number of node labels to show in the interactive plot.",
    )
    parser.add_argument(
        "--show-names",
        action="store_true",
        help="Always show node labels in the visualization viewport.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv()

    graph = build_graph(
        limit=args.limit, combine_mode=args.combine_mode, target=args.graph
    )
    if args.largest_component:
        graph = largest_component_subgraph(graph)

    analysis = CentralityAnalysis(graph)
    centrality_values = analysis.compute_measures(args.measures)
    if not centrality_values:
        logger.error("No centrality measures were computed; exiting.")
        return

    role_map = parse_impressum(args.impressum)

    top_rows: Dict[str, List[Tuple[int, str, float, str]]] = {}
    for name, values in centrality_values.items():
        rows = analysis.build_rankings(values, args.top_k, role_map)
        top_rows[name] = rows
        analysis.print_table(name, rows)

    analysis.summarize_hubs(top_rows, role_map)

    if args.visualize:
        selected = args.visualize_measure
        if selected not in centrality_values:
            logger.error(
                "Cannot visualize measure '%s' because it was not computed.", selected
            )
        else:
            visualize_measure(graph, selected, centrality_values[selected], args)


if __name__ == "__main__":
    main()
