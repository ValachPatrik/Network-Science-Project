"""Shared helpers for multilayer author graphs. We use it through author_network.py and other analysis scripts."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict

import networkx as nx


logger = logging.getLogger("multilayer_network")


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
