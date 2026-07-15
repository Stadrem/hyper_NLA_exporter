param(
    [string]$BlenderPath = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $BlenderPath)) {
    throw "Blender executable was not found: $BlenderPath"
}

$TestsDir = $PSScriptRoot
$AddonRoot = Split-Path -Parent $TestsDir
$FixtureScript = Join-Path $TestsDir "test_blender_fixtures.py"

$Cases = @(
    [pscustomobject]@{
        Name = "Smoke"
        Arguments = @(
            "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1",
            "--python", (Join-Path $TestsDir "test_blender_smoke.py")
        )
    },
    [pscustomobject]@{
        Name = "Synthetic FBX/GLB"
        Arguments = @(
            "--background", "--factory-startup", "--disable-autoexec",
            "--python-exit-code", "1",
            "--python", (Join-Path $TestsDir "test_blender_exports.py")
        )
    }
)

$OptionalFixtures = @(
    [pscustomobject]@{ Name = "Real Rig Source"; File = "NextStep_Arrow.blend" },
    [pscustomobject]@{ Name = "Real Rig NLA"; File = "NextStep_Arrow_NLA.blend" }
)

foreach ($Fixture in $OptionalFixtures) {
    $FixturePath = Join-Path $TestsDir $Fixture.File
    if (Test-Path -LiteralPath $FixturePath) {
        $Cases += [pscustomobject]@{
            Name = $Fixture.Name
            Arguments = @(
                "--background", "--factory-startup", "--disable-autoexec",
                $FixturePath,
                "--python-exit-code", "1",
                "--python", $FixtureScript
            )
        }
    }
    else {
        Write-Host "Skipping optional fixture: $($Fixture.File)" -ForegroundColor Yellow
    }
}

Push-Location $AddonRoot
try {
    foreach ($Case in $Cases) {
        Write-Host "`n=== $($Case.Name) ===" -ForegroundColor Cyan
        $Arguments = $Case.Arguments
        & $BlenderPath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Test failed: $($Case.Name) (exit code $LASTEXITCODE)"
        }
    }
}
finally {
    Pop-Location
}

Write-Host "`nALL_HYPER_NLA_TESTS_OK" -ForegroundColor Green
