"""BigQuery loader for UNKNOWN Brain transcript data."""

import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.cloud import bigquery
from google.cloud.exceptions import NotFound
from rich.console import Console
from rich.table import Table

console = Console()


class BigQueryLoader:
    """Handles loading transcript data to BigQuery"""
    
    def __init__(self, credentials_path: str = "gcp_service_account_creds.json"):
        """Initialize BigQuery client with service account credentials or default auth"""
        self.credentials_path = Path(credentials_path)
        
        # Get configuration from environment
        self.project_id = os.getenv('BQ_PROJECT_ID', 'angular-stacker-471711-k4')
        self.dataset_name = os.getenv('BQ_DATASET', 'unknown_brain')
        self.table_name = os.getenv('BQ_TABLE', 'meeting_transcripts')
        
        # Initialize BigQuery client - use default credentials on Cloud Run
        if self.credentials_path.exists():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(self.credentials_path.absolute())
            self.client = bigquery.Client(project=self.project_id)
        else:
            # Use default service account on Cloud Run
            self.client = bigquery.Client(project=self.project_id)
        
        console.print(f"[green]Initialized BigQuery client for project: {self.project_id}[/green]")
    
    def create_dataset_if_not_exists(self) -> None:
        """Create dataset if it doesn't exist"""
        dataset_id = f"{self.project_id}.{self.dataset_name}"
        
        try:
            self.client.get_dataset(dataset_id)
            console.print(f"[blue]Dataset {self.dataset_name} already exists[/blue]")
        except NotFound:
            dataset = bigquery.Dataset(dataset_id)
            dataset.location = "US"
            dataset.description = "UNKNOWN Brain meeting transcript analysis data"
            
            dataset = self.client.create_dataset(dataset, timeout=30)
            console.print(f"[green]Created dataset {self.dataset_name}[/green]")
    
    def merge_jsonl_data(self, jsonl_path: Path) -> int:
        """
        Merge JSONL data to BigQuery table using UPSERT (prevents duplicates)
        
        Args:
            jsonl_path: Path to JSONL file
        
        Returns:
            Number of rows processed
        """
        if not jsonl_path.exists():
            console.print(f"[red]JSONL file not found: {jsonl_path}[/red]")
            return 0
        
        # Ensure dataset exists
        self.create_dataset_if_not_exists()
        
        # Load data into temporary table first
        temp_table_id = f"{self.project_id}.{self.dataset_name}.temp_upload_{int(__import__('time').time())}"
        target_table_id = f"{self.project_id}.{self.dataset_name}.{self.table_name}"
        
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
            write_disposition="WRITE_TRUNCATE"  # Always overwrite temp table
        )
        
        console.print(f"[blue]Loading data to temporary table: {temp_table_id}[/blue]")
        
        # Load to temp table
        with open(jsonl_path, "rb") as source_file:
            job = self.client.load_table_from_file(
                source_file, 
                temp_table_id, 
                job_config=job_config
            )
        
        console.print("[yellow]Uploading to temporary table...[/yellow]")
        job.result()  # Wait for completion
        
        if job.errors:
            console.print(f"[red]Temporary table load failed: {job.errors}[/red]")
            return 0
        
        # Now perform MERGE from temp table to target table
        merge_query = f"""
        MERGE `{target_table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.meeting_id = source.meeting_id
        WHEN MATCHED THEN
            UPDATE SET
                date = source.date,
                company = source.company,
                total_score = source.total_score,
                qualified = source.qualified,
                now_score = source.now_score,
                now_evidence = source.now_evidence,
                next_score = source.next_score,
                next_evidence = source.next_evidence,
                measure_score = source.measure_score,
                measure_evidence = source.measure_evidence,
                blocker_score = source.blocker_score,
                blocker_evidence = source.blocker_evidence,
                fit_score = source.fit_score,
                fit_labels = source.fit_labels,
                fit_evidence = source.fit_evidence,
                scored_at = source.scored_at,
                llm_model = source.llm_model
        WHEN NOT MATCHED THEN
            INSERT ROW
        """
        
        console.print(f"[blue]Merging data from temp table to {target_table_id}[/blue]")
        merge_job = self.client.query(merge_query)
        merge_result = merge_job.result()
        
        # Get stats from the merge operation
        stats = merge_job._properties.get('statistics', {}).get('query', {})
        dml_stats = stats.get('dmlStats', {})
        
        inserted_rows = int(dml_stats.get('insertedRowCount', 0))
        updated_rows = int(dml_stats.get('updatedRowCount', 0))
        
        console.print(f"[green]MERGE completed: {inserted_rows} inserted, {updated_rows} updated[/green]")
        
        # Clean up temp table
        self.client.delete_table(temp_table_id)
        console.print(f"[blue]Cleaned up temporary table[/blue]")
        
        # Show final table status
        final_table = self.client.get_table(target_table_id)
        console.print(f"[blue]Total table rows: {final_table.num_rows}[/blue]")
        
        return inserted_rows + updated_rows

    def load_jsonl_data(self, jsonl_path: Path, write_disposition: str = "WRITE_APPEND") -> int:
        """
        Load JSONL data to BigQuery table
        
        Args:
            jsonl_path: Path to JSONL file
            write_disposition: How to handle existing data (WRITE_APPEND, WRITE_TRUNCATE, WRITE_EMPTY)
        
        Returns:
            Number of rows loaded
        """
        if not jsonl_path.exists():
            console.print(f"[red]JSONL file not found: {jsonl_path}[/red]")
            return 0
        
        # Ensure dataset exists
        self.create_dataset_if_not_exists()
        
        # Configure the load job
        table_id = f"{self.project_id}.{self.dataset_name}.{self.table_name}"
        
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,  # Auto-detect schema from JSON
            write_disposition=write_disposition,
        )
        
        console.print(f"[blue]Loading data from {jsonl_path} to {table_id}[/blue]")
        
        # Load data
        with open(jsonl_path, "rb") as source_file:
            job = self.client.load_table_from_file(
                source_file, 
                table_id, 
                job_config=job_config
            )
        
        # Wait for job to complete
        console.print("[yellow]Uploading data to BigQuery...[/yellow]")
        job.result()  # Waits for the job to complete
        
        if job.errors:
            console.print(f"[red]Job completed with errors: {job.errors}[/red]")
            return 0
        
        # Get the destination table
        table = self.client.get_table(table_id)
        
        console.print(f"[green]Successfully loaded {job.output_rows} rows to {table_id}[/green]")
        console.print(f"[blue]Total table rows: {table.num_rows}[/blue]")
        
        return job.output_rows
    
    def deduplicate_table(self) -> int:
        """
        Remove duplicate rows from table, keeping the most recent scored_at timestamp
        
        Returns:
            Number of duplicate rows removed
        """
        table_id = f"{self.project_id}.{self.dataset_name}.{self.table_name}"
        
        # First, count duplicates
        count_query = f"""
        SELECT 
            COUNT(*) - COUNT(DISTINCT meeting_id) as duplicate_count
        FROM `{table_id}`
        """
        
        count_result = self.client.query(count_query).result()
        duplicate_count = list(count_result)[0][0]
        
        if duplicate_count == 0:
            console.print("[green]No duplicates found[/green]")
            return 0
        
        console.print(f"[yellow]Found {duplicate_count} duplicate rows to remove[/yellow]")
        
        # Create temp table with deduplicated data
        temp_table_id = f"{self.project_id}.{self.dataset_name}.temp_dedup_{int(__import__('time').time())}"
        
        dedup_query = f"""
        CREATE TABLE `{temp_table_id}` AS
        SELECT * EXCEPT(row_num)
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY meeting_id 
                    ORDER BY scored_at DESC
                ) as row_num
            FROM `{table_id}`
        )
        WHERE row_num = 1
        """
        
        console.print(f"[blue]Creating deduplicated temp table: {temp_table_id}[/blue]")
        dedup_job = self.client.query(dedup_query)
        dedup_job.result()
        
        # Replace original table with deduplicated data
        console.print(f"[yellow]Replacing {table_id} with deduplicated data[/yellow]")
        
        # Copy data back to original table
        replace_query = f"""
        CREATE OR REPLACE TABLE `{table_id}` AS
        SELECT * FROM `{temp_table_id}`
        """
        
        replace_job = self.client.query(replace_query)
        replace_job.result()
        
        # Clean up temp table
        self.client.delete_table(temp_table_id)
        
        # Verify final state
        final_table = self.client.get_table(table_id)
        console.print(f"[green]Deduplication complete. Removed {duplicate_count} duplicates[/green]")
        console.print(f"[blue]Final table rows: {final_table.num_rows}[/blue]")
        
        return duplicate_count
    
    def get_table_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the table"""
        table_id = f"{self.project_id}.{self.dataset_name}.{self.table_name}"
        
        try:
            table = self.client.get_table(table_id)
            
            return {
                "table_id": table_id,
                "created": table.created.isoformat() if table.created else None,
                "modified": table.modified.isoformat() if table.modified else None,
                "num_rows": table.num_rows,
                "num_bytes": table.num_bytes,
                "schema_fields": len(table.schema),
                "description": table.description
            }
        except NotFound:
            return None
    
    def query_recent_uploads(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Query recent uploads to verify data"""
        table_id = f"{self.project_id}.{self.dataset_name}.{self.table_name}"
        
        query = f"""
        SELECT 
            meeting_id,
            company,
            date,
            total_score,
            qualified,
            scored_at,
            llm_model,
            source
        FROM `{table_id}`
        ORDER BY scored_at DESC
        LIMIT {limit}
        """
        
        try:
            query_job = self.client.query(query)
            results = query_job.result()
            
            return [dict(row) for row in results]
        except Exception as e:
            console.print(f"[red]Query failed: {e}[/red]")
            return []
    
    def display_table_status(self) -> None:
        """Display current table status"""
        info = self.get_table_info()
        
        if not info:
            console.print("[yellow]Table does not exist yet[/yellow]")
            return
        
        table = Table(title="BigQuery Table Status")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="magenta")
        
        table.add_row("Table ID", info["table_id"])
        table.add_row("Total Rows", str(info["num_rows"]))
        table.add_row("Size (bytes)", f"{info['num_bytes']:,}")
        table.add_row("Schema Fields", str(info["schema_fields"]))
        table.add_row("Created", info["created"] or "Unknown")
        table.add_row("Last Modified", info["modified"] or "Unknown")
        
        console.print(table)
        
        # Show recent uploads
        recent = self.query_recent_uploads()
        if recent:
            console.print("\n[bold]Recent Uploads:[/bold]")
            recent_table = Table()
            recent_table.add_column("Meeting ID", style="cyan", max_width=40)
            recent_table.add_column("Company", style="green")
            recent_table.add_column("Score", style="magenta")
            recent_table.add_column("Qualified", style="yellow")
            recent_table.add_column("Uploaded", style="blue")
            
            for row in recent:
                recent_table.add_row(
                    row["meeting_id"][:37] + "..." if len(row["meeting_id"]) > 40 else row["meeting_id"],
                    row["company"] or "Unknown",
                    f"{row['total_score']}/5",
                    "✓" if row["qualified"] else "✗",
                    row["scored_at"].strftime("%Y-%m-%d %H:%M") if row["scored_at"] else "Unknown"
                )
            
            console.print(recent_table)


def upload_to_bigquery(jsonl_path: Path, write_disposition: str = "WRITE_APPEND") -> bool:
    """
    Convenience function to upload JSONL data to BigQuery
    
    Args:
        jsonl_path: Path to JSONL file
        write_disposition: How to handle existing data
    
    Returns:
        True if successful, False otherwise
    """
    try:
        loader = BigQueryLoader()
        rows_loaded = loader.load_jsonl_data(jsonl_path, write_disposition)
        
        if rows_loaded > 0:
            loader.display_table_status()
            return True
        return False
        
    except Exception as e:
        console.print(f"[red]Upload failed: {e}[/red]")
        return False


if __name__ == "__main__":
    # Test with existing export file
    jsonl_path = Path("out/bq_export.jsonl")
    if jsonl_path.exists():
        upload_to_bigquery(jsonl_path)
    else:
        console.print(f"[yellow]No JSONL file found at {jsonl_path}[/yellow]")
        console.print("Run 'python -m src.cli score' first to generate the export file.")