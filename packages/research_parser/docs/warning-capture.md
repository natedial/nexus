# Warning Capture System

The research parser automatically captures warnings to individual files for later review. This helps track issues with specific documents during extraction.

## How It Works

When any `logger.warning()` is called with document context (file_name and file_id), the system automatically:

1. Creates a timestamped file in `data/warnings/`
2. Stores the warning message and all context data
3. Continues processing without interruption

## Warning File Location

```
data/warnings/{document_name}_{timestamp}.txt
```

Example:
```
data/warnings/Goldman_Sachs_Research_Q4_20260101_123045.txt
```

## What Gets Captured

Warnings are captured from these extraction steps:

- **Theme extraction failures** - When JSON parsing fails for themes
- **Trade extraction failures** - When JSON parsing fails for trades
- **Metadata extraction failures** - When JSON parsing fails for metadata
- **Boilerplate stripping issues** - When text cleaning fails
- **PDF parsing timeouts** - When LlamaIndex parsing times out

## Warning File Format

Each warning file contains:

```
================================================================================
WARNING CAPTURED
================================================================================

Timestamp: 2026-01-01T12:30:45.123456

Document Information:
  File Name: Goldman_Sachs_Research_Q4.pdf
  File ID:   abc123xyz789

Warning: Failed to parse themes JSON

Context:
  error:
    Invalid JSON format: Unexpected token at line 5
  raw:
    {"themes": [
      {"label": "Equity Market Outlook"
      // truncated invalid JSON...
================================================================================
```

## Reviewing Warnings

### List all warning files
```bash
ls -lh data/warnings/
```

### View a specific warning
```bash
cat data/warnings/My_Document_20260101_120000.txt
```

### Search warnings by document name
```bash
grep -l "Goldman_Sachs" data/warnings/*.txt
```

### Count warnings by date
```bash
ls data/warnings/ | cut -d_ -f-1 | sort | uniq -c
```

### View most recent warnings
```bash
ls -t data/warnings/ | head -5 | xargs -I {} cat "data/warnings/{}"
```

## Common Warning Patterns

### JSON Parsing Failures

**Cause**: LLM returned malformed JSON

**Example**:
```
Warning: Failed to parse themes JSON
Context:
  error: Invalid JSON format
  raw: {"themes": [{"label": "Market Outlook"...
```

**Action**: Review the raw output to see if the LLM response was truncated or malformed

### Extraction Timeouts

**Cause**: LLM took too long or API issues

**Example**:
```
Warning: Theme extraction failed
Context:
  error: Request timeout after 60s
```

**Action**: Check API status, consider retrying the document

### Missing Required Fields

**Cause**: LLM didn't include all required fields in response

**Example**:
```
Warning: Failed to parse metadata JSON
Context:
  error: Missing required field 'source'
```

**Action**: Review extraction prompts, may need adjustment

## Integration with Pipeline

The warning capture integrates seamlessly with the processing pipeline:

```python
# In pipeline.py
log = logger.bind(file_id=file_id, file_name=file_name)

try:
    extraction.themes = extract_themes(llm, clean_text, config)
except Exception as e:
    # This warning is automatically captured to a file
    log.warning("Theme extraction failed", error=str(e))
```

## Configuration

Warning capture is enabled by default. The processor is configured in `src/main.py`:

```python
structlog.configure(
    processors=[
        # ... other processors
        warning_processor,  # Captures warnings to files
        # ... remaining processors
    ]
)
```

### Change Warning Directory

To customize the warnings directory, modify `src/storage/warnings.py`:

```python
# Default location
WARNINGS_DIR = Path(__file__).parent.parent.parent / "data" / "warnings"

# Or pass custom path
capture = WarningCapture(warnings_dir=Path("/custom/path"))
```

## Cleanup

Warning files accumulate over time. To manage storage:

### Delete old warnings (older than 30 days)
```bash
find data/warnings -type f -mtime +30 -delete
```

### Archive warnings by month
```bash
# Create archive directory
mkdir -p data/warnings/archive/2025-12

# Move files
mv data/warnings/*_202512*.txt data/warnings/archive/2025-12/
```

### Compress old warnings
```bash
tar -czf warnings-archive-2025-12.tar.gz data/warnings/archive/2025-12/
rm -rf data/warnings/archive/2025-12/
```

## Testing

Test the warning capture system:

```bash
python3 scripts/test_warning_capture.py
```

This will create sample warnings in `data/warnings/` to verify the system is working.

## Troubleshooting

### No warnings being captured

**Check 1**: Ensure warnings have document context
```python
# ✗ Won't be captured (no context)
logger.warning("Something failed")

# ✓ Will be captured
log = logger.bind(file_name="document.pdf", file_id="123")
log.warning("Something failed")
```

**Check 2**: Verify processor is configured
```bash
grep -r "warning_processor" src/main.py
```

### Permission errors

Ensure the warnings directory is writable:
```bash
chmod 755 data/warnings
```

### Disk space issues

Check warning directory size:
```bash
du -sh data/warnings/
```

## Related Documentation

- [State Database](./reviewing-state-database.md) - Track processing status
- [Pipeline Architecture](../CLAUDE.md#architecture) - How extraction works
- [Fault Tolerance](../CLAUDE.md#fault-tolerance-design) - Error handling design
