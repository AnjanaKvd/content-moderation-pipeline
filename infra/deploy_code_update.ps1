# deploy_code_update.ps1
# Pushes code changes (Dockerfile updates) to Azure without re-creating infra

param (
    [switch]$BuildApiImage,      # Rebuild API image
    [switch]$BuildWorkerImage    # Rebuild Worker image
)

$ErrorActionPreference = "Stop"

# -- Fixed values matching existing deployment --------------------------------
$SUFFIX          = "6254"
$RG_NAME         = "CMRG"
$LOCATION        = "southeastasia"
$ACR_NAME        = "contentmodacr$SUFFIX"
$API_APP_NAME    = "content-mod-api"
$WORKER_APP_NAME = "content-mod-worker"

# -- Preflight ----------------------------------------------------------------
az account show 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Not logged in. Run 'az login' first." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host ">>> Deploy Code Update -- Content Moderation Pipeline <<<" -ForegroundColor Cyan
$StartTime = Get-Date

# -- STEP 1: Build & push API image to ACR -----------------------------------
if ($BuildApiImage) {
    Write-Host ""
    Write-Host "[1/6] Building API image via ACR build..." -ForegroundColor Green
    az acr build `
        --resource-group $RG_NAME `
        --registry $ACR_NAME `
        --image "${API_APP_NAME}:latest" `
        --file api/Dockerfile .
    Write-Host "      API image pushed successfully."
} else {
    Write-Host ""
    Write-Host "[1/6] Skipping API image build (pass -BuildApiImage to rebuild)." -ForegroundColor DarkGray
}

# -- STEP 2: Build & push Worker image to ACR --------------------------------
if ($BuildWorkerImage) {
    Write-Host ""
    Write-Host "[2/6] Building Worker image via ACR build..." -ForegroundColor Green
    az acr build `
        --resource-group $RG_NAME `
        --registry $ACR_NAME `
        --image "${WORKER_APP_NAME}:latest" `
        --file api/Dockerfile.worker .
    Write-Host "      Worker image pushed successfully."
} else {
    Write-Host ""
    Write-Host "[2/6] Skipping Worker image build (pass -BuildWorkerImage to rebuild)." -ForegroundColor DarkGray
}

# -- STEP 3: Get ACR credentials ----------------------------------------------
Write-Host ""
Write-Host "[3/6] Retrieving ACR credentials..." -ForegroundColor Green
$ACR_PASSWORD = az acr credential show `
    --name $ACR_NAME `
    --query passwords[0].value -o tsv

# -- STEP 4: Update API Container App image -----------------------------------
Write-Host ""
Write-Host "[4/6] Updating API Container App '$API_APP_NAME'..." -ForegroundColor Green
az containerapp update `
    --name $API_APP_NAME `
    --resource-group $RG_NAME `
    --image "$ACR_NAME.azurecr.io/${API_APP_NAME}:latest" | Out-Null
Write-Host "      API app updated."

# -- STEP 5: Update Worker Container App image --------------------------------
Write-Host ""
Write-Host "[5/6] Updating Worker Container App '$WORKER_APP_NAME'..." -ForegroundColor Green
az containerapp update `
    --name $WORKER_APP_NAME `
    --resource-group $RG_NAME `
    --image "$ACR_NAME.azurecr.io/${API_APP_NAME}:latest" | Out-Null
Write-Host "      Worker app updated."

# -- STEP 6: Print updated URLs -----------------------------------------------
Write-Host ""
Write-Host "[6/6] Fetching updated app URLs..." -ForegroundColor Green
$API_URL = az containerapp show `
    --name $API_APP_NAME `
    --resource-group $RG_NAME `
    --query properties.configuration.ingress.fqdn -o tsv

$Elapsed = [math]::Round(((Get-Date) - $StartTime).TotalSeconds)

Write-Host ""
Write-Host "OK  Code update deployed in ${Elapsed}s." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  API URL        : https://$API_URL" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Usage examples:" -ForegroundColor Yellow
Write-Host "  Rebuild both       : .\infra\deploy_code_update.ps1 -BuildApiImage -BuildWorkerImage"
Write-Host "  Rebuild API only   : .\infra\deploy_code_update.ps1 -BuildApiImage"
Write-Host "  Rebuild Worker only: .\infra\deploy_code_update.ps1 -BuildWorkerImage"
Write-Host "  Rolling restart    : .\infra\deploy_code_update.ps1"
Write-Host ""
