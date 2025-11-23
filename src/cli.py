import typer
import json
import os
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.progress import track

from .importers.plaintext import PlaintextImporter
from .importers.granola_drive import GranolaDriveImporter
from .llm_scorer import LLMScorer
from .scoring import OutputGenerator
from .bq_loader import BigQueryLoader

app = typer.Typer(help="UNKNOWN Brain - LLM-powered Transcript Scoring")
console = Console()

def _is_granola_format(file_path: Path) -> bool:
    """Check if a .txt file is in Granola format by looking for JSON header"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read(200)  # Read first 200 chars
            return '```json' in content and 'granola_note_id' in content
    except Exception:
        return False

@app.command()
def ingest(
    input_dir: Path = typer.Option(Path("data/transcripts"), "--in", help="Input directory containing transcript files"),
    output_dir: Path = typer.Option(Path("data/json"), "--out", help="Output directory for JSON files"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output")
):
    """Ingest transcript files into canonical JSON format."""
    
    if not input_dir.exists():
        console.print(f"[red]Error: Input directory {input_dir} does not exist[/red]")
        raise typer.Exit(1)
    
    # Look for transcript files (.md and .txt)
    md_files = list(input_dir.glob("*.md"))
    txt_files = list(input_dir.glob("*.txt"))
    
    if not md_files and not txt_files:
        console.print(f"[red]Error: No .md or .txt files found in {input_dir}[/red]")
        raise typer.Exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize importers
    plaintext_importer = PlaintextImporter()
    granola_importer = GranolaDriveImporter()
    
    files_processed = 0
    files_failed = 0
    
    # Combine all files to process
    all_files = md_files + txt_files
    
    # Process transcript files
    for transcript_file in track(all_files, description="Processing transcript files..."):
        try:
            # Choose importer based on file extension
            if transcript_file.suffix == '.md':
                transcript = plaintext_importer.parse_file(transcript_file)
            elif transcript_file.suffix == '.txt':
                # Check if it's a Granola file format
                if _is_granola_format(transcript_file):
                    transcript = granola_importer.parse_file(transcript_file)
                else:
                    transcript = plaintext_importer.parse_file(transcript_file)
            else:
                continue
            
            output_path = output_dir / f"{transcript.meeting_id}.json"
            
            with open(output_path, 'w') as f:
                json.dump(transcript.model_dump(mode='json'), f, indent=2, default=str)
            
            files_processed += 1
            
            if verbose:
                console.print(f"[green]✓[/green] Processed {transcript_file.name} -> {output_path.name}")
                
        except Exception as e:
            files_failed += 1
            console.print(f"[red]✗[/red] Failed to process {transcript_file.name}: {e}")
    
    # Summary
    console.print(f"\n[bold green]Ingest completed![/bold green]")
    console.print(f"Files processed: {files_processed}")
    console.print(f"Files failed: {files_failed}")
    console.print(f"Output directory: {output_dir}")


@app.command()  
def score(
    input_dir: Path = typer.Option(Path("data/json"), "--in", help="Input directory containing JSON files"),
    output_dir: Path = typer.Option(Path("out"), "--out", help="Output directory for score results"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output"),
    llm_model: str = typer.Option(os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini"), "--model", help="LLM model to use"),
    bq_export: bool = typer.Option(False, "--bq-export", help="Generate BigQuery JSONL export")
):
    """Score JSON transcripts using LLM and generate outputs."""
    
    if not input_dir.exists():
        console.print(f"[red]Error: Input directory {input_dir} does not exist[/red]")
        raise typer.Exit(1)
    
    json_files = list(input_dir.glob("*.json"))
    if not json_files:
        console.print(f"[red]Error: No JSON files found in {input_dir}[/red]")
        raise typer.Exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize LLM scorer
    try:
        llm_scorer = LLMScorer(model=llm_model)
    except ValueError as e:
        console.print(f"[red]Error initializing LLM scorer: {e}[/red]")
        console.print("[yellow]Make sure OPENAI_API_KEY is set in .env file[/yellow]")
        raise typer.Exit(1)
    
    generator = OutputGenerator()
    
    # Load and score transcripts with LLM
    console.print(f"Loading and scoring {len(json_files)} transcripts with LLM ({llm_model})...")
    results = []
    transcripts = {}  # Store transcripts for BigQuery export
    
    for json_file in track(json_files, description="Scoring with LLM..."):
        try:
            with open(json_file) as f:
                data = json.load(f)
            from .schemas import Transcript
            transcript = Transcript(**data)
            transcripts[transcript.meeting_id] = transcript  # Store for BQ export
            result = llm_scorer.score_transcript(transcript)
            results.append(result)
        except Exception as e:
            console.print(f"[red]Failed to score {json_file.name}: {e}[/red]")
    
    if not results:
        console.print("[red]No transcripts were successfully scored[/red]")
        raise typer.Exit(1)
    
    # Generate outputs
    json_output = output_dir / "scores.json"
    csv_output = output_dir / "scores.csv" 
    markdown_output = output_dir / "leaderboard.md"
    
    console.print("Generating output files...")
    generator.generate_json_output(results, json_output)
    generator.generate_csv_output(results, csv_output)
    generator.generate_leaderboard(results, markdown_output)
    
    # Generate BigQuery export if requested
    if bq_export:
        bq_output = output_dir / "bq_export.jsonl"
        console.print("Generating BigQuery JSONL export...")
        generator.generate_bq_output(results, transcripts, bq_output, llm_model)
    
    # Display summary table
    qualified_count = sum(1 for r in results if r.qualified)
    qualified_pct = (qualified_count / len(results)) * 100 if results else 0
    avg_score = sum(r.total_qualified_sections for r in results) / len(results) if results else 0
    
    table = Table(title=f"UNKNOWN Brain Scoring Results ({llm_model})")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("Total Transcripts", str(len(results)))
    table.add_row("Qualified (≥3/5)", f"{qualified_count} ({qualified_pct:.1f}%)")
    table.add_row("Average Score", f"{avg_score:.1f}/5")
    
    console.print(table)
    
    if verbose:
        console.print(f"\n[bold]Top Scoring Meetings:[/bold]")
        sorted_results = sorted(results, key=lambda x: x.total_qualified_sections, reverse=True)
        for i, result in enumerate(sorted_results[:5], 1):
            console.print(f"{i}. {result.meeting_id} ({result.company or 'Unknown'}) - {result.total_qualified_sections}/5")
    
    console.print(f"\n[bold green]Scoring completed![/bold green]")
    console.print(f"JSON output: {json_output}")
    console.print(f"CSV output: {csv_output}")
    console.print(f"Leaderboard: {markdown_output}")
    if bq_export:
        console.print(f"BigQuery export: {bq_output}")


@app.command("upload-bq")
def upload_bq(
    jsonl_file: Path = typer.Option(Path("out/bq_export.jsonl"), "--file", help="JSONL file to upload"),
    write_mode: str = typer.Option("append", "--mode", help="Write mode: append, replace, or empty"),
    show_status: bool = typer.Option(True, "--status/--no-status", help="Show table status after upload")
):
    """Upload scored transcript data to BigQuery."""
    
    if not jsonl_file.exists():
        console.print(f"[red]Error: JSONL file not found: {jsonl_file}[/red]")
        console.print("[yellow]Run 'python -m src.cli score --bq-export' first to generate the file.[/yellow]")
        raise typer.Exit(1)
    
    # Map write mode to BigQuery constants
    write_disposition_map = {
        "append": "WRITE_APPEND",
        "replace": "WRITE_TRUNCATE", 
        "empty": "WRITE_EMPTY"
    }
    
    if write_mode not in write_disposition_map:
        console.print(f"[red]Invalid write mode: {write_mode}. Must be one of: {', '.join(write_disposition_map.keys())}[/red]")
        raise typer.Exit(1)
    
    write_disposition = write_disposition_map[write_mode]
    
    try:
        loader = BigQueryLoader()
        
        if show_status:
            console.print("\n[bold]Current Table Status:[/bold]")
            loader.display_table_status()
            console.print()
        
        # Upload the data
        rows_loaded = loader.load_jsonl_data(jsonl_file, write_disposition)
        
        if rows_loaded > 0:
            console.print(f"\n[bold green]Upload completed successfully![/bold green]")
            
            if show_status:
                console.print("\n[bold]Updated Table Status:[/bold]")
                loader.display_table_status()
        else:
            console.print("[red]Upload failed - no rows were loaded[/red]")
            raise typer.Exit(1)
            
    except Exception as e:
        console.print(f"[red]Upload failed: {e}[/red]")
        raise typer.Exit(1)

@app.command("upload-bq-merge")
def upload_bq_merge(
    jsonl_file: Path = typer.Option(Path("out/bq_export.jsonl"), "--file", help="JSONL file to upload"),
    show_status: bool = typer.Option(True, "--status/--no-status", help="Show table status after upload")
):
    """Upload scored transcript data to BigQuery using MERGE (prevents duplicates)."""
    
    if not jsonl_file.exists():
        console.print(f"[red]Error: JSONL file not found: {jsonl_file}[/red]")
        console.print("[yellow]Run 'python -m src.cli score --bq-export' first to generate the file.[/yellow]")
        raise typer.Exit(1)
    
    try:
        loader = BigQueryLoader()
        
        if show_status:
            console.print("\n[bold]Current Table Status:[/bold]")
            loader.display_table_status()
        
        rows_processed = loader.merge_jsonl_data(jsonl_file)
        
        if rows_processed > 0:
            console.print(f"\n[green]Successfully processed {rows_processed} rows[/green]")
        else:
            console.print("\n[yellow]No data processed[/yellow]")
        
        if show_status:
            console.print("\n[bold]Updated Table Status:[/bold]")
            loader.display_table_status()
    
    except Exception as e:
        console.print(f"[red]Upload failed: {e}[/red]")
        raise typer.Exit(1)
    
    console.print("\n[bold]Upload completed![/bold]")

@app.command("dedupe-bq")
def dedupe_bq():
    """Remove duplicate rows from BigQuery table."""
    
    try:
        loader = BigQueryLoader()
        
        console.print("\n[bold]Current Table Status:[/bold]")
        loader.display_table_status()
        
        # Ask for confirmation
        duplicate_count = loader.deduplicate_table()
        
        if duplicate_count > 0:
            console.print(f"\n[green]Successfully removed {duplicate_count} duplicate rows[/green]")
            
            console.print("\n[bold]Updated Table Status:[/bold]")
            loader.display_table_status()
        
    except Exception as e:
        console.print(f"[red]Deduplication failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("compare-models")
def compare_models(
    models: str = typer.Option("gpt-5-mini,gpt-4o-mini", "--models", help="Comma-separated list of models to compare"),
    input_dir: Path = typer.Option(Path("data/json"), "--in", help="Input directory containing JSON files"),
    limit: int = typer.Option(3, "--limit", help="Number of transcripts to test"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output")
):
    """Compare different LLM models on the same transcripts."""
    
    if not input_dir.exists():
        console.print(f"[red]Error: Input directory {input_dir} does not exist[/red]")
        raise typer.Exit(1)
    
    # Parse models list
    model_list = [model.strip() for model in models.split(",")]
    if len(model_list) < 2:
        console.print(f"[red]Error: Please provide at least 2 models to compare[/red]")
        raise typer.Exit(1)
    
    # Find JSON files
    json_files = list(input_dir.glob("*.json"))[:limit]
    if not json_files:
        console.print(f"[red]Error: No JSON files found in {input_dir}[/red]")
        raise typer.Exit(1)
    
    console.print(f"[blue]Comparing {len(model_list)} models on {len(json_files)} transcripts...[/blue]")
    
    # Initialize scorers for each model
    scorers = {}
    model_info = {}
    
    for model in model_list:
        try:
            scorer = LLMScorer(model=model)
            scorers[model] = scorer
            model_info[model] = scorer.get_model_info()
            console.print(f"✓ {model}: {model_info[model]['config'].get('description', 'Unknown')}")
        except Exception as e:
            console.print(f"✗ {model}: Failed to initialize - {e}")
            del model_list[model_list.index(model)]  # Remove failed model
    
    if not scorers:
        console.print(f"[red]Error: No models could be initialized[/red]")
        raise typer.Exit(1)
    
    # Results storage
    comparison_results = {}
    
    # Process each transcript
    for json_file in track(json_files, description="Comparing models..."):
        try:
            with open(json_file) as f:
                data = json.load(f)
            from .schemas import Transcript
            transcript = Transcript(**data)
            
            meeting_id = transcript.meeting_id
            comparison_results[meeting_id] = {
                "transcript": transcript,
                "results": {}
            }
            
            # Score with each model
            for model, scorer in scorers.items():
                try:
                    result = scorer.score_transcript(transcript)
                    comparison_results[meeting_id]["results"][model] = result
                    
                    if verbose:
                        console.print(f"  {model}: {result.total_qualified_sections}/5 ({'✓' if result.qualified else '✗'})")
                        
                except Exception as e:
                    console.print(f"[yellow]Warning: {model} failed on {meeting_id}: {e}[/yellow]")
                    comparison_results[meeting_id]["results"][model] = None
                    
        except Exception as e:
            console.print(f"[red]Failed to process {json_file.name}: {e}[/red]")
    
    # Display comparison results
    console.print(f"\n[bold]Model Comparison Results[/bold]")
    
    # Summary table
    summary_table = Table(title="Model Performance Summary")
    summary_table.add_column("Model", style="cyan")
    summary_table.add_column("Avg Score", style="magenta")
    summary_table.add_column("Qualified", style="green")
    summary_table.add_column("Success Rate", style="yellow")
    summary_table.add_column("Config", style="blue")
    
    for model in model_list:
        results = []
        successes = 0
        total_attempts = 0
        
        for meeting_id, data in comparison_results.items():
            total_attempts += 1
            result = data["results"].get(model)
            if result:
                results.append(result)
                successes += 1
        
        if results:
            avg_score = sum(r.total_qualified_sections for r in results) / len(results)
            qualified_count = sum(1 for r in results if r.qualified)
            qualified_pct = (qualified_count / len(results)) * 100
        else:
            avg_score = 0
            qualified_pct = 0
        
        success_rate = (successes / total_attempts) * 100 if total_attempts > 0 else 0
        config = model_info.get(model, {}).get('config', {})
        config_str = f"{config.get('token_param', 'unknown')}"
        if not config.get('supports_temperature', True):
            config_str += ", no temp"
        
        summary_table.add_row(
            model,
            f"{avg_score:.1f}/5",
            f"{qualified_count}/{len(results)} ({qualified_pct:.0f}%)" if results else "0/0",
            f"{success_rate:.0f}%",
            config_str
        )
    
    console.print(summary_table)
    
    # Detailed comparison for verbose mode
    if verbose and comparison_results:
        console.print(f"\n[bold]Detailed Comparison[/bold]")
        
        for meeting_id, data in comparison_results.items():
            console.print(f"\n[underline]{meeting_id}[/underline] ({data['transcript'].company or 'Unknown'})")
            
            detail_table = Table()
            detail_table.add_column("Model", style="cyan")
            detail_table.add_column("Score", style="magenta")
            detail_table.add_column("NOW", style="green")
            detail_table.add_column("NEXT", style="blue")
            detail_table.add_column("MEASURE", style="yellow")
            detail_table.add_column("BLOCKER", style="red")
            detail_table.add_column("FIT", style="purple")
            
            for model in model_list:
                result = data["results"].get(model)
                if result:
                    detail_table.add_row(
                        model,
                        f"{result.total_qualified_sections}/5",
                        str(getattr(result, 'now_score', '?')),
                        str(getattr(result, 'next_score', '?')),
                        str(getattr(result, 'measure_score', '?')),
                        str(getattr(result, 'blocker_score', '?')),
                        str(getattr(result, 'fit_score', '?'))
                    )
                else:
                    detail_table.add_row(model, "FAILED", "-", "-", "-", "-", "-")
            
            console.print(detail_table)
    
    console.print(f"\n[bold green]Model comparison completed![/bold green]")


@app.command()
def fix_client_names(
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Preview changes without applying them"),
    use_file: bool = typer.Option(False, "--use-file", help="Use client_mappings.json instead of BigQuery table")
):
    """Fix corrupted and duplicate client names in BigQuery using mappings from BigQuery table."""

    loader = BigQueryLoader()

    # Load mappings from BigQuery or file
    if use_file:
        mappings_file = Path("client_mappings.json")
        if not mappings_file.exists():
            console.print(f"[red]Error: Mappings file {mappings_file} does not exist[/red]")
            raise typer.Exit(1)

        with open(mappings_file) as f:
            config = json.load(f)
            mappings = config.get("mappings", {})
        console.print(f"[blue]Loaded {len(mappings)} client name mappings from file[/blue]")
    else:
        mappings = loader.load_client_mappings()

    if not mappings:
        console.print("[yellow]No mappings found. Add mappings using 'add-client-mapping' command[/yellow]")
        return

    table_id = f"{loader.project_id}.{loader.dataset_name}.{loader.new_table_name}"

    # Find records that need fixing
    # Escape single quotes for SQL
    escaped_variants = [k.replace("'", "\\'") for k in mappings.keys()]
    variant_list = "', '".join(escaped_variants)
    query = f"""
    SELECT
        meeting_id,
        JSON_VALUE(client_info, '$.client') as current_client
    FROM `{table_id}`
    WHERE JSON_VALUE(client_info, '$.client') IN ('{variant_list}')
    """

    console.print(f"[yellow]Searching for records to fix...[/yellow]")
    results = loader.client.query(query).result()
    records = list(results)

    if not records:
        console.print("[green]No records need fixing![/green]")
        return

    # Show what will be changed
    change_table = Table(title=f"Client Name Changes {'(DRY RUN)' if dry_run else ''}")
    change_table.add_column("Meeting ID", style="cyan", max_width=40)
    change_table.add_column("Current Name", style="yellow")
    change_table.add_column("→", style="white")
    change_table.add_column("New Name", style="green")

    for record in records:
        current = record.current_client
        new_name = mappings.get(current, current)
        change_table.add_row(
            record.meeting_id[:37] + "..." if len(record.meeting_id) > 40 else record.meeting_id,
            current,
            "→",
            new_name
        )

    console.print(change_table)
    console.print(f"\n[bold]Total records to update: {len(records)}[/bold]")

    if dry_run:
        console.print(f"\n[yellow]DRY RUN - No changes made[/yellow]")
        console.print(f"[blue]Run with --execute to apply changes[/blue]")
        return

    # Apply updates
    console.print(f"\n[yellow]Applying updates to BigQuery...[/yellow]")

    for record in track(records, description="Updating records..."):
        current = record.current_client
        new_name = mappings.get(current, current)
        meeting_id = record.meeting_id

        # Update the client name in client_info JSON
        update_query = f"""
        UPDATE `{table_id}`
        SET client_info = JSON_SET(client_info, '$.client', '{new_name}')
        WHERE meeting_id = '{meeting_id}'
        """

        try:
            loader.client.query(update_query).result()
        except Exception as e:
            console.print(f"[red]Failed to update {meeting_id}: {e}[/red]")

    console.print(f"\n[bold green]Successfully updated {len(records)} records![/bold green]")


@app.command()
def list_clients(
    limit: int = typer.Option(100, "--limit", "-n", help="Maximum number of clients to show"),
    show_counts: bool = typer.Option(False, "--counts", "-c", help="Show meeting count per client")
):
    """List all unique client names from BigQuery."""

    loader = BigQueryLoader()
    table_id = f"{loader.project_id}.{loader.dataset_name}.{loader.new_table_name}"

    if show_counts:
        query = f"""
        SELECT
            JSON_VALUE(client_info, '$.client') as client,
            COUNT(*) as meeting_count
        FROM `{table_id}`
        WHERE JSON_VALUE(client_info, '$.client') IS NOT NULL
        GROUP BY client
        ORDER BY meeting_count DESC, client
        LIMIT {limit}
        """
    else:
        query = f"""
        SELECT DISTINCT
            JSON_VALUE(client_info, '$.client') as client
        FROM `{table_id}`
        WHERE JSON_VALUE(client_info, '$.client') IS NOT NULL
        ORDER BY client
        LIMIT {limit}
        """

    console.print(f"[yellow]Querying unique clients...[/yellow]")
    results = loader.client.query(query).result()

    if show_counts:
        client_table = Table(title="Client Names with Meeting Counts")
        client_table.add_column("Client", style="cyan")
        client_table.add_column("Meetings", style="magenta", justify="right")

        total_meetings = 0
        for row in results:
            client_table.add_row(row.client, str(row.meeting_count))
            total_meetings += row.meeting_count

        console.print(client_table)
        console.print(f"\n[blue]Total unique clients: {results.total_rows}[/blue]")
        console.print(f"[blue]Total meetings: {total_meetings}[/blue]")
    else:
        clients = [row.client for row in results]

        for i, client in enumerate(clients, 1):
            console.print(f"{i:3d}. {client}")

        console.print(f"\n[blue]Total unique clients: {len(clients)}[/blue]")


@app.command()
def add_client_mapping(
    variant: str = typer.Argument(..., help="Variant client name to map"),
    canonical: str = typer.Argument(..., help="Canonical client name"),
    notes: str = typer.Option(None, "--notes", "-n", help="Notes about this mapping")
):
    """Add or update a client name mapping in BigQuery."""

    loader = BigQueryLoader()
    success = loader.add_client_mapping(variant, canonical, notes)

    if not success:
        raise typer.Exit(1)


@app.command()
def delete_client_mapping(
    variant: str = typer.Argument(..., help="Variant client name to delete")
):
    """Delete a client name mapping from BigQuery."""

    loader = BigQueryLoader()
    success = loader.delete_client_mapping(variant)

    if not success:
        raise typer.Exit(1)


@app.command()
def list_mappings():
    """List all client name mappings from BigQuery."""

    loader = BigQueryLoader()
    mappings = loader.list_client_mappings()

    if not mappings:
        console.print("[yellow]No mappings found in BigQuery[/yellow]")
        console.print("[blue]Use 'add-client-mapping' to add mappings[/blue]")
        return

    # Display mappings table
    mapping_table = Table(title="Client Name Mappings")
    mapping_table.add_column("Variant Name", style="yellow")
    mapping_table.add_column("→", style="white")
    mapping_table.add_column("Canonical Name", style="green")
    mapping_table.add_column("Notes", style="blue")
    mapping_table.add_column("Updated", style="cyan")

    for mapping in mappings:
        updated = mapping["updated_at"].strftime("%Y-%m-%d") if mapping.get("updated_at") else "Unknown"
        mapping_table.add_row(
            mapping["variant_name"],
            "→",
            mapping["canonical_name"],
            mapping.get("notes") or "",
            updated
        )

    console.print(mapping_table)
    console.print(f"\n[blue]Total mappings: {len(mappings)}[/blue]")


@app.command()
def init_mappings(
    from_file: bool = typer.Option(True, "--from-file/--empty", help="Initialize from client_mappings.json")
):
    """Initialize BigQuery mappings table (optionally from JSON file)."""

    loader = BigQueryLoader()
    loader.create_dataset_if_not_exists()
    loader.create_mappings_table_if_not_exists()

    if from_file:
        mappings_file = Path("client_mappings.json")
        if not mappings_file.exists():
            console.print(f"[yellow]Mappings file {mappings_file} not found, skipping import[/yellow]")
            return

        with open(mappings_file) as f:
            config = json.load(f)
            mappings = config.get("mappings", {})

        console.print(f"[blue]Importing {len(mappings)} mappings from {mappings_file}...[/blue]")

        success_count = 0
        for variant, canonical in track(mappings.items(), description="Importing mappings..."):
            if loader.add_client_mapping(variant, canonical):
                success_count += 1

        console.print(f"\n[green]Successfully imported {success_count}/{len(mappings)} mappings[/green]")
    else:
        console.print("[green]Mappings table initialized (empty)[/green]")


@app.command("rescore-compare")
def rescore_compare(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of latest meetings to re-score"),
    llm_model: str = typer.Option(os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini"), "--model", help="LLM model to use"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed section-level changes")
):
    """Re-score latest meetings from BigQuery and compare old vs new scores."""

    loader = BigQueryLoader()
    table_id = f"{loader.project_id}.{loader.dataset_name}.{loader.new_table_name}"

    # Fetch latest meetings with their transcript content and old scores
    query = f"""
    SELECT
        meeting_id,
        date,
        JSON_VALUE(client_info, '$.client') as client,
        participants,
        enhanced_notes,
        full_transcript,
        total_qualified_sections as old_score,
        now,
        next,
        measure,
        blocker,
        fit,
        llm_model as old_model
    FROM `{table_id}`
    WHERE enhanced_notes IS NOT NULL OR full_transcript IS NOT NULL
    ORDER BY date DESC
    LIMIT {limit}
    """

    console.print(f"[blue]Fetching {limit} latest meetings from BigQuery...[/blue]")

    try:
        results = loader.client.query(query).result()
        meetings = list(results)
    except Exception as e:
        console.print(f"[red]Failed to fetch meetings: {e}[/red]")
        raise typer.Exit(1)

    if not meetings:
        console.print("[yellow]No meetings found with transcript content[/yellow]")
        raise typer.Exit(1)

    console.print(f"[green]Found {len(meetings)} meetings to re-score[/green]")

    # Initialize scorer
    try:
        llm_scorer = LLMScorer(model=llm_model)
    except ValueError as e:
        console.print(f"[red]Error initializing LLM scorer: {e}[/red]")
        raise typer.Exit(1)

    # Re-score each meeting
    from .schemas import Transcript, Note
    from datetime import date as DateType

    comparison_results = []

    for meeting in track(meetings, description=f"Re-scoring with {llm_model}..."):
        try:
            # Reconstruct transcript from BQ data
            meeting_date = meeting.date
            if isinstance(meeting_date, str):
                from datetime import datetime
                meeting_date = datetime.strptime(meeting_date, "%Y-%m-%d").date()

            transcript = Transcript(
                meeting_id=meeting.meeting_id,
                date=meeting_date,
                company=meeting.client,
                participants=meeting.participants or [],
                desk="Unknown",
                notes=[],
                source="bigquery",
                enhanced_notes=meeting.enhanced_notes,
                full_transcript=meeting.full_transcript
            )

            # Score with new prompts
            new_result = llm_scorer.score_transcript_new(transcript)

            # Parse old section scores
            old_now = meeting.now.get("qualified", False) if meeting.now else False
            old_next = meeting.next.get("qualified", False) if meeting.next else False
            old_measure = meeting.measure.get("qualified", False) if meeting.measure else False
            old_blocker = meeting.blocker.get("qualified", False) if meeting.blocker else False
            old_fit = meeting.fit.get("qualified", False) if meeting.fit else False

            comparison_results.append({
                "meeting_id": meeting.meeting_id,
                "client": meeting.client or "Unknown",
                "date": str(meeting.date),
                "old_score": meeting.old_score,
                "new_score": new_result.total_qualified_sections,
                "delta": new_result.total_qualified_sections - meeting.old_score,
                "old_qualified": meeting.old_score >= 3,
                "new_qualified": new_result.qualified,
                "old_model": meeting.old_model,
                "sections": {
                    "now": {"old": old_now, "new": new_result.now.qualified},
                    "next": {"old": old_next, "new": new_result.next.qualified},
                    "measure": {"old": old_measure, "new": new_result.measure.qualified},
                    "blocker": {"old": old_blocker, "new": new_result.blocker.qualified},
                    "fit": {"old": old_fit, "new": new_result.fit.qualified}
                }
            })

        except Exception as e:
            console.print(f"[red]Failed to score {meeting.meeting_id}: {e}[/red]")

    if not comparison_results:
        console.print("[red]No meetings were successfully re-scored[/red]")
        raise typer.Exit(1)

    # Display comparison table
    comparison_table = Table(title=f"Score Comparison: Old vs New ({llm_model})")
    comparison_table.add_column("Client", style="cyan", max_width=20)
    comparison_table.add_column("Date", style="white")
    comparison_table.add_column("Old", style="yellow", justify="center")
    comparison_table.add_column("New", style="green", justify="center")
    comparison_table.add_column("Δ", style="magenta", justify="center")
    comparison_table.add_column("Status", style="blue")

    for r in sorted(comparison_results, key=lambda x: x["delta"], reverse=True):
        delta_str = f"+{r['delta']}" if r['delta'] > 0 else str(r['delta'])

        # Status indicator
        if not r["old_qualified"] and r["new_qualified"]:
            status = "✓ Now qualified"
        elif r["old_qualified"] and not r["new_qualified"]:
            status = "✗ Lost qualification"
        elif r["delta"] > 0:
            status = "↑ Improved"
        elif r["delta"] < 0:
            status = "↓ Decreased"
        else:
            status = "= Same"

        comparison_table.add_row(
            r["client"][:20],
            r["date"],
            f"{r['old_score']}/5",
            f"{r['new_score']}/5",
            delta_str,
            status
        )

    console.print(comparison_table)

    # Summary stats
    total = len(comparison_results)
    improved = sum(1 for r in comparison_results if r["delta"] > 0)
    decreased = sum(1 for r in comparison_results if r["delta"] < 0)
    same = sum(1 for r in comparison_results if r["delta"] == 0)
    newly_qualified = sum(1 for r in comparison_results if not r["old_qualified"] and r["new_qualified"])
    lost_qualified = sum(1 for r in comparison_results if r["old_qualified"] and not r["new_qualified"])

    old_avg = sum(r["old_score"] for r in comparison_results) / total
    new_avg = sum(r["new_score"] for r in comparison_results) / total

    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Improved: {improved}/{total} ({improved/total*100:.0f}%)")
    console.print(f"  Decreased: {decreased}/{total} ({decreased/total*100:.0f}%)")
    console.print(f"  Same: {same}/{total} ({same/total*100:.0f}%)")
    console.print(f"  Newly qualified: {newly_qualified}")
    console.print(f"  Lost qualification: {lost_qualified}")
    console.print(f"  Avg score: {old_avg:.1f} → {new_avg:.1f}")

    # Verbose: show section-level changes
    if verbose:
        console.print(f"\n[bold]Section-Level Changes:[/bold]")

        section_changes = {"now": 0, "next": 0, "measure": 0, "blocker": 0, "fit": 0}
        section_gains = {"now": 0, "next": 0, "measure": 0, "blocker": 0, "fit": 0}

        for r in comparison_results:
            for section in section_changes.keys():
                old_val = r["sections"][section]["old"]
                new_val = r["sections"][section]["new"]
                if old_val != new_val:
                    section_changes[section] += 1
                    if new_val and not old_val:
                        section_gains[section] += 1

        section_table = Table()
        section_table.add_column("Section", style="cyan")
        section_table.add_column("Changed", style="yellow", justify="center")
        section_table.add_column("Gains", style="green", justify="center")

        for section in section_changes.keys():
            section_table.add_row(
                section.upper(),
                str(section_changes[section]),
                f"+{section_gains[section]}"
            )

        console.print(section_table)

    console.print(f"\n[bold green]Comparison completed![/bold green]")


if __name__ == "__main__":
    app()
else:
    # Support running with python -m src.cli
    import sys
    if len(sys.argv) > 0 and sys.argv[0].endswith('cli.py'):
        app()