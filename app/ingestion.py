"""Log file ingestion with streaming/chunked I/O for large files."""

import gzip
import io
from typing import Iterator, BinaryIO

# Chunk size for reading large files (64KB)
CHUNK_SIZE = 64 * 1024


def read_log_file(file: BinaryIO, filename: str) -> Iterator[str]:
    """
    Read a log file with streaming support for large files.
    
    Supports both plain .log files and .gz compressed files.
    Uses chunked reading to handle files larger than memory.
    
    Args:
        file: File-like object with binary content
        filename: Original filename (used to detect compression)
        
    Yields:
        Individual log lines as strings
    """
    if filename.endswith('.gz'):
        yield from _read_gzip_file(file)
    else:
        yield from _read_plain_file(file)


def _read_gzip_file(file: BinaryIO) -> Iterator[str]:
    """Read a gzip-compressed log file."""
    # Read all content first (gzip needs full file for decompression)
    content = file.read()
    
    with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
        # Wrap in TextIOWrapper for line-by-line reading
        text_stream = io.TextIOWrapper(gz, encoding='utf-8', errors='replace')
        buffer = ""
        
        while True:
            chunk = text_stream.read(CHUNK_SIZE)
            if not chunk:
                if buffer:
                    yield buffer
                break
            
            buffer += chunk
            lines = buffer.split('\n')
            
            # Yield all complete lines, keep the last partial line in buffer
            for line in lines[:-1]:
                yield line
            buffer = lines[-1]


def _read_plain_file(file: BinaryIO) -> Iterator[str]:
    """Read a plain text log file."""
    buffer = ""
    
    while True:
        chunk = file.read(CHUNK_SIZE)
        if not chunk:
            if buffer:
                yield buffer
            break
        
        # Decode chunk, handling encoding errors gracefully
        try:
            decoded = chunk.decode('utf-8')
        except UnicodeDecodeError:
            decoded = chunk.decode('utf-8', errors='replace')
        
        buffer += decoded
        lines = buffer.split('\n')
        
        # Yield all complete lines, keep the last partial line in buffer
        for line in lines[:-1]:
            yield line
        buffer = lines[-1]


def estimate_line_count(file: BinaryIO, filename: str, sample_size: int = 10000) -> int:
    """
    Estimate total lines in a file by sampling.
    
    This is useful for progress estimation on very large files.
    
    Args:
        file: File-like object
        filename: Original filename
        sample_size: Bytes to sample for estimation
        
    Returns:
        Estimated line count
    """
    file.seek(0, 2)  # Seek to end
    total_size = file.tell()
    file.seek(0)  # Reset to start
    
    if total_size == 0:
        return 0
    
    # Read sample
    sample = file.read(sample_size)
    file.seek(0)  # Reset again
    
    if filename.endswith('.gz'):
        try:
            decompressed = gzip.decompress(sample[:sample_size])
            lines_in_sample = decompressed.count(b'\n')
            # Estimate compression ratio ~10x
            estimated_lines = int((total_size * 10 / sample_size) * lines_in_sample)
        except Exception:
            estimated_lines = total_size // 100  # Rough fallback
    else:
        lines_in_sample = sample.count(b'\n')
        if lines_in_sample == 0:
            return 1
        avg_line_length = sample_size / lines_in_sample
        estimated_lines = int(total_size / avg_line_length)
    
    return max(estimated_lines, 1)
