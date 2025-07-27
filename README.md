# Waveform MCP Server

MCP (Model Context Protocol) server for RTL waveform analysis using WAL (Waveform Analysis Language).

## Tools

### get_signal_list
Get hierarchical list of signals from waveform file with optional regex filtering.
- `waveform_file` (required): Path to waveform file
- `pattern` (optional): Regex pattern to filter signals

**Example:**
```json
{"tool": "get_signal_list", "arguments": {"waveform_file": "sim.vcd", "pattern": "cpu.*"}}
```

### get_signal_transitions  
Extract signal transitions within specified time ranges.
- `waveform_file` (required): Path to waveform file
- `signal_name` (required): Full signal name
- `start_time` (optional): Start time, default 0
- `end_time` (optional): End time, default end of simulation

**Example:**
```json
{"tool": "get_signal_transitions", "arguments": {"waveform_file": "sim.vcd", "signal_name": "clk", "start_time": 0, "end_time": 100}}
```

### get_waveform_length
Get the total simulation length/duration.
- `waveform_file` (required): Path to waveform file

**Example:**
```json
{"tool": "get_waveform_length", "arguments": {"waveform_file": "sim.vcd"}}
```

### execute_wal_expression
Execute WAL expressions for advanced waveform analysis.
- `waveform_file` (required): Path to waveform file  
- `expression` (required): WAL expression to execute

**Example:**
```json
{"tool": "execute_wal_expression", "arguments": {"waveform_file": "sim.vcd", "expression": "(find (= clk 1))"}}
```

### get_wal_help
Get comprehensive WAL documentation and syntax reference.
- `topic` (optional): Help topic ('overview', 'functions', 'examples', 'debugging', 'syntax')

**Example:**
```json
{"tool": "get_wal_help", "arguments": {"topic": "examples"}}
```

### get_wal_examples
Generate signal-specific WAL examples for your waveform.
- `waveform_file` (required): Path to waveform file

**Example:**
```json
{"tool": "get_wal_examples", "arguments": {"waveform_file": "sim.vcd"}}
```

## Supported Formats

- VCD (Value Change Dump)
- FST (Fast Signal Trace)  
- Other formats supported by WAL

## Credits

Built on [WAL (Waveform Analysis Language)](https://github.com/ics-jku/wal), a domain-specific language for hardware waveform analysis. See the [WAL website](https://wal-lang.org/) for more information.

## Installation

```bash
pip install -e .
```

## Development

To set up a development environment, install the `dev` dependencies:

```bash
pip install -e .[dev]
```

## Testing

To run the test suite:

```bash
pytest
```

## Usage

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "waveform": {
      "command": "waveform-mcp",
      "args": []
    }
  }
}
```

For WAL expression syntax and advanced examples, see the [WAL documentation](https://wal-lang.org/documentation/usage).

## Requirements

- Python 3.9+
- `cmake` (for FST support)
- [WAL (Waveform Analysis Language)](https://github.com/ics-jku/wal) >= 0.8.0
- MCP Python SDK >= 1.0.0

## License

BSD 3-Clause License. See [LICENSE](LICENSE) for details.