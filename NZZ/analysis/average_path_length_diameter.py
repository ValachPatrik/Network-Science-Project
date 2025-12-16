import networkx as nx
from article_graph_builder import ArticleGraphBuilder
import random
import re
import os
from bs4 import BeautifulSoup
from difflib import get_close_matches
from dotenv import load_dotenv


# PARSE NZZ IMPRESSUM (extract people : roles)


def parse_impressum(html_path):
    """
    Reads impressum.html and extracts a dictionary:
        { "Full Name": "Role / Department" }
    """
    if not os.path.exists(html_path):
        print(f"WARNING: impressum file not found: {html_path}")
        return {}

    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    role_map = {}

    # The Impressum uses <strong>, <b>, and <p> blocks
    current_section = None

    for tag in soup.find_all(["h2", "h3", "strong", "b", "p"]):
        text = tag.get_text(" ", strip=True)

        # Section headers (e.g. Ressort International, Chefredaktion)
        if len(text.split()) <= 4 and text.endswith(":"):
            current_section = text[:-1]
            continue

        # Try to detect "Name – Role" or "Name, Role" patterns
        if "–" in text:
            parts = [p.strip() for p in text.split("–", 1)]
        elif "-" in text:
            parts = [p.strip() for p in text.split("-", 1)]
        elif "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
        else:
            continue

        if len(parts) == 2:
            name, role = parts
            if len(name.split()) >= 2:  # avoid garbage
                if current_section:
                    role_map[name] = f"{role} ({current_section})"
                else:
                    role_map[name] = role

    print(f"\n[Impressum] Extracted {len(role_map)} names with roles.")
    return role_map


def binarize_graph(G):
    """Convert weighted graph into an unweighted graph:
    Edge exists if weight > 0."""
    B = nx.Graph()
    for u, v, data in G.edges(data=True):
        if data.get("weight", 0) > 0:
            B.add_edge(u, v)
    return B


def largest_component_subgraph(G: nx.Graph) -> nx.Graph:
    """Return a copy of the largest connected component."""
    if G.number_of_nodes() == 0:
        return nx.Graph()
    if nx.is_connected(G):
        return G.copy()
    largest_nodes = max(nx.connected_components(G), key=len)
    return G.subgraph(largest_nodes).copy()


def compute_small_world_statistics(G):
    n = G.number_of_nodes()
    m = G.number_of_edges()

    p = (2 * m) / (n * (n - 1))
    G_rand = nx.erdos_renyi_graph(n, p)

    L_real = nx.average_shortest_path_length(G)
    C_real = nx.average_clustering(G)

    if not nx.is_connected(G_rand):
        G_rand = G_rand.subgraph(max(nx.connected_components(G_rand), key=len)).copy()

    L_rand = nx.average_shortest_path_length(G_rand)
    C_rand = nx.average_clustering(G_rand)

    return {
        "L_real": L_real,
        "C_real": C_real,
        "L_rand": L_rand,
        "C_rand": C_rand,
        "small_world": (L_real / L_rand < 2) and (C_real / C_rand > 2),
    }


def main():
    print("\n LOADING BUILDER V2")
    load_dotenv()
    builder = ArticleGraphBuilder()
    builder.load_data(limit=None)
    builder.build_author_map()
    related_graph = builder.build_related_layer()
    builder.summarize_graph("related (analysis)", related_graph)

    largest = largest_component_subgraph(related_graph)
    print(f"\nNodes in largest component: {largest.number_of_nodes()}")
    print(f"Edges in largest component: {largest.number_of_edges()}")

    # 1) BINARIZE GRAPH
    print("\n BINARY GRAPH (weight > 0 : edge exists)")
    B = binarize_graph(largest)
    print(f"Binary graph: {B.number_of_nodes()} nodes, {B.number_of_edges()} edges")

    # 2) AVERAGE PATH LENGTH
    print("\n AVERAGE PATH LENGTH")
    if nx.is_connected(B):
        avg_path = nx.average_shortest_path_length(B)
    else:
        B_largest = B.subgraph(max(nx.connected_components(B), key=len)).copy()
        avg_path = nx.average_shortest_path_length(B_largest)
    print(f"Average Path Length: {avg_path:.4f}")

    # 3) DIAMETER

    print("\n DIAMETER")
    if nx.is_connected(B):
        diameter = nx.diameter(B)
    else:
        B_largest = B.subgraph(max(nx.connected_components(B), key=len)).copy()
        diameter = nx.diameter(B_largest)
    print(f"Diameter: {diameter}")

    # 4) SMALL WORLD
    print("\n SMALL-WORLD ANALYSIS")
    B_largest = B.subgraph(max(nx.connected_components(B), key=len)).copy()

    sw = compute_small_world_statistics(B_largest)
    print("\n--- Small-World Report ---")
    print(f"L_real  = {sw['L_real']:.4f}")
    print(f"L_rand  = {sw['L_rand']:.4f}")
    print(f"C_real  = {sw['C_real']:.4f}")
    print(f"C_rand  = {sw['C_rand']:.4f}")
    print(f"\nSmall-world?    {'YES' if sw['small_world'] else 'NO'}")
    print("---------------------------")

    # 5) ROLE MATCHING BASED ON IMPRESSUM
    print("\n EXTRACTING ROLES FROM IMPRESSUM")

    impressum_path = "NZZ/impressum.html"  # adjust if needed
    impressum_roles = parse_impressum(impressum_path)

    print("\n MATCHING AUTHORS TO ROLES (Fuzzy Matching)")

    for node in largest.nodes():
        author_raw = largest.nodes[node].get("name") or str(node)

        # Exact match first
        if author_raw in impressum_roles:
            largest.nodes[node]["role"] = impressum_roles[author_raw]
            continue

        # Fuzzy match
        candidates = get_close_matches(
            author_raw, impressum_roles.keys(), n=1, cutoff=0.82
        )
        if candidates:
            match = candidates[0]
            largest.nodes[node]["role"] = impressum_roles[match]
        else:
            largest.nodes[node]["role"] = "Unknown"

    # Maybe we need to check the immressum html


if __name__ == "__main__":
    main()
