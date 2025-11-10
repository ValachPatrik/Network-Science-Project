# analysis_nzz.py
import sqlite3
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import networkx as nx

# === 1. Load data from database ===
conn = sqlite3.connect("nzz_scraped_articles.db")

# Load all columns (in case naming differs)
df = pd.read_sql("SELECT * FROM articles", conn)
conn.close()

print("Columns found in DB:", df.columns.tolist())
print(f"Loaded {len(df)} total rows.")

# === 2. Normalize column names ===
cols = [c.lower() for c in df.columns]
df.columns = cols

# Try to locate title/description/author columns
title_col = next((c for c in cols if "title" in c), None)
desc_col = next((c for c in cols if "description" in c or "content" in c), None)
author_col = next((c for c in cols if "author" in c), None)

if not title_col:
    raise KeyError("No column containing 'title' found in database.")

# === 3. Create combined text field ===
if desc_col:
    df["text"] = df[title_col].fillna('') + " " + df[desc_col].fillna('')
else:
    df["text"] = df[title_col].fillna('')

df = df.dropna(subset=["text"])
texts = df["text"].astype(str).tolist()

print(f"Prepared {len(texts)} texts for TF-IDF vectorization.")

# === 4. TF-IDF embeddings ===
vectorizer = TfidfVectorizer(max_features=3000)
X = vectorizer.fit_transform(texts)

# === 5. Compute cosine similarity ===
similarity = cosine_similarity(X)

# === 6. Build graph (edges if sim > 0.3) ===
G = nx.Graph()
for i in range(len(df)):
    node_title = str(df.iloc[i].get(title_col, "") or "").strip()
    node_author = str(df.iloc[i].get(author_col, "Unknown") or "Unknown").strip()
    G.add_node(i, title=node_title, author=node_author)


threshold = 0.3
for i in range(len(df)):
    for j in range(i + 1, len(df)):
        if similarity[i, j] > threshold:
            G.add_edge(i, j, weight=float(similarity[i, j]))

print(f"Graph created with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")

# === 7. Save to Gephi-compatible file ===
nx.write_gexf(G, "nzz_article_network.gexf")
print("✅ Graph exported to nzz_article_network.gexf (open with Gephi)")
