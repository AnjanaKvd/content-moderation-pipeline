param (
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$true)]
    [string]$Location
)

$ErrorActionPreference = "Stop"

# Ensure user is logged in
az account show 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ You are not logged in. Run 'az login' first." -ForegroundColor Red
    exit 1
}

# Generate unique suffix for global resources
$SUFFIX = Get-Random -Minimum 1000 -Maximum 9999

$ACR_NAME = "contentmodacr$SUFFIX"
$ACA_ENV = "content-mod-env"
$API_APP_NAME = "content-mod-api"
$REDIS_NAME = "content-mod-redis-$SUFFIX"
$APP_INSIGHTS_NAME = "content-mod-insights-$SUFFIX"
$LOG_ANALYTICS_NAME = "content-mod-logs-$SUFFIX"

Write-Host "Starting Deployment to Azure..." -ForegroundColor Cyan
$StartTime = Get-Date

# STEP 1: Create Resource Group
Write-Host "`n[1/11] Creating Resource Group '$ResourceGroupName'..." -ForegroundColor Green
az group create --name $ResourceGroupName --location $Location | Out-Null

# STEP 2: Create Azure Container Registry
Write-Host "`n[2/11] Creating ACR '$ACR_NAME'..." -ForegroundColor Green
az acr create --resource-group $ResourceGroupName --name $ACR_NAME --sku Basic --admin-enabled true | Out-Null

# STEP 3: Build and push Docker image
Write-Host "`n[3/11] Building & pushing Docker image..." -ForegroundColor Green
az acr login --name $ACR_NAME | Out-Null
docker build -f api/Dockerfile -t "$ACR_NAME.azurecr.io/$API_APP_NAME`:latest" .
docker push "$ACR_NAME.azurecr.io/$API_APP_NAME`:latest"

# STEP 4: Create Redis
Write-Host "`n[4/11] Creating Redis '$REDIS_NAME'..." -ForegroundColor Green

$redisCreate = az redis create `
    --resource-group $ResourceGroupName `
    --name $REDIS_NAME `
    --location $Location `
    --sku Basic `
    --vm-size C0 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Redis creation failed:" -ForegroundColor Red
    Write-Host $redisCreate
    exit 1
}

Write-Host "Waiting for Redis provisioning..." -NoNewline
$maxAttempts = 40
$attempt = 0

while ($attempt -lt $maxAttempts) {
    $state = az redis show `
        --resource-group $ResourceGroupName `
        --name $REDIS_NAME `
        --query provisioningState -o tsv 2>$null

    if ($state -eq "Succeeded") {
        Write-Host " Done!"
        break
    }

    Start-Sleep -Seconds 30
    Write-Host "." -NoNewline
    $attempt++
}

if ($attempt -eq $maxAttempts) {
    Write-Host "`n❌ Redis provisioning timed out." -ForegroundColor Red
    exit 1
}

# STEP 5: Get Redis details
Write-Host "`n[5/11] Getting Redis details..." -ForegroundColor Green
$REDIS_HOST = az redis show --resource-group $ResourceGroupName --name $REDIS_NAME --query hostName -o tsv
$REDIS_KEY = az redis list-keys --resource-group $ResourceGroupName --name $REDIS_NAME --query primaryKey -o tsv

# STEP 6: Log Analytics
Write-Host "`n[6/11] Creating Log Analytics..." -ForegroundColor Green
az monitor log-analytics workspace create `
    --resource-group $ResourceGroupName `
    --workspace-name $LOG_ANALYTICS_NAME | Out-Null

$LOG_WS_ID = az monitor log-analytics workspace show `
    --resource-group $ResourceGroupName `
    --workspace-name $LOG_ANALYTICS_NAME `
    --query customerId -o tsv

$LOG_WS_KEY = az monitor log-analytics workspace get-shared-keys `
    --resource-group $ResourceGroupName `
    --workspace-name $LOG_ANALYTICS_NAME `
    --query primarySharedKey -o tsv

# STEP 7: Application Insights
Write-Host "`n[7/11] Creating App Insights..." -ForegroundColor Green
az monitor app-insights component create `
    --resource-group $ResourceGroupName `
    --app $APP_INSIGHTS_NAME `
    --location $Location `
    --workspace $LOG_ANALYTICS_NAME | Out-Null

# STEP 8: Container Apps Environment
Write-Host "`n[8/11] Creating Container Apps Environment..." -ForegroundColor Green
az containerapp env create `
    --name $ACA_ENV `
    --resource-group $ResourceGroupName `
    --location $Location `
    --logs-workspace-id $LOG_WS_ID `
    --logs-workspace-key $LOG_WS_KEY | Out-Null

# STEP 9: Get ACR credentials
Write-Host "`n[9/11] Getting ACR credentials..." -ForegroundColor Green
$ACR_PASSWORD = az acr credential show --name $ACR_NAME --query passwords[0].value -o tsv

# STEP 10: Create Container App
Write-Host "`n[10/11] Creating Container App..." -ForegroundColor Green
az containerapp create `
    --name $API_APP_NAME `
    --resource-group $ResourceGroupName `
    --environment $ACA_ENV `
    --image "$ACR_NAME.azurecr.io/$API_APP_NAME`:latest" `
    --registry-server "$ACR_NAME.azurecr.io" `
    --registry-username $ACR_NAME `
    --registry-password $ACR_PASSWORD `
    --ingress external `
    --target-port 8000 `
    --min-replicas 0 `
    --max-replicas 10 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --env-vars `
        "REDIS_HOST=$REDIS_HOST" `
        "REDIS_PORT=6380" `
        "REDIS_PASSWORD=$REDIS_KEY" `
        "REDIS_SSL=true" `
        "ENVIRONMENT=production" | Out-Null

# STEP 11: Get App URL
Write-Host "`n[11/11] Getting App URL..." -ForegroundColor Green
$APP_URL = az containerapp show `
    --resource-group $ResourceGroupName `
    --name $API_APP_NAME `
    --query properties.configuration.ingress.fqdn -o tsv

$ElapsedTime = (Get-Date) - $StartTime

Write-Host "`n✅ Deployment completed in $($ElapsedTime.TotalSeconds) seconds." -ForegroundColor Green
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "API URL: https://$APP_URL" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan