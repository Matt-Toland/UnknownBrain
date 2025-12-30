#!/bin/bash
# Deploy UNKNOWN Brain to Cloud Run with rollback capability
# This script saves the current revision before deployment for easy rollback

set -e

echo "================================================"
echo "Deploying UNKNOWN Brain to Cloud Run"
echo "================================================"

# Configuration
PROJECT_ID="angular-stacker-471711-k4"
SERVICE_NAME="unknown-brain"
REGION="us-central1"

# Set the correct project
echo ""
echo "Setting GCP project to: $PROJECT_ID"
gcloud config set project $PROJECT_ID

echo ""
echo "Checking current Cloud Run deployment..."

# Save current revision for rollback (if service exists)
CURRENT_REVISION=$(gcloud run services describe $SERVICE_NAME \
  --region=$REGION \
  --format='value(status.latestReadyRevisionName)' 2>/dev/null || echo "")

if [ -n "$CURRENT_REVISION" ]; then
  echo "Current revision: $CURRENT_REVISION (saved for rollback)"
  echo ""
  echo "To rollback after deployment, run:"
  echo "  gcloud run services update-traffic $SERVICE_NAME \\"
  echo "    --to-revisions=$CURRENT_REVISION=100 \\"
  echo "    --region=$REGION"
else
  echo "No existing deployment found. This will be the first deployment."
fi

echo ""
echo "Building and deploying with Cloud Build..."
echo "This will:"
echo "  1. Build Docker image"
echo "  2. Push to Artifact Registry"
echo "  3. Deploy to Cloud Run"
echo ""

# Deploy using Cloud Build
gcloud builds submit --config cloudbuild.yaml --project=$PROJECT_ID

echo ""
echo "================================================"
echo "Deployment complete!"
echo "================================================"
echo ""
echo "Service URL:"
gcloud run services describe $SERVICE_NAME --region=$REGION --format='value(status.url)'

echo ""
echo "Useful commands:"
echo ""
echo "1. View logs:"
echo "   gcloud logs tail --service=$SERVICE_NAME --region=$REGION"
echo ""
echo "2. Check service status:"
echo "   gcloud run services describe $SERVICE_NAME --region=$REGION"
echo ""
echo "3. List all revisions:"
echo "   gcloud run revisions list --service=$SERVICE_NAME --region=$REGION"
echo ""
echo "4. Rollback to previous version (if needed):"
if [ -n "$CURRENT_REVISION" ]; then
  echo "   gcloud run services update-traffic $SERVICE_NAME \\"
  echo "     --to-revisions=$CURRENT_REVISION=100 \\"
  echo "     --region=$REGION"
else
  echo "   (No previous revision available)"
fi
echo ""
echo "5. Disable sales scoring without redeployment:"
echo "   gcloud run services update $SERVICE_NAME \\"
echo "     --set-env-vars=\"ENABLE_SALES_SCORING=false\" \\"
echo "     --region=$REGION"
echo ""
echo "================================================"
echo "Sales scoring is now enabled in Cloud Run!"
echo "All new transcripts will get both opportunity"
echo "and sales assessment scoring."
echo "================================================"