#!/bin/bash

echo "🚀 1. Provisioning AWS Infrastructure..."
terraform apply -auto-approve

echo "🏗️  2. Building the Angular App (with the newly injected IP)..."
cd frontend/dashboard-ui
ng build

echo "☁️  3. Uploading to AWS S3..."
aws s3 sync dist/dashboard-ui/browser s3://trading-bot-frontend-dashboard-12345

# Go back to the root directory where the Terraform files are
cd ../..

echo ""
echo "✅ Deployment Complete! Your bot is live."
echo "========================================================"
echo "🌐 Frontend URL: http://$(terraform output -raw frontend_website_url)"
echo "🔌 Backend API:  $(terraform output -raw backend_api_url)"
echo "========================================================"
