# Requires: ListenAI Gateway at http://localhost:8000
# Run from repo root: .\scripts\benchmark_dashboard.ps1
#
# Default: includeKeywords = empty array => Stat matches ALL posts in date range (same as homework wide query).
# For keyword "機器人":  .\scripts\benchmark_dashboard.ps1 -IncludeKeywords '機器人'

param(
    [string]$GatewayUrl = 'http://localhost:8000',
    [string]$Username = 'admin',
    [string]$Password = 'admin123',
    # Empty = no keyword filter (Stat: match every post in date window). Single string OK; becomes one-element array.
    [AllowEmptyCollection()]
    [string[]]$IncludeKeywords = @(),
    [AllowEmptyCollection()]
    [string[]]$ExcludeKeywords = @(),
    [string]$FromDate = '2000-01-01',
    [string]$ToDate = '2030-12-31',
    [int]$SampleSize = 5,
    [int]$Warmup = 0
)

$ErrorActionPreference = 'Stop'

# Allow -IncludeKeywords '機器人' (single string) -> wrap as array
if ($IncludeKeywords -is [string]) {
    $IncludeKeywords = @($IncludeKeywords)
}

function Get-AuthToken {
    param([string]$BaseUrl, [string]$User, [string]$Pass)
    $loginBody = @{ username = $User; password = $Pass } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri ($BaseUrl + '/auth/login') -Method Post -ContentType 'application/json' -Body $loginBody
    return $resp.token
}

$token = Get-AuthToken -BaseUrl $GatewayUrl -User $Username -Pass $Password
$headers = @{ Authorization = ('Bearer ' + $token) }

$payload = @{
    includeKeywords = @($IncludeKeywords)
    excludeKeywords = @($ExcludeKeywords)
    fromDate        = $FromDate
    toDate          = $ToDate
    sampleSize      = $SampleSize
} | ConvertTo-Json

for ($i = 0; $i -lt $Warmup; $i++) {
    $null = Invoke-RestMethod -Uri ($GatewayUrl + '/api/dashboard') -Method Post -Headers $headers -ContentType 'application/json' -Body $payload
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$data = Invoke-RestMethod -Uri ($GatewayUrl + '/api/dashboard') -Method Post -Headers $headers -ContentType 'application/json' -Body $payload
$sw.Stop()

$elapsed = [Math]::Round($sw.Elapsed.TotalSeconds, 4)

$nlpCalls = if ($null -eq $data.nlpCalls) { 0 } else { [int]$data.nlpCalls }
$cached = if ($null -eq $data.cachedSentiments) { 0 } else { [int]$data.cachedSentiments }

$result = [ordered]@{
    gateway            = $GatewayUrl
    elapsed_sec        = $elapsed
    mentionCount       = $data.mentionCount
    totalAnalyzedPosts = $data.totalAnalyzedPosts
    nlpCalls           = $nlpCalls
    cachedSentiments   = $cached
}

$result | Format-List

Write-Host ''
Write-Host '========================================'
Write-Host ('End-to-end latency: ' + [string]$elapsed + ' sec')
Write-Host '========================================'
Write-Host ''
Write-Host ('nlpCalls          = ' + [string]$nlpCalls)
Write-Host ('cachedSentiments  = ' + [string]$cached)
Write-Host ('mentionCount      = ' + [string]$data.mentionCount)
Write-Host ''

if (-not $data.mentionCount -or [int]$data.mentionCount -eq 0) {
    Write-Host 'WARNING: mentionCount is 0. No posts matched filters.' -ForegroundColor Yellow
    Write-Host 'Fix: use empty keywords (default), widen dates, or point Gateway/Stat at the DB that has data.' -ForegroundColor Yellow
    Write-Host 'Example keyword run: .\scripts\benchmark_dashboard.ps1 -IncludeKeywords ''機器人''' -ForegroundColor Yellow
    Write-Host ''
}

Write-Host 'Fill LaTeX column (seconds only):'
Write-Host ('  ' + [string]$elapsed)
Write-Host ''
$rowHint = -join @(
    'LaTeX row hint: ',
    [string]$elapsed,
    ' sec | nlpCalls=',
    [string]$nlpCalls,
    ' | cached=',
    [string]$cached
)
Write-Host $rowHint
