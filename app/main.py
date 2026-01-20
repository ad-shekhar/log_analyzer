"""FastAPI application for the Intelligent Log Analyzer."""

import os
import json
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from .analyzer import LogAnalyzer
from .models import LogLevel


# Create FastAPI app
app = FastAPI(
    title="Intelligent Log Analyzer",
    description="""
    A lightweight log analysis tool that helps developers quickly understand 
    what went wrong without reading thousands of log lines.
    
    ## Features
    - Supports `.log` and `.gz` files
    - Parses JSON and plain-text logs
    - Handles multiline stack traces
    - De-duplicates errors using template patterns
    - Clusters similar errors using TF-IDF + MiniBatchKMeans
    - Optional LLM-powered natural language summaries
    
    ## Usage
    Upload a log file to `/analyze` and receive a structured JSON summary.
    """,
    version="0.1.0",
)


# Configuration from environment
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "100"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


@app.get("/")
async def root():
    """Health check and API info."""
    return {
        "service": "Intelligent Log Analyzer",
        "version": "0.1.0",
        "status": "healthy",
        "endpoints": {
            "analyze": "POST /analyze - Upload and analyze a log file",
            "docs": "GET /docs - Interactive API documentation",
        }
    }


@app.post("/analyze")
async def analyze_log(
    file: UploadFile = File(..., description="Log file (.log or .gz)"),
    max_clusters: int = Query(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of error clusters to create"
    ),
    use_llm: bool = Query(
        default=False,
        description="Use LLM for natural language summary (requires GEMINI_API_KEY)"
    ),
    min_level: str = Query(
        default="warn",
        description="Minimum log level to analyze (trace, debug, info, warn, error, fatal)"
    ),
    pretty: bool = Query(
        default=False,
        description="Return pretty-printed JSON output (easier to read in terminal)"
    ),
):
    """
    Analyze an uploaded log file and return a structured summary.
    
    ## Supported Formats
    - Plain text log files (`.log`, `.txt`)
    - Gzip compressed logs (`.gz`)
    - JSON logs (one JSON object per line)
    - Plain text logs with various timestamp/level formats
    
    ## Response
    Returns a JSON object with:
    - **summary**: Basic statistics (total lines, error counts)
    - **top_error_templates**: Most frequent error patterns with de-duplication
    - **error_clusters**: Grouped similar errors with keywords and samples
    - **natural_language_summary**: Human-readable summary of issues
    - **processing_time_ms**: How long the analysis took
    
    ## Example
    ```bash
    curl -X POST "http://localhost:8000/analyze" \\
         -F "file=@application.log" \\
         -F "max_clusters=10"
    ```
    """
    # Validate filename
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    
    filename_lower = file.filename.lower()
    if not any(filename_lower.endswith(ext) for ext in ['.log', '.txt', '.gz']):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload .log, .txt, or .gz files."
        )
    
    # Validate file size (read in chunks to check)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB."
        )
    
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    
    # Parse min_level
    try:
        level = LogLevel.from_string(min_level)
        if level == LogLevel.UNKNOWN:
            level = LogLevel.WARN
    except Exception:
        level = LogLevel.WARN
    
    # Create analyzer
    analyzer = LogAnalyzer(
        max_clusters=max_clusters,
        min_level=level,
        use_llm=use_llm,
        llm_api_key=os.environ.get("OPENAI_API_KEY"),
    )
    
    # Analyze
    try:
        # Create file-like object from content
        import io
        file_obj = io.BytesIO(content)
        
        result = await analyzer.analyze(file_obj, file.filename)
        
        # Return pretty-printed or compact JSON
        if pretty:
            return PlainTextResponse(
                content=json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                status_code=200,
                media_type="application/json"
            )
        else:
            return JSONResponse(
                content=result.to_dict(),
                status_code=200,
            )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy"}


# Error handlers
@app.exception_handler(413)
async def request_entity_too_large(request, exc):
    return JSONResponse(
        status_code=413,
        content={"detail": f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB."}
    )


@app.exception_handler(500)
async def internal_server_error(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."}
    )
