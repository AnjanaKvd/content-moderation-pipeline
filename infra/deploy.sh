#!/bin/bash
# Enterprise Content Moderation Pipeline — Azure Deployment Script
# Usage: ./infra/deploy.sh <resource-group-name> <location>
# Example: ./infra/deploy.sh content-mod-rg eastus

set -euo pipefail

# Check arguments
if [ "$#" -ne 2 ]; then
    echo -e "\033[31mError: Missing required arguments.\033[0m"
    echo "Usage: $0 <resource-group-name> <location>"
    exit 1
fi

RG_NAME=$1
LOCATION=$2
ACR_NAME="contentmodacr$RANDOM"
ACA_ENV="content-mod-env"
API_APP_NAME="content-mod-api"
REDIS_NAME="content-mod-redis"
APP_INSIGHTS_NAME="content-mod-insights"
LOG_ANALYTICS_NAME="content-mod-logs"

echo -e "\033[36mStarting Deployment to Azure...\033[0m"
START_TIME=$SECONDS

# STEP 1: Create Resource Group
echo -e "\n\033[32m[1/11] Creating Resource Group '$RG_NAME' in '$LOCATION'...\033[0m"
az group create --name "$RG_NAME" --location "$LOCATION" -o none

# STEP 2: Create Azure Container Registry
echo -e "\n\033[32m[2/11] Creating Azure Container Registry '$ACR_NAME'...\033[0m"
az acr create --resource-group "$RG_NAME" --name "$ACR_NAME" --sku Basic --admin-enabled true -o none

# STEP 3: Build and push Docker image to ACR
echo -e "\n\033[32m[3/11] Building and pushing Docker image to ACR...\033[0m"
az acr build --resource-group "$RG_NAME" --registry "$ACR_NAME" --image "$API_APP_NAME:latest" --file api/Dockerfile ./

# STEP 4: Create Azure Cache for Redis (Basic C0)
echo -e "\n\033[32m[4/11] Creating Azure Cache for Redis '$REDIS_NAME' (This may take ~15 minutes)...\033[0m"
az redis create --resource-group "$RG_NAME" --name "$REDIS_NAME" --location "$LOCATION" --sku Basic --vm-size C0 -o none

echo "Waiting for Redis to finish provisioning..."
while [ "$(az redis show --resource-group "$RG_NAME" --name "$REDIS_NAME" --query provisioningState -o tsv)" != "Succeeded" ]; do
    sleep 30
    echo -n "."
done
echo " Done!"

# STEP 5: Get Redis connection details
echo -e "\n\033[32m[5/11] Retrieving Redis connection details...\033[0m"
REDIS_HOST=$(az redis show --resource-group "$RG_NAME" --name "$REDIS_NAME" --query hostName -o tsv)
REDIS_KEY=$(az redis list-keys --resource-group "$RG_NAME" --name "$REDIS_NAME" --query primaryKey -o tsv)

# STEP 6: Create Log Analytics Workspace
echo -e "\n\033[32m[6/11] Creating Log Analytics Workspace '$LOG_ANALYTICS_NAME'...\033[0m"
az monitor log-analytics workspace create --resource-group "$RG_NAME" --workspace-name "$LOG_ANALYTICS_NAME" -o none
LOG_WS_ID=$(az monitor log-analytics workspace show --resource-group "$RG_NAME" --workspace-name "$LOG_ANALYTICS_NAME" --query customerId -o tsv)
LOG_WS_KEY=$(az monitor log-analytics workspace get-shared-keys --resource-group "$RG_NAME" --workspace-name "$LOG_ANALYTICS_NAME" --query primarySharedKey -o tsv)

# STEP 7: Create Application Insights
echo -e "\n\033[32m[7/11] Creating Application Insights '$APP_INSIGHTS_NAME'...\033[0m"
az monitor app-insights component create --resource-group "$RG_NAME" --app "$APP_INSIGHTS_NAME" --location "$LOCATION" --workspace "$LOG_ANALYTICS_NAME" -o none

# STEP 8: Create Container Apps Environment
echo -e "\n\033[32m[8/11] Creating Container Apps Environment '$ACA_ENV'...\033[0m"
az containerapp env create \
    --name "$ACA_ENV" \
    --resource-group "$RG_NAME" \
    --location "$LOCATION" \
    --logs-workspace-id "$LOG_WS_ID" \
    --logs-workspace-key "$LOG_WS_KEY" \
    -o none

# STEP 9: Get ACR credentials
echo -e "\n\033[32m[9/11] Retrieving ACR credentials...\033[0m"
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query passwords[0].value -o tsv)

# STEP 10: Create Container App
echo -e "\n\033[32m[10/11] Creating Container App '$API_APP_NAME'...\033[0m"
az containerapp create \
    --name "$API_APP_NAME" \
    --resource-group "$RG_NAME" \
    --environment "$ACA_ENV" \
    --image "$ACR_NAME.azurecr.io/$API_APP_NAME:latest" \
    --registry-server "$ACR_NAME.azurecr.io" \
    --registry-username "$ACR_NAME" \
    --registry-password "$ACR_PASSWORD" \
    --ingress external \
    --target-port 8000 \
    --min-replicas 0 \
    --max-replicas 10 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --env-vars \
        REDIS_HOST="$REDIS_HOST" \
        REDIS_PORT=6380 \
        REDIS_PASSWORD="$REDIS_KEY" \
        REDIS_SSL=true \
        ENVIRONMENT=production \
    -o none

# STEP 11: Print the public URL
echo -e "\n\033[32m[11/11] Retrieving App URL...\033[0m"
APP_URL=$(az containerapp show --resource-group "$RG_NAME" --name "$API_APP_NAME" --query properties.configuration.ingress.fqdn -o tsv)

ELAPSED_TIME=$(($SECONDS - $START_TIME))
echo -e "\n\033[32mSuccessfully completed deployment in $ELAPSED_TIME seconds.\033[0m"
echo -e "\033[36m========================================================================\033[0m"
echo -e "\033[36mAPI URL: https://$APP_URL\033[0m"
echo -e "\033[36m========================================================================\033[0m"
