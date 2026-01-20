#!/usr/bin/env python3
"""
Command-line tool for analyzing log files with pretty output.

Usage:
    python analyze.py samples/sample.log
    python analyze.py samples/sample.log --use-llm
    python analyze.py path/to/your.log --url http://localhost:8000
"""

import argparse
import json
import sys
import httpx
from pathlib import Path


def format_output(data: dict) -> str:
    """Format the analysis result for readable console output."""
    lines = []
    
    # Header
    lines.append("=" * 70)
    lines.append("                    LOG ANALYSIS REPORT")
    lines.append("=" * 70)
    lines.append("")
    
    # Summary section
    summary = data.get("summary", {})
    lines.append("📊 SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Total lines processed:  {summary.get('total_lines_processed', 0):,}")
    lines.append(f"  Error lines:            {summary.get('error_lines', 0):,}")
    lines.append(f"  Fatal lines:            {summary.get('fatal_lines', 0):,}")
    lines.append(f"  Warning lines:          {summary.get('warning_lines', 0):,}")
    lines.append(f"  Exceptions detected:    {summary.get('exceptions_detected', 0):,}")
    lines.append("")
    
    # Natural language summary
    nl_summary = data.get("natural_language_summary")
    if nl_summary:
        lines.append("💡 ANALYSIS")
        lines.append("-" * 40)
        # Word wrap the summary
        words = nl_summary.split()
        current_line = "  "
        for word in words:
            if len(current_line) + len(word) + 1 > 68:
                lines.append(current_line)
                current_line = "  " + word
            else:
                current_line += " " + word if current_line != "  " else word
        if current_line.strip():
            lines.append(current_line)
        lines.append("")
    
    # Top error templates
    templates = data.get("top_error_templates", [])
    if templates:
        lines.append("🔥 TOP ERROR PATTERNS")
        lines.append("-" * 40)
        for i, template in enumerate(templates[:5], 1):
            count = template.get("count", 0)
            pattern = template.get("pattern", "")
            # Truncate long patterns
            if len(pattern) > 55:
                pattern = pattern[:52] + "..."
            lines.append(f"  {i}. [{count:3}x] {pattern}")
        if len(templates) > 5:
            lines.append(f"      ... and {len(templates) - 5} more patterns")
        lines.append("")
    
    # Error clusters
    clusters = data.get("error_clusters", [])
    if clusters:
        lines.append("📦 ERROR CLUSTERS")
        lines.append("-" * 40)
        for cluster in clusters[:5]:
            cid = cluster.get("cluster_id", 0)
            total = cluster.get("total_occurrences", 0)
            patterns = cluster.get("unique_patterns", 0)
            keywords = cluster.get("keywords", [])[:4]
            keywords_str = ", ".join(keywords) if keywords else "N/A"
            
            lines.append(f"  Cluster #{cid + 1}: {total} occurrences ({patterns} patterns)")
            lines.append(f"    Keywords: {keywords_str}")
            
            # Show representative sample
            rep = cluster.get("representative_pattern", "")
            if rep:
                if len(rep) > 60:
                    rep = rep[:57] + "..."
                lines.append(f"    Pattern:  {rep}")
            lines.append("")
        
        if len(clusters) > 5:
            lines.append(f"  ... and {len(clusters) - 5} more clusters")
            lines.append("")
    
    # Footer
    processing_time = data.get("processing_time_ms", 0)
    lines.append("-" * 40)
    lines.append(f"⏱️  Processing time: {processing_time:.1f}ms")
    lines.append("=" * 70)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze log files and get a readable summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze.py samples/sample.log
  python analyze.py samples/sample.log --use-llm
  python analyze.py app.log --json
        """
    )
    parser.add_argument("logfile", help="Path to the log file to analyze")
    parser.add_argument("--url", default="http://localhost:8000", help="API server URL")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for summary")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted")
    parser.add_argument("--max-clusters", type=int, default=10, help="Maximum clusters")
    
    args = parser.parse_args()
    
    # Check file exists
    filepath = Path(args.logfile)
    if not filepath.exists():
        print(f"Error: File not found: {args.logfile}", file=sys.stderr)
        sys.exit(1)
    
    # Build URL with query params
    url = f"{args.url}/analyze"
    params = {
        "use_llm": str(args.use_llm).lower(),
        "max_clusters": args.max_clusters,
    }
    
    print(f"Analyzing {filepath.name}...", file=sys.stderr)
    
    try:
        with open(filepath, "rb") as f:
            files = {"file": (filepath.name, f, "application/octet-stream")}
            response = httpx.post(url, files=files, params=params, timeout=60.0)
        
        if response.status_code != 200:
            print(f"Error: API returned {response.status_code}", file=sys.stderr)
            print(response.text, file=sys.stderr)
            sys.exit(1)
        
        data = response.json()
        
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(format_output(data))
            
    except httpx.ConnectError:
        print(f"Error: Cannot connect to {args.url}", file=sys.stderr)
        print("Make sure the server is running: uvicorn app.main:app --reload", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
