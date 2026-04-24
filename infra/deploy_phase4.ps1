# infra/deploy_phase4.ps1
# Deploys the Streamlit UI to Azure Container Apps

param (
    [switch]$BuildImage
)

$ErrorActionPreference = "Stop"

# These should match what you used in Phase 2/3
$RG_NAME = "CMRG"
$LOCATION = "southeastasia" # Update if your region is different
$ACR_NAME = "contentmodacr6254" # Ensure this matches your actual ACR name
$ACA_ENV = "content-mod-env"
$UI_APP_NAME = "content-mod-ui"

Write-Host "Fetching API URL..." -ForegroundColor Cyan
$API_URL = az containerapp show --resource-group $RG_NAME --name content-mod-api --query properties.configuration.ingress.fqdn -o tsv

Write-Host "Starting Phase 4 Deployment (Streamlit UI)..." -ForegroundColor Cyan

if ($BuildImage) {
    Write-Host "Building and pushing UI image to ACR..." -ForegroundColor Yellow
    az acr build --image ${UI_APP_NAME}:latest --registry $ACR_NAME --file ui/Dockerfile .
} else {
    Write-Host "Skipping image build (use -BuildImage to force build)." -ForegroundColor Yellow
}

Write-Host "Creating Container App for UI..." -ForegroundColor Yellow
az containerapp create `
  --name $UI_APP_NAME `
  --resource-group $RG_NAME `
  --environment $ACA_ENV `
  --image "$ACR_NAME.azurecr.io/${UI_APP_NAME}:latest" `
  --env-vars "API_URL=https://$API_URL" `
  --registry-server "$ACR_NAME.azurecr.io" `
  --ingress external `
  --target-port 8501 `
  --min-replicas 0 `
  --max-replicas 2 `
  --cpu 0.5 --memory 1.0Gi

$uiUrl = az containerapp show --name $UI_APP_NAME --resource-group $RG_NAME --query "properties.configuration.ingress.fqdn" -o tsv

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "SUCCESS! Phase 4 Complete." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "Live UI URL: https://$uiUrl" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Green