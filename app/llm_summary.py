"""Optional LLM-based summary generation.

This module provides LLM integration for generating natural language summaries.
The LLM NEVER sees raw logs - only sanitized cluster summaries with patterns.

Uses Google Gemini API (free tier available).
"""

import os
from typing import Optional
import httpx

from .models import ErrorCluster
from .aggregation import prepare_cluster_summary_for_llm


# Default API key (Gemini free tier)
# Gemini API endpoint
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# System prompt for the LLM
SYSTEM_PROMPT = """You are a senior software engineer analyzing error logs.
You will receive a sanitized summary of error clusters (not raw logs).
Your task is to:
1. Identify the dominant issues
2. Explain what likely went wrong
3. Suggest next investigation steps

Be concise (2-4 sentences). Focus on actionable insights.
Do not make up specific details not present in the data."""


async def generate_llm_summary(
    clusters: list[ErrorCluster],
    total_lines: int,
    error_count: int,
    api_key: Optional[str] = None,
    model: str = "gemini-2.5-flash",
) -> Optional[str]:
    """
    Generate a natural language summary using Google Gemini.
    
    IMPORTANT: The LLM only sees sanitized cluster summaries,
    never raw log data.
    
    Args:
        clusters: List of error clusters
        total_lines: Total lines processed
        error_count: Number of error lines
        api_key: Gemini API key (falls back to GEMINI_API_KEY env var or default)
        model: Model to use (default: gemini-2.5-flash - free tier)
        
    Returns:
        Generated summary string, or None if LLM is unavailable
    """
    # Get API key (priority: parameter > env var > default)
    key = api_key or os.environ.get("GEMINI_API_KEY") or DEFAULT_GEMINI_API_KEY
    if not key:
        return None
    
    try:
        # Prepare sanitized input
        cluster_summary = prepare_cluster_summary_for_llm(clusters)
        
        user_message = f"""Analyzed {total_lines:,} log lines. Found {error_count:,} error/warning entries.

{cluster_summary}

Provide a brief summary of the main issues and suggested next steps."""

        # Combine system prompt and user message for Gemini
        full_prompt = f"{SYSTEM_PROMPT}\n\n{user_message}"
        
        # Prepare request payload for Gemini API
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": full_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 300,
            }
        }
        
        # Make API request
        url = GEMINI_API_URL.format(model=model)
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                params={"key": key},
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                print(f"Gemini API error: {response.status_code} - {response.text}")
                return None
            
            result = response.json()
            
            # Extract text from Gemini response
            if "candidates" in result and len(result["candidates"]) > 0:
                candidate = result["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
            
            return None
        
    except Exception as e:
        # Log error but don't fail the whole analysis
        print(f"LLM summary generation failed: {e}")
        return None


def generate_basic_summary(
    clusters: list[ErrorCluster],
    total_lines: int,
    error_count: int,
    fatal_count: int,
) -> str:
    """
    Generate a basic summary without LLM (rule-based fallback).
    
    Args:
        clusters: List of error clusters
        total_lines: Total lines processed
        error_count: Number of error lines
        fatal_count: Number of fatal lines
        
    Returns:
        Basic summary string
    """
    if not clusters:
        if error_count == 0:
            return f"Processed {total_lines:,} lines. No significant errors detected."
        return f"Processed {total_lines:,} lines with {error_count:,} errors, but no patterns could be clustered."
    
    # Analyze clusters
    total_clustered = sum(c.total_count for c in clusters)
    top_cluster = clusters[0] if clusters else None
    
    parts = [f"Processed {total_lines:,} lines."]
    
    if fatal_count > 0:
        parts.append(f"CRITICAL: {fatal_count:,} fatal errors detected.")
    
    parts.append(f"Found {error_count:,} error entries grouped into {len(clusters)} clusters.")
    
    if top_cluster:
        keywords_str = ", ".join(top_cluster.keywords[:3]) if top_cluster.keywords else "various errors"
        parts.append(
            f"Most frequent issue ({top_cluster.total_count:,} occurrences): "
            f"related to {keywords_str}."
        )
    
    # Suggest investigation
    if top_cluster and top_cluster.keywords:
        parts.append(f"Suggested investigation: Search codebase for '{top_cluster.keywords[0]}'.")
    
    return " ".join(parts)
