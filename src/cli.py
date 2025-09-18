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


if __name__ == "__main__":
    app()
else:
    # Support running with python -m src.cli
    import sys
    if len(sys.argv) > 0 and sys.argv[0].endswith('cli.py'):
        app()