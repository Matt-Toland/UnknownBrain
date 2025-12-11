"""
BIGQUERY LOADER UPDATES FOR SALESPERSON ASSESSMENT
Updates to add to src/bq_loader.py in the upstream scoring project

This adds:
1. New schema columns for sales assessment
2. Updated MERGE query
3. Migration method to add columns to existing table
"""

from google.cloud import bigquery
from typing import List

# =============================================================================
# NEW SCHEMA FIELDS TO ADD
# =============================================================================

# Add these fields to the schema list in create_new_table_if_not_exists()
SALES_ASSESSMENT_SCHEMA_FIELDS = [
    # Salesperson identification
    bigquery.SchemaField("salesperson_name", "STRING", mode="NULLABLE", 
                         description="UNKNOWN rep name (from creator_name)"),
    bigquery.SchemaField("salesperson_email", "STRING", mode="NULLABLE", 
                         description="UNKNOWN rep email (from creator_email)"),
    
    # Sales assessment totals
    bigquery.SchemaField("sales_total_score", "INTEGER", mode="NULLABLE", 
                         description="Total sales assessment score (0-24)"),
    bigquery.SchemaField("sales_total_qualified", "INTEGER", mode="NULLABLE", 
                         description="Number of sales criteria qualified (0-8)"),
    bigquery.SchemaField("sales_qualified", "BOOLEAN", mode="NULLABLE", 
                         description="True if sales assessment meets threshold (5/8)"),
    
    # Sales assessment JSON blobs (8 criteria)
    bigquery.SchemaField("sales_introduction", "JSON", mode="NULLABLE", 
                         description="Introduction & Framing assessment"),
    bigquery.SchemaField("sales_discovery", "JSON", mode="NULLABLE", 
                         description="Discovery of problems/pain assessment"),
    bigquery.SchemaField("sales_scoping", "JSON", mode="NULLABLE", 
                         description="Opportunity scoping assessment"),
    bigquery.SchemaField("sales_solution", "JSON", mode="NULLABLE", 
                         description="Solution positioning assessment"),
    bigquery.SchemaField("sales_commercial", "JSON", mode="NULLABLE", 
                         description="Commercial confidence assessment"),
    bigquery.SchemaField("sales_case_studies", "JSON", mode="NULLABLE", 
                         description="Case studies/proof points assessment"),
    bigquery.SchemaField("sales_next_steps", "JSON", mode="NULLABLE", 
                         description="Next steps & stakeholder mapping assessment"),
    bigquery.SchemaField("sales_strategic_context", "JSON", mode="NULLABLE", 
                         description="Strategic context gathering assessment"),
    
    # Coaching summaries
    bigquery.SchemaField("sales_strengths", "STRING", mode="REPEATED", 
                         description="Top strengths identified"),
    bigquery.SchemaField("sales_improvements", "STRING", mode="REPEATED", 
                         description="Top improvement areas"),
    bigquery.SchemaField("sales_overall_coaching", "STRING", mode="NULLABLE", 
                         description="Overall coaching note"),
]


# =============================================================================
# ADD THIS METHOD TO BigQueryLoader CLASS
# =============================================================================

class BigQueryLoaderSalesAdditions:
    """
    Methods to add to the existing BigQueryLoader class.
    Copy these methods into src/bq_loader.py
    """

    def add_sales_assessment_columns(self) -> bool:
        """
        Add sales assessment columns to existing meeting_intel table.
        
        This is a migration method - run once to update existing table schema.
        BigQuery allows adding NULLABLE columns to existing tables.
        
        Returns:
            True if successful, False otherwise
        """
        table_id = f"{self.project_id}.{self.dataset_name}.{self.new_table_name}"
        
        try:
            # Get current table
            table = self.client.get_table(table_id)
            original_schema = list(table.schema)
            
            # Check which columns already exist
            existing_columns = {field.name for field in original_schema}
            
            # Add new columns that don't exist yet
            new_fields = []
            for field in SALES_ASSESSMENT_SCHEMA_FIELDS:
                if field.name not in existing_columns:
                    new_fields.append(field)
                    console.print(f"[blue]Adding column: {field.name}[/blue]")
                else:
                    console.print(f"[yellow]Column already exists: {field.name}[/yellow]")
            
            if not new_fields:
                console.print("[green]All sales assessment columns already exist[/green]")
                return True
            
            # Update schema
            new_schema = original_schema + new_fields
            table.schema = new_schema
            
            # Apply the update
            updated_table = self.client.update_table(table, ["schema"])
            
            console.print(f"[green]Successfully added {len(new_fields)} new columns to {table_id}[/green]")
            console.print(f"[blue]Total schema fields: {len(updated_table.schema)}[/blue]")
            
            return True
            
        except Exception as e:
            console.print(f"[red]Failed to add sales assessment columns: {e}[/red]")
            return False

    def merge_new_jsonl_data_with_sales(self, jsonl_path) -> int:
        """
        Merge JSONL data to meeting_intel BigQuery table using UPSERT.
        
        This is an updated version of merge_new_jsonl_data() that includes
        the sales assessment columns in the MERGE statement.
        
        Args:
            jsonl_path: Path to JSONL file with combined scoring format
            
        Returns:
            Number of rows processed
        """
        if not jsonl_path.exists():
            console.print(f"[red]JSONL file not found: {jsonl_path}[/red]")
            return 0

        # Ensure dataset and table exist
        self.create_dataset_if_not_exists()
        self.create_new_table_if_not_exists()
        
        # Add sales columns if they don't exist
        self.add_sales_assessment_columns()

        # Load data into temporary table first
        import time
        temp_table_id = f"{self.project_id}.{self.dataset_name}.temp_upload_{int(time.time())}"
        target_table_id = f"{self.project_id}.{self.dataset_name}.{self.new_table_name}"

        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=False,
            write_disposition="WRITE_TRUNCATE",
            schema=self.client.get_table(target_table_id).schema
        )

        console.print(f"[blue]Loading data to temporary table: {temp_table_id}[/blue]")

        with open(jsonl_path, "rb") as source_file:
            job = self.client.load_table_from_file(
                source_file,
                temp_table_id,
                job_config=job_config
            )

        console.print("[yellow]Uploading to temporary table...[/yellow]")
        job.result()

        if job.errors:
            console.print(f"[red]Temporary table load failed: {job.errors}[/red]")
            return 0

        # MERGE query with all fields including sales assessment
        merge_query = f"""
        MERGE `{target_table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.meeting_id = source.meeting_id
        WHEN MATCHED THEN
            UPDATE SET
                -- Core fields
                date = source.date,
                participants = source.participants,
                desk = source.desk,
                source = source.source,
                client_info = source.client_info,
                
                -- Granola metadata
                granola_note_id = source.granola_note_id,
                title = source.title,
                creator_name = source.creator_name,
                creator_email = source.creator_email,
                calendar_event_title = source.calendar_event_title,
                calendar_event_id = source.calendar_event_id,
                calendar_event_time = source.calendar_event_time,
                granola_link = source.granola_link,
                file_created_timestamp = source.file_created_timestamp,
                zapier_step_id = source.zapier_step_id,
                
                -- Content sections
                enhanced_notes = source.enhanced_notes,
                my_notes = source.my_notes,
                full_transcript = source.full_transcript,
                
                -- Opportunity scoring (existing)
                total_qualified_sections = source.total_qualified_sections,
                qualified = source.qualified,
                now = source.now,
                next = source.next,
                measure = source.measure,
                blocker = source.blocker,
                fit = source.fit,
                
                -- Taxonomy tagging
                challenges = source.challenges,
                results = source.results,
                offering = source.offering,
                
                -- Processing metadata
                scored_at = source.scored_at,
                llm_model = source.llm_model,
                
                -- === NEW: Sales Assessment Fields ===
                salesperson_name = source.salesperson_name,
                salesperson_email = source.salesperson_email,
                sales_total_score = source.sales_total_score,
                sales_total_qualified = source.sales_total_qualified,
                sales_qualified = source.sales_qualified,
                
                -- Sales assessment criteria
                sales_introduction = source.sales_introduction,
                sales_discovery = source.sales_discovery,
                sales_scoping = source.sales_scoping,
                sales_solution = source.sales_solution,
                sales_commercial = source.sales_commercial,
                sales_case_studies = source.sales_case_studies,
                sales_next_steps = source.sales_next_steps,
                sales_strategic_context = source.sales_strategic_context,
                
                -- Coaching summaries
                sales_strengths = source.sales_strengths,
                sales_improvements = source.sales_improvements,
                sales_overall_coaching = source.sales_overall_coaching
                
        WHEN NOT MATCHED THEN
            INSERT ROW
        """

        console.print(f"[blue]Merging data from temp table to {target_table_id}[/blue]")
        merge_job = self.client.query(merge_query)
        merge_job.result()

        # Get stats
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

    def query_sales_performance(self, days: int = 7, limit: int = 20) -> List[dict]:
        """
        Query sales performance data from BigQuery.
        
        Returns salesperson performance metrics for the emailer to consume.
        
        Args:
            days: Number of days to look back
            limit: Maximum rows to return
            
        Returns:
            List of dictionaries with sales performance data
        """
        table_id = f"{self.project_id}.{self.dataset_name}.{self.new_table_name}"
        
        query = f"""
        SELECT
            meeting_id,
            salesperson_name,
            salesperson_email,
            JSON_VALUE(client_info, '$.client') as client,
            date,
            title,
            granola_link,
            
            -- Sales assessment totals
            sales_total_score,
            sales_total_qualified,
            sales_qualified,
            
            -- Individual criteria scores (extracted from JSON)
            CAST(JSON_VALUE(sales_introduction, '$.score') AS INT64) as intro_score,
            CAST(JSON_VALUE(sales_discovery, '$.score') AS INT64) as discovery_score,
            CAST(JSON_VALUE(sales_scoping, '$.score') AS INT64) as scoping_score,
            CAST(JSON_VALUE(sales_solution, '$.score') AS INT64) as solution_score,
            CAST(JSON_VALUE(sales_commercial, '$.score') AS INT64) as commercial_score,
            CAST(JSON_VALUE(sales_case_studies, '$.score') AS INT64) as case_studies_score,
            CAST(JSON_VALUE(sales_next_steps, '$.score') AS INT64) as next_steps_score,
            CAST(JSON_VALUE(sales_strategic_context, '$.score') AS INT64) as strategic_score,
            
            -- Coaching notes
            JSON_VALUE(sales_introduction, '$.coaching_note') as intro_coaching,
            JSON_VALUE(sales_discovery, '$.coaching_note') as discovery_coaching,
            JSON_VALUE(sales_scoping, '$.coaching_note') as scoping_coaching,
            JSON_VALUE(sales_solution, '$.coaching_note') as solution_coaching,
            JSON_VALUE(sales_commercial, '$.coaching_note') as commercial_coaching,
            JSON_VALUE(sales_case_studies, '$.coaching_note') as case_studies_coaching,
            JSON_VALUE(sales_next_steps, '$.coaching_note') as next_steps_coaching,
            JSON_VALUE(sales_strategic_context, '$.coaching_note') as strategic_coaching,
            
            -- Overall coaching
            sales_strengths,
            sales_improvements,
            sales_overall_coaching,
            
            -- Also include opportunity scoring for context
            total_qualified_sections as opportunity_score,
            qualified as opportunity_qualified
            
        FROM `{table_id}`
        WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND sales_total_score IS NOT NULL
        ORDER BY date DESC, sales_total_score DESC
        LIMIT {limit}
        """
        
        try:
            query_job = self.client.query(query)
            results = [dict(row) for row in query_job.result()]
            console.print(f"[green]Found {len(results)} meetings with sales assessments[/green]")
            return results
        except Exception as e:
            console.print(f"[red]Sales performance query failed: {e}[/red]")
            return []

    def query_salesperson_summary(self, days: int = 7) -> List[dict]:
        """
        Query aggregated sales performance by salesperson.
        
        Returns per-person averages and totals for the emailer.
        
        Args:
            days: Number of days to look back
            
        Returns:
            List of dictionaries with per-salesperson metrics
        """
        table_id = f"{self.project_id}.{self.dataset_name}.{self.new_table_name}"
        
        query = f"""
        SELECT
            salesperson_name,
            salesperson_email,
            COUNT(*) as total_meetings,
            
            -- Average scores
            ROUND(AVG(sales_total_score), 1) as avg_total_score,
            ROUND(AVG(sales_total_qualified), 1) as avg_qualified_count,
            
            -- Per-criteria averages
            ROUND(AVG(CAST(JSON_VALUE(sales_introduction, '$.score') AS INT64)), 1) as avg_intro,
            ROUND(AVG(CAST(JSON_VALUE(sales_discovery, '$.score') AS INT64)), 1) as avg_discovery,
            ROUND(AVG(CAST(JSON_VALUE(sales_scoping, '$.score') AS INT64)), 1) as avg_scoping,
            ROUND(AVG(CAST(JSON_VALUE(sales_solution, '$.score') AS INT64)), 1) as avg_solution,
            ROUND(AVG(CAST(JSON_VALUE(sales_commercial, '$.score') AS INT64)), 1) as avg_commercial,
            ROUND(AVG(CAST(JSON_VALUE(sales_case_studies, '$.score') AS INT64)), 1) as avg_case_studies,
            ROUND(AVG(CAST(JSON_VALUE(sales_next_steps, '$.score') AS INT64)), 1) as avg_next_steps,
            ROUND(AVG(CAST(JSON_VALUE(sales_strategic_context, '$.score') AS INT64)), 1) as avg_strategic,
            
            -- Qualification rate
            ROUND(100.0 * COUNTIF(sales_qualified = TRUE) / COUNT(*), 1) as qualification_rate,
            
            -- Best and worst meetings
            MAX(sales_total_score) as best_score,
            MIN(sales_total_score) as worst_score
            
        FROM `{table_id}`
        WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND sales_total_score IS NOT NULL
            AND salesperson_name IS NOT NULL
        GROUP BY salesperson_name, salesperson_email
        HAVING total_meetings >= 1
        ORDER BY avg_total_score DESC
        """
        
        try:
            query_job = self.client.query(query)
            results = [dict(row) for row in query_job.result()]
            console.print(f"[green]Found {len(results)} salespeople with assessments[/green]")
            return results
        except Exception as e:
            console.print(f"[red]Salesperson summary query failed: {e}[/red]")
            return []

    def display_sales_assessment_status(self) -> None:
        """Display sales assessment data status"""
        table_id = f"{self.project_id}.{self.dataset_name}.{self.new_table_name}"
        
        # Count rows with sales data
        count_query = f"""
        SELECT 
            COUNT(*) as total_rows,
            COUNTIF(sales_total_score IS NOT NULL) as rows_with_sales_assessment,
            COUNTIF(sales_qualified = TRUE) as qualified_meetings,
            ROUND(AVG(sales_total_score), 1) as avg_sales_score,
            COUNT(DISTINCT salesperson_name) as unique_salespeople
        FROM `{table_id}`
        WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        """
        
        try:
            results = list(self.client.query(count_query).result())
            if results:
                data = dict(results[0])
                
                from rich.table import Table
                table = Table(title="Sales Assessment Status (Last 30 Days)")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="magenta")
                
                table.add_row("Total Meetings", str(data.get("total_rows", 0)))
                table.add_row("With Sales Assessment", str(data.get("rows_with_sales_assessment", 0)))
                table.add_row("Qualified Meetings", str(data.get("qualified_meetings", 0)))
                table.add_row("Avg Sales Score", f"{data.get('avg_sales_score', 0)}/24")
                table.add_row("Unique Salespeople", str(data.get("unique_salespeople", 0)))
                
                console.print(table)
                
        except Exception as e:
            console.print(f"[red]Status query failed: {e}[/red]")


# =============================================================================
# UPDATED create_new_table_if_not_exists() - FULL REPLACEMENT
# =============================================================================

def create_new_table_if_not_exists_with_sales(self) -> None:
    """
    Create the new meeting_intel table with JSON column types INCLUDING sales assessment.
    
    This is an updated version of create_new_table_if_not_exists() that includes
    all the sales assessment columns from the start.
    
    Replace the existing method with this one, or use add_sales_assessment_columns()
    to migrate an existing table.
    """
    table_id = f"{self.project_id}.{self.dataset_name}.{self.new_table_name}"

    try:
        self.client.get_table(table_id)
        console.print(f"[blue]Table {self.new_table_name} already exists[/blue]")
        return
    except Exception:
        pass

    # Define schema for the new table with JSON types + sales assessment
    schema = [
        # === Core fields ===
        bigquery.SchemaField("meeting_id", "STRING", mode="REQUIRED", description="Unique meeting identifier"),
        bigquery.SchemaField("date", "DATE", mode="REQUIRED", description="Meeting date"),
        bigquery.SchemaField("participants", "STRING", mode="REPEATED", description="List of participants"),
        bigquery.SchemaField("desk", "STRING", mode="NULLABLE", description="Business category"),
        bigquery.SchemaField("source", "STRING", mode="REQUIRED", description="Source of transcript"),

        # Enhanced client information as JSON
        bigquery.SchemaField("client_info", "JSON", mode="REQUIRED", description="Client information as JSON blob"),

        # === Granola metadata fields ===
        bigquery.SchemaField("granola_note_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("title", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("creator_name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("creator_email", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("calendar_event_title", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("calendar_event_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("calendar_event_time", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("granola_link", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("file_created_timestamp", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("zapier_step_id", "INTEGER", mode="NULLABLE"),

        # === Content sections ===
        bigquery.SchemaField("enhanced_notes", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("my_notes", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("full_transcript", "STRING", mode="NULLABLE"),

        # === Opportunity scoring results (existing) ===
        bigquery.SchemaField("total_qualified_sections", "INTEGER", mode="REQUIRED", description="Total qualified sections (0-5)"),
        bigquery.SchemaField("qualified", "BOOLEAN", mode="REQUIRED", description="True if meets threshold"),

        # JSON blob scoring sections
        bigquery.SchemaField("now", "JSON", mode="REQUIRED", description="NOW scoring as JSON blob"),
        bigquery.SchemaField("next", "JSON", mode="REQUIRED", description="NEXT scoring as JSON blob"),
        bigquery.SchemaField("measure", "JSON", mode="REQUIRED", description="MEASURE scoring as JSON blob"),
        bigquery.SchemaField("blocker", "JSON", mode="REQUIRED", description="BLOCKER scoring as JSON blob"),
        bigquery.SchemaField("fit", "JSON", mode="REQUIRED", description="FIT scoring as JSON blob"),

        # Client taxonomy tagging
        bigquery.SchemaField("challenges", "STRING", mode="REPEATED", description="Client challenges from taxonomy"),
        bigquery.SchemaField("results", "STRING", mode="REPEATED", description="Desired results from taxonomy"),
        bigquery.SchemaField("offering", "STRING", mode="NULLABLE", description="Primary offering type from taxonomy"),

        # === NEW: Sales Assessment Fields ===
        
        # Salesperson identification
        bigquery.SchemaField("salesperson_name", "STRING", mode="NULLABLE", 
                             description="UNKNOWN rep name"),
        bigquery.SchemaField("salesperson_email", "STRING", mode="NULLABLE", 
                             description="UNKNOWN rep email"),
        
        # Sales assessment totals
        bigquery.SchemaField("sales_total_score", "INTEGER", mode="NULLABLE", 
                             description="Total sales assessment score (0-24)"),
        bigquery.SchemaField("sales_total_qualified", "INTEGER", mode="NULLABLE", 
                             description="Number of sales criteria qualified (0-8)"),
        bigquery.SchemaField("sales_qualified", "BOOLEAN", mode="NULLABLE", 
                             description="True if sales assessment meets threshold"),
        
        # Sales assessment JSON blobs (8 criteria)
        bigquery.SchemaField("sales_introduction", "JSON", mode="NULLABLE", 
                             description="Introduction & Framing assessment"),
        bigquery.SchemaField("sales_discovery", "JSON", mode="NULLABLE", 
                             description="Discovery assessment"),
        bigquery.SchemaField("sales_scoping", "JSON", mode="NULLABLE", 
                             description="Opportunity scoping assessment"),
        bigquery.SchemaField("sales_solution", "JSON", mode="NULLABLE", 
                             description="Solution positioning assessment"),
        bigquery.SchemaField("sales_commercial", "JSON", mode="NULLABLE", 
                             description="Commercial confidence assessment"),
        bigquery.SchemaField("sales_case_studies", "JSON", mode="NULLABLE", 
                             description="Case studies assessment"),
        bigquery.SchemaField("sales_next_steps", "JSON", mode="NULLABLE", 
                             description="Next steps assessment"),
        bigquery.SchemaField("sales_strategic_context", "JSON", mode="NULLABLE", 
                             description="Strategic context assessment"),
        
        # Coaching summaries
        bigquery.SchemaField("sales_strengths", "STRING", mode="REPEATED", 
                             description="Top strengths identified"),
        bigquery.SchemaField("sales_improvements", "STRING", mode="REPEATED", 
                             description="Top improvement areas"),
        bigquery.SchemaField("sales_overall_coaching", "STRING", mode="NULLABLE", 
                             description="Overall coaching note"),

        # === Processing metadata ===
        bigquery.SchemaField("scored_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("llm_model", "STRING", mode="REQUIRED")
    ]

    table = bigquery.Table(table_id, schema=schema)
    table.description = "UNKNOWN Brain meeting intelligence with opportunity and sales assessment scoring"

    table = self.client.create_table(table, timeout=30)
    console.print(f"[green]Created table {self.new_table_name} with {len(schema)} columns (including sales assessment)[/green]")


# =============================================================================
# CLI COMMAND TO ADD (for src/cli.py)
# =============================================================================

"""
Add this command to src/cli.py:

@app.command("migrate-sales-schema")
def migrate_sales_schema():
    '''Add sales assessment columns to existing meeting_intel table.'''
    
    try:
        loader = BigQueryLoader()
        
        console.print("\\n[bold]Adding sales assessment columns to BigQuery table...[/bold]")
        
        success = loader.add_sales_assessment_columns()
        
        if success:
            console.print("\\n[bold green]Migration completed successfully![/bold green]")
            loader.display_sales_assessment_status()
        else:
            console.print("\\n[red]Migration failed[/red]")
            raise typer.Exit(1)
            
    except Exception as e:
        console.print(f"[red]Migration failed: {e}[/red]")
        raise typer.Exit(1)

@app.command("sales-status")
def sales_status():
    '''Display sales assessment data status.'''
    
    try:
        loader = BigQueryLoader()
        loader.display_sales_assessment_status()
        
        # Show per-person summary
        console.print("\\n[bold]Per-Salesperson Summary (Last 7 Days):[/bold]")
        summary = loader.query_salesperson_summary(days=7)
        
        if summary:
            from rich.table import Table
            table = Table()
            table.add_column("Name", style="cyan")
            table.add_column("Meetings", style="white")
            table.add_column("Avg Score", style="magenta")
            table.add_column("Qual Rate", style="green")
            
            for person in summary:
                table.add_row(
                    person.get("salesperson_name", "Unknown"),
                    str(person.get("total_meetings", 0)),
                    f"{person.get('avg_total_score', 0)}/24",
                    f"{person.get('qualification_rate', 0)}%"
                )
            
            console.print(table)
        else:
            console.print("[yellow]No sales assessment data found[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Status check failed: {e}[/red]")
        raise typer.Exit(1)
"""