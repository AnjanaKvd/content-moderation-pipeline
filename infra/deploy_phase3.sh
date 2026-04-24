#!/bin/bash
# Phase 3 — Service Bus + App Insights + Worker Container App
# Assumes Phase 2 resources already exist with SUFFIX=6254
# ResourceGroup = CMRG, Region = southeastasia
#
# Usage: bash infra/deploy_phase3.sh
# Run from the root of the repository.

set -euo pipefail

# ── Fixed values matching Phase 2 deployment ────────────────────────────────
SUFFIX="6254"
RG_NAME="CMRG"
LOCATION="southeastasia"
ACR_NAME="contentmodacr${SUFFIX}"
ACA_ENV="content-mod-env"
API_APP_NAME="content-mod-api"
WORKER_APP_NAME="content-mod-worker"
REDIS_NAME="content-mod-redis-${SUFFIX}"
LOG_ANALYTICS_NAME="content-mod-logs-${SUFFIX}"
APP_INSIGHTS_NAME="content-mod-insights-${SUFFIX}"
SB_NAMESPACE="content-mod-sb-${SUFFIX}"
SB_QUEUE="moderation-queue"

# ── Preflight ────────────────────────────────────────────────────────────────
az account show -o none 2>/dev/null || { echo "❌ Not logged in. Run 'az login' first."; exit 1; }

echo -e "\n\033[36m🚀 Phase 3 Deployment — Content Moderation Pipeline\033[0m"
START_TIME=$SECONDS

# ── STEP 1: Fetch existing Redis connection details ──────────────────────────
echo -e "\n\033[32m[1/7] Fetching Redis connection details...\033[0m"
REDIS_HOST=$(az redis show --resource-group "$RG_NAME" --name "$REDIS_NAME" --query hostName -o tsv)
REDIS_KEY=$(az redis list-keys --resource-group "$RG_NAME" --name "$REDIS_NAME" --query primaryKey -o tsv)
echo "  Redis Host: $REDIS_HOST"

# ── STEP 2: Create Application Insights ─────────────────────────────────────
echo -e "\n\033[32m[2/7] Creating Application Insights '$APP_INSIGHTS_NAME'...\033[0m"
EXISTING_AI=$(az monitor app-insights component show --app "$APP_INSIGHTS_NAME" --resource-group "$RG_NAME" --query name -o tsv 2>/dev/null || echo "")
if [ "$EXISTING_AI" = "$APP_INSIGHTS_NAME" ]; then
    echo "  Already exists, skipping creation."
else
    az monitor app-insights component create \
        --resource-group "$RG_NAME" \
        --app "$APP_INSIGHTS_NAME" \
        --location "$LOCATION" \
        --workspace "$LOG_ANALYTICS_NAME" \
        -o none
    echo "  Created."
fi

APP_INSIGHTS_CONN_STR=$(az monitor app-insights component show \
    --app "$APP_INSIGHTS_NAME" \
    --resource-group "$RG_NAME" \
    --query connectionString -o tsv)
echo "  Connection string retrieved."

# ── STEP 3: Create Service Bus Namespace + Queue ─────────────────────────────
echo -e "\n\033[32m[3/7] Creating Service Bus Namespace '$SB_NAMESPACE'...\033[0m"
EXISTING_SB=$(az servicebus namespace show --resource-group "$RG_NAME" --name "$SB_NAMESPACE" --query name -o tsv 2>/dev/null || echo "")
if [ "$EXISTING_SB" = "$SB_NAMESPACE" ]; then
    echo "  Namespace already exists, skipping creation."
else
    az servicebus namespace create \
        --resource-group "$RG_NAME" \
        --name "$SB_NAMESPACE" \
        --location "$LOCATION" \
        --sku Standard \
        -o none
    echo "  Namespace created."
fi

EXISTING_Q=$(az servicebus queue show --resource-group "$RG_NAME" --namespace-name "$SB_NAMESPACE" --name "$SB_QUEUE" --query name -o tsv 2>/dev/null || echo "")
if [ "$EXISTING_Q" = "$SB_QUEUE" ]; then
    echo "  Queue '$SB_QUEUE' already exists, skipping."
else
    az servicebus queue create \
        --resource-group "$RG_NAME" \
        --namespace-name "$SB_NAMESPACE" \
        --name "$SB_QUEUE" \
        -o none
    echo "  Queue '$SB_QUEUE' created."
fi

SB_CONN_STR=$(az servicebus namespace authorization-rule keys list \
    --resource-group "$RG_NAME" \
    --namespace-name "$SB_NAMESPACE" \
    --name RootManageSharedAccessKey \
    --query primaryConnectionString -o tsv)
echo "  Connection string retrieved."

# ── STEP 4: Build & push worker image to ACR ────────────────────────────────
echo -e "\n\033[32m[4/7] Building & pushing Worker image to ACR '$ACR_NAME'...\033[0m"
az acr build \
    --resource-group "$RG_NAME" \
    --registry "$ACR_NAME" \
    --image "${WORKER_APP_NAME}:latest" \
    --file api/Dockerfile.worker .
echo "  Worker image pushed successfully."

# ── STEP 5: Update existing API Container App with new env vars ──────────────
echo -e "\n\033[32m[5/7] Updating API Container App '$API_APP_NAME' with Service Bus + App Insights env vars...\033[0m"
az containerapp update \
    --name "$API_APP_NAME" \
    --resource-group "$RG_NAME" \
    --set-env-vars \
        "SERVICEBUS_CONNECTION_STRING=$SB_CONN_STR" \
        "SERVICEBUS_QUEUE_NAME=$SB_QUEUE" \
        "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN_STR" \
    -o none
echo "  API app updated."

# ── STEP 6: Create Worker Container App with KEDA autoscaling ───────────────
echo -e "\n\033[32m[6/7] Creating Worker Container App '$WORKER_APP_NAME'...\033[0m"
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query passwords[0].value -o tsv)

az containerapp create \
    --name "$WORKER_APP_NAME" \
    --resource-group "$RG_NAME" \
    --environment "$ACA_ENV" \
    --image "$ACR_NAME.azurecr.io/${WORKER_APP_NAME}:latest" \
    --registry-server "$ACR_NAME.azurecr.io" \
    --registry-username "$ACR_NAME" \
    --registry-password "$ACR_PASSWORD" \
    --min-replicas 0 \
    --max-replicas 20 \
    --cpu 1.0 \
    --memory 2.0Gi \
    --secrets "servicebus-conn=$SB_CONN_STR" \
    --env-vars \
        "REDIS_HOST=$REDIS_HOST" \
        "REDIS_PORT=6380" \
        "REDIS_PASSWORD=$REDIS_KEY" \
        "REDIS_SSL=true" \
        "SERVICEBUS_CONNECTION_STRING=secretref:servicebus-conn" \
        "SERVICEBUS_QUEUE_NAME=$SB_QUEUE" \
        "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN_STR" \
        "WORKER_MODE=true" \
    --scale-rule-name "queue-scaler" \
    --scale-rule-type "azure-servicebus" \
    --scale-rule-metadata "queueName=$SB_QUEUE" "messageCount=10" "namespace=$SB_NAMESPACE" \
    --scale-rule-auth "connection=servicebus-conn" \
    -o none
echo "  Worker app created with KEDA scaler (0-20 replicas, 1 replica per 10 messages)."

# ── STEP 7: Print summary ────────────────────────────────────────────────────
echo -e "\n\033[32m[7/7] Fetching API URL...\033[0m"
APP_URL=$(az containerapp show --resource-group "$RG_NAME" --name "$API_APP_NAME" --query properties.configuration.ingress.fqdn -o tsv)

ELAPSED=$((SECONDS - START_TIME))
echo -e "\n\033[32m✅ Phase 3 deployment completed in ${ELAPSED}s.\033[0m"
echo -e "\033[36m═══════════════════════════════════════════════════════\033[0m"
echo -e "\033[36m  API URL         : https://$APP_URL\033[0m"
echo -e "\033[36m  Service Bus NS  : $SB_NAMESPACE\033[0m"
echo -e "\033[36m  Queue           : $SB_QUEUE\033[0m"
echo -e "\033[36m  Worker App      : $WORKER_APP_NAME (scales 0→20 via KEDA)\033[0m"
echo -e "\033[36m  App Insights    : $APP_INSIGHTS_NAME\033[0m"
echo -e "\033[36m═══════════════════════════════════════════════════════\033[0m"
