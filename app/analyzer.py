"""Main analyzer orchestrating all components."""

import time
from typing import BinaryIO, Optional

from .ingestion import read_log_file
from .parsing import LogParser
from .normalization import LogNormalizer, LogLevel
from .clustering import ErrorClusterer
from .aggregation import build_analysis_result
from .llm_summary import generate_llm_summary, generate_basic_summary
from .models import AnalysisResult


class LogAnalyzer:
    """
    Main orchestrator for log analysis.
    
    Coordinates:
    - File ingestion (streaming)
    - Log parsing (JSON/plain-text, multiline)
    - Normalization and de-duplication
    - Clustering
    - Summary generation
    """
    
    def __init__(
        self,
        max_clusters: int = 10,
        min_level: LogLevel = LogLevel.WARN,
        use_llm: bool = False,
        llm_api_key: Optional[str] = None,
    ):
        """
        Initialize the analyzer.
        
        Args:
            max_clusters: Maximum number of error clusters
            min_level: Minimum log level to analyze
            use_llm: Whether to use LLM for summary generation
            llm_api_key: Optional OpenAI API key
        """
        self.parser = LogParser()
        self.normalizer = LogNormalizer(min_level=min_level)
        self.clusterer = ErrorClusterer(max_clusters=max_clusters)
        self.use_llm = use_llm
        self.llm_api_key = llm_api_key
    
    async def analyze(
        self, 
        file: BinaryIO, 
        filename: str
    ) -> AnalysisResult:
        """
        Analyze a log file and return structured results.
        
        Args:
            file: File-like object with binary content
            filename: Original filename (for format detection)
            
        Returns:
            AnalysisResult with analysis data
        """
        start_time = time.perf_counter()
        
        # Step 1: Ingest and parse
        lines = read_log_file(file, filename)
        parsed_entries = self.parser.parse_lines(lines)
        
        # Step 2: Count total and filter/normalize
        # We need to iterate twice: once for counting, once for processing
        # But we can combine by collecting entries
        all_entries = list(parsed_entries)
        total_lines = len(all_entries)
        
        # Step 3: Filter and normalize (creates templates)
        error_entries, templates = self.normalizer.process_entries(iter(all_entries))
        
        # Step 4: Cluster similar errors
        clusters = self.clusterer.cluster_templates(templates)
        
        # Step 5: Generate summary
        error_count = len(error_entries)
        fatal_count = sum(1 for e in error_entries if e.level == LogLevel.FATAL)
        
        llm_summary = None
        if self.use_llm and clusters:
            llm_summary = await generate_llm_summary(
                clusters=clusters,
                total_lines=total_lines,
                error_count=error_count,
                api_key=self.llm_api_key,
            )
        
        # If no LLM summary, generate basic one
        if not llm_summary:
            llm_summary = generate_basic_summary(
                clusters=clusters,
                total_lines=total_lines,
                error_count=error_count,
                fatal_count=fatal_count,
            )
        
        # Calculate processing time
        processing_time_ms = (time.perf_counter() - start_time) * 1000
        
        # Build result
        return build_analysis_result(
            total_lines=total_lines,
            error_entries=error_entries,
            templates=templates,
            clusters=clusters,
            processing_time_ms=processing_time_ms,
            llm_summary=llm_summary,
        )


def analyze_log_file_sync(
    file: BinaryIO,
    filename: str,
    max_clusters: int = 10,
    use_llm: bool = False,
    llm_api_key: Optional[str] = None,
) -> AnalysisResult:
    """
    Synchronous wrapper for log analysis.
    
    Args:
        file: File-like object with binary content
        filename: Original filename
        max_clusters: Maximum clusters to create
        use_llm: Whether to use LLM
        llm_api_key: Optional API key
        
    Returns:
        AnalysisResult
    """
    import asyncio
    
    analyzer = LogAnalyzer(
        max_clusters=max_clusters,
        use_llm=use_llm,
        llm_api_key=llm_api_key,
    )
    
    # Run async in sync context
    return asyncio.run(analyzer.analyze(file, filename))
