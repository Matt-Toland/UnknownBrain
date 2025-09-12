# UNKNOWN Brain — LLM-Powered Transcript Scoring

An intelligent scoring system that uses OpenAI's GPT-5 and GPT-4o models to analyze meeting transcripts and identify business opportunities for UNKNOWN's talent services. Features BigQuery integration for analytics and advanced duplicate prevention.

## Quick Start

```bash
# Set up virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up API keys and BigQuery credentials
echo "OPENAI_API_KEY=your-key-here" > .env
echo "DEFAULT_LLM_MODEL=gpt-5-mini" >> .env
# Add gcp_service_account_creds.json for BigQuery

# Complete pipeline
python -m src.cli ingest                    # Process transcript files
python -m src.cli score --bq-export        # Score with GPT-5-mini + generate BigQuery export
python -m src.cli upload-bq-merge          # Upload to BigQuery (prevents duplicates)
```

## Complete End-to-End Pipeline

### 1. Setup (One-time)
```bash
# Environment setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure API keys
echo "OPENAI_API_KEY=sk-your-key-here" > .env
echo "DEFAULT_LLM_MODEL=gpt-5-mini" >> .env

# BigQuery setup (optional)
# Place gcp_service_account_creds.json in project root
echo "BQ_PROJECT_ID=your-project-id" >> .env
echo "BQ_DATASET=unknown_brain" >> .env
echo "BQ_TABLE=meeting_transcripts" >> .env
```

### 2. Processing Pipeline
```bash
# Step 1: Add transcript files to data/transcripts/
# Supports: Granola format (.txt) and Markdown (.md)

# Step 2: Ingest transcripts
python -m src.cli ingest
# Converts: data/transcripts/*.{md,txt} → data/json/*.json

# Step 3: Score with LLM  
python -m src.cli score --bq-export -v
# Uses: GPT-5-mini (default, best performance)
# Generates: out/scores.json, out/scores.csv, out/leaderboard.md, out/bq_export.jsonl

# Step 4: Upload to BigQuery (optional)
python -m src.cli upload-bq-merge
# Creates: BigQuery table with duplicate prevention
```

### 3. Advanced Commands
```bash
# Compare model performance
python -m src.cli compare-models --models gpt-5-mini,gpt-4o-mini,gpt-4o --verbose

# Use specific models
python -m src.cli score --model gpt-5         # Full GPT-5 with 400k context
python -m src.cli score --model gpt-4o        # Standard GPT-4o
python -m src.cli score --model gpt-4o-mini   # Fallback option

# BigQuery operations
python -m src.cli upload-bq-merge       # MERGE upload (prevents duplicates - RECOMMENDED)
python -m src.cli upload-bq             # Regular append (may create duplicates)
python -m src.cli dedupe-bq             # Clean existing duplicates

# Custom directories
python -m src.cli ingest --in custom/transcripts --out custom/json
python -m src.cli score --in custom/json --out custom/results
```

## Features

- **Multi-Model LLM Analysis**: GPT-5-mini (default), GPT-5, GPT-4o, with automatic API routing
- **Dual Format Support**: Granola Drive (.txt) and Markdown (.md) transcripts  
- **5-Point Scoring System**: NOW, NEXT, MEASURE, BLOCKER, FIT criteria with evidence extraction
- **Multiple Output Formats**: JSON, CSV, Markdown, and BigQuery JSONL
- **BigQuery Integration**: Complete analytics pipeline with duplicate prevention
- **Model Comparison**: Side-by-side performance testing across models
- **Production Ready**: Built for UNKNOWN's real meeting data with Granola→Zapier→Drive workflow
- **Performance Optimized**: GPT-5-mini delivers best results (5/5 scores vs 4/5 for GPT-4o)

## Project Structure

```
unknown-brain/
├── data/
│   ├── transcripts/          # Meeting transcript files (.md, .txt from Granola)
│   └── json/                 # Processed JSON files
├── src/
│   ├── llm_scorer.py        # Multi-model LLM scoring (GPT-5, GPT-4o)
│   ├── bq_loader.py         # BigQuery integration with duplicate prevention
│   ├── cli.py               # Command interface with model comparison
│   ├── schemas.py           # Data models and BigQuery schemas
│   ├── scoring.py           # Output generation (JSON, CSV, MD, JSONL)
│   └── importers/           # PlaintextImporter + GranolaDriveImporter
├── out/                     # Scoring results + BigQuery exports
├── tests/                   # Test suite
├── gcp_service_account_creds.json  # BigQuery credentials (not in repo)
└── venv/                    # Virtual environment
```

## Scoring System

Each transcript is evaluated across 5 criteria using GPT models:

1. **NOW** (1 point): Urgent hiring needs (≤60 days)
2. **NEXT** (1 point): Future opportunities (60-180 days) 
3. **MEASURE** (1 point): Clear success metrics/KPIs
4. **BLOCKER** (1 point): Obstacles/constraints mentioned
5. **FIT** (1 point): Matches UNKNOWN services (Talent/Evolve/Ventures)

**Qualified threshold**: ≥3/5 points

## CLI Commands

### Ingest Transcripts
Convert transcript files to JSON format:
```bash
# Default: data/transcripts/ → data/json/
python -m src.cli ingest

# Custom directories
python -m src.cli ingest --in custom/transcripts --out custom/json
```

### Score Transcripts
Analyze transcripts with LLM:
```bash
# Default: data/json/ → out/
python -m src.cli score

# With GPT-4o (higher quality)
python -m src.cli score --model gpt-4o

# Verbose output
python -m src.cli score -v
```

## Output Files

The scoring process generates multiple output files:

- **`out/scores.json`** - Complete results with evidence and model info
- **`out/scores.csv`** - Spreadsheet format for analysis
- **`out/leaderboard.md`** - Ranked results with detailed summaries
- **`out/bq_export.jsonl`** - BigQuery-ready format (when using --bq-export)

### BigQuery Integration
Upload scored data to BigQuery for advanced analytics:
```bash
# Generate BigQuery export during scoring
python -m src.cli score --bq-export

# Upload with duplicate prevention (recommended)
python -m src.cli upload-bq-merge

# Clean existing duplicates if needed
python -m src.cli dedupe-bq
```

## Example Results

```
UNKNOWN Brain Scoring Results (gpt-5-mini)
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Metric            ┃ Value      ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ Total Transcripts │ 1          │
│ Qualified (≥3/5)  │ 1 (100.0%) │
│ Average Score     │ 4.0/5      │
└───────────────────┴────────────┘

Top Scoring Meetings:
1. 31959290-405c-4490-ac7f-ad8cc88c43fe (Test Europe) - 4/5
```

## Model Performance Comparison

| Model | Typical Score | Speed | Cost | Use Case |
|-------|---------------|-------|------|----------|
| **gpt-5-mini** | 5/5 ⭐ | Fast | Low | **Default - Best overall performance** |
| gpt-4o-mini | 4/5 | Fast | Low | Reliable fallback option |
| gpt-4o | 4/5 | Medium | Medium | Standard alternative |
| gpt-5 | Varies | Slow | High | Full reasoning with 400k context |

Run model comparison:
```bash
python -m src.cli compare-models --models gpt-5-mini,gpt-4o-mini,gpt-4o --verbose
```

## Transcript Format

The system expects markdown files with structured meeting notes:

```markdown
# Meeting Title

Date, participants info...

### Section Headers

* Bullet point discussion items
* Key decisions and outcomes
* Action items and next steps
```

## Development

```bash
# Run tests
pytest -v

# Test with coverage
pytest --cov=src tests/

# Add new transcript
# 1. Place .md file in data/transcripts/
# 2. Run: python -m src.cli ingest
# 3. Run: python -m src.cli score
```

## Configuration

### API Keys
Set up your OpenAI API key and model preferences in `.env`:
```bash
OPENAI_API_KEY=sk-your-key-here
DEFAULT_LLM_MODEL=gpt-5-mini
FALLBACK_MODEL=gpt-4o-mini
LLM_MAX_TOKENS=2000
```

### BigQuery Setup (Optional)
For BigQuery integration:
```bash
BQ_PROJECT_ID=your-project-id
BQ_DATASET=unknown_brain
BQ_TABLE=meeting_transcripts
```

Place your service account credentials at `gcp_service_account_creds.json`.

### Environment Variables
Alternatively, export as environment variables:
```bash
export OPENAI_API_KEY=sk-your-key-here
export DEFAULT_LLM_MODEL=gpt-5-mini
```

## Available CLI Commands

```bash
python -m src.cli --help                    # Show all commands
python -m src.cli ingest --help             # Ingest options  
python -m src.cli score --help              # Scoring options
python -m src.cli upload-bq-merge --help    # BigQuery upload options
python -m src.cli compare-models --help     # Model comparison options
```

## Cloud Deployment (Production)

### Google Cloud Run Deployment

For production use, deploy to Google Cloud Run for automatic scaling, Cloud Storage integration, and serverless operation.

#### Quick Deploy
```bash
# 1. Set your Google Cloud project
export GOOGLE_CLOUD_PROJECT=your-project-id

# 2. Run deployment script
./deploy.sh
```

The deployment script automatically:
- Enables required GCP APIs
- Creates Cloud Storage bucket for transcripts
- Creates BigQuery dataset
- Builds and deploys to Cloud Run
- Sets up proper networking and permissions

#### Manual Deployment Steps
```bash
# Enable APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com

# Create Cloud Storage bucket
gsutil mb gs://unknown-brain-transcripts

# Deploy with Cloud Build
gcloud builds submit --config cloudbuild.yaml

# Set environment variables
gcloud run services update unknown-brain --region=us-central1 \
    --set-env-vars OPENAI_API_KEY=your-key,DEFAULT_LLM_MODEL=gpt-5-mini,GCS_BUCKET_NAME=unknown-brain-transcripts
```

#### API Endpoints (Cloud Run)
Once deployed, your API will be available at:
```
https://unknown-brain-xxx.run.app/
├── GET  /health              # Health check
├── GET  /docs                # Interactive API documentation  
├── POST /process-transcript  # Full pipeline processing
├── POST /process-batch       # Batch processing
├── POST /ingest              # Convert transcript to JSON
├── POST /score               # Score with LLM
├── POST /upload-bq           # Upload to BigQuery
└── GET  /status/{id}         # Check processing status
```

#### Production Features
- **Auto-scaling**: 0-10 instances based on demand
- **60-minute timeout**: Handles long LLM processing
- **Cloud Storage**: Automatic file management
- **BigQuery integration**: Built-in analytics
- **Caching**: GCS-based result caching
- **Error handling**: Comprehensive retry logic

#### Cost Estimate (1000 transcripts/month)
- Cloud Run: ~$2-3/month
- Cloud Storage: ~$0.02/month  
- BigQuery: ~$5/month (depending on queries)
- GPT-5-mini API: Main cost driver (~$20-50/month)

#### Monitoring & Logs
```bash
# View logs
gcloud logs read "resource.type=cloud_run_revision"

# Monitor metrics
gcloud run services describe unknown-brain --region=us-central1
```

---

Built for UNKNOWN's business development workflow. Analyzes real meeting transcripts from Granola→Zapier→Drive pipeline to identify qualified talent acquisition opportunities using state-of-the-art GPT-5 models.

**Local Development** → CLI-based processing with local files  
**Production Deployment** → Cloud Run API with GCS storage and BigQuery analytics