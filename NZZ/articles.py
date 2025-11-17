import sqlite3
import networkx as nx
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import re
import plotly.graph_objects as go
import json
import ast


# === 1. Load data from database ===
conn = sqlite3.connect("nzz_scraped_articles.db")

# Load all columns (in case naming differs)
df = pd.read_sql("SELECT * FROM articles ORDER BY article_date DESC", conn)

conn.close()

print("Columns found in DB:", df.columns.tolist())
print(f"Loaded {len(df)} total rows.")

df.info()
# df = df.dropna()

print(df.head())

# # Create a new graph
G = nx.Graph()
print(type(df.loc[0, 'related_articles']))

for _, row in df.iterrows():
    article = row['article_id']
    G.add_node(article)
    
    # related_articles is already a list of strings
    if pd.notnull(row['related_articles']):
        try:
            related_list = ast.literal_eval(row['related_articles'])  # convert string repr of list to actual list
            for rel in related_list:
                G.add_edge(article, rel)
        except Exception as e:
            print(f"Error parsing related_articles for {article}: {e}")

# Check if the graph is connected
is_connected = nx.is_connected(G)
print("Graph connected?", is_connected)

# If not connected, get number of connected components
if not is_connected:
    # components = nx.number_connected_components(G)
    

    # Get all connected components
    components = list(nx.connected_components(G))

    print("Number of connected components:", len(components))

    # Sort them by size (descending)
    components_sorted = sorted(components, key=len, reverse=True)

    # Print results
    for i, comp in enumerate(components_sorted, 1):
        print(f"Component {i} (size {len(comp)}): {comp}")

# # Draw the graph
# plt.figure(figsize=(12, 8))
# pos = nx.spring_layout(G, k=0.3)
# nx.draw(G, pos, with_labels=True, node_size=500, node_color="skyblue", font_size=8, edge_color="gray")
# plt.title("Network of Articles and Related Articles")
# plt.show()

node, degree = max(G.degree, key=lambda x: x[1])

print(f"Node with most edges: {node} (degree: {degree})")

# edges = list(G.edges(node))
# print(f"Edges of node {node}:")
# for edge in edges:
#     print(edge)

target_node = "1911310"
component_of_node = None

for comp in components_sorted:
    if target_node in comp:
        component_of_node = comp
        break

if component_of_node:
    print(f"Node {target_node} is in a component of size {len(component_of_node)}")
    #print(component_of_node)
else:
    print(f"Node {target_node} not found in the graph")


# Component 1 (largest)
largest_component = components[0]

# All nodes in the graph
all_nodes = set(G.nodes())

# Nodes not in component 1
nodes_not_in_component1 = all_nodes - largest_component

print(f"Total nodes not in component 1: {len(nodes_not_in_component1)}")


#g_random = nx.algorithms.smallworld.random_reference(G=G,niter=7,connectivity=False)