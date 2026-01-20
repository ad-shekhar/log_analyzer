"""Lightweight clustering using TF-IDF and MiniBatchKMeans."""

import re
from collections import Counter
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import MiniBatchKMeans

from .models import ErrorTemplate, ErrorCluster


# Stop words for log analysis (common log tokens that don't add meaning)
LOG_STOP_WORDS = [
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
    'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
    'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above',
    'below', 'between', 'under', 'again', 'further', 'then', 'once',
    'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few',
    'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
    'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but',
    'if', 'or', 'because', 'until', 'while', 'this', 'that', 'these',
    'those', 'it', 'its', 'log', 'logging', 'logger', 'timestamp', 'time',
    'date', 'level', 'message', 'msg', 'info', 'debug', 'warn', 'warning',
]


class ErrorClusterer:
    """
    Clusters similar error templates using TF-IDF and MiniBatchKMeans.
    
    This approach is:
    - Lightweight: Uses sparse matrices and incremental clustering
    - Explainable: Keywords are extracted from TF-IDF features
    - Interpretable: Each cluster has representative samples
    """
    
    def __init__(
        self,
        max_clusters: int = 10,
        min_samples_per_cluster: int = 2,
        max_features: int = 1000,
    ):
        """
        Initialize the clusterer.
        
        Args:
            max_clusters: Maximum number of clusters to create
            min_samples_per_cluster: Minimum samples needed to form a cluster
            max_features: Maximum TF-IDF features to use
        """
        self.max_clusters = max_clusters
        self.min_samples_per_cluster = min_samples_per_cluster
        
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            stop_words=LOG_STOP_WORDS,
            ngram_range=(1, 2),  # Unigrams and bigrams
            min_df=1,
            max_df=0.95,
            token_pattern=r'\b[a-zA-Z_][a-zA-Z0-9_]*\b',  # Code-like tokens
        )
        
        self._kmeans: Optional[MiniBatchKMeans] = None
        self._feature_names: list[str] = []
    
    def cluster_templates(
        self, 
        templates: dict[str, ErrorTemplate]
    ) -> list[ErrorCluster]:
        """
        Cluster error templates by similarity.
        
        Args:
            templates: Dictionary of template_key -> ErrorTemplate
            
        Returns:
            List of ErrorCluster objects
        """
        if not templates:
            return []
        
        template_list = list(templates.values())
        
        # If very few templates, don't cluster
        if len(template_list) < self.min_samples_per_cluster:
            return self._create_single_cluster(template_list)
        
        # Prepare text for vectorization
        texts = [self._prepare_text(t.template) for t in template_list]
        
        # Vectorize
        try:
            tfidf_matrix = self.vectorizer.fit_transform(texts)
            self._feature_names = self.vectorizer.get_feature_names_out().tolist()
        except ValueError:
            # If vectorization fails (e.g., all stop words), return single cluster
            return self._create_single_cluster(template_list)
        
        # Determine optimal number of clusters
        n_samples = len(template_list)
        n_clusters = min(
            self.max_clusters,
            max(1, n_samples // self.min_samples_per_cluster)
        )
        
        if n_clusters <= 1:
            return self._create_single_cluster(template_list)
        
        # Cluster
        self._kmeans = MiniBatchKMeans(
            n_clusters=n_clusters,
            random_state=42,
            batch_size=min(100, n_samples),
            n_init=3,
        )
        
        cluster_labels = self._kmeans.fit_predict(tfidf_matrix)
        
        # Build cluster objects
        clusters = self._build_clusters(
            template_list, 
            cluster_labels, 
            tfidf_matrix
        )
        
        return clusters
    
    def _prepare_text(self, template: str) -> str:
        """Prepare template text for vectorization."""
        # Remove placeholders for better clustering
        text = re.sub(r'<[A-Z_]+>', '', template)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _create_single_cluster(
        self, 
        templates: list[ErrorTemplate]
    ) -> list[ErrorCluster]:
        """Create a single cluster containing all templates."""
        if not templates:
            return []
        
        cluster = ErrorCluster(
            cluster_id=0,
            templates=templates,
            total_count=sum(t.count for t in templates),
            keywords=self._extract_keywords_simple(templates),
            representative_sample=templates[0].template if templates else "",
        )
        return [cluster]
    
    def _build_clusters(
        self,
        templates: list[ErrorTemplate],
        labels: np.ndarray,
        tfidf_matrix,
    ) -> list[ErrorCluster]:
        """Build ErrorCluster objects from clustering results."""
        clusters_dict: dict[int, list[ErrorTemplate]] = {}
        
        for i, label in enumerate(labels):
            if label not in clusters_dict:
                clusters_dict[label] = []
            clusters_dict[label].append(templates[i])
        
        clusters = []
        for cluster_id, cluster_templates in sorted(clusters_dict.items()):
            # Get indices for this cluster
            indices = [i for i, l in enumerate(labels) if l == cluster_id]
            
            # Extract keywords from cluster centroid
            keywords = self._extract_cluster_keywords(indices, tfidf_matrix)
            
            # Find representative sample (closest to centroid or highest count)
            representative = max(cluster_templates, key=lambda t: t.count)
            
            cluster = ErrorCluster(
                cluster_id=int(cluster_id),
                templates=cluster_templates,
                total_count=sum(t.count for t in cluster_templates),
                keywords=keywords,
                representative_sample=representative.template,
            )
            clusters.append(cluster)
        
        # Sort by total count (most important first)
        clusters.sort(key=lambda c: c.total_count, reverse=True)
        
        # Reassign cluster IDs after sorting
        for i, cluster in enumerate(clusters):
            cluster.cluster_id = i
        
        return clusters
    
    def _extract_cluster_keywords(
        self, 
        indices: list[int], 
        tfidf_matrix
    ) -> list[str]:
        """Extract top keywords for a cluster."""
        if not self._feature_names or not indices:
            return []
        
        # Average TF-IDF scores for documents in this cluster
        cluster_vectors = tfidf_matrix[indices].toarray()
        avg_scores = np.mean(cluster_vectors, axis=0)
        
        # Get top features
        top_indices = np.argsort(avg_scores)[-10:][::-1]
        keywords = [
            self._feature_names[i] 
            for i in top_indices 
            if avg_scores[i] > 0
        ]
        
        return keywords
    
    def _extract_keywords_simple(
        self, 
        templates: list[ErrorTemplate]
    ) -> list[str]:
        """Extract keywords without clustering (simple frequency-based)."""
        word_counts: Counter = Counter()
        
        for template in templates:
            # Tokenize
            words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', template.template.lower())
            # Filter stop words
            words = [w for w in words if w not in LOG_STOP_WORDS and len(w) > 2]
            word_counts.update(words)
        
        # Return top keywords
        return [word for word, _ in word_counts.most_common(10)]


def format_clusters_for_output(clusters: list[ErrorCluster]) -> list[dict]:
    """
    Format clusters for JSON output.
    
    Args:
        clusters: List of ErrorCluster objects
        
    Returns:
        List of dictionaries suitable for JSON serialization
    """
    output = []
    
    for cluster in clusters:
        # Get sample messages (up to 3 unique ones)
        samples = []
        seen_messages = set()
        for template in cluster.templates:
            for msg in template.original_messages:
                if msg not in seen_messages and len(samples) < 3:
                    samples.append(msg)
                    seen_messages.add(msg)
        
        output.append({
            "cluster_id": cluster.cluster_id,
            "total_occurrences": cluster.total_count,
            "unique_patterns": len(cluster.templates),
            "keywords": cluster.keywords,
            "representative_pattern": cluster.representative_sample,
            "sample_messages": samples,
        })
    
    return output
