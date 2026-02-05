#!/bin/bash
set -e

# Default values
ENVIRONMENT="dev"
PLATFORM="arm64"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -e|--environment)
      ENVIRONMENT="$2"
      shift 2
      ;;
    -p|--platform)
      PLATFORM="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [-e|--environment dev|prod] [-p|--platform arm64|amd64]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "=========================================="
echo "Deploying OpenAI API Convertor"
echo "Environment: $ENVIRONMENT"
echo "Platform: $PLATFORM"
echo "=========================================="

# Export environment variables
export CDK_PLATFORM=$PLATFORM

# Install dependencies
npm install

# Bootstrap (if needed)
npx cdk bootstrap

# Deploy all stacks
npx cdk deploy --all -c environment=$ENVIRONMENT --require-approval never

echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
