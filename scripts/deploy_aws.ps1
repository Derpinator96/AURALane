# Deploy the stack, create the four reader accounts, stage the simulated-ingest pool.
#
#   powershell -ExecutionPolicy Bypass -File scripts/deploy_aws.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/deploy_aws.ps1 -SkipDeploy     # users and pool only
#
# Run from the repository root with the venv's Python on PATH and AWS
# credentials for account 294488969610 (us-east-1). Nothing here stores or
# prints a password: each reader's password is typed at a hidden prompt and
# passed straight to Cognito. Press Enter at a prompt to leave that user as it is.
#
# NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
param(
    [string]$Stack = "Auralane",
    [switch]$SkipDeploy,
    [switch]$SkipPool,
    [string]$PoolTypes = "chest,brain,ct"
)
$ErrorActionPreference = "Stop"
$env:AWS_REGION = "us-east-1"

if (-not $SkipDeploy) {
    Write-Host "1/3 images and stack (brain and CT images first: SageMaker needs Docker v2 manifests)"
    Push-Location infra
    try {
        python push_images.py
        if ($LASTEXITCODE -ne 0) { throw "push_images.py failed" }
        npx cdk deploy $Stack --asset-parallelism=false --require-approval never
        if ($LASTEXITCODE -ne 0) { throw "cdk deploy failed" }
    } finally { Pop-Location }
}

Write-Host "2/3 reader accounts radiologist-1 to radiologist-4 (display names in models/readers.json)"
$pool = aws cloudformation describe-stacks --stack-name $Stack `
    --query "Stacks[0].Outputs[?Description=='AURALANE_COGNITO_POOL_ID'].OutputValue" --output text
if (-not $pool -or $pool -eq "None") { throw "no AURALANE_COGNITO_POOL_ID output on stack $Stack" }
foreach ($n in 1..4) {
    $user = "radiologist-$n"
    aws cognito-idp admin-get-user --user-pool-id $pool --username $user 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        aws cognito-idp admin-create-user --user-pool-id $pool --username $user `
            --message-action SUPPRESS | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "could not create $user" }
        Write-Host "  created $user"
    } else {
        Write-Host "  $user exists"
    }
    aws cognito-idp admin-add-user-to-group --user-pool-id $pool --username $user `
        --group-name radiologist
    $secure = Read-Host "  password for $user (Enter to keep the current one)" -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    if ($plain) {
        aws cognito-idp admin-set-user-password --user-pool-id $pool --username $user `
            --password $plain --permanent
        if ($LASTEXITCODE -ne 0) { throw "Cognito refused the password for $user (8+ chars, upper, lower, digit, symbol)" }
        Write-Host "  password set for $user"
    }
    $plain = $null
}

if (-not $SkipPool) {
    Write-Host "3/3 de-identify the local corpora here and upload them to pool/ (brain MR takes minutes each)"
    python scripts/stage_pool.py --stack $Stack --types $PoolTypes
    if ($LASTEXITCODE -ne 0) { throw "stage_pool.py failed" }
}

Write-Host "done. On Render (auralane-api), confirm AURALANE_CHEST_FUNCTION, AURALANE_BRAIN_ENDPOINT"
Write-Host "and AURALANE_CT_ENDPOINT are set to the stack outputs: simulated ingest needs them."
