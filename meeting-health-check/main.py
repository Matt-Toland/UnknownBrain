import functions_framework
from google.cloud import bigquery
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@functions_framework.http
def check_meeting_health(request):
    """
    Cloud Function that checks if meetings have been ingested recently.
    Logs an ERROR if no meetings in the last 3 days, which triggers Cloud Monitoring alerts.
    """

    client = bigquery.Client(project="angular-stacker-471711-k4")

    query = """
    SELECT COUNT(*) as meeting_count
    FROM `angular-stacker-471711-k4.unknown_brain.meeting_intel`
    WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    """

    try:
        result = client.query(query).result()
        row = list(result)[0]
        meeting_count = row.meeting_count

        if meeting_count == 0:
            # This ERROR log will trigger Cloud Monitoring alerts
            logger.error(
                f"MEETING_INGESTION_ALERT: No meetings ingested in the last 3 days! "
                f"Check Zapier, Granola connection, or brain-uploader service."
            )
            return {
                "status": "alert",
                "message": "No meetings in last 3 days",
                "meeting_count": meeting_count
            }, 200  # Return 200 so scheduler doesn't retry
        else:
            logger.info(f"Meeting health check passed: {meeting_count} meetings in last 3 days")
            return {
                "status": "healthy",
                "message": f"{meeting_count} meetings in last 3 days",
                "meeting_count": meeting_count
            }, 200

    except Exception as e:
        logger.error(f"MEETING_HEALTH_CHECK_ERROR: Failed to query BigQuery: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }, 500
