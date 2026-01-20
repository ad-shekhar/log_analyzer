"""Log parsing for JSON and plain-text formats with multiline support."""

import json
import re
from typing import Iterator, Optional

from .models import ParsedLogEntry, LogLevel


# Common timestamp patterns
TIMESTAMP_PATTERNS = [
    # ISO 8601: 2024-01-15T10:30:45.123Z
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?',
    # Common: 2024-01-15 10:30:45,123
    r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d{3}',
    # Common: 2024/01/15 10:30:45
    r'\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}',
    # Unix timestamp with brackets: [1705312245]
    r'\[\d{10,13}\]',
    # Date with brackets: [2024-01-15 10:30:45]
    r'\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?\]',
]

# Combined pattern for timestamp detection
TIMESTAMP_REGEX = re.compile('|'.join(f'({p})' for p in TIMESTAMP_PATTERNS))

# Log level patterns (word boundaries for accuracy)
LOG_LEVEL_PATTERN = re.compile(
    r'\b(TRACE|DEBUG|INFO|INFORMATION|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|CRIT|SEVERE|PANIC)\b',
    re.IGNORECASE
)

# Exception/traceback indicators
EXCEPTION_PATTERNS = [
    re.compile(r'^\s*Traceback \(most recent call last\):', re.IGNORECASE),
    re.compile(r'^\s*at\s+[\w\.$]+\([\w]+\.\w+:\d+\)'),  # Java stack trace
    re.compile(r'^\s*File ".*", line \d+'),  # Python stack trace
    re.compile(r'^\s+at\s+.*\(.*:\d+:\d+\)'),  # JavaScript stack trace
    re.compile(r'Exception|Error|Throwable', re.IGNORECASE),
]

# Pattern for continuation lines (stacktrace, multiline messages)
CONTINUATION_PATTERNS = [
    re.compile(r'^\s+at\s+'),  # Java/JS stack trace continuation
    re.compile(r'^\s+File\s+"'),  # Python stack trace
    re.compile(r'^\s+\w+Error:'),  # Error continuation
    re.compile(r'^\s{4,}'),  # Generic indentation (4+ spaces)
    re.compile(r'^\t+'),  # Tab indentation
    re.compile(r'^\s*\.\.\.\s*\d+\s+more'),  # Java "... X more"
    re.compile(r'^\s*Caused by:'),  # Java chained exceptions
]


class LogParser:
    """
    Parses log files supporting both JSON and plain-text formats.
    
    Handles:
    - JSON logs (one JSON object per line)
    - Plain text logs with various formats
    - Multiline stack traces
    - Various timestamp formats
    """
    
    def __init__(self):
        self._pending_multiline: Optional[ParsedLogEntry] = None
    
    def parse_lines(self, lines: Iterator[str]) -> Iterator[ParsedLogEntry]:
        """
        Parse an iterator of log lines into structured entries.
        
        Handles multiline log entries by detecting continuation patterns.
        
        Args:
            lines: Iterator of raw log lines
            
        Yields:
            ParsedLogEntry objects
        """
        self._pending_multiline = None
        
        for line_num, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            
            # Check if this is a continuation of a multiline entry
            if self._is_continuation_line(line):
                if self._pending_multiline:
                    self._append_to_multiline(line)
                    continue
            
            # Flush any pending multiline entry
            if self._pending_multiline:
                yield self._pending_multiline
                self._pending_multiline = None
            
            # Parse the new line
            entry = self._parse_single_line(line, line_num)
            
            # Check if this might be the start of a multiline entry
            if self._might_have_continuation(entry):
                self._pending_multiline = entry
            else:
                yield entry
        
        # Flush any remaining multiline entry
        if self._pending_multiline:
            yield self._pending_multiline
    
    def _parse_single_line(self, line: str, line_num: int) -> ParsedLogEntry:
        """Parse a single log line."""
        stripped = line.strip()
        
        # Try JSON first
        if stripped.startswith('{'):
            entry = self._parse_json_line(stripped, line_num)
            if entry:
                return entry
        
        # Fall back to plain text parsing
        return self._parse_plain_line(line, line_num)
    
    def _parse_json_line(self, line: str, line_num: int) -> Optional[ParsedLogEntry]:
        """Attempt to parse a JSON log line."""
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                return None
            
            # Extract common fields (various naming conventions)
            level_str = (
                data.get('level') or 
                data.get('severity') or 
                data.get('log_level') or
                data.get('lvl') or
                ''
            )
            
            message = (
                data.get('message') or 
                data.get('msg') or 
                data.get('text') or
                data.get('@message') or
                str(data)
            )
            
            timestamp = (
                data.get('timestamp') or 
                data.get('time') or 
                data.get('@timestamp') or
                data.get('ts') or
                None
            )
            
            logger = (
                data.get('logger') or 
                data.get('name') or 
                data.get('source') or
                None
            )
            
            # Check for exception/error info
            exception = (
                data.get('exception') or 
                data.get('error') or 
                data.get('stack_trace') or
                data.get('stacktrace') or
                data.get('err') or
                None
            )
            
            if isinstance(exception, dict):
                exception = json.dumps(exception)
            
            return ParsedLogEntry(
                raw_line=line,
                line_number=line_num,
                level=LogLevel.from_string(str(level_str)),
                message=str(message),
                timestamp=str(timestamp) if timestamp else None,
                logger=str(logger) if logger else None,
                exception=str(exception) if exception else None,
            )
            
        except json.JSONDecodeError:
            return None
    
    def _parse_plain_line(self, line: str, line_num: int) -> ParsedLogEntry:
        """Parse a plain text log line."""
        # Extract timestamp
        timestamp_match = TIMESTAMP_REGEX.search(line)
        timestamp = timestamp_match.group() if timestamp_match else None
        
        # Extract log level
        level = LogLevel.UNKNOWN
        level_match = LOG_LEVEL_PATTERN.search(line)
        if level_match:
            level = LogLevel.from_string(level_match.group())
        
        # The message is everything after level (or the whole line)
        message = line
        if level_match:
            # Try to extract just the message portion
            parts = line[level_match.end():].strip()
            if parts:
                # Remove common separators
                message = re.sub(r'^[\s\-:\]]+', '', parts)
        
        # Check for exception indicators
        exception = None
        for pattern in EXCEPTION_PATTERNS:
            if pattern.search(line):
                exception = line
                if level == LogLevel.UNKNOWN:
                    level = LogLevel.ERROR
                break
        
        return ParsedLogEntry(
            raw_line=line,
            line_number=line_num,
            level=level,
            message=message,
            timestamp=timestamp,
            exception=exception,
        )
    
    def _is_continuation_line(self, line: str) -> bool:
        """Check if a line is a continuation of a multiline entry."""
        for pattern in CONTINUATION_PATTERNS:
            if pattern.match(line):
                return True
        
        # Also check if line doesn't start with timestamp (common indicator)
        if not TIMESTAMP_REGEX.match(line.strip()):
            # And doesn't start with a log level at the beginning
            stripped = line.strip()
            if stripped and not LOG_LEVEL_PATTERN.match(stripped[:20]):
                # Check if it looks like a continuation (starts with whitespace but has content)
                if line.startswith((' ', '\t')) and stripped:
                    return True
        
        return False
    
    def _might_have_continuation(self, entry: ParsedLogEntry) -> bool:
        """Check if an entry might have continuation lines."""
        # Entries with exceptions often have stack traces following
        if entry.has_exception:
            return True
        
        # Error/Fatal entries might have stack traces
        if entry.level in (LogLevel.ERROR, LogLevel.FATAL):
            return True
        
        # Check for exception-related keywords
        keywords = ['exception', 'error', 'traceback', 'stack', 'caused by']
        message_lower = entry.message.lower()
        return any(kw in message_lower for kw in keywords)
    
    def _append_to_multiline(self, line: str) -> None:
        """Append a line to the pending multiline entry."""
        if self._pending_multiline:
            self._pending_multiline.is_multiline = True
            self._pending_multiline.raw_line += '\n' + line
            
            # Update exception if this looks like stack trace
            if self._pending_multiline.exception:
                self._pending_multiline.exception += '\n' + line
            else:
                for pattern in EXCEPTION_PATTERNS:
                    if pattern.search(line):
                        self._pending_multiline.exception = line
                        break
