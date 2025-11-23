import sqlite3
import ast
import pandas as pd
import networkx as nx
from pyvis.network import Network
import matplotlib.pyplot as plt
import numpy as np
from fa2_modified import ForceAtlas2


class ArticleGraphBuilder:
    """Loads NZZ article data, builds a graph, and performs graph analysis."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.df = None
        self.G = nx.Graph()
        self.components_sorted = None

    # === 1. Load data ===
    def load_data(self):
        """Load articles from SQLite into a DataFrame."""
        conn = sqlite3.connect(self.db_path)
        self.df = pd.read_sql("SELECT * FROM articles ORDER BY article_date DESC", conn)
        conn.close()

        print("Columns found:", self.df.columns.tolist())
        print(f"Loaded {len(self.df)} rows.")
        return self.df

    def _normalize_authors(self, author_field):
        """
        Convert author field into a list of authors.
        Handles your format:
        '["Alain Zucker", "Martin Berz"]'
        '["Alain Zucker"]'
        """
        if pd.isna(author_field):
            return []

        if isinstance(author_field, list):
            # Already a list
            return [a.strip() for a in author_field]

        if isinstance(author_field, str):
            try:
                parsed = ast.literal_eval(author_field)
                if isinstance(parsed, list):
                    return [a.strip() for a in parsed]
            except Exception:
                pass

        # fallback: single author
        return [str(author_field).strip()]

    def build_authors_graph(self):

        for author_group in self.df["authors"]:
            if pd.isna(author_group):
                continue

            # Convert string like '["Albert Steck", "Jürg Meier"]' into a Python list
            try:
                author_group = ast.literal_eval(author_group)
            except Exception as e:
                print(f"Error parsing related_articles for {author_group}: {e}")

            for i in range(len(author_group)):
                for j in range(i + 1, len(author_group)):
                    # Add edge between author_group[i] and author_group[j]

                    if self.G.has_edge(author_group[i], author_group[j]):
                        self.G[author_group[i]][author_group[j]]["weight"] += 10
                    else:
                        self.G.add_edge(author_group[i], author_group[j], weight=10)

    # === 2. Build graph ===
    def build_graph(self):
        """Build graph of articles and their related articles."""
        if self.df is None:
            raise ValueError("Data not loaded. Call load_data() first.")

        author_map = {
            row["article_id"]: self._normalize_authors(row["authors"])
            for _, row in self.df.iterrows()
        }

        # Add all authors as nodes
        all_authors = {a for authors in author_map.values() for a in authors}
        self.G.add_nodes_from(all_authors)

        for _, row in self.df.iterrows():
            source_id = row["article_id"]
            source_authors = author_map[source_id]
            # self.G.add_node(article)

            if pd.notnull(row["related_articles"]):
                try:
                    related_list = ast.literal_eval(row["related_articles"])
                    for target_id in related_list:

                        if target_id not in author_map:
                            continue

                        target_authors = author_map[target_id]

                        # print(target_authors)

                        for a1 in source_authors:
                            for a2 in target_authors:
                                if a1 == a2:
                                    continue

                                if self.G.has_edge(a1, a2):
                                    self.G[a1][a2]["weight"] += 1
                                else:
                                    self.G.add_edge(a1, a2, weight=1)

                except Exception as e:
                    print(f"Error parsing related_articles for {source_authors}: {e}")

        print(
            "Graph built with",
            len(self.G.nodes),
            "nodes and",
            len(self.G.edges),
            "edges.",
        )

    # === 3. Analyze connected components ===
    def analyze_components(self):
        """Compute connected components sorted by size."""
        components = list(nx.connected_components(self.G))
        self.components_sorted = sorted(components, key=len, reverse=True)

        print("Graph connected?", nx.is_connected(self.G))
        print("Number of components:", len(self.components_sorted))

        for i, comp in enumerate(self.components_sorted, 1):
            print(f"Component {i} (size {len(comp)}) and {comp}")

        return self.components_sorted

    # === 4. Find node with highest degree ===
    def highest_degree_node(self):
        """Return node with the most edges."""
        node, degree = max(self.G.degree, key=lambda x: x[1])
        print(f"Highest-degree node: {node} (degree {degree})")
        return node, degree

    def degree_of_author(self, author_name: str):
        if author_name not in self.G:
            print(f"Author '{author_name}' not found in graph.")
            return None

        deg = self.G.degree[author_name]
        print(f"Degree of '{author_name}': {deg}")
        return deg

    # === 5. Find the component containing a specific node ===
    def component_of_node(self, node_id: str):
        """Return component containing the given node."""
        if self.components_sorted is None:
            raise ValueError("Run analyze_components() first.")

        for comp in self.components_sorted:
            if node_id in comp:
                print(f"Node {node_id} is in a component of size {len(comp)}")
                return comp

        print(f"Node {node_id} not found.")
        return None

    # === 6. Get nodes not in the largest component ===
    def nodes_not_in_largest(self):
        """Return all nodes not in the largest connected component."""
        if self.components_sorted is None:
            raise ValueError("Run analyze_components() first.")

        largest = self.components_sorted[0]
        all_nodes = set(self.G.nodes)

        excluded = all_nodes - largest
        print(f"Nodes not in largest component: {len(excluded)}")
        return excluded

    def save_graph_to_gexf(self, filename="authors_graph.gexf"):
        """
        Save a NetworkX graph to a GEXF file.

        Parameters:
        -----------
        filename : str
            The name of the output GEXF file.
        """
        nx.write_gexf(self.G, filename)
        print(f"Graph successfully saved to {filename}")

    def get_largest_component_graph(self):

        largest_component = self.analyze_components()[0]

        G_largest = self.G.subgraph(largest_component).copy()

        return G_largest


def visualize_interactive(G, filename="authors_graph_weighted.html"):
    net = Network(
        notebook=False,
        height="800px",
        width="100%",
        bgcolor="#ffffff",
        font_color="#000000",
    )

    print(G.nodes())
    # Add nodes with size proportional to weighted degree
    for node in G.nodes():
        strength = G.degree(node, weight="weight")
        size = 5 + strength * 1.5
        net.add_node(
            node,
            label=node,
            size=size,  # node size
            title=f"Autor: {size}",
            shape="dot",  # ensures label is inside the node
            font={
                "size": 14,  # fixed font size
                "align": "center",  # center label over the circle
                "vadjust": 0,  # vertical adjustment (keeps text centered)
            },
        )

    # Add edges with weights
    for u, v, data in G.edges(data=True):
        w = data.get("weight", 1)
        net.add_edge(
            u,
            v,
            value=w,  # PyVis: used for physics weight
            title=f"Weight: {w}",
        )

    # ---- ForceAtlas2 with edge weights ----
    net.set_options(
        """
    {
        "configure": {
            "enabled": true,
            "filter": ["physics"]
        },
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -50,
                "centralGravity": 0.01,
                "springConstant": 0.2,
                "springLength": 80,
                "damping": 0.4,
                "avoidOverlap": 20
                },
            "solver": "forceAtlas2Based",
            "timestep": 0.4
        },
        "edges": {
            "scaling": {
            "min": 1,
            "max": 20
            }
        },
        "nodes": {
            "shape": "dots",
            "scaling": {
                "min": 5,
                "max": 50
            }
        }
    }
    """
    )
    # net.show_buttons(filter_=['physics'])
    net.write_html(filename, open_browser=True)
    print(f"Interactive visualization saved as: {filename}")


def normalize_node_sizes(values, new_min=5, new_max=100):
    """
    Normalize a list of numeric values into a given range [new_min, new_max].

    Parameters:
        values (list of float/int): Original values to normalize
        new_min (float): Lower bound of target range (default = 5)
        new_max (float): Upper bound of target range (default = 100)

    Returns:
        list of float: Normalized values
    """
    old_min = min(values)
    old_max = max(values)

    # Avoid division by zero if all values are the same
    if old_min == old_max:
        return [new_min for _ in values]

    return [
        new_min + (val - old_min) * (new_max - new_min) / (old_max - old_min)
        for val in values
    ]



def visualize_existing_graph_interactive(
    G,
    node_scale=5,
    figsize=(24, 16),
    weight_threshold=0,
    label_top_n=50,
    iterations=1000,
):
    # Filter edges by weight
    filtered_edges = [
        (u, v) for u, v, w in G.edges(data="weight") if w > weight_threshold
    ]
    H = G.edge_subgraph(filtered_edges).copy()

    # Compute node weights
    node_weights = {node: 0 for node in H.nodes()}
    #print(node_weights)
    for u, v, w in H.edges(data="weight"):
        node_weights[u] += w
        node_weights[v] += w

    node_sizes = [node_weights[n] * node_scale for n in H.nodes()]
    # pos = nx.spring_layout(H, weight='weight',scale=500, center=(0,0),seed=layout_seed, k=2)

    node_sizes = normalize_node_sizes(values=node_sizes)
    

    # Configure ForceAtlas2
    forceatlas2 = ForceAtlas2(
        outboundAttractionDistribution=False,
        linLogMode=False,
        adjustSizes=True,
        edgeWeightInfluence=1,
        jitterTolerance=1.0,
        barnesHutOptimize=True,
        barnesHutTheta=1.2,
        scalingRatio=100.0
        strongGravityMode=False,
        gravity=0.1,
        verbose=True,
    )

    # Compute layout
    pos = forceatlas2.forceatlas2_networkx_layout(H, pos=None, iterations=iterations)


    # Draw
    fig, ax = plt.subplots(figsize=figsize)


    nx.draw_networkx_nodes(
        H, pos, node_size=node_sizes, node_color="skyblue", alpha=0.7, ax=ax
    )
    # nx.draw_networkx_edges(H, pos, width=[H[u][v]['weight'] for u, v in H.edges()],
    #                        edge_color='gray', alpha=0.5, ax=ax)

    nx.draw_networkx_edges(H, pos, edge_color="gray",width=0.2, alpha=0.5, ax=ax)

    ax.set_title("Weighted Network Graph", fontsize=14)
    ax.axis("off")
    plt.tight_layout()

    # --- Helper: update labels dynamically ---
    def update_labels():
        # Clear old labels
        for artist in ax.texts:
            artist.remove()
        # Show labels only for nodes currently visible
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        visible_nodes = []
        for node, (x, y) in pos.items():
            if xlim[0] <= x <= xlim[1] and ylim[0] <= y <= ylim[1]:
                visible_nodes.append(node)
        # Limit to top-N by weight
        top_nodes = sorted(
            [(n, node_weights[n]) for n in visible_nodes],
            key=lambda x: x[1],
            reverse=True,
        )[:label_top_n]
        labels = {node: node for node, _ in top_nodes}
        nx.draw_networkx_labels(H, pos, labels=labels, font_size=8, ax=ax)

    # --- Add scroll zoom and pan ---
    def zoom(event):
        base_scale = 1.1
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        xdata = event.xdata
        ydata = event.ydata
        if xdata is None or ydata is None:
            return
        if event.button == "up":  # zoom in
            scale_factor = 1 / base_scale
        elif event.button == "down":  # zoom out
            scale_factor = base_scale
        else:
            scale_factor = 1
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
        ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
        update_labels()  # refresh labels after zoom
        fig.canvas.draw_idle()

    def pan(event):
        if event.button == 1 and event.inaxes == ax:  # left mouse drag
            dx = -event.xdata + pan.prev_x
            dy = -event.ydata + pan.prev_y
            cur_xlim = ax.get_xlim()
            cur_ylim = ax.get_ylim()
            ax.set_xlim(cur_xlim + dx)
            ax.set_ylim(cur_ylim + dy)
            update_labels()  # refresh labels after pan
            fig.canvas.draw_idle()
        pan.prev_x, pan.prev_y = event.xdata, event.ydata

    pan.prev_x, pan.prev_y = None, None
    fig.canvas.mpl_connect("scroll_event", zoom)
    fig.canvas.mpl_connect("motion_notify_event", pan)

    update_labels()

    plt.show(block=True)

# === Example Usage ===
if __name__ == "__main__":
    builder = ArticleGraphBuilder("nzz_scraped_articles.db")

    builder.load_data()
    builder.build_authors_graph()
    builder.build_graph()
    builder.analyze_components()

    builder.highest_degree_node()
    builder.component_of_node("Eric Gujer")
    builder.degree_of_author("Eric Gujer")
    builder.nodes_not_in_largest()
    # builder.save_graph_to_gexf(filename="authors_graph_100.gexf")

    # visualize_gephi_style(builder.G)

    # visualize_interactive(builder.G, filename="authors_graph_weighted.html")

    # visualize_gephi_style_no_overlap(builder.G)

    # visualize_existing_graph(builder.G)
    visualize_existing_graph_interactive(builder.get_largest_component_graph())
