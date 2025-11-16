# author_network.py
import sqlite3
import pandas as pd
import itertools
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# === 1. Load articles from NZZ database ===
conn = sqlite3.connect("nzz_scraped_articles.db")
df = pd.read_sql("SELECT author, title, content, description FROM articles", conn)
conn.close()

# === 2. Combine text and clean ===
df["text"] = (
    df["title"].fillna('') + " " +
    df["description"].fillna('') + " " +
    df["content"].fillna('')
).str.strip()

df = df.dropna(subset=["text", "author"])
df = df[df["author"].str.strip() != ""]  # remove empty authors

print(f"Loaded {len(df)} articles from {df['author'].nunique()} unique authors.")

# === 3. Compute textual similarity ===
vectorizer = TfidfVectorizer(max_features=3000)
X = vectorizer.fit_transform(df["text"])
similarity = cosine_similarity(X)

# === 4. Build Author–Author network ===
G = nx.Graph()

for (i, j) in itertools.combinations(range(len(df)), 2):
    if similarity[i, j] > 0.3:  # similarity threshold
        a1, a2 = df.iloc[i]["author"], df.iloc[j]["author"]
        if a1 != a2:  # link different authors
            if G.has_edge(a1, a2):
                G[a1][a2]["weight"] += similarity[i, j]
            else:
                G.add_edge(a1, a2, weight=similarity[i, j])

print(f"Author network: {G.number_of_nodes()} authors, {G.number_of_edges()} edges.")

# === 5. Export to Gephi format ===
nx.write_gexf(G, "author_network.gexf")
print("Exported to author_network.gexf — open it in Gephi.")
