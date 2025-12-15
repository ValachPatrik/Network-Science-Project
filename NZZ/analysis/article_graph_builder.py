import pandas as pd
import networkx as nx
import ast
import itertools
import os
from typing import List, Dict, Sequence, Iterable, Any, Optional, Tuple
from collections import defaultdict

import logging

try:
    from .multilayer_network import MultiLayerAuthorGraph
except ImportError:
    from multilayer_network import MultiLayerAuthorGraph


# Conditional imports based on your new code's requirements
try:
    from sqlalchemy import create_engine
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


logger = logging.getLogger("author_network")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
class ArticleGraphBuilder:
    """
    Loads NZZ article data from Supabase, builds multilayer author graphs, 
    and performs initial graph analysis.
    """

    def __init__(self):
        """Initialize ArticleGraphBuilder with Supabase PostgreSQL connection."""
        if not HAS_SQLALCHEMY:
            raise ImportError(
                "SQLAlchemy is required. Install with: pip install sqlalchemy psycopg2-binary python-dotenv"
            )

        # State Variables
        self.df: Optional[pd.DataFrame] = None
        self.G: nx.Graph = nx.Graph()  # Combined graph
        self.author_map: Optional[Dict[str, List[str]]] = None
        self.all_authors: Optional[List[str]] = None
        
        # Analysis results storage (from new code)
        self.components_sorted = None
        self.clusters = None
        self.cluster_counts = {}
        self.cluster_author_map = {}
        self.authors_to_category = {}

        # PostgreSQL connection parameters from environment
        self.user = os.getenv("user")
        self.password = os.getenv("password")
        self.host = os.getenv("host")
        self.port = os.getenv("port", "5432")
        self.dbname = os.getenv("dbname")

        # Validate connection parameters
        if not all([self.user, self.password, self.host, self.dbname]):
            missing = [k for k in ["user", "password", "host", "dbname"] if not os.getenv(k)]
            raise ValueError(
                f"Missing required database connection parameters: {', '.join(missing)}\n"
                "Set the following in your .env file..."
            )

        # Create SQLAlchemy engine
        self.engine = self._create_engine()


    def _create_engine(self):
        """Create SQLAlchemy engine for PostgreSQL (Supabase) connection."""
        try:
            connection_string = (
                f"postgresql://{self.user}:{self.password}@"
                f"{self.host}:{self.port}/{self.dbname}"
            )
            # Add connect_args to increase statement timeout (in milliseconds)
            engine = create_engine(
                connection_string,
                pool_pre_ping=True,
                connect_args={
                    "connect_timeout": 30,
                    "options": "-c statement_timeout=300000",  # 5 minutes
                },
            )
            return engine
        except Exception as e:
            raise ConnectionError(f"Failed to create database engine: {e}")

    # === 1. Load data ===
    def load_data(self, limit: Optional[int] = None, chunk_size: int = 10000) -> pd.DataFrame:
        """Load articles from Supabase PostgreSQL into a DataFrame."""
        try:
            # First, try to get total count
            count_query = "SELECT COUNT(*) FROM articles"
            total_count = pd.read_sql(count_query, self.engine).iloc[0, 0]
            print(f"Total articles in database: {total_count:,}")

            total_to_load = min(limit, total_count) if limit else total_count

            # Columns to select, using COALESCE for fallback
            columns = "article_id, authors, category, COALESCE(related_articles_filtered, related_articles) as related_articles_filtered"

            # If dataset is large, load in chunks
            if total_to_load > chunk_size:
                # Chunked loading logic (omitted for brevity, keeping existing print statements)
                chunks = []
                offset = 0

                while offset < total_to_load:
                    current_chunk_size = min(chunk_size, total_to_load - offset)
                    query = (
                        f"SELECT {columns} FROM articles "
                        f"ORDER BY article_date DESC "
                        f"LIMIT {current_chunk_size} OFFSET {offset}"
                    )
                    print(
                        f"Loading chunk: rows {offset:,} to {offset + current_chunk_size:,}..."
                    )
                    chunk_df = pd.read_sql(query, self.engine)
                    if len(chunk_df) == 0:
                        break
                    chunks.append(chunk_df)
                    offset += len(chunk_df)

                self.df = pd.concat(chunks, ignore_index=True)
            else:
                # Small dataset, load all at once
                query = f"SELECT {columns} FROM articles ORDER BY article_date DESC"
                if limit:
                    query += f" LIMIT {limit}"
                print("Loading data from Supabase...")
                self.df = pd.read_sql(query, self.engine)

            print("Columns found:", self.df.columns.tolist())
            print(f"Loaded {len(self.df)} rows.")
            return self.df
        except Exception as e:
            error_msg = str(e)
            if (
                "statement timeout" in error_msg.lower()
                or "querycanceled" in error_msg.lower()
            ):
                print("Warning: Query timed out. Consider using load_data(limit=N).")
            raise ConnectionError(f"Failed to load data from database: {e}")

    # === 2. Data Preprocessing ===
    def _normalize_authors(self, author_field: Any) -> List[str]:
        """
        Convert author field into a list of cleaned author strings.
        Handles list, JSON string, and single string formats.
        """
        if pd.isna(author_field):
            return []
        
        if isinstance(author_field, list):
            return [str(a).strip() for a in author_field if str(a).strip()]

        if isinstance(author_field, str):
            try:
                # Attempt to parse a string representing a list (JSON or Python literal)
                parsed = ast.literal_eval(author_field)
                if isinstance(parsed, list):
                    return [str(a).strip() for a in parsed if str(a).strip()]
            except Exception:
                pass

            # Fallback for a single string author
            return [author_field.strip()]
        
        return [str(author_field).strip()] if str(author_field).strip() else []
    

    def _parse_related_articles(self, value: object) -> List[str]:
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


    def build_author_map(self) -> Dict[str, List[str]]:
        """
        Builds a mapping of article_id -> normalized list of authors 
        and identifies all unique authors.
        """
        if self.df is None:
            raise RuntimeError("DataFrame is not loaded. Call load_data() first.")
            
        print("Building author map...")
        
        author_map: Dict[str, List[str]] = {}
        all_authors_set: set[str] = set()

        for row in self.df.itertuples(index=False):
            authors = self._normalize_authors(getattr(row, 'authors', None))
            
            article_id = getattr(row, 'article_id', None)
            if article_id is not None:
                str_article_id = str(article_id)
                author_map[str_article_id] = authors
                all_authors_set.update(authors)
                
                # Also store category membership for later node attributes
                category = getattr(row, 'category', 'Unknown')
                for author in authors:
                    # Simple assignment; complex logic (e.g., majority category) would go here
                    self.authors_to_category[author] = category 

        self.author_map = author_map
        self.all_authors = sorted(list(all_authors_set))
        
        print(f"Total unique authors identified: {len(self.all_authors)}")
        return self.author_map

    # === 3. Layer Construction Methods===

    def build_coauthor_layer(self) -> nx.Graph:
        """Create the co-authorship layer where weights are joint article counts."""
        if not self.author_map or not self.all_authors:
            raise RuntimeError("Must call build_author_map() first.")

        G = nx.Graph(layer="coauthor")
        G.add_nodes_from(self.all_authors)
        
        for authors in self.author_map.values():
            unique_authors = sorted(set(a for a in authors if a))
            if len(unique_authors) < 2:
                continue
            
            for a1, a2 in itertools.combinations(unique_authors, 2):
                if G.has_edge(a1, a2):
                    G[a1][a2]["weight"] += 1
                else:
                    G.add_edge(a1, a2, weight=1)

        self.summarize_graph("Co-Author Layer", G)
        return G

    def build_related_layer(self) -> nx.Graph:
        """Create the related-articles layer with weights equal to shared references/links."""
        if not self.df is None and "related_articles_filtered" not in self.df.columns:
            # Check if the needed column exists after loading
            pass

        if not self.author_map or not self.all_authors:
            raise RuntimeError("Must call build_author_map() first.")

        G = nx.Graph(layer="related")
        G.add_nodes_from(self.all_authors)

        # Determine the column for related articles (relies on load_data COALESCE)
        related_column = "related_articles_filtered"
        if related_column not in self.df.columns:
            print("Warning: Column 'related_articles_filtered' not found after load. Returning empty layer.")
            return G

        for row in self.df.itertuples(index=False):
            source_id = str(getattr(row, 'article_id', None))
            source_authors = self.author_map.get(source_id, [])
            if not source_authors:
                continue

            related_field = getattr(row, related_column, None)
            related_list = self._parse_related_articles(related_field)
            if not related_list:
                continue
            
            for target_id in related_list:
                target_authors = self.author_map.get(target_id, [])
                if not target_authors:
                    continue
                
                # Edges between every source author and every target author
                for a1 in source_authors:
                    for a2 in target_authors:
                        if a1 == a2:
                            continue 
                        
                        # Accumulate edge weight
                        u, v = (a1, a2) if a1 < a2 else (a2, a1)
                        
                        if G.has_edge(u, v):
                            G[u][v]["weight"] += 1
                        else:
                            G.add_edge(u, v, weight=1)

        self.summarize_graph("Related-Article Layer", G)
        return G

    # === 4. Analysis Methods===

    def summarize_graph(self, name: str, G: nx.Graph) -> None:
        """Print quick stats about a graph/layer."""
        
        num_nodes = G.number_of_nodes()
        num_edges = G.number_of_edges()
        
        if num_nodes == 0:
             print(f"{name} → nodes: 0 | edges: 0")
             return

        # Ensure all nodes are added to the graph before checking components
        if self.all_authors:
            G.add_nodes_from(self.all_authors)

        # Components are only calculated for the largest graphs
        components = list(nx.connected_components(G))
        largest_component = max((len(c) for c in components), default=0)
        
        density = nx.density(G) if num_nodes > 1 else 0.0
        isolated_nodes = len(list(nx.isolates(G)))

        # Using print as placeholder for logger.info
        print(
            f"{name} → nodes: {num_nodes} | edges: {num_edges} | largest component: {largest_component} | density: {density:.4f} | isolates: {isolated_nodes}"
        )
    
    def build_base_graph(self, limit: Optional[int]) -> Tuple[nx.Graph, Dict[str, int]]:
        """
        Builds the base, unweighted, combined graph and its degree profile.
        
        The process involves: Loading data -> Building author map -> Building layers 
        -> Combining layers (sum) -> Removing weights for a 'base' unweighted graph.
        """
        # 1. Load Data
        self.load_data(limit=limit)

        # 2. Build Author Map (and self.all_authors)
        self.build_author_map()
        
        # 3. Build Layers (via the internal pipeline method)
        # We use a placeholder for MultiLayerAuthorGraph for execution logic
        layers, combined_weighted = self.build_empirical_multilayer(
            limit=None, # Already filtered by self.load_data(limit)
            combine_mode="sum", 
            run_load_data=False # Already loaded
        )

        # 4. Summarize (already done inside build_empirical_multilayer)
        # builder.summarize_graph("coauthor (empirical)", layers["coauthor"])
        # builder.summarize_graph("related (empirical)", layers["related"])
        # builder.summarize_graph("combined (empirical)", combined_weighted)

        # 5. Create the Base Graph (unweighted version of the combined graph)
        base_graph = nx.Graph()
        base_graph.add_nodes_from(combined_weighted.nodes())
        # Adding edges without weights (by not passing data=True)
        base_graph.add_edges_from(combined_weighted.edges()) 

        degree_profile = dict(base_graph.degree())
        
        # logger.info (using print as placeholder)
        avg_degree = (sum(degree_profile.values()) / max(len(degree_profile), 1)) if degree_profile else 0.0
        print(
            f"Base graph contains {base_graph.number_of_nodes()} authors and {base_graph.number_of_edges()} edges. Avg degree {avg_degree:.2f}"
        )
        return base_graph, degree_profile


    def build_empirical_multilayer(
        self, 
        limit: Optional[int], 
        combine_mode: str = "sum", 
        run_load_data: bool = True
    ) -> Tuple[Dict[str, nx.Graph], nx.Graph]:
        """
        Build and return the empirical multilayer author graphs.

        The method handles the full pipeline: load data, build layers, and combine.

        Returns
        -------
        layers : dict[str, nx.Graph]
            Dictionary with entries ``"coauthor"`` and ``"related"``.
        combined : nx.Graph
            Combined multilayer graph produced via ``combine_mode``.
        """
        # Ensure MultiLayerAuthorGraph is available.
        # Placeholder/Assumption: MultiLayerAuthorGraph is imported or accessible.
        try:
             MultiLayerAuthorGraph
        except NameError:
             raise NameError("MultiLayerAuthorGraph class must be defined/imported to use this method.")


        # 1. Load data and build author map if not already done
        if run_load_data or self.df is None:
            self.load_data(limit=limit)
        
        if self.author_map is None:
            self.build_author_map()
        
        # Since the class methods already work on self.df, we don't need to copy df or pass author_map/all_authors
        # The original functions needed df.copy() because they were *external*.

        # 2. Initialize multilayer container
        multilayer = MultiLayerAuthorGraph()

        # 3. Build Layers
        coauthor_graph = self.build_coauthor_layer()
        self.summarize_graph("coauthor", coauthor_graph)
        multilayer.add_layer("coauthor", coauthor_graph)

        related_graph = self.build_related_layer()
        self.summarize_graph("related", related_graph)
        multilayer.add_layer("related", related_graph)

        # 4. Combine Layers
        combined_graph = multilayer.combine_layers(mode=combine_mode)
        self.summarize_graph("combined", combined_graph)

        layers = {"coauthor": coauthor_graph, "related": related_graph}
        return layers, combined_graph
