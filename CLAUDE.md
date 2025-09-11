# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Set up virtual environment (first time only)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up OpenAI API key in .env file
echo "OPENAI_API_KEY=your-key-here" > .env

# Ingest transcript files into JSON format
python -m src.cli ingest

# Score transcripts using LLM (default: gpt-5-mini)
python -m src.cli score --bq-export

# Use specific LLM model
python -m src.cli score --model gpt-4o-mini
python -m src.cli score --model gpt-5-mini
python -m src.cli score --model gpt-5

# Compare multiple models performance
python -m src.cli compare-models --models gpt-5-mini,gpt-4o-mini --verbose

# Upload scored data to BigQuery
python -m src.cli upload-bq

# Verbose output with detailed results
python -m src.cli score -v

# Custom input/output directories
python -m src.cli ingest --in custom/transcripts --out custom/json
python -m src.cli score --in custom/json --out custom/results

# Run all tests
pytest -v

# Run with coverage
pytest --cov=src tests/
```

## Architecture Overview

This is an LLM-powered transcript scoring system for UNKNOWN Brain that analyzes meeting notes to identify business opportunities.

### Core Components

**Data Flow**: Transcript Files → JSON → LLM Scoring → Multiple Output Formats → BigQuery
- `src/importers/` - Transcript parsers (PlaintextImporter + GranolaDriveImporter)
- `src/schemas.py` - Pydantic models for type safety
- `src/llm_scorer.py` - Multi-model LLM scoring (GPT-5, GPT-4o, o1)
- `src/scoring.py` - Output generation utilities
- `src/bq_loader.py` - BigQuery integration
- `src/cli.py` - Typer-based CLI with model comparison

### LLM Scoring System

5 binary checks using GPT models (0-5 total score):
1. **NOW**: Urgent hiring needs (≤60 days) 
2. **NEXT**: Future opportunities (60-180 days)
3. **MEASURE**: Clear success metrics/KPIs mentioned
4. **BLOCKER**: Explicit obstacles/constraints
5. **FIT**: Matches UNKNOWN services (Talent/Evolve/Ventures)

**Qualified threshold**: ≥3/5 points

### Data Model

Canonical JSON schema in `src/schemas.py`:
- `Transcript` - Main document with meeting_id, date, company, notes
- `Note` - Individual content entries (no timestamps required)
- `ScoreResult` - LLM scoring output with evidence and confidence
- `CheckResult/FitResult` - Individual criterion results

### LLM Integration

- **Models**: Multi-model support with automatic API routing
  - **GPT-5-mini** (default): Best performance (5/5 scores), uses Responses API
  - **GPT-5**: Full model with 400k context, uses Responses API
  - **GPT-4o-mini**: Reliable fallback (4/5 scores), uses Chat Completions
  - **GPT-4o**: Standard model, uses Chat Completions
  - **o1-mini**: Reasoning model (partial support)
- **Smart Routing**: Automatically uses correct API (Responses vs Chat Completions)
- **Prompts**: Specialized for UNKNOWN's business criteria
- **Evidence**: Each score includes supporting text from transcript
- **Error Handling**: Retry logic, empty response handling, graceful fallbacks

## Directory Structure

```
unknown-brain/
├── data/
│   ├── transcripts/          # Meeting notes (.md, .txt from Granola)
│   └── json/                 # Processed JSON files
├── src/
│   ├── importers/            # PlaintextImporter + GranolaDriveImporter
│   ├── llm_scorer.py        # Multi-model LLM scoring (GPT-5, GPT-4o)
│   ├── bq_loader.py         # BigQuery integration
│   ├── cli.py               # CLI with model comparison
│   ├── schemas.py           # Data models + BigQuery schemas
│   └── scoring.py           # Output generation (JSON, CSV, MD, JSONL)
├── tests/                   # Test files
├── out/                     # Scoring results + BigQuery exports
├── venv/                    # Python virtual environment
├── gcp_service_account_creds.json  # BigQuery credentials
├── requirements.txt         # Dependencies (includes google-cloud-bigquery)
└── .env                     # API keys + BigQuery config
```

## Production Usage

### Complete End-to-End Workflow

1. **Add transcript files** to `data/transcripts/` 
   - Granola format (.txt files with JSON metadata)
   - Markdown format (.md files)

2. **Ingest**: `python -m src.cli ingest` 
   - Auto-detects Granola vs Markdown format
   - Converts to canonical JSON

3. **Score**: `python -m src.cli score --bq-export`
   - Uses GPT-5-mini by default (best performance)
   - Generates all output formats including BigQuery JSONL

4. **Upload to BigQuery**: `python -m src.cli upload-bq-merge`
   - Creates dataset/table automatically  
   - Uses MERGE to prevent duplicates (recommended)
   - Updates existing records if re-scored

5. **Review results** in:
   - `out/leaderboard.md` - Human-readable summary
   - `out/scores.csv` - Spreadsheet format
   - BigQuery table for advanced analytics

### Model Performance Comparison

| Model | Score | Speed | Cost | Use Case |
|-------|--------|-------|------|----------|
| **gpt-5-mini** | 5/5 ⭐ | Fast | Low | **Default - Best overall** |
| gpt-4o-mini | 4/5 | Fast | Low | Reliable fallback |
| gpt-4o | 4/5 | Medium | Medium | Standard option |
| gpt-5 | Varies | Slow | High | Full reasoning |

### Advanced Commands

```bash
# Compare model performance
python -m src.cli compare-models --models gpt-5-mini,gpt-4o-mini,gpt-4o --verbose

# Upload with MERGE (prevents duplicates - RECOMMENDED)
python -m src.cli upload-bq-merge

# Upload with different modes (may create duplicates)
python -m src.cli upload-bq --mode replace  # Replace all data
python -m src.cli upload-bq --mode append   # Add to existing data

# Clean existing duplicates
python -m src.cli dedupe-bq

# Custom scoring with specific model
python -m src.cli score --model gpt-5 --bq-export --verbose
```

### BigQuery Duplicate Prevention

The system provides multiple approaches to handle duplicates:

1. **MERGE Upload** (Recommended): `upload-bq-merge`
   - Uses BigQuery MERGE statement for upserts
   - Prevents duplicates by matching on `meeting_id`
   - Updates existing records with latest scores
   - Safe to run multiple times

2. **Deduplication**: `dedupe-bq` 
   - Removes existing duplicates from table
   - Keeps most recent `scored_at` timestamp
   - One-time cleanup command

3. **Regular Upload**: `upload-bq`
   - Traditional append mode (may create duplicates)
   - Use only when certain no duplicates exist

## Development Notes

- **LLM-first approach**: Optimized for business conversation understanding  
- **Multi-model support**: Automatic API routing for different model types
- **Real transcript format**: Handles both Granola and markdown formats
- **Production ready**: Built for UNKNOWN's actual meeting data
- **BigQuery integration**: Complete analytics pipeline with duplicate prevention
- **Extensible**: Easy to add new models and scoring criteria
- **Performance optimized**: GPT-5-mini delivers best results