param(
    [string]$ProjectRoot = ".",
    [int]$IntervalSeconds = 15,
    [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $Source = Join-Path $ProjectRoot "data\outputs\archive\current_stable_official_en"
} else {
    $Source = (Resolve-Path $SourceDir).Path
}

$Official = Join-Path $ProjectRoot "ChinaTravel\results\TPCAgent_TPCLLM_en"
$Mirror = Join-Path $ProjectRoot "data\outputs\results\TPCAgent_TPCLLM_en"
$LogDir = Join-Path $ProjectRoot "data\outputs\archive"
$LogPath = Join-Path $LogDir "official_results_watchdog.log"

New-Item -ItemType Directory -Force -Path $Official, $Mirror, $LogDir | Out-Null
if (-not (Test-Path $Source)) {
    throw "Stable source directory not found: $Source"
}

function Write-WatchLog([string]$Message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$stamp] $Message"
}

function Get-HashMap([string]$Dir) {
    $map = @{}
    Get-ChildItem -Path $Dir -Filter "*.json" -File | ForEach-Object {
        $map[$_.Name] = (Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash
    }
    return $map
}

function Restore-StableResults {
    Copy-Item -Force (Join-Path $Source "*.json") $Official
    Copy-Item -Force (Join-Path $Source "*.json") $Mirror
}

$expected = Get-HashMap $Source
Write-WatchLog "watchdog started; source=$Source official=$Official"
Restore-StableResults

while ($true) {
    try {
        $changed = $false
        foreach ($name in $expected.Keys) {
            $path = Join-Path $Official $name
            if (-not (Test-Path $path)) {
                $changed = $true
                Write-WatchLog "missing official file: $name"
                break
            }
            $hash = (Get-FileHash -Algorithm SHA256 -Path $path).Hash
            if ($hash -ne $expected[$name]) {
                $changed = $true
                Write-WatchLog "official file changed: $name"
                break
            }
        }
        $extra = Get-ChildItem -Path $Official -Filter "*.json" -File |
            Where-Object { -not $expected.ContainsKey($_.Name) }
        if ($extra) {
            $changed = $true
            Write-WatchLog "extra official result files detected: $($extra.Name -join ', ')"
        }
        if ($changed) {
            Restore-StableResults
            Write-WatchLog "stable official results restored"
        }
    } catch {
        Write-WatchLog "watchdog error: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSeconds
}
