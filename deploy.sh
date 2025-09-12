#!/bin/bash

# UNKNOWN Brain Cloud Run Deployment Script
# Run this script to deploy to Google Cloud Run

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID=${GOOGLE_CLOUD_PROJECT:-""}
REGION="us-central1"
SERVICE_NAME="unknown-brain"
BUCKET_NAME="unknown-brain-transcripts"

echo -e "${BLUE}🚀 UNKNOWN Brain Cloud Run Deployment${NC}"
echo -e "${BLUE}======================================${NC}"

# Check if PROJECT_ID is set
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}❌ Error: GOOGLE_CLOUD_PROJECT environment variable not set${NC}"
    echo -e "${YELLOW}💡 Run: export GOOGLE_CLOUD_PROJECT=your-project-id${NC}"
    exit 1
fi

echo -e "${BLUE}📋 Project: ${PROJECT_ID}${NC}"
echo -e "${BLUE}📍 Region: ${REGION}${NC}"
echo -e "${BLUE}🔧 Service: ${SERVICE_NAME}${NC}"

# Check if gcloud is installed and authenticated
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ Error: gcloud CLI not installed${NC}"
    echo -e "${YELLOW}💡 Install from: https://cloud.google.com/sdk/docs/install${NC}"
    exit 1
fi

# Set the project
echo -e "${BLUE}🔧 Setting project...${NC}"
gcloud config set project $PROJECT_ID

# Enable required APIs
echo -e "${BLUE}🔧 Enabling required APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    storage.googleapis.com \
    bigquery.googleapis.com \
    secretmanager.googleapis.com

# Create Cloud Storage bucket for transcripts
echo -e "${BLUE}📦 Creating Cloud Storage bucket...${NC}"
if ! gsutil ls gs://$BUCKET_NAME &> /dev/null; then
    gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://$BUCKET_NAME
    echo -e "${GREEN}✅ Created bucket: gs://$BUCKET_NAME${NC}"
else
    echo -e "${YELLOW}⚠️  Bucket already exists: gs://$BUCKET_NAME${NC}"
fi

# Create directories in bucket
echo -e "${BLUE}📁 Creating bucket structure...${NC}"
echo "" | gsutil cp - gs://$BUCKET_NAME/transcripts/.gitkeep
echo "" | gsutil cp - gs://$BUCKET_NAME/cache/.gitkeep
echo "" | gsutil cp - gs://$BUCKET_NAME/results/.gitkeep

# Create BigQuery dataset
echo -e "${BLUE}🏗️  Creating BigQuery dataset...${NC}"
if ! bq show --dataset $PROJECT_ID:unknown_brain &> /dev/null; then
    bq mk --dataset --location=$REGION $PROJECT_ID:unknown_brain
    echo -e "${GREEN}✅ Created BigQuery dataset: unknown_brain${NC}"
else
    echo -e "${YELLOW}⚠️  BigQuery dataset already exists${NC}"
fi

# Build and deploy using Cloud Build
echo -e "${BLUE}🔨 Building and deploying with Cloud Build...${NC}"
gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_REGION=$REGION,_SERVICE_NAME=$SERVICE_NAME

# Get the service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --region=$REGION \
    --format='value(status.url)')

echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
echo -e "${GREEN}🔗 Service URL: ${SERVICE_URL}${NC}"
echo -e "${GREEN}🏥 Health check: ${SERVICE_URL}/health${NC}"
echo -e "${GREEN}📖 API docs: ${SERVICE_URL}/docs${NC}"

echo ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo -e "${YELLOW}1. Set up environment variables in Cloud Run:${NC}"
echo -e "   gcloud run services update $SERVICE_NAME --region=$REGION \\"
echo -e "       --set-env-vars OPENAI_API_KEY=your-key-here,DEFAULT_LLM_MODEL=gpt-5-mini,GCS_BUCKET_NAME=$BUCKET_NAME"
echo ""
echo -e "${YELLOW}2. Test the API:${NC}"
echo -e "   curl ${SERVICE_URL}/health"
echo ""
echo -e "${YELLOW}3. Upload a test transcript to:${NC}"
echo -e "   gs://$BUCKET_NAME/transcripts/test.txt"
echo ""
echo -e "${YELLOW}4. Process via API:${NC}"
echo -e "   curl -X POST ${SERVICE_URL}/process-transcript \\"
echo -e "       -H 'Content-Type: application/json' \\"
echo -e "       -d '{\"bucket\":\"$BUCKET_NAME\", \"file_path\":\"transcripts/test.txt\"}'"

echo ""
echo -e "${GREEN}🎯 Deployment complete! Your UNKNOWN Brain API is live.${NC}"