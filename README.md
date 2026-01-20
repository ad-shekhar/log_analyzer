# Intelligent Log Analyzer

A lightweight, user-friendly log analysis tool that helps developers quickly understand what went wrong without reading thousands of log lines.

## Features

- **Smart File Handling**: Supports `.log`, `.txt`, and `.gz` compressed files with streaming I/O for large files
- **Flexible Parsing**: Handles both JSON and plain-text logs, including multiline stack traces
- **Noise Reduction**: Extracts only high-signal errors (ERROR, FATAL, Exceptions, Tracebacks, timeouts)
- **Template De-duplication**: Collapses repetitive logs by replacing variable values (IDs, IPs, UUIDs, numbers) with placeholders
- **Error Clustering**: Groups similar errors using TF-IDF + MiniBatchKMeans for interpretable clusters
- **Actionable Summaries**: Returns structured JSON with statistics, patterns, and clusters
- **Optional LLM Integration**: Generate natural language summaries (LLM only sees sanitized patterns, never raw logs)

## Quick Start

### Installation

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### Running the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### API Documentation

Interactive docs available at: `http://localhost:8000/docs`

## Usage

### Analyze a Log File

```bash
curl -X POST "http://localhost:8000/analyze" \
     -F "file=@your-application.log"
```

### With Options

```bash
curl -X POST "http://localhost:8000/analyze" \
     -F "file=@your-application.log" \
     -F "max_clusters=10" \
     -F "min_level=error"
```

### With LLM Summary (uses Gemini free tier)

```bash
# Uses built-in Gemini API key by default, or set your own:
# export GEMINI_API_KEY=your-key
curl -X POST "http://localhost:8000/analyze?use_llm=true" \
     -F "file=@your-application.log"
```

## Response Format

```json
{
  "summary": {
    "total_lines_processed": 50000,
    "error_lines": 342,
    "fatal_lines": 2,
    "warning_lines": 1205,
    "exceptions_detected": 89
  },
  "top_error_templates": [
    {
      "pattern": "Connection to <IP>:<PORT> refused after <DURATION>",
      "count": 156,
      "first_seen_line": 1234,
      "examples": [
        "Connection to 192.168.1.100:5432 refused after 30s",
        "Connection to 10.0.0.50:5432 refused after 30s"
      ]
    }
  ],
  "error_clusters": [
    {
      "cluster_id": 0,
      "total_occurrences": 245,
      "unique_patterns": 3,
      "keywords": ["connection", "refused", "timeout", "database"],
      "representative_pattern": "Connection to <IP>:<PORT> refused after <DURATION>",
      "sample_messages": ["Connection to 192.168.1.100:5432 refused after 30s"]
    }
  ],
  "natural_language_summary": "Processed 50,000 lines. Found 342 error entries grouped into 5 clusters. Most frequent issue (245 occurrences): related to connection, refused, timeout. Suggested investigation: Search codebase for 'connection'.",
  "processing_time_ms": 1234.56
}
```

## Architecture

```
app/
├── __init__.py          # Package initialization
├── main.py              # FastAPI application and endpoint
├── analyzer.py          # Main orchestrator
├── models.py            # Data models (ParsedLogEntry, ErrorTemplate, etc.)
├── ingestion.py         # File reading with streaming support
├── parsing.py           # JSON/plain-text parsing, multiline handling
├── normalization.py     # Variable replacement, de-duplication
├── clustering.py        # TF-IDF + MiniBatchKMeans clustering
├── aggregation.py       # Result building and formatting
└── llm_summary.py       # Optional LLM integration
```

### Module Responsibilities

| Module          | Purpose                                                        |
| --------------- | -------------------------------------------------------------- |
| `ingestion`     | Stream-based file reading for large files (.log, .gz)          |
| `parsing`       | Parse JSON and plain-text logs, handle multiline stack traces  |
| `normalization` | Replace variables with placeholders, filter high-signal errors |
| `clustering`    | Group similar errors using explainable NLP techniques          |
| `aggregation`   | Build final response with statistics and summaries             |
| `llm_summary`   | Generate natural language summaries (optional)                 |

## Configuration

### Environment Variables

| Variable           | Default    | Description                                  |
| ------------------ | ---------- | -------------------------------------------- |
| `MAX_FILE_SIZE_MB` | 100        | Maximum upload file size in MB               |
| `GEMINI_API_KEY`   | (built-in) | API key for Gemini LLM summaries (free tier) |

### Query Parameters

| Parameter      | Default | Description                             |
| -------------- | ------- | --------------------------------------- |
| `max_clusters` | 10      | Maximum number of error clusters (1-50) |
| `min_level`    | warn    | Minimum log level to analyze            |
| `use_llm`      | false   | Enable LLM-powered summaries            |

## Supported Log Formats

### JSON Logs

```json
{
  "timestamp": "2024-01-15T10:30:45Z",
  "level": "ERROR",
  "message": "Connection failed",
  "error": "timeout"
}
```

### Plain Text Logs

```
2024-01-15 10:30:45,123 ERROR [com.app.Service] - Connection failed: timeout
[2024-01-15 10:30:45] ERROR Connection failed: timeout
ERROR 2024-01-15 10:30:45 Connection failed
```

### Multiline Stack Traces

```
2024-01-15 10:30:45 ERROR Exception occurred
Traceback (most recent call last):
  File "app.py", line 42, in process
    raise ValueError("Invalid input")
ValueError: Invalid input
```

## Template Patterns

Variables are replaced with placeholders for de-duplication:

| Pattern              | Placeholder   |
| -------------------- | ------------- |
| UUIDs                | `<UUID>`      |
| IP addresses         | `<IP>`        |
| URLs                 | `<URL>`       |
| File paths           | `<PATH>`      |
| Timestamps           | `<TIMESTAMP>` |
| Durations (10ms, 5s) | `<DURATION>`  |
| Large numbers (IDs)  | `<ID>`        |
| Hex values           | `<HEX>`       |
| Email addresses      | `<EMAIL>`     |

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Project Structure

The codebase is designed to be:

- **Modular**: Each component has a single responsibility
- **Readable**: Clear naming and documentation
- **Extensible**: Easy to add new parsers, patterns, or clustering methods

## Limitations

- Synchronous processing (no background workers)
- Single-file analysis (no batch processing)
- In-memory processing (very large files may need chunking adjustments)
- No persistent storage or history
- No authentication (add if deploying publicly)

## License

MIT
