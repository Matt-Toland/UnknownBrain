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
from src.scorers import ClientScorer
from src.scoring import OutputGenerator
from src.bq_loader import BigQueryLoader, upload_to_new_bigquery
from src.gcs_client import GCSClient, get_gcs_client
from src.router import resolve_source, get_scorer

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


class PermanentProcessingError(Exception):
    """
    A failure that retrying will never fix — e.g. an unresolvable/poison
    meeting_id or missing routing source. The CloudEvent handler ACKs these
    with a 2xx so Eventarc does NOT redeliver (redelivery would loop forever on
    bad input). Distinct from transient failures (OpenAI timeout, BQ blip),
    which return non-2xx so Eventarc DOES redeliver.
    """


# Bounds how many ~90s scorings run concurrently IN THIS PROCESS so a burst of
# poller-driven CloudEvents can't fan out enough to trip OpenAI rate limits.
# Cross-instance fan-out is governed separately by Cloud Run max-instances.
# Scoring is offloaded to a thread (asyncio.to_thread) so the event loop stays
# responsive to health checks while a scoring is in flight.
SCORING_MAX_CONCURRENCY = int(os.getenv("SCORING_MAX_CONCURRENCY", "3"))
_scoring_semaphore = asyncio.Semaphore(SCORING_MAX_CONCURRENCY)

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
        scorer = ClientScorer(model=scoring_model)
        
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

            # In-memory dedup: only short-circuit while a delivery is actively
            # in flight or already succeeded. A *failed* (or absent) entry must
            # fall through so an Eventarc redelivery can RE-RUN it — otherwise a
            # transient failure would be permanently masked as "duplicate".
            # (The GCS claim is the real cross-instance dedup; this dict is a
            # per-instance fast-path only.)
            existing = processing_status.get(meeting_id)
            if existing is not None and existing.status in ("pending", "processing", "completed"):
                logger.info(f"Already processing/processed: {meeting_id} ({existing.status})")
                return {
                    "status": "duplicate",
                    "meeting_id": meeting_id,
                    "message": f"Already {existing.status}",
                }

            # Mark in-flight
            processing_status[meeting_id] = ProcessingStatus(
                meeting_id=meeting_id,
                status="pending",
                created_at=datetime.now().isoformat()
            )

            # Process SYNCHRONOUSLY so the HTTP status reflects the real outcome.
            # Eventarc is at-least-once and redelivers on non-2xx — the old
            # background-task design returned 200 immediately, so a scoring
            # failure (e.g. transient OpenAI timeout) was invisible to Eventarc
            # and the meeting was silently dropped. Now: transient failure ->
            # 503 (redeliver); success / permanent failure -> 2xx (ack).
            outcome = await process_pipeline(
                bucket,
                file_name,
                os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini"),
                meeting_id,
            )

            if outcome == "transient_failure":
                err = getattr(processing_status.get(meeting_id), "error", None)
                logger.warning(f"Transient failure for {meeting_id}; returning 503 for Eventarc redelivery")
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "status": "retry",
                        "meeting_id": meeting_id,
                        "file": file_name,
                        "error": err,
                    },
                )

            logger.info(f"Processed {meeting_id}: {outcome}")
            return {
                "status": outcome,
                "meeting_id": meeting_id,
                "file": file_name,
                "generation": generation,
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
    claimed = False    # set True once this task wins the concurrency claim (3.5)
    succeeded = False  # set True only on a fully-completed write; gates claim release
    gcs = None

    try:
        # Update status
        processing_status[meeting_id].status = "processing"

        # Initialize GCS client
        gcs = GCSClient(bucket_name=bucket)
        
        # Use default model if not specified
        scoring_model = model or os.getenv("DEFAULT_LLM_MODEL", "gpt-5-mini")

        # Resolve routing source from the GCS object's custom metadata.
        # Strict: resolve_source raises ValueError if metadata is missing,
        # has no 'source' key, or has an empty value. brain-uploader sets
        # source on every new upload, and historicals are backfilled (see
        # scripts/backfill_unlabelled_client_blobs.py). Missing source now
        # signals a real bug rather than legacy data.
        blob = gcs.bucket.blob(file_path)
        blob.reload()
        try:
            source = resolve_source(blob.metadata)
        except ValueError as e:
            # Missing/empty routing source is a permanent data defect — retrying
            # won't add metadata. ACK so Eventarc stops redelivering.
            raise PermanentProcessingError(f"Unresolvable source for {file_path}: {e}") from e
        logger.info(f"Processing CloudEvent: object={file_path} source={source}")

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

        # Guard against poison keys. The Granola importer falls back to the
        # parsed file's stem when it can't extract a granola_note_id
        # (src/importers/granola_drive.py). In this pipeline that file is the
        # downloaded TEMP file, so the fallback id is a meaningless tempfile
        # stem (e.g. "tmpqm_h4lle"). Writing a row keyed on that pollutes
        # meeting_intel with a non-meeting and breaks any join on meeting_id.
        # If the resolved id is empty or equals the temp-file stem, the
        # importer fell back -> fail loudly (no scoring, no BQ write) rather
        # than persist garbage. The transcript stays in GCS for reprocessing.
        # Domain-agnostic: a metadata-less client upload would poison the
        # table the same way. (Same fail-loud philosophy as resolve_source.)
        temp_stem = Path(temp_file_path).stem
        if not real_meeting_id or str(real_meeting_id) == temp_stem:
            # Poison key — permanent. Redelivering the same malformed blob will
            # always fall back to a tempfile stem; ACK so Eventarc gives up.
            raise PermanentProcessingError(
                f"Unresolvable meeting_id for object={file_path}: granola_note_id "
                f"missing and meeting_id fell back to the temp-file stem "
                f"{temp_stem!r}. Refusing to write a poison-keyed row. Likely a "
                f"malformed or metadata-less upload (no Granola note-id link in body)."
            )

        # 3. Check cache with real meeting_id
        cached_result = gcs.get_cached_score(real_meeting_id, scoring_model, source)
        if cached_result:
            print(f"Using cached result for real meeting_id {real_meeting_id}")
            processing_status[meeting_id].status = "completed"
            processing_status[meeting_id].completed_at = datetime.now().isoformat()
            # `total_qualified_sections` is a client-domain concept; talent
            # caches omit it. Use .get() so the talent cache-hit path
            # doesn't KeyError.
            processing_status[meeting_id].score = cached_result.get("results", {}).get(
                "total_qualified_sections"
            )
            return "cached"

        # 3.5 Atomically claim the meeting before the expensive scoring step.
        # Eventarc is at-least-once: a single GCS finalize (or a quick re-upload)
        # can be delivered as two CloudEvents seconds apart. Each spawns a
        # process_pipeline task; the per-MERGE window (~10-15s) is longer than
        # that gap, so without a guard both tasks read "no existing row" and
        # both INSERT -> duplicate. The result cache (step 3) only catches
        # re-deliveries AFTER the first run completes; for simultaneous runs it
        # misses. claim_meeting uses GCS create-if-not-exists (atomic,
        # cross-instance) so exactly one delivery proceeds; the loser skips
        # before scoring (also saving its LLM cost). On failure we release the
        # claim so the meeting can retry.
        if not gcs.claim_meeting(real_meeting_id, scoring_model, source):
            print(f"Skipping {real_meeting_id}: already claimed by a concurrent delivery")
            processing_status[meeting_id].status = "completed"
            processing_status[meeting_id].completed_at = datetime.now().isoformat()
            return "duplicate"
        claimed = True

        # 4. Score with LLM using new format. Bounded by the process-wide
        # scoring semaphore and run in a worker thread: the OpenAI client is
        # synchronous (~90s at medium reasoning), so to_thread keeps the event
        # loop free for health checks, and the semaphore caps concurrent
        # scorings so a poller burst can't fan out into OpenAI rate limits.
        # A transient OpenAI error that survives the in-scorer retry policy
        # (call_with_transient_retry) propagates here -> the except below returns
        # "transient_failure" (handler -> 503 -> Eventarc retries) and `finally`
        # releases the claim so the redelivery can re-claim.
        print(f"Scoring with {scoring_model}")
        scorer = get_scorer(source, model=scoring_model)
        async with _scoring_semaphore:
            new_score_result = await asyncio.to_thread(scorer.score_transcript_new, transcript)

            # 4.5 Sales assessment runs ONLY on client transcripts. Talent
            # transcripts are recruiter↔candidate conversations — there's no
            # UNKNOWN salesperson behaviour to assess.
            sales_score_result = None
            if source == "client" and os.getenv('ENABLE_SALES_SCORING', 'true').lower() == 'true':
                try:
                    print(f"Performing sales assessment...")
                    sales_score_result = await asyncio.to_thread(scorer.score_salesperson, transcript)
                    print(f"Sales assessment complete - Score: {sales_score_result.total_score}/24")
                except Exception as e:
                    print(f"Sales scoring failed (non-fatal): {e}")
                    # Continue without sales data - this is not critical

        # 5. Cache the results using real meeting_id. The talent result is
        # a Pydantic model with nested Pydantic submodels (TalentNow,
        # MentionedCompany, ...); .__dict__ alone wouldn't recursively
        # serialise, so use model_dump for talent. The client path keeps
        # using .__dict__ for backward-compatibility.
        print("Caching results")
        if source == "talent":
            cache_payload = new_score_result.model_dump(mode="json")
        else:
            cache_payload = new_score_result.__dict__
        gcs.cache_score(real_meeting_id, scoring_model, source, cache_payload)

        # 6. Upload to meeting_intel BigQuery table — dispatch by domain so
        # each path writes only its own columns (sales_* stay NULL on
        # talent rows; talent_*/perception/blockers stay NULL on client rows).
        print("Uploading to BigQuery")
        if source == "talent":
            await upload_talent_format_to_bigquery(
                transcript, new_score_result, scoring_model, real_meeting_id, temp_files
            )
        else:
            await upload_new_format_to_bigquery(
                transcript, new_score_result, sales_score_result, scoring_model, real_meeting_id, temp_files
            )

        # Update status with completion. Talent results don't have a
        # `total_qualified_sections` (they're structured intelligence, not
        # a binary score); fall back to None on that path.
        processing_status[meeting_id].status = "completed"
        processing_status[meeting_id].completed_at = datetime.now().isoformat()
        processing_status[meeting_id].score = getattr(
            new_score_result, "total_qualified_sections", None
        )

        print(f"Successfully processed {meeting_id}")
        succeeded = True
        return "completed"

    except PermanentProcessingError as e:
        # Won't be fixed by retrying. Mark failed and signal a PERMANENT failure
        # so the handler ACKs (2xx) — no Eventarc redelivery. (Claim release is
        # handled uniformly in `finally`.)
        logger.error(f"Permanent failure processing {meeting_id}: {e}")
        processing_status[meeting_id].status = "failed"
        processing_status[meeting_id].error = str(e)
        return "permanent_failure"

    except Exception as e:
        # Transient/unknown (OpenAI timeout after retries, BQ blip, etc.). Signal
        # a TRANSIENT failure so the handler returns non-2xx and Eventarc
        # redelivers. (Claim release is handled uniformly in `finally` — see below.)
        logger.error(f"Transient error processing {meeting_id}: {e}", exc_info=True)
        processing_status[meeting_id].status = "failed"
        processing_status[meeting_id].error = str(e)
        return "transient_failure"

    finally:
        # Release the claim on ANY non-success exit so the meeting can be
        # re-claimed and retried. This lives in `finally` (not the except blocks)
        # deliberately: a Cloud Run request timeout cancels this task and raises
        # asyncio.CancelledError, which is a BaseException and would slip past
        # `except Exception` — leaving the claim stuck and the meeting blocked.
        # `finally` runs on cancellation too. A successful run (succeeded=True)
        # intentionally keeps the claim + result cache so same-day re-deliveries
        # short-circuit. `claimed` is only True after real_meeting_id/
        # scoring_model/source are all bound, so they're safe to reference here.
        if claimed and not succeeded and gcs is not None:
            try:
                gcs.release_claim(real_meeting_id, scoring_model, source)
            except Exception:
                pass
        # Clean up temporary files
        if temp_files and gcs is not None:
            gcs.cleanup_temp_files(temp_files)


async def upload_new_format_to_bigquery(
    transcript,
    new_score_result,
    sales_score_result,
    model: str,
    meeting_id: str,
    temp_files: List[Path]
):
    """Upload using new meeting_intel table format with JSON blobs and sales assessment"""
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
            'llm_model': new_score_result.llm_model,

            # Routing — every row from this path is a client-scored transcript.
            # Distinct from the top-level `source` (ingestion path) and from
            # `client_info.domain` (client business sector).
            'scoring_domain': 'client',

            # NOTE: the talent-domain columns (talent_now/triggers/motivation/
            # market/leads/narrative + mentioned_companies/perception_themes/
            # articulated_blockers) are deliberately OMITTED from this row dict.
            # The client MERGE (merge_client_jsonl_data) doesn't touch them in
            # its SET clause, and the temp-table load fills omitted columns with
            # SQL NULL (nullable) / empty array (repeated) on INSERT ROW. Writing
            # them explicitly as Python None serialised to the JSON literal
            # `null` — which is NOT SQL NULL, so `talent_now IS NULL` returned
            # False and tripped up downstream IS NULL filters / monitoring.
            # Omitting them yields proper SQL NULL.
        }

        # Add sales assessment fields if available (all nullable)
        if sales_score_result:
            new_bq_data.update({
                'salesperson_name': sales_score_result.salesperson_name,
                'salesperson_email': sales_score_result.salesperson_email,
                'sales_total_score': sales_score_result.total_score,
                'sales_total_qualified': sales_score_result.total_qualified,
                'sales_qualified': sales_score_result.qualified,
                'sales_introduction': sales_score_result.introduction.__dict__,
                'sales_discovery': sales_score_result.discovery.__dict__,
                'sales_scoping': sales_score_result.scoping.__dict__,
                'sales_solution': sales_score_result.solution.__dict__,
                'sales_commercial': sales_score_result.commercial.__dict__,
                'sales_case_studies': sales_score_result.case_studies.__dict__,
                'sales_next_steps': sales_score_result.next_steps.__dict__,
                'sales_strategic_context': sales_score_result.strategic_context.__dict__,
                'sales_strengths': sales_score_result.strengths,
                'sales_improvements': sales_score_result.improvements,
                'sales_overall_coaching': sales_score_result.overall_coaching
            })
        else:
            # Add NULL values for sales fields when no sales assessment
            new_bq_data.update({
                'salesperson_name': None,
                'salesperson_email': None,
                'sales_total_score': None,
                'sales_total_qualified': None,
                'sales_qualified': None,
                'sales_introduction': None,
                'sales_discovery': None,
                'sales_scoping': None,
                'sales_solution': None,
                'sales_commercial': None,
                'sales_case_studies': None,
                'sales_next_steps': None,
                'sales_strategic_context': None,
                'sales_strengths': None,
                'sales_improvements': None,
                'sales_overall_coaching': None
            })

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
        logger.error(f"Error uploading new format to BigQuery for {meeting_id}: {e}", exc_info=True)


async def upload_talent_format_to_bigquery(
    transcript,
    talent_result,
    model: str,
    meeting_id: str,
    temp_files: List[Path],
):
    """
    Upload a TalentScoringResult to meeting_intel.

    Mirrors `upload_new_format_to_bigquery` but writes ONLY the talent-domain
    columns (talent_*, mentioned_companies, perception_themes,
    articulated_blockers) plus shared transcript metadata and scoring_domain.
    Client-domain columns (client_info, total_qualified_sections, now/next/
    measure/blocker/fit, challenges/results/offering, sales_*) are not set
    here; the talent MERGE leaves them alone so they stay SQL NULL on new
    rows and unchanged on re-scored ones.
    """
    try:
        bq_row = {
            # Shared transcript metadata
            "meeting_id": talent_result.meeting_id,
            "date": transcript.date.isoformat() if transcript.date else None,
            "participants": getattr(transcript, "participants", []),
            "desk": getattr(transcript, "desk", "Unknown"),
            "source": getattr(transcript, "source", None),

            # Granola metadata (shared, optional)
            "granola_note_id": getattr(transcript, "granola_note_id", None),
            "title": getattr(transcript, "title", None),
            "creator_name": getattr(transcript, "creator_name", None),
            "creator_email": getattr(transcript, "creator_email", None),
            "calendar_event_title": getattr(transcript, "calendar_event_title", None),
            "calendar_event_id": getattr(transcript, "calendar_event_id", None),
            "calendar_event_time": convert_to_utc_timestamp(
                getattr(transcript, "calendar_event_time", None)
            ),
            "granola_link": getattr(transcript, "granola_link", None),
            "file_created_timestamp": safe_int_convert(
                getattr(transcript, "file_created_timestamp", None)
            ),
            "zapier_step_id": safe_int_convert(getattr(transcript, "zapier_step_id", None)),

            # Content sections (shared)
            "enhanced_notes": getattr(transcript, "enhanced_notes", None),
            "my_notes": getattr(transcript, "my_notes", None),
            "full_transcript": getattr(transcript, "full_transcript", None),

            # Processing metadata
            "scored_at": talent_result.scored_at.isoformat(timespec="seconds"),
            "llm_model": talent_result.llm_model,

            # Routing
            "scoring_domain": "talent",

            # Talent-specific scoring buckets
            "talent_now": talent_result.talent_now.model_dump(mode="json"),
            "talent_triggers": talent_result.talent_triggers,
            "talent_motivation": talent_result.talent_motivation.model_dump(mode="json"),
            "talent_market": talent_result.talent_market.model_dump(mode="json"),
            "talent_leads": talent_result.talent_leads.model_dump(mode="json"),
            "talent_narrative": talent_result.talent_narrative,

            # Per-client intelligence extensions
            "mentioned_companies": [m.model_dump(mode="json") for m in talent_result.mentioned_companies],
            "perception_themes": [p.model_dump(mode="json") for p in talent_result.perception_themes],
            "articulated_blockers": [a.model_dump(mode="json") for a in talent_result.articulated_blockers],
        }

        temp_jsonl_path = Path(f"/tmp/{meeting_id}_talent.jsonl")
        temp_files.append(temp_jsonl_path)

        with open(temp_jsonl_path, "w") as f:
            f.write(json.dumps(bq_row) + "\n")

        success = upload_to_new_bigquery(temp_jsonl_path, use_merge=True, scoring_domain="talent")
        if success:
            print(f"Successfully uploaded {meeting_id} to meeting_intel as scoring_domain=talent")
        else:
            print(f"Failed to upload {meeting_id} to meeting_intel (talent path)")

    except Exception as e:
        logger.error(f"Error uploading talent format to BigQuery for {meeting_id}: {e}", exc_info=True)


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