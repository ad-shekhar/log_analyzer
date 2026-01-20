"""Log normalization and template-based de-duplication."""

import re
from typing import Iterator
from collections import defaultdict

from .models import ParsedLogEntry, LogLevel, ErrorTemplate


# Patterns for variable replacement (order matters - more specific first)
VARIABLE_PATTERNS = [
    # UUIDs (various formats)
    (re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'), '<UUID>'),
    
    # MongoDB ObjectIds
    (re.compile(r'[0-9a-fA-F]{24}'), '<OBJECT_ID>'),
    
    # SHA hashes (commit hashes, checksums)
    (re.compile(r'\b[0-9a-fA-F]{40}\b'), '<SHA>'),
    (re.compile(r'\b[0-9a-fA-F]{64}\b'), '<SHA256>'),
    
    # IP addresses (IPv4 and IPv6)
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '<IP>'),
    (re.compile(r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'), '<IPv6>'),
    
    # URLs and paths
    (re.compile(r'https?://[^\s<>"\']+'), '<URL>'),
    (re.compile(r'/[\w\-./]+(?:\.\w+)?'), '<PATH>'),
    
    # Email addresses
    (re.compile(r'\b[\w.+-]+@[\w.-]+\.\w+\b'), '<EMAIL>'),
    
    # Timestamps (various formats)
    (re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'), '<TIMESTAMP>'),
    (re.compile(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?'), '<TIMESTAMP>'),
    (re.compile(r'\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}'), '<TIMESTAMP>'),
    
    # Durations
    (re.compile(r'\d+(?:\.\d+)?(?:ms|s|m|h|ns|µs)'), '<DURATION>'),
    
    # Hex values (memory addresses, etc.)
    (re.compile(r'\b0x[0-9a-fA-F]+\b'), '<HEX>'),
    
    # Large numbers (IDs, counts) - be conservative
    (re.compile(r'\b\d{6,}\b'), '<ID>'),
    
    # Smaller numbers in specific contexts
    (re.compile(r'(?<=port\s)\d+'), '<PORT>'),
    (re.compile(r'(?<=:\s)\d+(?=\s|$|,)'), '<NUM>'),
    (re.compile(r'(?<==)\d+'), '<NUM>'),
    
    # Request IDs / Trace IDs (alphanumeric with specific patterns)
    (re.compile(r'\b[A-Za-z0-9]{20,}\b'), '<REQUEST_ID>'),
]

# High-signal error patterns to always capture
ERROR_KEYWORDS = {
    'error', 'exception', 'fail', 'fatal', 'panic', 'crash',
    'traceback', 'timeout', 'refused', 'denied', 'unauthorized',
    'forbidden', 'not found', 'null', 'undefined', 'invalid',
    'cannot', 'unable', 'could not', 'failed to',
}


class LogNormalizer:
    """
    Normalizes log entries and creates de-duplicated templates.
    
    Handles:
    - Variable replacement with placeholders
    - Template-based de-duplication
    - Noise filtering (keeps only high-signal errors)
    """
    
    def __init__(self, min_level: LogLevel = LogLevel.WARN):
        """
        Initialize the normalizer.
        
        Args:
            min_level: Minimum log level to process (default: WARN)
        """
        self.min_level = min_level
        self._templates: dict[str, ErrorTemplate] = {}
    
    def normalize_message(self, message: str) -> str:
        """
        Normalize a log message by replacing variables with placeholders.
        
        Args:
            message: Raw log message
            
        Returns:
            Normalized message with placeholders
        """
        normalized = message
        
        for pattern, placeholder in VARIABLE_PATTERNS:
            normalized = pattern.sub(placeholder, normalized)
        
        # Collapse multiple consecutive placeholders of the same type
        normalized = re.sub(r'(<\w+>)(\s*\1)+', r'\1', normalized)
        
        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def is_high_signal(self, entry: ParsedLogEntry) -> bool:
        """
        Determine if a log entry is high-signal (worth analyzing).
        
        Args:
            entry: Parsed log entry
            
        Returns:
            True if the entry should be included in analysis
        """
        # Always include errors and fatals
        if entry.level in (LogLevel.ERROR, LogLevel.FATAL):
            return True
        
        # Include entries with exceptions
        if entry.has_exception:
            return True
        
        # Check for error keywords in message
        message_lower = entry.message.lower()
        if any(kw in message_lower for kw in ERROR_KEYWORDS):
            return True
        
        # Include warnings if configured
        if entry.level == LogLevel.WARN and self.min_level.value <= LogLevel.WARN.value:
            return True
        
        return False
    
    def process_entries(
        self, 
        entries: Iterator[ParsedLogEntry]
    ) -> tuple[list[ParsedLogEntry], dict[str, ErrorTemplate]]:
        """
        Process log entries: filter, normalize, and de-duplicate.
        
        Args:
            entries: Iterator of parsed log entries
            
        Returns:
            Tuple of (filtered high-signal entries, template dictionary)
        """
        high_signal_entries = []
        self._templates = {}
        
        for entry in entries:
            if not self.is_high_signal(entry):
                continue
            
            high_signal_entries.append(entry)
            
            # Create/update template
            template_key = self.normalize_message(entry.message)
            
            if template_key not in self._templates:
                self._templates[template_key] = ErrorTemplate(
                    template=template_key,
                    count=0,
                    first_occurrence_line=entry.line_number,
                )
            
            self._templates[template_key].add_occurrence(
                entry.message, 
                entry.line_number
            )
        
        return high_signal_entries, self._templates
    
    def get_top_templates(self, n: int = 10) -> list[ErrorTemplate]:
        """
        Get the top N most frequent error templates.
        
        Args:
            n: Number of templates to return
            
        Returns:
            List of ErrorTemplate objects sorted by count
        """
        sorted_templates = sorted(
            self._templates.values(),
            key=lambda t: t.count,
            reverse=True
        )
        return sorted_templates[:n]


def extract_error_context(entry: ParsedLogEntry, max_length: int = 500) -> str:
    """
    Extract a clean error context from a log entry.
    
    Args:
        entry: Parsed log entry
        max_length: Maximum length of the context
        
    Returns:
        Cleaned error context string
    """
    # Prefer exception info if available
    if entry.exception:
        context = entry.exception
    else:
        context = entry.message
    
    # Truncate if needed
    if len(context) > max_length:
        context = context[:max_length] + "..."
    
    return context
