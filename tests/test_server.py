

import pytest
import os
from unittest.mock import patch

# Make sure the server module is importable
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from waveform_mcp import server
from mcp.types import TextContent

# Paths to the sample waveform files
TRACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'traces'))
VCD_FILE = os.path.join(TRACE_DIR, 'counter.vcd')
FST_FILE = os.path.join(TRACE_DIR, 'counter.fst')

WAVEFORM_FILES = [VCD_FILE, FST_FILE]

@pytest.fixture(autouse=True)
def clear_waveform_cache():
    """Clear the waveform cache before each test."""
    server._waveform_cache.clear()

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_load_waveform(waveform_file):
    """Test the _load_waveform function caches the result."""
    assert len(server._waveform_cache) == 0
    
    # First load
    container = await server._load_waveform(waveform_file)
    assert container is not None
    assert len(server._waveform_cache) == 1
    assert waveform_file in server._waveform_cache

    # Second load should be from cache
    container2 = await server._load_waveform(waveform_file)
    assert container2 is container  # Should be the same object
    assert len(server._waveform_cache) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_signal_list_all(waveform_file):
    """Test get_signal_list without any pattern."""
    args = {"waveform_file": waveform_file}
    result = await server._get_signal_list(args)
    
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    
    text = result[0].text
    assert f"Signals in {waveform_file}:" in text
    assert "tb.clk [1 bit]" in text
    assert "tb.reset [1 bit]" in text
    assert "tb.dut.counter [4 bits]" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_signal_list_with_pattern(waveform_file):
    """Test get_signal_list with a regex pattern."""
    args = {"waveform_file": waveform_file, "pattern": "tb\\.dut"}
    result = await server._get_signal_list(args)
    
    text = result[0].text
    assert "Filter pattern: tb\\.dut" in text
    assert "tb.dut.counter [4 bits]" in text
    assert "tb.clk" not in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_signal_list_no_match(waveform_file):
    """Test get_signal_list with a pattern that matches nothing."""
    args = {"waveform_file": waveform_file, "pattern": "nonexistent"}
    result = await server._get_signal_list(args)
    
    text = result[0].text
    assert "No signals found matching regex pattern." in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_signal_list_invalid_regex(waveform_file):
    """Test get_signal_list with an invalid regex pattern."""
    args = {"waveform_file": waveform_file, "pattern": "["}
    result = await server._get_signal_list(args)
    
    text = result[0].text
    assert "Invalid regex pattern '['" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_waveform_length(waveform_file):
    """Test get_waveform_length."""
    args = {"waveform_file": waveform_file}
    result = await server._get_waveform_length(args)
    
    text = result[0].text
    assert "Length: 81 time steps" in text
    assert "Time range: 0 to 80" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_signal_transitions_exists(waveform_file):
    """Test get_signal_transitions for a signal that exists."""
    args = {"waveform_file": waveform_file, "signal_name": "tb.clk"}
    result = await server._get_signal_transitions(args)
    
    text = result[0].text
    assert "Signal analysis for 'tb.clk'" in text
    assert "Width: 1 bit" in text
    assert "Initial value at time 0: 0" in text
    assert "Transitions detected:" in text
    assert "Time 1: 0 -> 1" in text
    assert "Time 2: 1 -> 0" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_signal_transitions_not_exists(waveform_file):
    """Test get_signal_transitions for a signal that does not exist."""
    args = {"waveform_file": waveform_file, "signal_name": "nonexistent"}
    result = await server._get_signal_transitions(args)
    
    text = result[0].text
    assert "Error: Signal 'nonexistent' not found" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_valid(waveform_file):
    """Test execute_wal_expression with a valid expression."""
    args = {
        "waveform_file": waveform_file,
        "expression": "(length (find (= tb.clk 1)))"
    }
    result = await server._execute_wal_expression(args)
    
    text = result[0].text
    assert "WAL Expression: (length (find (= tb.clk 1)))" in text
    assert "Result: 40" in text
    assert "Result type: int" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_invalid_syntax(waveform_file):
    """Test execute_wal_expression with invalid syntax."""
    args = {
        "waveform_file": waveform_file,
        "expression": "(count (= tb.clk 1)"  # Missing closing parenthesis
    }
    result = await server._execute_wal_expression(args)
    
    text = result[0].text
    assert "Execution Error:" in text

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_undefined_signal(waveform_file):
    """Test execute_wal_expression with an undefined signal."""
    args = {
        "waveform_file": waveform_file,
        "expression": "(find (= non_existent_signal 1))"
    }
    result = await server._execute_wal_expression(args)
    
    text = result[0].text
    assert "Execution Error:" in text

@pytest.mark.asyncio
async def test_get_wal_help():
    """Test get_wal_help for different topics."""
    # Default topic
    result_default = await server._get_wal_help({})
    text_default = result_default[0].text
    assert "WAL Help - Overview" in text_default

    # Specific topic
    result_functions = await server._get_wal_help({"topic": "functions"})
    text_functions = result_functions[0].text
    assert "WAL Help - Functions" in text_functions
    assert "Core WAL Functions" in text_functions

    # Invalid topic
    result_invalid = await server._get_wal_help({"topic": "invalid"})
    text_invalid = result_invalid[0].text
    assert "Unknown topic 'invalid'" in text_invalid

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_get_wal_examples(waveform_file):
    """Test get_wal_examples."""
    args = {"waveform_file": waveform_file}
    result = await server._get_wal_examples(args)
    
    text = result[0].text
    assert f"WAL Examples for {waveform_file}" in text
    assert "BASIC SIGNAL ACCESS:" in text
    assert "CLOCK ANALYSIS (using tb.clk):" in text
    assert "RESET ANALYSIS (using tb.reset):" in text
    assert "COUNTER ANALYSIS (using tb.dut.counter):" in text

@pytest.mark.asyncio
async def test_list_tools_return_format():
    """Test that list_tools returns proper List[Tool] format."""
    tools = await server.list_tools()
    
    # Should return a list of Tool objects
    assert isinstance(tools, list)
    assert len(tools) == 6  # We have 6 tools defined
    
    # Check that all items are Tool objects with required fields
    for tool in tools:
        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description') 
        assert hasattr(tool, 'inputSchema')
        assert isinstance(tool.name, str)
        assert isinstance(tool.description, str)
        assert isinstance(tool.inputSchema, dict)
    
    # Verify specific tool names exist
    tool_names = [tool.name for tool in tools]
    expected_tools = [
        "get_signal_list", "get_signal_transitions", "get_waveform_length",
        "execute_wal_expression", "get_wal_help", "get_wal_examples"
    ]
    for expected_tool in expected_tools:
        assert expected_tool in tool_names

@pytest.mark.asyncio
async def test_invalid_waveform_file_paths():
    """Test behavior with invalid waveform file paths."""
    invalid_paths = [
        "/nonexistent/path/file.vcd",
        "not_a_real_file.fst", 
        "",
        "/tmp/corrupted.vcd"
    ]
    
    for invalid_path in invalid_paths:
        # Test get_signal_list with invalid path
        result = await server._get_signal_list({"waveform_file": invalid_path})
        assert isinstance(result, list)
        assert len(result) == 1
        assert "Error:" in result[0].text or "error" in result[0].text.lower()
        
        # Test get_waveform_length with invalid path  
        result = await server._get_waveform_length({"waveform_file": invalid_path})
        assert isinstance(result, list)
        assert len(result) == 1
        assert "Error:" in result[0].text or "error" in result[0].text.lower()

@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_signal_transitions_time_range_parameters(waveform_file):
    """Test get_signal_transitions with different time range parameters."""
    signal_name = "tb.clk"
    
    # Test with start_time only
    args = {"waveform_file": waveform_file, "signal_name": signal_name, "start_time": 5}
    result = await server._get_signal_transitions(args)
    text = result[0].text
    assert f"Initial value at time 5:" in text
    assert "Time range analyzed: 5 to" in text
    
    # Test with both start_time and end_time
    args = {"waveform_file": waveform_file, "signal_name": signal_name, "start_time": 10, "end_time": 20}
    result = await server._get_signal_transitions(args)
    text = result[0].text
    assert "Initial value at time 10:" in text
    assert "Time range analyzed: 10 to 20" in text
    
    # Test with end_time = 0 (should use full range)
    args = {"waveform_file": waveform_file, "signal_name": signal_name, "start_time": 0, "end_time": 0}
    result = await server._get_signal_transitions(args)
    text = result[0].text
    assert "Initial value at time 0:" in text
    assert "Time range analyzed: 0 to 80" in text  # Based on known waveform length
    
    # Test with invalid time range (start > end)
    args = {"waveform_file": waveform_file, "signal_name": signal_name, "start_time": 50, "end_time": 30}
    result = await server._get_signal_transitions(args)
    text = result[0].text
    assert "Time range analyzed: 50 to 30" in text
    assert "No transitions detected" in text  # Should find no transitions

@pytest.mark.asyncio
@patch('waveform_mcp.server._get_signal_list')
async def test_call_tool_routing(mock_get_signals):
    """Test that call_tool routes to the correct function."""
    mock_get_signals.return_value = [TextContent(type="text", text="mocked")]
    
    await server.call_tool("get_signal_list", {})
    mock_get_signals.assert_called_once()

    result = await server.call_tool("unknown_tool", {})
    assert "Unknown tool: unknown_tool" in result[0].text

@pytest.mark.asyncio
async def test_call_tool_exception_handling():
    """Test that call_tool handles exceptions properly."""
    # Test with invalid arguments that should cause an exception
    result = await server.call_tool("get_signal_list", {"invalid_arg": "value"})
    assert isinstance(result, list)
    assert len(result) == 1
    assert "Error:" in result[0].text

@pytest.mark.asyncio
async def test_corrupted_waveform_handling():
    """Test error handling for corrupted/invalid waveform files."""
    # Create a temporary file with invalid VCD content
    import tempfile
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.vcd', delete=False) as f:
        f.write("This is not a valid VCD file content")
        temp_file = f.name
    
    try:
        # Test various operations with corrupted file
        result = await server._get_signal_list({"waveform_file": temp_file})
        assert isinstance(result, list)
        assert len(result) == 1
        assert "Error:" in result[0].text or "error" in result[0].text.lower()
        
        result = await server._get_waveform_length({"waveform_file": temp_file})
        assert isinstance(result, list) 
        assert len(result) == 1
        assert "Error:" in result[0].text or "error" in result[0].text.lower()
        
        result = await server._get_signal_transitions({
            "waveform_file": temp_file, 
            "signal_name": "any_signal"
        })
        assert isinstance(result, list)
        assert len(result) == 1
        assert "Error:" in result[0].text or "error" in result[0].text.lower()
        
    finally:
        # Clean up temp file
        import os
        try:
            os.unlink(temp_file)
        except:
            pass

@pytest.mark.asyncio 
async def test_waveform_cache_error_handling():
    """Test that waveform cache handles loading errors properly."""
    # Test that failed loads don't pollute the cache
    invalid_file = "/definitely/does/not/exist.vcd"
    
    # Verify cache is empty initially
    assert len(server._waveform_cache) == 0
    
    # Try to load invalid file - should raise exception but not cache
    try:
        await server._load_waveform(invalid_file)
    except:
        pass  # Expected to fail
    
    # Cache should still be empty after failed load
    assert len(server._waveform_cache) == 0

