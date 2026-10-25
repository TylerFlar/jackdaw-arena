<#
.SYNOPSIS
  Stores the GitHub OAuth App's client ID and secret in SSM Parameter Store, where the API reads
  them when it starts.

.DESCRIPTION
  Run it yourself, in your own terminal: the secret is typed here (hidden) and goes straight to
  AWS, never through a command line, a file you keep, Terraform state or anyone else's session.
  New API environments pick the values up; run a deploy to replace the running ones.

.EXAMPLE
  .\infra\scripts\set-secrets.ps1
  .\infra\scripts\set-secrets.ps1 -AwsProfile arena -Region us-west-2
#>
param(
    [string]$AwsProfile = $(if ($env:AWS_PROFILE) { $env:AWS_PROFILE } else { "arena" }),
    [string]$Region = "us-west-2",
    [string]$Path = "/arena/prod"
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw "The AWS CLI isn't on PATH."
}

$clientId = (Read-Host "GitHub OAuth App client ID").Trim()
$secure = Read-Host "GitHub OAuth App client secret (hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
# The CLI reads the request from this file, so the secret is never in a process's arguments.
$request = Join-Path ([IO.Path]::GetTempPath()) ("arena-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    $secret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim()
    if (-not $clientId -or -not $secret) {
        throw "Both the client ID and the secret are required."
    }
    $parameters = @(
        @{ Name = "$Path/github_client_id"; Type = "String"; Value = $clientId },
        @{ Name = "$Path/github_client_secret"; Type = "SecureString"; Value = $secret }
    )
    foreach ($p in $parameters) {
        $body = @{ Name = $p.Name; Type = $p.Type; Value = $p.Value; Overwrite = $true } | ConvertTo-Json -Compress
        [IO.File]::WriteAllText($request, $body) # UTF-8, no BOM
        aws ssm put-parameter --cli-input-json "file://$request" --profile $AwsProfile --region $Region --query Version --output text | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "aws ssm put-parameter failed for $($p.Name)"
        }
        Write-Host "stored $($p.Name) ($($p.Type))"
    }
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    Remove-Variable secret -ErrorAction SilentlyContinue
    if (Test-Path $request) {
        Remove-Item $request -Force
    }
}
Write-Host "Done. The next deploy (or any new API environment) signs in with GitHub using them."
