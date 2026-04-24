# Phase 3 -- Service Bus + App Insights + Worker Container App
# Assumes Phase 2 resources already exist with SUFFIX=6254
# ResourceGroup = CMRG, Region = southeastasia
#
# Usage:
#   First-time deploy (builds + pushes worker image):
#       .\infra\deploy_phase3.ps1 -BuildWorkerImage
#
#   Subsequent runs (only creates/updates Azure resources, SKIPS image build):
#       .\infra\deploy_phase3.ps1
#
# NOTE: The worker Dockerfile bakes in the ONNX model (~400MB).
#       az acr build uploads the full build context each time, so only
#       use -BuildWorkerImage when worker code actually changed.

param (
    [switch]$BuildWorkerImage   # Pass this flag to rebuild + push the worker image
)

$ErrorActionPreference = "Stop"

# -- Fixed values matching Phase 2 deployment --------------------------------
$SUFFIX             = "6254"
$RG_NAME            = "CMRG"
$LOCATION           = "southeastasia"
$ACR_NAME           = "contentmodacr$SUFFIX"
$ACA_ENV            = "content-mod-env"
$API_APP_NAME       = "content-mod-api"
$WORKER_APP_NAME    = "content-mod-worker"
$REDIS_NAME         = "content-mod-redis-$SUFFIX"
$LOG_ANALYTICS_NAME = "content-mod-logs-$SUFFIX"
$APP_INSIGHTS_NAME  = "content-mod-insights-$SUFFIX"
$SB_NAMESPACE       = "content-mod-sb-$SUFFIX"
$SB_QUEUE           = "moderation-queue"

# -- Preflight ----------------------------------------------------------------
az account show 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Not logged in. Run 'az login' first." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host ">>> Phase 3 Deployment -- Content Moderation Pipeline <<<" -ForegroundColor Cyan
$StartTime = Get-Date

# -- STEP 1: Fetch existing Redis connection details -------------------------
Write-Host ""
Write-Host "[1/7] Fetching Redis connection details..." -ForegroundColor Green

$REDIS_HOST = az redis show `
    --resource-group $RG_NAME `
    --name $REDIS_NAME `
    --query hostName -o tsv

$REDIS_KEY = az redis list-keys `
    --resource-group $RG_NAME `
    --name $REDIS_NAME `
    --query primaryKey -o tsv

Write-Host "      Redis Host: $REDIS_HOST"

# -- STEP 2: App Insights (already created, just fetch conn string) ----------
Write-Host ""
Write-Host "[2/7] Fetching Application Insights connection string..." -ForegroundColor Green

# Use try/catch so a missing resource does not crash the script
$APP_INSIGHTS_CONN_STR = $null
try {
    $APP_INSIGHTS_CONN_STR = az monitor app-insights component show `
        --app $APP_INSIGHTS_NAME `
        --resource-group $RG_NAME `
        --query connectionString -o tsv 2>$null

    if ($LASTEXITCODE -ne 0 -or -not $APP_INSIGHTS_CONN_STR) {
        throw "App Insights not found"
    }
    Write-Host "      Already exists -- connection string retrieved."
} catch {
    Write-Host "      Not found. Creating..." -ForegroundColor Yellow
    az monitor app-insights component create `
        --resource-group $RG_NAME `
        --app $APP_INSIGHTS_NAME `
        --location $LOCATION `
        --workspace $LOG_ANALYTICS_NAME | Out-Null

    $APP_INSIGHTS_CONN_STR = az monitor app-insights component show `
        --app $APP_INSIGHTS_NAME `
        --resource-group $RG_NAME `
        --query connectionString -o tsv
    Write-Host "      Created and connection string retrieved."
}

# -- STEP 3: Service Bus Namespace + Queue -----------------------------------
Write-Host ""
Write-Host "[3/7] Ensuring Service Bus Namespace '$SB_NAMESPACE'..." -ForegroundColor Green

# Check existence without crashing on 404
$ErrorActionPreference = "Continue"
$sbCheck = az servicebus namespace show `
    --resource-group $RG_NAME `
    --name $SB_NAMESPACE `
    --query name -o tsv 2>$null
$ErrorActionPreference = "Stop"

if ($sbCheck -eq $SB_NAMESPACE) {
    Write-Host "      Namespace already exists, skipping."
} else {
    Write-Host "      Creating namespace..." -ForegroundColor Yellow
    az servicebus namespace create `
        --resource-group $RG_NAME `
        --name $SB_NAMESPACE `
        --location $LOCATION `
        --sku Standard | Out-Null
    Write-Host "      Namespace created."
}

$ErrorActionPreference = "Continue"
$qCheck = az servicebus queue show `
    --resource-group $RG_NAME `
    --namespace-name $SB_NAMESPACE `
    --name $SB_QUEUE `
    --query name -o tsv 2>$null
$ErrorActionPreference = "Stop"

if ($qCheck -eq $SB_QUEUE) {
    Write-Host "      Queue '$SB_QUEUE' already exists, skipping."
} else {
    az servicebus queue create `
        --resource-group $RG_NAME `
        --namespace-name $SB_NAMESPACE `
        --name $SB_QUEUE | Out-Null
    Write-Host "      Queue '$SB_QUEUE' created."
}

$SB_CONN_STR = az servicebus namespace authorization-rule keys list `
    --resource-group $RG_NAME `
    --namespace-name $SB_NAMESPACE `
    --name RootManageSharedAccessKey `
    --query primaryConnectionString -o tsv

Write-Host "      Service Bus connection string retrieved."

# -- STEP 4: Build & push worker image to ACR --------------------------------
Write-Host ""
if ($BuildWorkerImage) {
    Write-Host "[4/7] Building worker image via ACR build..." -ForegroundColor Green
    Write-Host "      NOTE: This uploads the full build context including the ONNX model (~400MB)." -ForegroundColor Yellow
    az acr build `
        --resource-group $RG_NAME `
        --registry $ACR_NAME `
        --image "${WORKER_APP_NAME}:latest" `
        --file api/Dockerfile.worker .
    Write-Host "      Worker image pushed successfully."
} else {
    Write-Host "[4/7] Skipping worker image build (pass -BuildWorkerImage to rebuild)." -ForegroundColor DarkGray
    # Verify the image exists in ACR so the container app creation won't fail
    $imgCheck = az acr repository show-tags `
        --name $ACR_NAME `
        --repository $WORKER_APP_NAME `
        --query "[?@ == 'latest']" -o tsv 2>$null
    if (-not $imgCheck) {
        Write-Host "      [WARN] No 'latest' tag found for '$WORKER_APP_NAME' in ACR." -ForegroundColor Yellow
        Write-Host "      Re-run with -BuildWorkerImage to build and push the image first." -ForegroundColor Yellow
    } else {
        Write-Host "      Image '$WORKER_APP_NAME:latest' found in ACR -- skipping build."
    }
}

# -- STEP 5: Update API Container App with new env vars ----------------------
Write-Host ""
Write-Host "[5/7] Updating API Container App '$API_APP_NAME'..." -ForegroundColor Green
az containerapp update `
    --name $API_APP_NAME `
    --resource-group $RG_NAME `
    --set-env-vars `
        "SERVICEBUS_CONNECTION_STRING=$SB_CONN_STR" `
        "SERVICEBUS_QUEUE_NAME=$SB_QUEUE" `
        "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN_STR" | Out-Null
Write-Host "      API app env vars updated."

# -- STEP 6: Create Worker Container App with KEDA ---------------------------
Write-Host ""
Write-Host "[6/7] Creating Worker Container App '$WORKER_APP_NAME'..." -ForegroundColor Green

$ACR_PASSWORD = az acr credential show `
    --name $ACR_NAME `
    --query passwords[0].value -o tsv

az containerapp create `
    --name $WORKER_APP_NAME `
    --resource-group $RG_NAME `
    --environment $ACA_ENV `
    --image "$ACR_NAME.azurecr.io/${WORKER_APP_NAME}:latest" `
    --registry-server "$ACR_NAME.azurecr.io" `
    --registry-username $ACR_NAME `
    --registry-password $ACR_PASSWORD `
    --min-replicas 0 `
    --max-replicas 20 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --secrets "servicebus-conn=$SB_CONN_STR" `
    --env-vars `
        "REDIS_HOST=$REDIS_HOST" `
        "REDIS_PORT=6380" `
        "REDIS_PASSWORD=$REDIS_KEY" `
        "REDIS_SSL=true" `
        "SERVICEBUS_CONNECTION_STRING=secretref:servicebus-conn" `
        "SERVICEBUS_QUEUE_NAME=$SB_QUEUE" `
        "APPLICATIONINSIGHTS_CONNECTION_STRING=$APP_INSIGHTS_CONN_STR" `
        "WORKER_MODE=true" `
    --scale-rule-name "queue-scaler" `
    --scale-rule-type "azure-servicebus" `
    --scale-rule-metadata "queueName=$SB_QUEUE" "messageCount=10" "namespace=$SB_NAMESPACE" `
    --scale-rule-auth "connection=servicebus-conn" | Out-Null

Write-Host "      Worker app created (KEDA: 0 to 20 replicas, 1 per 10 messages)."

# -- STEP 7: Summary ---------------------------------------------------------
Write-Host ""
Write-Host "[7/7] Fetching API URL..." -ForegroundColor Green
$APP_URL = az containerapp show `
    --resource-group $RG_NAME `
    --name $API_APP_NAME `
    --query properties.configuration.ingress.fqdn -o tsv

$Elapsed = [math]::Round(((Get-Date) - $StartTime).TotalSeconds)

Write-Host ""
Write-Host "OK  Phase 3 deployment completed in ${Elapsed}s." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  API URL        : https://$APP_URL" -ForegroundColor Cyan
Write-Host "  Service Bus NS : $SB_NAMESPACE" -ForegroundColor Cyan
Write-Host "  Queue          : $SB_QUEUE" -ForegroundColor Cyan
Write-Host "  Worker App     : $WORKER_APP_NAME (KEDA 0->20 replicas)" -ForegroundColor Cyan
Write-Host "  App Insights   : $APP_INSIGHTS_NAME" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
