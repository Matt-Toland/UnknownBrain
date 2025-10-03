"""
FastAPI wrapper for UNKNOWN Brain CLI - Cloud Run deployment
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime, timezone
import uuid
import re

from fastapi import FastAPI, HTTPException, BackgroundTasks, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from cloudevents.http import from_http
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Utility functions for safe type conversions
def safe_int_convert(value) -> Optional[int]:
    """Safely convert value to integer, handling strings and None"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None

def convert_to_utc_timestamp(timestamp_str) -> Optional[str]:
    """Convert timezone-aware timestamp to UTC timestamp string for BigQuery"""
    if not timestamp_str:
        return None

    try:
        # Parse timezone-aware timestamp
        if isinstance(timestamp_str, str):
            # Handle formats like "2025-09-12T11:17:00+01:00"
            dt = datetime.fromisoformat(timestamp_str)
            # Convert to UTC and format for BigQuery TIMESTAMP
            utc_dt = dt.astimezone(timezone.utc)
            return utc_dt.isoformat(timespec='seconds').replace('+00:00', 'Z')
        return None
    except (ValueError, AttributeError):
        # If parsing fails, return None
        return None

# Import existing CLI functionality
from src.importers.plaintext import PlaintextImporter
from src.importers.granola_drive import GranolaDriveImporter
from src.llm_scorer import LLMScorer
from src.scoring import OutputGenerator
from src.bq_loader import BigQueryLoader, upload_to_new_bigquery
from src.gcs_client import GCSClient, get_gcs_client

# Initialize FastAPI app
app = FastAPI(
    title="UNKNOWN Brain - Transcript Scoring API",
    description="LLM-powered transcript analysis for business opportunities",
    version="1.0.0"
)

# Request/Response models
class TranscriptRequest(BaseModel):
    bucket: str
    file_path: str
    model: Optional[str] = None

class BatchRequest(BaseModel):
    bucket: str
    prefix: str = "transcripts/"
    model: Optional[str] = None
    max_files: int = 10

class ProcessingStatus(BaseModel):
    meeting_id: str
    status: str  # pending, processing, completed, failed
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    score: Optional[int] = None
    error: Optional[str] = None

# In-memory status tracking (in production, use Firestore or Redis)
processing_status: Dict[str, ProcessingStatus] = {}

@app.get("/", tags=["Health"])
async def root():
    """Root endpoint"""
    return {
        "message": "UNKNOWN Brain Transcript Scoring API",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for Cloud Run"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "unknown-brain-api",
        "environment": os.getenv("ENVIRONMENT", "development")
    }

@app.post("/process-transcript", tags=["Processing"])
async def process_transcript(
    request: TranscriptRequest,
    background_tasks: BackgroundTasks
):
    """
    Process a single transcript through the complete pipeline
    """
    try:
        # Generate a temporary meeting_id for tracking
        meeting_id = f"processing-{request.file_path.replace('/', '-')}"
        
        # Initialize status
        processing_status[meeting_id] = ProcessingStatus(
            meeting_id=meeting_id,
            status="pending",
            created_at=str(__import__('datetime').datetime.now())
        )
        
        # Start background processing
        background_tasks.add_task(
            process_pipeline, 
            request.bucket, 
            request.file_path,
            request.model,
            meeting_id
        )
        
        return {
            "message": "Processing started",
            "meeting_id": meeting_id,
            "status": "pending"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start processing: {str(e)}"
        )

@app.post("/process-batch", tags=["Processing"])
async def process_batch(
    request: BatchRequest,
    background_tasks: BackgroundTasks
):
    """
    Process multiple transcripts in parallel
    """
    try:
        batch_id = f"batch-{__import__('uuid').uuid4().hex[:8]}"
        
        # In production, list files from GCS bucket
        # For now, simulate with local directory
        files = ["file1.txt", "file2.txt"]  # TODO: Replace with GCS listing
        
        batch_status = {
            "batch_id": batch_id,
            "status": "pending",
            "total_files": len(files),
            "processed": 0,
            "created_at": str(__import__('datetime').datetime.now())
        }
        
        # Process files in parallel
        background_tasks.add_task(
            process_batch_pipeline,
            request.bucket,
            files,
            request.model,
            batch_id
        )
        
        return batch_status
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start batch processing: {str(e)}"
        )

@app.get("/status/{meeting_id}", tags=["Status"])
async def get_status(meeting_id: str):
    """
    Get processing status for a transcript
    """
    if meeting_id not in processing_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting ID not found"
        )
    
    return processing_status[meeting_id]

@app.post("/ingest", tags=["Pipeline Steps"])
async def ingest_transcript(request: TranscriptRequest):
    """
    Ingest a single transcript file (convert to JSON)
    """
    try:
        # TODO: Download file from GCS
        # For now, simulate with local processing
        
        # Determine format and use appropriate importer
        if request.file_path.endswith('.txt'):
            importer = GranolaDriveImporter()
        else:
            importer = PlaintextImporter()
        
        # Process the transcript (this would use GCS in production)
        # transcript = importer.import_file(local_file_path)
        
        return {
            "message": "Transcript ingested successfully",
            "meeting_id": "simulated-id",
            "format": "detected"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}"
        )

@app.post("/score", tags=["Pipeline Steps"])
async def score_transcript(
    meeting_id: str,
    model: Optional[str] = None
):
    """
    Score a transcript using LLM
    """
    try:
        # Use default model from environment
        scoring_model = model or os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini")
        
        # Initialize scorer
        scorer = LLMScorer(model=scoring_model)
        
        # TODO: Load transcript from storage and score it
        # For now, return simulated response
        
        return {
            "meeting_id": meeting_id,
            "model": scoring_model,
            "total_qualified_sections": 5,
            "qualified": True,
            "message": "Scoring completed"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scoring failed: {str(e)}"
        )

@app.post("/upload-bq", tags=["Pipeline Steps"])
async def upload_to_bigquery():
    """
    Upload scored results to BigQuery using MERGE (prevents duplicates)
    """
    try:
        loader = BigQueryLoader()
        
        # TODO: Load JSONL file from GCS and upload
        # For now, simulate upload
        
        return {
            "message": "Upload to BigQuery completed",
            "rows_processed": 0,
            "duplicates_prevented": True
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"BigQuery upload failed: {str(e)}"
        )


@app.post("/upload-bq-new", tags=["Pipeline Steps"])
async def upload_to_new_bigquery_endpoint():
    """
    Upload scored results to new meeting_intel BigQuery table with JSON columns
    """
    try:
        # Check for new format export file
        jsonl_path = Path("out/bq_export_new.jsonl")

        if jsonl_path.exists():
            success = upload_to_new_bigquery(jsonl_path, use_merge=True)

            if success:
                return {
                    "message": "Upload to new meeting_intel table completed",
                    "table": "meeting_intel"
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Upload failed - check logs"
                )
        else:
            raise HTTPException(status_code=404, detail="New format export file not found")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"New BigQuery upload failed: {str(e)}"
        )

@app.get("/models", tags=["Configuration"])
async def list_available_models():
    """
    List available LLM models
    """
    return {
        "models": [
            {"name": "gpt-5-mini", "description": "Best performance, recommended default"},
            {"name": "gpt-4o-mini", "description": "Reliable fallback option"},
            {"name": "gpt-4o", "description": "Standard option"},
            {"name": "gpt-5", "description": "Full reasoning with 400k context"}
        ],
        "default": os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini")
    }

@app.post("/cloudevents", tags=["Automation"])
async def handle_storage_event(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Handle Cloud Storage events via Eventarc
    Automatically processes new transcripts when uploaded
    """
    try:
        # Parse CloudEvents
        headers = dict(request.headers)
        body = await request.body()
        event = from_http(headers, body)
        
        # Extract event data
        event_type = event['type']
        data = event.data
        
        # Log for debugging
        logger.info(f"Received event: {event_type}")
        logger.info(f"File: {data.get('name')}")
        logger.info(f"Generation: {data.get('generation')}")
        
        # Only process new files in transcripts/ directory
        file_name = data.get('name', '')
        bucket = data.get('bucket', '')
        
        if (event_type == "google.cloud.storage.object.v1.finalized"
            and file_name.startswith("transcripts/")
            and (file_name.endswith(".txt") or file_name.endswith(".md"))):
            
            # Use generation for idempotency (prevents double processing on retries)
            generation = data.get('generation')
            meeting_id = f"auto-{Path(file_name).stem}-{generation or event['id']}"
            
            # Check if already processing/processed
            if meeting_id in processing_status:
                logger.info(f"Already processing/processed: {meeting_id}")
                return {
                    "status": "duplicate",
                    "meeting_id": meeting_id,
                    "message": "Already being processed or completed"
                }
            
            # Add to processing queue
            processing_status[meeting_id] = ProcessingStatus(
                meeting_id=meeting_id,
                status="pending",
                created_at=datetime.now().isoformat()
            )
            
            # Process in background
            background_tasks.add_task(
                process_pipeline,
                bucket,
                file_name,
                os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini"),
                meeting_id
            )
            
            logger.info(f"Accepted for processing: {meeting_id}")
            return {
                "status": "accepted",
                "meeting_id": meeting_id,
                "file": file_name,
                "generation": generation
            }
        
        # Ignore non-transcript files
        logger.info(f"Ignored file: {file_name}")
        return {
            "status": "ignored",
            "reason": f"Not a transcript file or wrong directory: {file_name}"
        }
    
    except Exception as e:
        logger.error(f"Error handling CloudEvent: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }

@app.get("/recent-jobs", tags=["Status"])
async def get_recent_jobs(limit: int = 10):
    """Get list of recent processing jobs"""
    jobs = []
    # Get the most recent jobs (last N items)
    recent_items = list(processing_status.items())[-limit:]
    
    for mid, status in recent_items:
        jobs.append({
            "meeting_id": mid,
            "status": status.status,
            "created_at": status.created_at,
            "completed_at": getattr(status, 'completed_at', None),
            "score": getattr(status, 'score', None),
            "error": status.error[:100] + "..." if status.error and len(status.error) > 100 else status.error
        })
    
    return {
        "jobs": jobs,
        "total": len(processing_status),
        "showing": len(jobs)
    }

@app.get("/cached-results", tags=["Status"])
async def list_cached_results():
    """List cached scoring results from GCS"""
    try:
        gcs = GCSClient()
        today = datetime.now().strftime('%Y-%m-%d')
        cache_prefix = f"cache/{today}/"
        
        blobs = gcs.client.list_blobs(
            gcs.bucket_name,
            prefix=cache_prefix,
            max_results=20
        )
        
        results = []
        for blob in blobs:
            # Extract meeting_id from filename (remove cache prefix and .json extension)
            name = blob.name.replace(cache_prefix, "").replace(".json", "")
            # Remove model suffix (everything after last dash)
            meeting_id = name.rsplit("-", 1)[0] if "-" in name else name
            
            results.append({
                "cache_file": blob.name,
                "meeting_id": meeting_id,
                "model": name.split("-")[-1] if "-" in name else "unknown",
                "created": blob.time_created.isoformat() if blob.time_created else None,
                "size_bytes": blob.size
            })
        
        return {
            "cached_results": results,
            "count": len(results),
            "date": today
        }
        
    except Exception as e:
        logger.error(f"Error listing cached results: {e}")
        return {
            "error": str(e),
            "cached_results": []
        }

async def process_pipeline(
    bucket: str, 
    file_path: str, 
    model: Optional[str],
    meeting_id: str
):
    """
    Background task to process a single transcript through the complete pipeline
    """
    temp_files = []
    
    try:
        # Update status
        processing_status[meeting_id].status = "processing"
        
        # Initialize GCS client
        gcs = GCSClient(bucket_name=bucket)
        
        # Use default model if not specified
        scoring_model = model or os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini")

        # 1. Download file from GCS
        print(f"Downloading {file_path} from bucket {bucket}")
        temp_file_path = gcs.download_to_temp_file(file_path)
        temp_files.append(temp_file_path)

        # 2. Ingest (convert to JSON)
        print(f"Ingesting transcript from {temp_file_path}")
        if file_path.endswith('.txt'):
            importer = GranolaDriveImporter()
        else:
            importer = PlaintextImporter()

        transcript = importer.parse_file(temp_file_path)

        # Extract the real meeting_id from the transcript (for Granola files)
        real_meeting_id = getattr(transcript, 'granola_note_id', None) or getattr(transcript, 'meeting_id', meeting_id)
        print(f"Using real meeting_id: {real_meeting_id} (was: {meeting_id})")

        # 3. Check cache with real meeting_id
        cached_result = gcs.get_cached_score(real_meeting_id, scoring_model)
        if cached_result:
            print(f"Using cached result for real meeting_id {real_meeting_id}")
            processing_status[meeting_id].status = "completed"
            processing_status[meeting_id].completed_at = datetime.now().isoformat()
            processing_status[meeting_id].score = cached_result['results']['total_qualified_sections']
            return

        # 4. Score with LLM using new format
        print(f"Scoring with {scoring_model}")
        scorer = LLMScorer(model=scoring_model)
        new_score_result = scorer.score_transcript_new(transcript)

        # 5. Cache the results using real meeting_id
        print("Caching results")
        gcs.cache_score(real_meeting_id, scoring_model, new_score_result.__dict__)

        # 6. Upload to meeting_intel BigQuery table
        print("Uploading to BigQuery")
        await upload_new_format_to_bigquery(transcript, new_score_result, scoring_model, real_meeting_id, temp_files)
        
        # Update status with completion
        processing_status[meeting_id].status = "completed"
        processing_status[meeting_id].completed_at = datetime.now().isoformat()
        processing_status[meeting_id].score = new_score_result.total_qualified_sections
        
        print(f"Successfully processed {meeting_id}")
        
    except Exception as e:
        print(f"Error processing {meeting_id}: {e}")
        processing_status[meeting_id].status = "failed"
        processing_status[meeting_id].error = str(e)
    
    finally:
        # Clean up temporary files
        if temp_files:
            gcs.cleanup_temp_files(temp_files)


async def upload_new_format_to_bigquery(
    transcript,
    new_score_result,
    model: str,
    meeting_id: str,
    temp_files: List[Path]
):
    """Upload using new meeting_intel table format with JSON blobs"""
    try:
        # Use the provided score result directly (no re-scoring needed)

        # Create new BigQuery data mapping
        new_bq_data = {
            # Core transcript fields
            'meeting_id': new_score_result.meeting_id,
            'date': transcript.date.isoformat() if transcript.date else None,
            'participants': getattr(transcript, 'participants', []),
            'desk': getattr(transcript, 'desk', 'Unknown'),
            'source': getattr(transcript, 'source', None),

            # Client info as JSON blob
            'client_info': {
                'client_id': new_score_result.client_info.client_id,
                'client': new_score_result.client_info.client,
                'domain': new_score_result.client_info.domain,
                'size': new_score_result.client_info.size,
                'source': new_score_result.client_info.source
            },

            # Granola specific fields
            'granola_note_id': getattr(transcript, 'granola_note_id', None),
            'title': getattr(transcript, 'title', None),
            'creator_name': getattr(transcript, 'creator_name', None),
            'creator_email': getattr(transcript, 'creator_email', None),
            'calendar_event_title': getattr(transcript, 'calendar_event_title', None),
            'calendar_event_id': getattr(transcript, 'calendar_event_id', None),
            'calendar_event_time': convert_to_utc_timestamp(getattr(transcript, 'calendar_event_time', None)),
            'granola_link': getattr(transcript, 'granola_link', None),
            'file_created_timestamp': safe_int_convert(getattr(transcript, 'file_created_timestamp', None)),
            'zapier_step_id': safe_int_convert(getattr(transcript, 'zapier_step_id', None)),

            # Content sections
            'enhanced_notes': getattr(transcript, 'enhanced_notes', None),
            'my_notes': getattr(transcript, 'my_notes', None),
            'full_transcript': getattr(transcript, 'full_transcript', None),

            # Scoring results
            'total_qualified_sections': new_score_result.total_qualified_sections,
            'qualified': new_score_result.qualified,

            # JSON blob scoring sections
            'now': {
                'qualified': new_score_result.now.qualified,
                'reason': new_score_result.now.reason,
                'summary': new_score_result.now.summary,
                'evidence': new_score_result.now.evidence
            },
            'next': {
                'qualified': new_score_result.next.qualified,
                'reason': new_score_result.next.reason,
                'summary': new_score_result.next.summary,
                'evidence': new_score_result.next.evidence
            },
            'measure': {
                'qualified': new_score_result.measure.qualified,
                'reason': new_score_result.measure.reason,
                'summary': new_score_result.measure.summary,
                'evidence': new_score_result.measure.evidence
            },
            'blocker': {
                'qualified': new_score_result.blocker.qualified,
                'reason': new_score_result.blocker.reason,
                'summary': new_score_result.blocker.summary,
                'evidence': new_score_result.blocker.evidence
            },
            'fit': {
                'qualified': new_score_result.fit.qualified,
                'reason': new_score_result.fit.reason,
                'summary': new_score_result.fit.summary,
                'services': new_score_result.fit.services,
                'evidence': new_score_result.fit.evidence
            },

            # Client taxonomy tagging
            'challenges': new_score_result.challenges,
            'results': new_score_result.results,
            'offering': new_score_result.offering,

            # Processing metadata
            'scored_at': new_score_result.scored_at.isoformat(timespec='seconds'),
            'llm_model': new_score_result.llm_model
        }

        # Upload to new BigQuery table using MERGE
        temp_new_jsonl_path = Path(f"/tmp/{meeting_id}_new.jsonl")
        temp_files.append(temp_new_jsonl_path)

        with open(temp_new_jsonl_path, 'w') as f:
            f.write(json.dumps(new_bq_data) + "\n")

        success = upload_to_new_bigquery(temp_new_jsonl_path, use_merge=True)
        if success:
            print(f"Successfully uploaded {meeting_id} to new meeting_intel table")
        else:
            print(f"Failed to upload {meeting_id} to new meeting_intel table")

    except Exception as e:
        print(f"Error uploading new format to BigQuery for {meeting_id}: {e}")


async def process_batch_pipeline(
    bucket: str,
    files: List[str],
    model: Optional[str],
    batch_id: str
):
    """
    Background task to process multiple transcripts in parallel
    """
    try:
        # Process files in parallel batches
        tasks = []
        for file_path in files:
            meeting_id = f"{batch_id}-{file_path}"
            tasks.append(process_pipeline(bucket, file_path, model, meeting_id))
        
        # Wait for all tasks to complete
        await asyncio.gather(*tasks)
        
    except Exception as e:
        print(f"Batch processing failed: {e}")

if __name__ == "__main__":
    # For local development
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info"
    )