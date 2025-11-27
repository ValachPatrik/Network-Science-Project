import networkx as nx
import pandas as pd

class CentralityAnalysis:
    """Performs centrality analysis on a given graph."""

    def __init__(self, graph: nx.Graph):
        """Initialize with a NetworkX graph."""
        self.graph = graph
        self.centrality_measures = {}

    def compute_degree_centrality(self):
        """Compute degree centrality for the graph."""
        self.centrality_measures['degree'] = nx.degree_centrality(self.graph)

        return self.centrality_measures['degree']   

    def compute_betweenness_centrality(self):
        """Compute betweenness centrality for the graph."""
        self.centrality_measures['betweenness'] = nx.betweenness_centrality(self.graph)

        return self.centrality_measures['betweenness']

    def compute_closeness_centrality(self):
        """Compute closeness centrality for the graph."""
        self.centrality_measures['closeness'] = nx.closeness_centrality(self.graph)

        return self.centrality_measures['closeness']

    def compute_eigenvector_centrality(self):
        """Compute eigenvector centrality for the graph."""
        self.centrality_measures['eigenvector'] = nx.eigenvector_centrality(self.graph, max_iter=1000)

        return self.centrality_measures['eigenvector']    

    def get_centrality_dataframe(self) -> pd.DataFrame:
        """Return a DataFrame with all computed centrality measures."""
        df = pd.DataFrame(self.centrality_measures)
        return df    