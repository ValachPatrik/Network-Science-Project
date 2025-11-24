import networkx as nx
from articles import ArticleGraphBuilderV2
from visualizer import GraphVisualizer
import community.community_louvain as community_louvain


import re

def run_louvain_with_resolution(G, resolution):
    """Run Louvain clustering with a custom resolution parameter."""
    return community_louvain.best_partition(
        G,
        weight="weight",
        resolution=resolution
    )


#  AUTHOR NAME CLEANING 

LOCATION_PREFIXES = [
    "Beirut", "Peking", "Genf", "Paris", "Bangkok", "Tokyo", "Tokio",
    "Nairobi", "London", "Saalbach", "Helsinki", "Ramallah"
]

NOISE_PATTERNS = [
    r"^NZZ", r"Redaktion", r"Bildredaktion", r"Chefredaktion",
    r"Interview", r"Visuals", r"Magazin", r"Fol.o", r"Geschichte",
]


def clean_author_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return None

    name = name.strip()
    name = name.replace("<br>", "").replace("<br/>", "")

    for loc in LOCATION_PREFIXES:
        if name.startswith(loc):
            parts = name.split(" ", 1)
            if len(parts) == 2:
                name = parts[1].strip()

    if "," in name:
        parts = [p.strip() for p in name.split(",") if len(p.strip()) > 1]
        parts = [p for p in parts if re.match(r"^[A-Za-zÄÖÜäöüß\-]{2,}", p)]
        if len(parts) == 1:
            name = parts[0]
        elif len(parts) >= 2:
            name = " ".join(parts[:2])

    if name in LOCATION_PREFIXES:
        return None

    for pat in NOISE_PATTERNS:
        if re.search(pat, name):
            return None

    if len(name) <= 2:
        return None

    if not re.search(r"[A-Za-zÄÖÜäöüß]", name):
        return None

    return name


#  CLEAN GRAPH ATTRIBUTES FOR GEXF EXPORT

def clean_graph_attributes(G):
    import math
    import numpy as np

    for n, data in G.nodes(data=True):
        for key, value in list(data.items()):
            if value is None or value is False:
                data[key] = ""
            elif isinstance(value, float) and (math.isnan(value) or np.isnan(value)):
                data[key] = ""
            elif isinstance(value, (list, dict)):
                data[key] = str(value)

    for u, v, data in G.edges(data=True):
        for key, value in list(data.items()):
            if value is None or value is False:
                data[key] = ""
            elif isinstance(value, float) and (math.isnan(value) or np.isnan(value)):
                data[key] = ""
            elif isinstance(value, (list, dict)):
                data[key] = str(value)


#  MAIN SCRIPT

def main():
    print("\n=== LOADING BUILDER V2 ===")
    builder = ArticleGraphBuilderV2()

    builder.load_data(limit=None)
    builder.build_related_graph()
    builder.analyze_components()

    largest = builder.get_largest_component_graph()

    # CLEAN AUTHOR NAMES

    print("\n=== CLEANING AUTHOR NAMES (Smart Mode) ===")

    cleaned_names = []
    for node in largest.nodes():
        raw = largest.nodes[node].get("name", node)
        cleaned = clean_author_name(raw)
        if cleaned:
            cleaned_names.append(cleaned)

    cleaned_names = sorted(set(cleaned_names))
    print(f"\nTotal cleaned authors: {len(cleaned_names)}\n")
    for a in cleaned_names:
        print(a)

    # DEFAULT CLUSTERING (resolution = 1.0)

    print("\n=== RUNNING LOUVAIN CLUSTERING (default resolution=1.0) ===")
    clusters_default = builder.compute_clusters(method="louvain")

    # RESOLUTION TUNING (“Resorts”)
    

    print("\n=== RUNNING LOUVAIN WITH CUSTOM RESOLUTIONS ===")
    clusters_res05 = run_louvain_with_resolution(largest, resolution=0.5)
    clusters_res15 = run_louvain_with_resolution(largest, resolution=1.5)

    print("\nCluster counts by resolution:")
    print(f"  resolution=0.5 → {len(set(clusters_res05.values()))} clusters")
    print(f"  resolution=1.0 → {len(set(clusters_default.values()))} clusters (default)")
    print(f"  resolution=1.5 → {len(set(clusters_res15.values()))} clusters")

    # CLUSTER QUALITY METRICS (Cluster coefficient, density, top authors)

    print("\n=== CLUSTER QUALITY METRICS ===")

    # Clustering Coefficient Per Node
    # Measures how many triangles each author participates in
    # A triangle means: A worked with B and C, and B also worked with C
    # Interpretation:
    # - Low coefficient: authors collaborate mostly 1-to-1, not in groups
    # - High coefficient: authors tend to co-author inside tightly knit
    #   groups where everyone works with everyone else.


    coeffs = nx.clustering(largest, weight="weight")

    # Average Clustering Coefficient per Community
    # Reflects how tightly connected a cluster is internally
    # Interpretation:
    # - Low avg coefficient (0.003–0.01):
    #       Large desks/sections with many authors who don't all
    #       collaborate with each other (loose, broad teams)
    # - High avg coefficient (>0.02):
    #       Small, tight editorial groups that frequently write together.

    cluster_avg_coeff = {}
    for node, cid in clusters_default.items():
        if cid < 0:
            continue
        cluster_avg_coeff.setdefault(cid, []).append(coeffs.get(node, 0))
    cluster_avg_coeff = {
        cid: sum(vals) / len(vals) for cid, vals in cluster_avg_coeff.items()
    }

    # Density per Cluster
    # Density = (# of existing edges) / (# of all possible edges)
    # Interpretation:
    # - Low density (0.02–0.08): large clusters where not everyone
    #       collaborates with everyone else — typical for big desks
    # - Medium density (0.1–0.3): mid-sized, partially connected teams
    # - High density (0.5–1.0): very small teams that collaborate heavily,
    #       often indicating a specific niche team or fixed project group


    cluster_densities = {}
    for cid in set(clusters_default.values()):
        if cid < 0:
            continue
        nodes = [n for n, c in clusters_default.items() if c == cid]
        sub = largest.subgraph(nodes)
        cluster_densities[cid] = nx.density(sub)

    # Top Authors per Cluster (Highest Degree)
    # Identifies the "hub authors" inside each community
    # They typically:
    # - collaborate with the largest number of people,
    # - act as central connectors inside a desk,
    # - often correspond to senior journalists, editors,
    #   or writers involved in cross-desk projects


    top_authors = {}
    for cid in set(clusters_default.values()):
        if cid < 0:
            continue
        nodes = [n for n, c in clusters_default.items() if c == cid]
        top_nodes = sorted(nodes, key=lambda x: largest.degree(x), reverse=True)[:5]
        top_authors[cid] = [
            largest.nodes[n].get("name", n) for n in top_nodes
        ]

    print("\n=== CLUSTER REPORT ===")
    for cid in sorted(cluster_avg_coeff.keys()):
        print(f"\nCluster {cid}:")
        print(f"  Avg Clustering Coefficient: {cluster_avg_coeff[cid]:.4f}")
        print(f"  Density: {cluster_densities[cid]:.4f}")
        print(f"  Top Authors: {', '.join(top_authors[cid])}")

   
    # Save to GEXF
    
    print("\nCleaning graph for GEXF export...")
    clean_graph_attributes(largest)

    for node in largest.nodes():
        largest.nodes[node]["cluster"] = clusters_default.get(node, -1)

    nx.write_gexf(largest, "author_clusters_louvain.gexf")
    nx.write_gexf(largest, "author_clusters_with_colors.gexf")

    print(" Saved: author_clusters_louvain.gexf")
    print(" Saved: author_clusters_with_colors.gexf")


    # Visualization

    print("\n=== VISUALIZING ===")
    cluster_colors = {node: clusters_default.get(node, -1) for node in largest.nodes()}
    vis = GraphVisualizer()

    vis.visualize_existing_graph_interactive(
        largest,
        show_names=True,
        cluster_colors=cluster_colors,
        node_scale=5,
        weight_threshold=0,
        iterations=1200,
    )

    print("\n DONE.")


if __name__ == "__main__":
    main()
