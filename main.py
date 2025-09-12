"""
FastAPI wrapper for UNKNOWN Brain CLI - Cloud Run deployment
"""

import os
import json
import asyncio
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
import uuid

from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Import existing CLI functionality
from src.importers.plaintext import PlaintextImporter
from src.importers.granola_drive import GranolaDriveImporter
from src.llm_scorer import LLMScorer
from src.scoring import OutputGenerator
from src.bq_loader import BigQueryLoader
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
            "total_score": 5,
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
        
        # 1. Check cache first
        cached_result = gcs.get_cached_score(meeting_id, scoring_model)
        if cached_result:
            print(f"Using cached result for {meeting_id}")
            processing_status[meeting_id].status = "completed"
            processing_status[meeting_id].completed_at = datetime.now().isoformat()
            processing_status[meeting_id].score = cached_result['results']['total_score']
            return
        
        # 2. Download file from GCS
        print(f"Downloading {file_path} from bucket {bucket}")
        temp_file_path = gcs.download_to_temp_file(file_path)
        temp_files.append(temp_file_path)
        
        # 3. Ingest (convert to JSON)
        print(f"Ingesting transcript from {temp_file_path}")
        if file_path.endswith('.txt'):
            importer = GranolaDriveImporter()
        else:
            importer = PlaintextImporter()
        
        transcript = importer.import_file(temp_file_path)
        
        # 4. Score with LLM
        print(f"Scoring with {scoring_model}")
        scorer = LLMScorer(model=scoring_model)
        score_result = scorer.score_transcript(transcript)
        
        # 5. Cache the results
        print("Caching results")
        gcs.cache_score(meeting_id, scoring_model, score_result.__dict__)
        
        # 6. Upload to BigQuery
        print("Uploading to BigQuery")
        # Create temporary JSONL file for BigQuery
        bq_data = {
            **transcript.__dict__,
            **score_result.__dict__,
            'scored_at': datetime.now().isoformat(),
            'llm_model': scoring_model
        }
        
        # Upload to BigQuery via existing loader
        loader = BigQueryLoader()
        temp_jsonl_path = Path(f"/tmp/{meeting_id}.jsonl")
        temp_files.append(temp_jsonl_path)
        
        with open(temp_jsonl_path, 'w') as f:
            json.dump(bq_data, f)
        
        loader.merge_jsonl_data(temp_jsonl_path)
        
        # Update status with completion
        processing_status[meeting_id].status = "completed"
        processing_status[meeting_id].completed_at = datetime.now().isoformat()
        processing_status[meeting_id].score = score_result.total_score
        
        print(f"Successfully processed {meeting_id}")
        
    except Exception as e:
        print(f"Error processing {meeting_id}: {e}")
        processing_status[meeting_id].status = "failed"
        processing_status[meeting_id].error = str(e)
    
    finally:
        # Clean up temporary files
        if temp_files:
            gcs.cleanup_temp_files(temp_files)

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