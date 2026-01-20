"""Tests for the log analyzer components."""

import io
import pytest
from app.parsing import LogParser
from app.normalization import LogNormalizer
from app.clustering import ErrorClusterer
from app.models import LogLevel, ParsedLogEntry


class TestLogParser:
    """Tests for LogParser."""
    
    def test_parse_json_log(self):
        """Test parsing JSON log lines."""
        parser = LogParser()
        lines = ['{"level": "ERROR", "message": "Connection failed", "timestamp": "2024-01-15T10:30:45Z"}']
        
        entries = list(parser.parse_lines(iter(lines)))
        
        assert len(entries) == 1
        assert entries[0].level == LogLevel.ERROR
        assert "Connection failed" in entries[0].message
    
    def test_parse_plain_text_log(self):
        """Test parsing plain text log lines."""
        parser = LogParser()
        lines = ['2024-01-15 10:30:45 ERROR Connection failed to database']
        
        entries = list(parser.parse_lines(iter(lines)))
        
        assert len(entries) == 1
        assert entries[0].level == LogLevel.ERROR
    
    def test_parse_multiline_stacktrace(self):
        """Test parsing multiline stack traces."""
        parser = LogParser()
        lines = [
            '2024-01-15 10:30:45 ERROR Exception occurred',
            'Traceback (most recent call last):',
            '  File "app.py", line 42, in process',
            '    raise ValueError("Invalid input")',
            'ValueError: Invalid input',
            '2024-01-15 10:30:46 INFO Normal log'
        ]
        
        entries = list(parser.parse_lines(iter(lines)))
        
        # Should consolidate the stack trace into one entry
        assert len(entries) == 2
        assert entries[0].is_multiline
        assert 'Traceback' in entries[0].raw_line
    
    def test_parse_various_levels(self):
        """Test parsing various log levels."""
        parser = LogParser()
        lines = [
            '2024-01-15 DEBUG Debug message',
            '2024-01-15 INFO Info message',
            '2024-01-15 WARN Warning message',
            '2024-01-15 ERROR Error message',
            '2024-01-15 FATAL Fatal message',
        ]
        
        entries = list(parser.parse_lines(iter(lines)))
        
        assert entries[0].level == LogLevel.DEBUG
        assert entries[1].level == LogLevel.INFO
        assert entries[2].level == LogLevel.WARN
        assert entries[3].level == LogLevel.ERROR
        assert entries[4].level == LogLevel.FATAL


class TestLogNormalizer:
    """Tests for LogNormalizer."""
    
    def test_normalize_uuid(self):
        """Test UUID replacement."""
        normalizer = LogNormalizer()
        message = "User 123e4567-e89b-12d3-a456-426614174000 logged in"
        
        result = normalizer.normalize_message(message)
        
        assert "<UUID>" in result
        assert "123e4567" not in result
    
    def test_normalize_ip(self):
        """Test IP address replacement."""
        normalizer = LogNormalizer()
        message = "Connection from 192.168.1.100 refused"
        
        result = normalizer.normalize_message(message)
        
        assert "<IP>" in result
        assert "192.168.1.100" not in result
    
    def test_normalize_timestamp(self):
        """Test timestamp replacement."""
        normalizer = LogNormalizer()
        message = "Event at 2024-01-15T10:30:45Z processed"
        
        result = normalizer.normalize_message(message)
        
        assert "<TIMESTAMP>" in result
    
    def test_normalize_url(self):
        """Test URL replacement."""
        normalizer = LogNormalizer()
        message = "Failed to connect to https://api.example.com/v1/users"
        
        result = normalizer.normalize_message(message)
        
        assert "<URL>" in result
    
    def test_is_high_signal_error(self):
        """Test high signal detection for errors."""
        normalizer = LogNormalizer()
        
        error_entry = ParsedLogEntry(
            raw_line="ERROR: Something failed",
            line_number=1,
            level=LogLevel.ERROR,
            message="Something failed"
        )
        
        assert normalizer.is_high_signal(error_entry)
    
    def test_is_high_signal_exception(self):
        """Test high signal detection for exceptions."""
        normalizer = LogNormalizer()
        
        entry = ParsedLogEntry(
            raw_line="INFO: Exception caught",
            line_number=1,
            level=LogLevel.INFO,
            message="Processing request",
            exception="NullPointerException"
        )
        
        assert normalizer.is_high_signal(entry)
    
    def test_is_not_high_signal_debug(self):
        """Test that debug logs are not high signal."""
        normalizer = LogNormalizer()
        
        entry = ParsedLogEntry(
            raw_line="DEBUG: Entering method",
            line_number=1,
            level=LogLevel.DEBUG,
            message="Entering method"
        )
        
        assert not normalizer.is_high_signal(entry)


class TestErrorClusterer:
    """Tests for ErrorClusterer."""
    
    def test_cluster_similar_errors(self):
        """Test clustering of similar error templates."""
        from app.models import ErrorTemplate
        
        clusterer = ErrorClusterer(max_clusters=3)
        
        templates = {
            "Connection to <IP> failed": ErrorTemplate(
                template="Connection to <IP> failed",
                original_messages=["Connection to 192.168.1.1 failed"],
                count=50
            ),
            "Connection to <IP> timeout": ErrorTemplate(
                template="Connection to <IP> timeout",
                original_messages=["Connection to 10.0.0.1 timeout"],
                count=30
            ),
            "Database query failed": ErrorTemplate(
                template="Database query failed",
                original_messages=["Database query failed"],
                count=20
            ),
        }
        
        clusters = clusterer.cluster_templates(templates)
        
        assert len(clusters) >= 1
        # Connection-related errors should cluster together
        total_items = sum(len(c.templates) for c in clusters)
        assert total_items == 3
    
    def test_empty_templates(self):
        """Test handling of empty template dict."""
        clusterer = ErrorClusterer()
        clusters = clusterer.cluster_templates({})
        
        assert clusters == []
    
    def test_single_template(self):
        """Test handling of single template."""
        from app.models import ErrorTemplate
        
        clusterer = ErrorClusterer()
        templates = {
            "Single error": ErrorTemplate(
                template="Single error",
                original_messages=["Single error"],
                count=1
            )
        }
        
        clusters = clusterer.cluster_templates(templates)
        
        assert len(clusters) == 1
        assert clusters[0].total_count == 1


class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.asyncio
    async def test_full_analysis(self):
        """Test full analysis pipeline."""
        from app.analyzer import LogAnalyzer
        
        log_content = """2024-01-15 10:30:45 INFO Application started
2024-01-15 10:30:46 ERROR Connection to 192.168.1.100:5432 failed
2024-01-15 10:30:47 ERROR Connection to 192.168.1.101:5432 failed
2024-01-15 10:30:48 ERROR Connection to 10.0.0.50:5432 failed
2024-01-15 10:30:49 FATAL Database unavailable
Traceback (most recent call last):
  File "db.py", line 10, in connect
    raise ConnectionError("Cannot connect")
ConnectionError: Cannot connect
2024-01-15 10:30:50 INFO Retrying connection
2024-01-15 10:30:51 ERROR Connection to 192.168.1.100:5432 failed
2024-01-15 10:30:52 WARN High memory usage: 85%
"""
        
        analyzer = LogAnalyzer(max_clusters=5, use_llm=False)
        file_obj = io.BytesIO(log_content.encode('utf-8'))
        
        result = await analyzer.analyze(file_obj, "test.log")
        
        assert result.total_lines > 0
        assert result.error_lines >= 4
        assert result.fatal_lines >= 1
        assert len(result.top_templates) > 0
        assert result.processing_time_ms > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
