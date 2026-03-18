#!/bin/bash
set -e

# Deploy OpenAI API Proxy to AWS via CDK
# Usage: ./scripts/deploy.sh [OPTIONS]
#
# Examples:
#   ./scripts/deploy.sh                          # Deploy all stacks (prod, arm64, current region)
#   ./scripts/deploy.sh -e dev -r us-west-2      # Deploy dev environment
#   ./scripts/deploy.sh -s ecs                    # Deploy only ECS stack (quick update)
#   ./scripts/deploy.sh -p amd64                  # Deploy with x86_64 platform

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ENVIRONMENT="prod"
REGION="${AWS_REGION:-us-west-2}"
PLATFORM="${CDK_PLATFORM:-arm64}"
STACK="all"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Deploy OpenAI API Proxy stacks via CDK

OPTIONS:
    -e, --environment ENV    Environment (dev|prod) [default: prod]
    -r, --region REGION      AWS region [default: \$AWS_REGION or us-west-2]
    -p, --platform PLATFORM  Platform (arm64|amd64) [default: arm64]
    -s, --stack STACK        Stack to deploy: all|ecs|cognito [default: all]
    -h, --help               Show this help message

EXAMPLES:
    $0                                  # First-time: deploy all stacks
    $0 -s ecs                           # Quick update: redeploy ECS only
    $0 -e dev -r us-west-2              # Deploy dev environment
    $0 -e prod -r ap-northeast-1 -p arm64

NOTES:
    - First-time deployment must use '-s all' (default) to create all stacks
    - Subsequent code updates can use '-s ecs' for faster deployment
    - Run from the project root directory (not cdk/)

EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment) ENVIRONMENT="$2"; shift 2 ;;
        -r|--region) REGION="$2"; shift 2 ;;
        -p|--platform) PLATFORM="$2"; shift 2 ;;
        -s|--stack) STACK="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; usage ;;
    esac
done

if [[ ! "$ENVIRONMENT" =~ ^(dev|prod)$ ]]; then
    echo -e "${RED}Error: Environment must be 'dev' or 'prod'${NC}"
    exit 1
fi

if [[ ! "$PLATFORM" =~ ^(arm64|amd64)$ ]]; then
    echo -e "${RED}Error: Platform must be 'arm64' or 'amd64'${NC}"
    exit 1
fi

if [[ ! "$STACK" =~ ^(all|ecs|cognito)$ ]]; then
    echo -e "${RED}Error: Stack must be 'all', 'ecs', or 'cognito'${NC}"
    exit 1
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}OpenAI API Proxy - CDK Deploy${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Environment: ${YELLOW}${ENVIRONMENT}${NC}"
echo -e "Region:      ${YELLOW}${REGION}${NC}"
echo -e "Platform:    ${YELLOW}${PLATFORM}${NC}"
echo -e "Stack:       ${YELLOW}${STACK}${NC}"
echo -e "${GREEN}========================================${NC}"
echo

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured properly.${NC}"
    exit 1
fi

# Check Docker
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker is not running. CDK needs Docker to build container images.${NC}"
    exit 1
fi

export AWS_REGION="$REGION"
export CDK_PLATFORM="$PLATFORM"

# Navigate to cdk directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$(dirname "$SCRIPT_DIR")/cdk"

if [[ ! -d "$CDK_DIR" ]]; then
    echo -e "${RED}Error: CDK directory not found at $CDK_DIR${NC}"
    exit 1
fi

cd "$CDK_DIR"

# Install dependencies if needed
if [[ ! -d "node_modules" ]]; then
    echo -e "${YELLOW}Installing CDK dependencies...${NC}"
    npm install
fi

case "$STACK" in
    all)
        echo -e "${YELLOW}Deploying all stacks (Network → DynamoDB → Cognito → ECS)...${NC}"
        npx cdk deploy --all -c environment="$ENVIRONMENT" --require-approval never
        ;;
    cognito)
        echo -e "${YELLOW}Deploying Cognito stack...${NC}"
        npx cdk deploy "OpenAIProxy-Cognito-${ENVIRONMENT}" -c environment="$ENVIRONMENT" --exclusively --require-approval never
        ;;
    ecs)
        # Check if Cognito stack exists (required dependency)
        COGNITO_STACK="OpenAIProxy-Cognito-${ENVIRONMENT}"
        if ! aws cloudformation describe-stacks --stack-name "$COGNITO_STACK" --region "$REGION" &> /dev/null; then
            echo -e "${YELLOW}Cognito stack not found. Deploying Cognito first...${NC}"
            npx cdk deploy "$COGNITO_STACK" -c environment="$ENVIRONMENT" --exclusively --require-approval never
            echo
        fi
        echo -e "${YELLOW}Deploying ECS stack...${NC}"
        npx cdk deploy "OpenAIProxy-ECS-${ENVIRONMENT}" -c environment="$ENVIRONMENT" --exclusively --require-approval never
        ;;
esac

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"

# Show outputs
ALB_DNS=$(aws cloudformation describe-stacks \
    --stack-name "OpenAIProxy-ECS-${ENVIRONMENT}" \
    --region "$REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`ALBDNSName`].OutputValue' \
    --output text 2>/dev/null || echo "N/A")

if [[ "$ALB_DNS" != "N/A" && -n "$ALB_DNS" ]]; then
    echo -e "API Endpoint:  ${YELLOW}http://${ALB_DNS}${NC}"
    echo -e "Admin Portal:  ${YELLOW}http://${ALB_DNS}/admin/${NC}"
fi

echo
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Get Master API Key: aws secretsmanager get-secret-value --secret-id openai-proxy-${ENVIRONMENT}-master-api-key --query 'SecretString' --output text | jq -r '.password'"
echo -e "  2. Create admin user:  ./scripts/create-admin-user.sh -e ${ENVIRONMENT} -r ${REGION} --email <admin@example.com>"
echo -e "${GREEN}========================================${NC}"
