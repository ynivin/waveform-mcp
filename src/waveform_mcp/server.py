"""MCP server for RTL waveform analysis using WAL (Waveform Analysis Language).

This server provides tools for analyzing waveform files from RTL simulations,
allowing LLMs to inspect signals, detect transitions, and debug hardware designs.

Supported formats: VCD, FST (via WAL)
"""

import asyncio
import logging
from typing import Any, Dict, List
import re

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.server.lowlevel import NotificationOptions
from mcp.types import TextContent, Tool

from wal.core import TraceContainer
from wal.eval import SEval
from wal.core import read_wal_sexpr

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Server("waveform-mcp")

_waveform_cache: Dict[str, TraceContainer] = {}

# WAL Documentation and Examples
WAL_DOCUMENTATION = {
    "overview": """
WAL (Waveform Analysis Language) - Quick Reference

WAL is a functional programming language designed for waveform analysis with Lisp-like syntax.
All expressions use parentheses: (function arg1 arg2 ...)

Key Concepts:
• Signals: Access by name (e.g., 'clk', 'tb.counter')
• Time: Navigate with (step N) or use INDEX for current time
• Lists: Most operations return lists of values/times
• Conditions: Use for filtering and searching
""",

    "functions": """
Core WAL Functions for Waveform Analysis:

TIME & NAVIGATION:
• (step N) - Move N steps forward in time
• INDEX - Current time index
• (find condition) - Find all times where condition is true

SIGNAL ACCESS:
• SIGNALS - List of all signal names
• signal_name - Access signal values at current time
• (length signal_or_list) - Get length of signal timeline or list

SEARCH & FILTER:
• (find condition) - Returns list of time indices where condition is true
• (count condition) - Count number of times condition is true
• (= signal value) - Test if signal equals value
• (!= signal value) - Test if signal not equal to value
• (> signal value) - Test if signal greater than value
• (< signal value) - Test if signal less than value

LOGICAL OPERATIONS:
• (&& cond1 cond2 ...) - Logical AND
• (|| cond1 cond2 ...) - Logical OR  
• Note: 'and', 'or', 'not' are not available in this WAL implementation

ARITHMETIC:
• (+ arg1 arg2 ...) - Addition
• (- arg1 arg2 ...) - Subtraction
• (* arg1 arg2 ...) - Multiplication
• (/ arg1 arg2 ...) - Division
""",

    "examples": """
WAL Usage Examples:

BASIC SIGNAL ACCESS:
• SIGNALS - List all signals
• clk - Get clock value at current time
• (step 10) - Move 10 time steps forward

TIME & COUNTING:
• (length (find true)) - Total simulation length
• (count (= clk 1)) - Count clock high periods
• (count (= reset 0)) - Count time steps where reset is low

SIGNAL TRANSITIONS:
• (find (= clk 1)) - Find times when clock is high
• (find (&& (= clk 0) (= data 1))) - Find times when clk=0 AND data=1
• (find (|| (= sig1 1) (= sig2 1))) - Find times when either signal is high

COMPLEX CONDITIONS:
• (find (> counter 10)) - Find times when counter > 10
• (find (&& (= clk 1) (> counter 5))) - Find clk high with counter > 5
• (length (find (= state 3))) - How long was state = 3

DEBUGGING PATTERNS:
• (find (= overflow 1)) - Find overflow events
• (find (&& (= valid 1) (= ready 0))) - Find handshake violations
• Note: WAL != operator syntax varies by implementation

MULTI-STEP ANALYSIS:
• (step 0) (find (= reset 1)) - Go to start, find reset assertion times
• (length SIGNALS) - Number of signals in waveform
""",

    "debugging": """
Common WAL Debugging Patterns:

PROTOCOL ANALYSIS:
• Handshake: (find (&& (= valid 1) (= ready 0))) - Stalled transactions
• Bus idle: (find (&& (= valid 0) (= ready 1))) - Ready but no data
• State machines: (find (= state target_state)) - Time in specific state

TIMING ANALYSIS:
• Clock analysis: (length (find (= clk 1))) - Count clock high periods
• Pulse width: Use find with consecutive conditions
• Frequency: (/ (length (find true)) (length (find (= clk 1)))) - Approximate period

SIGNAL VALIDATION:
• Unknown states: (find (= signal 'x')) - Find X states (if supported)
• Range check: (find (> signal max_value)) - Values out of range  
• Constant check: (count (!= signal expected)) - Non-constant periods

MEMORY/COUNTER ANALYSIS:
• Overflow: (find (and (= counter 15) (= overflow 0))) - Missing overflow flag
• Increment: (find (!= counter (+ (prev counter) 1))) - Non-sequential counts
• Reset behavior: (find (and (= reset 1) (!= counter 0))) - Reset failures

ERROR DETECTION:
• Glitches: Look for very short pulses
• Race conditions: Multiple signals changing simultaneously
• Protocol violations: Invalid state combinations
""",

    "syntax": """
WAL Syntax Reference:

BASIC SYNTAX:
• Parentheses required: (function arg1 arg2)
• Comments: ; This is a comment
• Numbers: 123, 0xFF (hex), 0b1010 (binary)
• Strings: "text" or text without spaces
• Booleans: #t (true), #f (false)

FUNCTION CALLS:
• (function) - No arguments
• (function arg) - One argument  
• (function arg1 arg2 arg3) - Multiple arguments

OPERATORS:
• Arithmetic: + - * / ** (power)
• Comparison: = != < > <= >=
• Logical: and or not
• List: length, nth (if available)

VARIABLES:
• SIGNALS - Built-in list of signal names
• INDEX - Built-in current time index
• signal_name - Direct signal access

CONTROL FLOW:
• (if condition then else) - Conditional
• (let ((var value)) body) - Local variables (if supported)

COMMON PATTERNS:
• (function (condition signal value)) - Nested conditions
• (operation (find condition)) - Apply operation to search results
• (length (find condition)) - Count matching conditions
"""
}


@app.list_tools()
async def list_tools() -> List[Tool]:
    """Return list of available waveform analysis tools."""
    return [
            Tool(
                name="get_signal_list",
                description="Get hierarchical list of signals from waveform file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "waveform_file": {
                            "type": "string",
                            "description": "Path to waveform file (.vcd, .fst, etc.)",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Optional regex pattern to filter signals (e.g., 'cpu.*', 'top\\.m1\\.*')",
                            "default": "",
                        },
                    },
                    "required": ["waveform_file"],
                },
            ),
            Tool(
                name="get_signal_transitions",
                description="Get signal transitions within a time range",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "waveform_file": {
                            "type": "string",
                            "description": "Path to waveform file",
                        },
                        "signal_name": {
                            "type": "string",
                            "description": "Full signal name (e.g., 'cpu.pc')",
                        },
                        "start_time": {
                            "type": "integer",
                            "description": "Start time in simulation time units",
                            "default": 0,
                        },
                        "end_time": {
                            "type": "integer",
                            "description": "End time in simulation time units (0 = end of simulation)",
                            "default": 0,
                        },
                    },
                    "required": ["waveform_file", "signal_name"],
                },
            ),
            Tool(
                name="get_waveform_length",
                description="Get the length of the waveform file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "waveform_file": {
                            "type": "string",
                            "description": "Path to waveform file",
                        },
                    },
                    "required": ["waveform_file"],
                },
            ),
            Tool(
                name="execute_wal_expression",
                description="""Execute WAL (Waveform Analysis Language) expressions for advanced signal analysis.
                
WAL is a functional language with Lisp-like syntax. Key capabilities:
• Signal access: SIGNALS (list all), signal_name (get value)  
• Time navigation: (step N), INDEX, (find condition)
• Search/filter: (find condition), (count condition)
• Logic: (and), (or), (not), (=), (!=), (<), (>)
• Math: (+), (-), (*), (/)

Examples:
• (count (= clk 1)) - Count clock high periods
• (find (and (= clk 1) (= data 0))) - Find clock high with data low
• (length (find (> counter 10))) - Time steps where counter > 10
• (find (= overflow 1)) - Find overflow events

Use get_wal_help for detailed documentation and examples.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "waveform_file": {
                            "type": "string",
                            "description": "Path to waveform file",
                        },
                        "expression": {
                            "type": "string",
                            "description": "WAL expression to execute",
                        },
                    },
                    "required": ["waveform_file", "expression"],
                },
            ),
            Tool(
                name="get_wal_help",
                description="Get WAL (Waveform Analysis Language) documentation and examples",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Help topic: 'overview', 'functions', 'examples', 'debugging', 'syntax'",
                            "default": "overview",
                        },
                    },
                },
            ),
            Tool(
                name="get_wal_examples",
                description="Get WAL examples customized for specific waveform signals",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "waveform_file": {
                            "type": "string",
                            "description": "Path to waveform file",
                        },
                    },
                    "required": ["waveform_file"],
                },
            ),
    ]


@app.call_tool()
async def call_tool(tool_name: str, arguments: Dict[str, Any]):
    """Route tool calls to appropriate handlers."""
    try:
        if tool_name == "get_signal_list":
            return await _get_signal_list(arguments)
        elif tool_name == "get_signal_transitions":
            return await _get_signal_transitions(arguments)
        elif tool_name == "get_waveform_length":
            return await _get_waveform_length(arguments)
        elif tool_name == "execute_wal_expression":
            return await _execute_wal_expression(arguments)
        elif tool_name == "get_wal_help":
            return await _get_wal_help(arguments)
        elif tool_name == "get_wal_examples":
            return await _get_wal_examples(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {tool_name}")]
    except Exception as e:
        logger.error(f"Error in {tool_name}: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _load_waveform(waveform_file: str) -> TraceContainer:
    """Load waveform file using WAL, with caching.

    Args:
        waveform_file: Path to waveform file (.vcd, .fst, etc.)

    Returns:
        TraceContainer: WAL container with loaded waveform data
    """
    if waveform_file not in _waveform_cache:
        logger.info(f"Loading waveform file: {waveform_file}")
        container = TraceContainer()
        container.load(waveform_file)
        _waveform_cache[waveform_file] = container
    return _waveform_cache[waveform_file]


async def _get_signal_list(args: Dict[str, Any]) -> List[TextContent]:
    """Get hierarchical list of signals from waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file
            - pattern: Optional regex pattern to filter signal names

    Returns:
        List of TextContent with formatted signal list
    """
    waveform_file = args["waveform_file"]
    pattern = args.get("pattern", "")

    container = await _load_waveform(waveform_file)
    all_signals = container.signals

    try:
        if pattern:
            regex = re.compile(pattern)
            filtered_signals = [s for s in all_signals if regex.search(s)]
        else:
            filtered_signals = all_signals

        result_lines = [f"Signals in {waveform_file}:"]
        if pattern:
            result_lines.append(f"Filter pattern: {pattern}")

        for signal in filtered_signals:
            width = container.signal_width(signal)
            bit_word = "bit" if width == 1 else "bits"
            result_lines.append(f"  {signal} [{width} {bit_word}]")

        if not filtered_signals:
            if pattern:
                result_lines.append("  No signals found matching regex pattern.")
            else:
                result_lines.append("  No signals found in waveform file.")

    except re.error as e:
        result_lines = [
            f"Signals in {waveform_file}:",
            f"Invalid regex pattern '{pattern}': {e}",
            "Please provide a valid regex pattern."
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _get_signal_transitions(args: Dict[str, Any]) -> List[TextContent]:
    """Get signal transitions within specified time range.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file
            - signal_name: Full signal name (e.g., 'cpu.pc')
            - start_time: Start time in simulation units (optional, default: 0)
            - end_time: End time in simulation units (optional, default: end)

    Returns:
        List of TextContent with signal transition information
    """
    waveform_file = args["waveform_file"]
    signal_name = args["signal_name"]
    start_time = args.get("start_time", 0)
    end_time = args.get("end_time", 0)

    container = await _load_waveform(waveform_file)

    if signal_name not in container.signals:
        return [TextContent(
            type="text",
            text=f"Error: Signal '{signal_name}' not found in {waveform_file}"
        )]

    result_lines = [f"Signal analysis for '{signal_name}':"]
    width = container.signal_width(signal_name)
    bit_word = "bit" if width == 1 else "bits"
    result_lines.append(f"  Width: {width} {bit_word}")

    try:
        evaluator = SEval(container)
        actual_end_time = end_time

        if end_time == 0:
            waveform_length = evaluator.eval(read_wal_sexpr("(length (find true))"))
            actual_end_time = waveform_length - 1
        container.step(start_time)
        prev_value = container.signal_value(signal_name)
        result_lines.append(f"  Initial value at time {start_time}: {prev_value}")

        transitions = []
        current_time = start_time

        while current_time < actual_end_time:
            try:
                container.step(1)  # Advance by 1 step
                current_time += 1
                curr_value = container.signal_value(signal_name)

                if prev_value != curr_value:
                    transitions.append(f"  Time {current_time}: {prev_value} -> {curr_value}")
                prev_value = curr_value

            except Exception:
                break
        if transitions:
            result_lines.append("")
            result_lines.append("Transitions detected:")
            result_lines.extend(transitions)
        else:
            result_lines.append("")
            result_lines.append("No transitions detected in time range.")

        time_range = f"{start_time} to {actual_end_time if end_time == 0 else end_time}"
        result_lines.append(f"")
        result_lines.append(f"Time range analyzed: {time_range}")
        result_lines.append(f"Total time steps checked: {current_time - start_time}")

    except Exception as e:
        result_lines.append(f"  Error during transition detection: {e}")

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _get_waveform_length(args: Dict[str, Any]) -> List[TextContent]:
    """Get the length of the waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file

    Returns:
        List of TextContent with waveform length information
    """
    waveform_file = args["waveform_file"]

    container = await _load_waveform(waveform_file)

    try:
        evaluator = SEval(container)
        waveform_length = evaluator.eval(read_wal_sexpr("(length (find true))"))
        
        result_lines = [
            f"Waveform file: {waveform_file}",
            f"Length: {waveform_length} time steps",
            f"Time range: 0 to {waveform_length - 1}",
            f"Method: WAL (length (find true))"
        ]

    except Exception as e:
        result_lines = [
            f"Waveform file: {waveform_file}",
            f"Error getting waveform length: {str(e)}"
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _execute_wal_expression(args: Dict[str, Any]) -> List[TextContent]:
    """Execute WAL expression on waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file
            - expression: WAL expression to execute

    Returns:
        List of TextContent with expression execution results
    """
    waveform_file = args["waveform_file"]
    expression = args["expression"]

    container = await _load_waveform(waveform_file)

    try:
        evaluator = SEval(container)
        parsed_expr = read_wal_sexpr(expression)
        result = evaluator.eval(parsed_expr)

        result_lines = [
            f"WAL Expression: {expression}",
            f"Waveform file: {waveform_file}",
            "",
            f"Result: {result}",
            f"Result type: {type(result).__name__}"
        ]

        if isinstance(result, list) and len(result) > 5:
            result_lines.append(f"Result length: {len(result)}")
            result_lines.append("First few elements:")
            for i, item in enumerate(result[:5]):
                result_lines.append(f"  [{i}]: {item}")
            if len(result) > 5:
                result_lines.append(f"  ... and {len(result) - 5} more")

    except Exception as e:
        # Get signal-specific suggestions
        all_signals = list(container.signals) if container else []
        suggestions = _get_wal_error_suggestions(str(e), all_signals)
        
        result_lines = [
            f"WAL Expression: {expression}",
            f"Waveform file: {waveform_file}",
            "",
            f"Execution Error: {str(e)}",
            "",
            *suggestions,
            "",
            "For more help: use get_wal_help with topics 'examples', 'functions', or 'debugging'"
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _get_wal_help(args: Dict[str, Any]) -> List[TextContent]:
    """Get WAL documentation and examples.

    Args:
        args: Dictionary containing:
            - topic: Help topic (overview, functions, examples, debugging, syntax)

    Returns:
        List of TextContent with WAL documentation
    """
    topic = args.get("topic", "overview")
    
    if topic not in WAL_DOCUMENTATION:
        available_topics = ", ".join(WAL_DOCUMENTATION.keys())
        return [TextContent(
            type="text",
            text=f"Unknown topic '{topic}'. Available topics: {available_topics}"
        )]
    
    content = WAL_DOCUMENTATION[topic]
    
    # Add topic header and navigation info
    result_lines = [
        f"WAL Help - {topic.title()}",
        "=" * 50,
        content.strip(),
        "",
        f"Available topics: {', '.join(WAL_DOCUMENTATION.keys())}",
        "Use get_wal_help with different topic for more information."
    ]
    
    return [TextContent(type="text", text="\n".join(result_lines))]


def _get_wal_error_suggestions(error_msg: str, signals: list) -> List[str]:
    """Generate helpful WAL suggestions based on error message and available signals."""
    suggestions = []
    
    if "undefined" in error_msg.lower():
        suggestions.extend([
            "Variable/function not found. Try:",
            "• Check signal names with SIGNALS",
            "• Use exact signal names from your waveform",
            f"• Available signals: {', '.join(signals[:5])}{'...' if len(signals) > 5 else ''}"
        ])
    
    if "argument must be a list" in error_msg.lower():
        suggestions.extend([
            "Function expects a list. Try:",
            "• (find condition) returns a list of time indices",
            "• (length (find condition)) to count matches",
            f"• Use signal names directly: {signals[0] if signals else 'signal_name'}"
        ])
    
    if not suggestions:
        # Generic suggestions
        suggestions.extend([
            "Common WAL patterns to try:",
            "• SIGNALS - List all signal names",
            "• (find (= signal_name value)) - Find when signal equals value",
            "• (count condition) - Count occurrences",
            "• (length (find true)) - Total simulation length"
        ])
    
    # Add signal-specific examples
    if signals:
        first_signal = signals[0]
        suggestions.extend([
            "",
            f"Examples with your signals (using '{first_signal}'):",
            f"• (find (= {first_signal} 1)) - Find when {first_signal} is high",
            f"• (count (= {first_signal} 0)) - Count when {first_signal} is low",
            f"• (length (find (!= {first_signal} 0))) - Time steps when {first_signal} != 0"
        ])
    
    return suggestions


async def _get_wal_examples(args: Dict[str, Any]) -> List[TextContent]:
    """Get WAL examples customized for the specific waveform signals.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file

    Returns:
        List of TextContent with signal-specific WAL examples
    """
    waveform_file = args["waveform_file"]
    
    try:
        container = await _load_waveform(waveform_file)
        all_signals = list(container.signals)
        
        if not all_signals:
            return [TextContent(
                type="text", 
                text="No signals found in waveform file"
            )]
        
        # Categorize signals by type for better examples
        clock_signals = [s for s in all_signals if 'clk' in s.lower()]
        reset_signals = [s for s in all_signals if 'reset' in s.lower() or 'rst' in s.lower()]
        counter_signals = [s for s in all_signals if 'counter' in s.lower() or 'count' in s.lower()]
        data_signals = [s for s in all_signals if s not in clock_signals + reset_signals + counter_signals]
        
        result_lines = [
            f"WAL Examples for {waveform_file}",
            "=" * 60,
            f"Available signals: {len(all_signals)} total",
            ""
        ]
        
        # Basic signal access examples
        result_lines.extend([
            "BASIC SIGNAL ACCESS:",
            "• SIGNALS - List all signals in waveform",
            f"• {all_signals[0]} - Get current value of {all_signals[0]}",
            "• INDEX - Current time index",
            "• (length (find true)) - Total simulation length",
            ""
        ])
        
        # Clock-specific examples
        if clock_signals:
            clk = clock_signals[0]
            result_lines.extend([
                f"CLOCK ANALYSIS (using {clk}):",
                f"• (find (= {clk} 1)) - Find all clock high times",
                f"• (length (find (= {clk} 1))) - Count clock high periods",
                f"• (step 0) (find (= {clk} 1)) - Go to start, find clock highs",
                ""
            ])
        
        # Reset-specific examples  
        if reset_signals:
            rst = reset_signals[0]
            result_lines.extend([
                f"RESET ANALYSIS (using {rst}):",
                f"• (find (= {rst} 1)) - Find reset assertion times",
                f"• (find (= {rst} 0)) - Find reset deassertion times",
                f"• (length (find (= {rst} 1))) - Total reset duration",
                ""
            ])
        
        # Counter-specific examples
        if counter_signals:
            cnt = counter_signals[0]
            result_lines.extend([
                f"COUNTER ANALYSIS (using {cnt}):",
                f"• (find (= {cnt} 0)) - Find when counter is zero",
                f"• (find (> {cnt} 10)) - Find when counter > 10",
                f"• (length (find (>= {cnt} 1))) - Non-zero periods",
                ""
            ])
        
        # Multi-signal analysis examples
        if len(all_signals) >= 2:
            sig1, sig2 = all_signals[0], all_signals[1]
            result_lines.extend([
                f"MULTI-SIGNAL PATTERNS:",
                f"• (find (&& (= {sig1} 1) (= {sig2} 0))) - {sig1} high AND {sig2} low",
                f"• (find (|| (= {sig1} 1) (= {sig2} 1))) - Either signal high",
                f"• (find (&& (>= {sig1} 1) (>= {sig2} 1))) - Both signals non-zero",
                ""
            ])
        
        # Debugging patterns
        result_lines.extend([
            "DEBUGGING PATTERNS:",
            f"• (find (= overflow 1)) - Find overflow events (if overflow signal exists)",
            f"• (find (&& (= valid 1) (= ready 0))) - Handshake stalls (if protocol signals exist)",
            f"• (length (find (> {all_signals[-1]} 15))) - Values out of range (example: >15)",
            "",
            "TIMING ANALYSIS:",
            f"• (step 0) INDEX - Go to start and show time",
            f"• (step 10) {all_signals[0]} - Advance 10 steps and show signal value",
            f"• (find (= {all_signals[0]} target)) - Find specific signal values",
            "",
            "For more help: use get_wal_help with topics 'functions', 'debugging', or 'syntax'"
        ])
        
    except Exception as e:
        result_lines = [
            f"Error loading waveform {waveform_file}: {str(e)}",
            "",
            "Use get_wal_help for general WAL documentation"
        ]
    
    return [TextContent(type="text", text="\n".join(result_lines))]


async def main():
    """Main entry point for the MCP server.

    Starts the server using stdio transport for communication with MCP clients.
    """
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="waveform-mcp",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())