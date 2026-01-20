"""Response aggregation and summary generation."""

from typing import Iterator

from .models import ParsedLogEntry, LogLevel, ErrorTemplate, ErrorCluster, AnalysisResult
from .clustering import format_clusters_for_output


def compute_statistics(
    entries: Iterator[ParsedLogEntry],
) -> dict[str, int]:
    """
    Compute basic statistics from log entries.
    
    Args:
        entries: Iterator of parsed log entries
        
    Returns:
        Dictionary with counts by level
    """
    stats = {
        "total": 0,
        "trace": 0,
        "debug": 0,
        "info": 0,
        "warn": 0,
        "error": 0,
        "fatal": 0,
        "unknown": 0,
        "exceptions": 0,
    }
    
    for entry in entries:
        stats["total"] += 1
        
        level_key = entry.level.name.lower()
        if level_key in stats:
            stats[level_key] += 1
        
        if entry.has_exception:
            stats["exceptions"] += 1
    
    return stats


def format_templates_for_output(
    templates: list[ErrorTemplate], 
    top_n: int = 10
) -> list[dict]:
    """
    Format top error templates for JSON output.
    
    Args:
        templates: List of ErrorTemplate objects (sorted by count)
        top_n: Number of templates to include
        
    Returns:
        List of dictionaries suitable for JSON serialization
    """
    output = []
    
    for template in templates[:top_n]:
        output.append({
            "pattern": template.template,
            "count": template.count,
            "first_seen_line": template.first_occurrence_line,
            "examples": template.original_messages[:3],
        })
    
    return output


def build_analysis_result(
    total_lines: int,
    error_entries: list[ParsedLogEntry],
    templates: dict[str, ErrorTemplate],
    clusters: list[ErrorCluster],
    processing_time_ms: float,
    llm_summary: str = None,
) -> AnalysisResult:
    """
    Build the final analysis result.
    
    Args:
        total_lines: Total number of lines processed
        error_entries: List of high-signal log entries
        templates: Dictionary of de-duplicated templates
        clusters: List of error clusters
        processing_time_ms: Processing time in milliseconds
        llm_summary: Optional LLM-generated summary
        
    Returns:
        AnalysisResult object
    """
    # Count by level
    level_counts = {level: 0 for level in LogLevel}
    exception_count = 0
    
    for entry in error_entries:
        level_counts[entry.level] += 1
        if entry.has_exception:
            exception_count += 1
    
    # Get top templates sorted by count
    sorted_templates = sorted(
        templates.values(),
        key=lambda t: t.count,
        reverse=True
    )
    
    return AnalysisResult(
        total_lines=total_lines,
        error_lines=level_counts.get(LogLevel.ERROR, 0),
        fatal_lines=level_counts.get(LogLevel.FATAL, 0),
        warning_lines=level_counts.get(LogLevel.WARN, 0),
        exception_count=exception_count,
        top_templates=format_templates_for_output(sorted_templates),
        clusters=format_clusters_for_output(clusters),
        llm_summary=llm_summary,
        processing_time_ms=processing_time_ms,
    )


def prepare_cluster_summary_for_llm(clusters: list[ErrorCluster]) -> str:
    """
    Prepare a sanitized summary of clusters for LLM consumption.
    
    IMPORTANT: This should never include raw log data, only
    sanitized patterns and statistics.
    
    Args:
        clusters: List of error clusters
        
    Returns:
        Sanitized text summary suitable for LLM input
    """
    if not clusters:
        return "No error clusters detected."
    
    lines = ["Error Cluster Summary:", ""]
    
    for cluster in clusters:
        lines.append(f"Cluster {cluster.cluster_id + 1}:")
        lines.append(f"  - Occurrences: {cluster.total_count}")
        lines.append(f"  - Unique patterns: {len(cluster.templates)}")
        lines.append(f"  - Keywords: {', '.join(cluster.keywords[:5])}")
        lines.append(f"  - Representative pattern: {cluster.representative_sample[:200]}")
        lines.append("")
    
    return "\n".join(lines)
