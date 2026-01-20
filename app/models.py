"""Data models for the log analyzer."""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class LogLevel(Enum):
    """Normalized log levels."""
    TRACE = 0
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    FATAL = 5
    UNKNOWN = -1

    @classmethod
    def from_string(cls, level_str: str) -> "LogLevel":
        """Parse a log level string to enum."""
        if not level_str:
            return cls.UNKNOWN
        
        normalized = level_str.upper().strip()
        
        # Handle common variations
        level_map = {
            "TRACE": cls.TRACE,
            "DEBUG": cls.DEBUG,
            "INFO": cls.INFO,
            "INFORMATION": cls.INFO,
            "WARN": cls.WARN,
            "WARNING": cls.WARN,
            "ERROR": cls.ERROR,
            "ERR": cls.ERROR,
            "FATAL": cls.FATAL,
            "CRITICAL": cls.FATAL,
            "CRIT": cls.FATAL,
            "SEVERE": cls.FATAL,
            "PANIC": cls.FATAL,
        }
        
        return level_map.get(normalized, cls.UNKNOWN)


@dataclass
class ParsedLogEntry:
    """A single parsed log entry."""
    raw_line: str
    line_number: int
    level: LogLevel = LogLevel.UNKNOWN
    message: str = ""
    timestamp: Optional[str] = None
    logger: Optional[str] = None
    exception: Optional[str] = None
    is_multiline: bool = False
    
    @property
    def is_error(self) -> bool:
        """Check if this is an error-level log."""
        return self.level in (LogLevel.ERROR, LogLevel.FATAL)
    
    @property
    def has_exception(self) -> bool:
        """Check if this log contains exception info."""
        return bool(self.exception)


@dataclass
class ErrorTemplate:
    """A de-duplicated error template."""
    template: str  # Message with placeholders
    original_messages: list[str] = field(default_factory=list)
    count: int = 0
    first_occurrence_line: int = 0
    
    def add_occurrence(self, message: str, line_number: int) -> None:
        """Add a new occurrence of this template."""
        self.count += 1
        if len(self.original_messages) < 3:  # Keep up to 3 examples
            self.original_messages.append(message)
        if self.first_occurrence_line == 0:
            self.first_occurrence_line = line_number


@dataclass
class ErrorCluster:
    """A cluster of similar error messages."""
    cluster_id: int
    templates: list[ErrorTemplate] = field(default_factory=list)
    total_count: int = 0
    keywords: list[str] = field(default_factory=list)
    representative_sample: str = ""
    
    def get_summary(self) -> dict:
        """Get a summary suitable for LLM consumption."""
        return {
            "cluster_id": self.cluster_id,
            "total_occurrences": self.total_count,
            "unique_patterns": len(self.templates),
            "keywords": self.keywords[:10],
            "sample_pattern": self.representative_sample,
        }


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    total_lines: int = 0
    error_lines: int = 0
    fatal_lines: int = 0
    warning_lines: int = 0
    exception_count: int = 0
    top_templates: list[dict] = field(default_factory=list)
    clusters: list[dict] = field(default_factory=list)
    llm_summary: Optional[str] = None
    processing_time_ms: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response."""
        return {
            "summary": {
                "total_lines_processed": self.total_lines,
                "error_lines": self.error_lines,
                "fatal_lines": self.fatal_lines,
                "warning_lines": self.warning_lines,
                "exceptions_detected": self.exception_count,
            },
            "top_error_templates": self.top_templates,
            "error_clusters": self.clusters,
            "natural_language_summary": self.llm_summary,
            "processing_time_ms": round(self.processing_time_ms, 2),
        }
