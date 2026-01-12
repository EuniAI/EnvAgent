#!/usr/bin/env python3
"""
Parse log files to extract token usage and calculate costs.
Supports both explicit token usage from logs and token counting from response text.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

# Import cost tracker to use its pricing logic
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import tiktoken
except ImportError:
    print("Warning: tiktoken not installed. Token counting from text will be disabled.")
    print("Install it with: pip install tiktoken")
    tiktoken = None

# Try to import pricing, fallback to local definition
try:
    from app.services.cost_tracker import MODEL_PRICING
except ImportError:
    # Fallback: define pricing locally
    MODEL_PRICING = {
        # OpenAI models
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        # Anthropic Claude models
        "claude-3-opus": {"input": 15.00, "output": 75.00},
        "claude-3-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-haiku": {"input": 0.25, "output": 1.25},
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        # Google Gemini models
        "gemini-pro": {"input": 0.50, "output": 1.50},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-2.0-flash-exp": {"input": 0.075, "output": 0.30},
        # Default fallback pricing
        "default": {"input": 1.00, "output": 3.00},
    }


def normalize_model_name(model_name: str) -> str:
    """Normalize model name to match pricing keys."""
    model_lower = model_name.lower()
    
    # Extract base model name (remove prefixes and version suffixes)
    if "/" in model_lower:
        model_lower = model_lower.split("/")[-1]
    
    # Check for exact matches
    for key in MODEL_PRICING.keys():
        if key in model_lower:
            return key
    
    # Try partial matches
    if "gpt-5" in model_lower:
        # GPT-5: use gpt-4o pricing as placeholder (update with actual pricing when available)
        return "gpt-4o"
    elif "gpt-4o" in model_lower:
        return "gpt-4o" if "mini" not in model_lower else "gpt-4o-mini"
    elif "gpt-4" in model_lower:
        return "gpt-4-turbo" if "turbo" in model_lower else "gpt-4"
    elif "gpt-3.5" in model_lower:
        return "gpt-3.5-turbo"
    elif "claude-3-opus" in model_lower:
        return "claude-3-opus"
    elif "claude-3-sonnet" in model_lower:
        return "claude-3-5-sonnet" if "5" in model_lower else "claude-3-sonnet"
    elif "claude-3-haiku" in model_lower:
        return "claude-3-haiku"
    elif "gemini-2.0" in model_lower or "gemini-2" in model_lower:
        return "gemini-2.0-flash-exp" if "flash" in model_lower else "gemini-pro"
    elif "gemini-1.5-pro" in model_lower:
        return "gemini-1.5-pro"
    elif "gemini-1.5-flash" in model_lower:
        return "gemini-1.5-flash"
    elif "gemini" in model_lower:
        return "gemini-pro"
    
    return "default"


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost based on model pricing."""
    normalized_name = normalize_model_name(model_name)
    pricing = MODEL_PRICING.get(normalized_name, MODEL_PRICING["default"])
    
    input_cost = (input_tokens * pricing["input"]) / 1_000_000
    output_cost = (output_tokens * pricing["output"]) / 1_000_000
    return input_cost + output_cost


def count_tokens_from_text(text: str, encoding_name: str = "o200k_base") -> int:
    """Count tokens in text using tiktoken.
    
    Args:
        text: Text to count tokens for
        encoding_name: Encoding to use (default: o200k_base for GPT models)
    
    Returns:
        Number of tokens
    """
    if tiktoken is None:
        # Fallback: rough estimate (1 token ≈ 4 characters for English text)
        return len(text) // 4
    
    try:
        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except Exception as e:
        # Fallback to character-based estimate if encoding fails
        print(f"Warning: Failed to count tokens with {encoding_name}: {e}")
        return len(text) // 4


def extract_content_from_line(line: str) -> Optional[str]:
    """Extract response content from a log line.
    
    Returns:
        Content string or None if not found
    """
    # Match content='...' or content="..."
    # Handle both single and double quotes
    content_patterns = [
        r"content='([^']*)'",  # Single quotes
        r'content="([^"]*)"',  # Double quotes
    ]
    
    for pattern in content_patterns:
        match = re.search(pattern, line)
        if match:
            content = match.group(1)
            # Unescape if needed
            content = content.replace("\\'", "'").replace('\\"', '"')
            return content
    
    return None


def extract_tool_calls_from_line(line: str) -> Optional[str]:
    """Extract tool_calls JSON string from a log line.
    
    Returns:
        JSON string of tool_calls or None if not found
    """
    # Match tool_calls=[...]
    tool_calls_pattern = r"'tool_calls':\s*(\[[^\]]*\])"
    match = re.search(tool_calls_pattern, line)
    if match:
        return match.group(1)
    
    # Also try to find it in additional_kwargs
    tool_calls_pattern2 = r"tool_calls.*?\[(.*?)\]"
    match = re.search(tool_calls_pattern2, line)
    if match:
        return "[" + match.group(1) + "]"
    
    return None


def extract_token_usage_from_line(line: str, use_text_calculation: bool = True) -> Optional[Dict]:
    """Extract token usage information from a log line.
    
    This function:
    1. First tries to extract explicit token usage from response_metadata/usage_metadata
    2. If not found and use_text_calculation=True, calculates tokens from response text
    3. Uses explicit values if available, otherwise uses calculated values
    
    Args:
        line: Log line to parse
        use_text_calculation: Whether to calculate tokens from text if explicit info is missing
    
    Returns:
        Dict with keys: model_name, input_tokens, output_tokens, total_tokens, cost,
                        calculated_output_tokens (if calculated), has_explicit_tokens
        or None if no token usage found and cannot calculate from text
    """
    explicit_input_tokens = None
    explicit_output_tokens = None
    calculated_output_tokens = None
    
    # Check if this line has DEBUG/INFO level and contains response_metadata or usage_metadata
    # This filters out non-LLM log lines
    is_llm_log_line = (
        "response_metadata" in line or 
        "usage_metadata" in line or
        "token_usage" in line or
        ("content=" in line and ("additional_kwargs" in line or "response_metadata" in line))
    )
    
    if not is_llm_log_line:
        return None
    
    # Try to extract from response_metadata.token_usage (OpenAI format)
    token_usage_pattern = r"'token_usage':\s*\{[^}]*'prompt_tokens':\s*(\d+),\s*'completion_tokens':\s*(\d+)"
    match = re.search(token_usage_pattern, line)
    if match:
        explicit_input_tokens = int(match.group(1))
        explicit_output_tokens = int(match.group(2))
    
    # Try to extract from usage_metadata (Anthropic/other format)
    if explicit_input_tokens is None or explicit_output_tokens is None:
        usage_pattern = r"'input_tokens':\s*(\d+),\s*'output_tokens':\s*(\d+)"
        match = re.search(usage_pattern, line)
        if match:
            explicit_input_tokens = int(match.group(1))
            explicit_output_tokens = int(match.group(2))
    
    # Extract model name
    model_pattern = r"'model_name':\s*'([^']+)'"
    model_match = re.search(model_pattern, line)
    model_name = model_match.group(1) if model_match else "unknown"
    
    # If we have explicit tokens, use them
    if explicit_input_tokens is not None and explicit_output_tokens is not None:
        input_tokens = explicit_input_tokens
        output_tokens = explicit_output_tokens
        has_explicit_tokens = True
        
        # Optionally calculate from text for comparison if enabled
        if use_text_calculation:
            content = extract_content_from_line(line)
            tool_calls_str = extract_tool_calls_from_line(line)
            
            content_tokens = count_tokens_from_text(content) if content else 0
            tool_calls_tokens = 0
            if tool_calls_str:
                tool_calls_tokens = count_tokens_from_text(tool_calls_str)
            
            calculated_output_tokens = content_tokens + tool_calls_tokens + 5
    elif use_text_calculation:
        # No explicit tokens, try to calculate from text
        content = extract_content_from_line(line)
        tool_calls_str = extract_tool_calls_from_line(line)
        
        # Only calculate if we have at least content or tool_calls
        if not content and not tool_calls_str:
            return None
        
        content_tokens = count_tokens_from_text(content) if content else 0
        tool_calls_tokens = 0
        if tool_calls_str:
            tool_calls_tokens = count_tokens_from_text(tool_calls_str)
        
        calculated_output_tokens = content_tokens + tool_calls_tokens + 5
        input_tokens = 0  # Can't calculate input tokens without full message history
        output_tokens = calculated_output_tokens
        has_explicit_tokens = False
    else:
        return None
    
    # Calculate final values
    total_tokens = input_tokens + output_tokens
    cost = calculate_cost(model_name, input_tokens, output_tokens)
    
    result = {
        "model_name": model_name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost": cost,
        "has_explicit_tokens": has_explicit_tokens,
    }
    
    if calculated_output_tokens is not None and has_explicit_tokens:
        result["calculated_output_tokens"] = calculated_output_tokens
        result["token_diff"] = calculated_output_tokens - output_tokens
    
    return result


def parse_log_file(log_path: Path, use_text_calculation: bool = True) -> List[Dict]:
    """Parse a log file and extract all token usage records.
    
    Args:
        log_path: Path to log file
        use_text_calculation: Whether to calculate tokens from text when explicit info is missing
    """
    records = []
    
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            token_info = extract_token_usage_from_line(line, use_text_calculation=use_text_calculation)
            if token_info:
                token_info["line_number"] = line_num
                records.append(token_info)
    
    return records


def aggregate_stats(records: List[Dict]) -> Dict:
    """Aggregate statistics from token usage records."""
    stats = defaultdict(lambda: {
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
    })
    
    global_stats = {
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
    }
    
    for record in records:
        model_name = record["model_name"]
        
        # Update model-specific stats
        stats[model_name]["total_calls"] += 1
        stats[model_name]["total_input_tokens"] += record["input_tokens"]
        stats[model_name]["total_output_tokens"] += record["output_tokens"]
        stats[model_name]["total_tokens"] += record["total_tokens"]
        stats[model_name]["total_cost"] += record["cost"]
        
        # Update global stats
        global_stats["total_calls"] += 1
        global_stats["total_input_tokens"] += record["input_tokens"]
        global_stats["total_output_tokens"] += record["output_tokens"]
        global_stats["total_tokens"] += record["total_tokens"]
        global_stats["total_cost"] += record["cost"]
    
    return {
        "global": global_stats,
        "by_model": dict(stats),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse log files to extract token usage and calculate costs"
    )
    parser.add_argument(
        "log_file",
        type=Path,
        nargs="+",
        help="Path(s) to the log file(s) to parse (can specify multiple)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to output JSON file (optional)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty print the output",
    )
    parser.add_argument(
        "--no-text-calculation",
        action="store_true",
        help="Disable token calculation from response text (only use explicit token info)",
    )
    
    args = parser.parse_args()
    
    all_records = []
    use_text_calculation = not args.no_text_calculation
    
    for log_file in args.log_file:
        if not log_file.exists():
            print(f"Warning: Log file not found: {log_file}")
            continue
        
        print(f"Parsing log file: {log_file}")
        if use_text_calculation:
            print(f"  Using text-based token calculation when explicit info is missing")
        records = parse_log_file(log_file, use_text_calculation=use_text_calculation)
        print(f"  Found {len(records)} token usage records")
        all_records.extend(records)
    
    if not all_records:
        print("No token usage information found in any log file.")
        return 0
    
    print(f"\nTotal records across all files: {len(all_records)}")
    
    stats = aggregate_stats(all_records)
    
    # Print summary
    print("\n" + "="*80)
    print("TOKEN USAGE SUMMARY")
    print("="*80)
    print(f"\nTotal Calls: {stats['global']['total_calls']}")
    print(f"Total Input Tokens: {stats['global']['total_input_tokens']:,}")
    print(f"Total Output Tokens: {stats['global']['total_output_tokens']:,}")
    print(f"Total Tokens: {stats['global']['total_tokens']:,}")
    print(f"Total Cost: ${stats['global']['total_cost']:.4f}")
    
    # Show statistics about explicit vs calculated tokens
    explicit_count = sum(1 for r in all_records if r.get("has_explicit_tokens", False))
    calculated_only_count = sum(1 for r in all_records if not r.get("has_explicit_tokens", False) and r.get("output_tokens", 0) > 0)
    
    if explicit_count > 0 or calculated_only_count > 0:
        print(f"\nToken Source Breakdown:")
        print(f"  Records with explicit token info: {explicit_count}")
        if calculated_only_count > 0:
            print(f"  Records with only calculated tokens (no explicit info): {calculated_only_count}")
        
        # Show average difference between calculated and explicit tokens
        diffs = [r.get("token_diff") for r in all_records if r.get("token_diff") is not None]
        if diffs:
            avg_diff = sum(diffs) / len(diffs)
            max_diff = max(diffs)
            min_diff = min(diffs)
            print(f"  Token comparison (calculated - explicit) for {len(diffs)} records:")
            print(f"    Average difference: {avg_diff:.1f} tokens")
            print(f"    Min difference: {min_diff:.1f} tokens")
            print(f"    Max difference: {max_diff:.1f} tokens")
            print(f"    Note: Differences may be due to reasoning tokens, message formatting overhead, etc.")
    
    print("\n" + "-"*80)
    print("BY MODEL")
    print("-"*80)
    
    # Sort by cost descending
    sorted_models = sorted(
        stats['by_model'].items(),
        key=lambda x: x[1]['total_cost'],
        reverse=True
    )
    
    for model_name, model_stats in sorted_models:
        print(f"\nModel: {model_name}")
        print(f"  Calls: {model_stats['total_calls']}")
        print(f"  Input Tokens: {model_stats['total_input_tokens']:,}")
        print(f"  Output Tokens: {model_stats['total_output_tokens']:,}")
        print(f"  Total Tokens: {model_stats['total_tokens']:,}")
        print(f"  Cost: ${model_stats['total_cost']:.4f}")
    
    # Save to file if requested
    if args.output:
        output_data = {
            "log_files": [str(f) for f in args.log_file],
            "total_records": len(all_records),
            "summary": stats,
            "records": all_records[:1000],  # Limit to first 1000 records to avoid huge files
        }
        
        with open(args.output, 'w', encoding='utf-8') as f:
            if args.pretty:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            else:
                json.dump(output_data, f, ensure_ascii=False)
        
        print(f"\nDetailed results saved to: {args.output}")
    
    return 0


if __name__ == "__main__":
    exit(main())

