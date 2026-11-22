param(
    [string]$Targets = 'android/arm64,android/amd64',
    [string]$MobileVersion = 'v0.0.0-20261117202452-47699113848a'
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    go install "golang.org/x/mobile/cmd/gomobile@$MobileVersion"
    if ($LASTEXITCODE) { throw 'Installing gomobile failed' }
    go install "golang.org/x/mobile/cmd/gobind@$MobileVersion"
    if ($LASTEXITCODE) { throw 'Installing gobind failed' }
    $goBin = go env GOBIN
    if (!$goBin) { $goBin = Join-Path (go env GOPATH) 'bin' }
    $env:Path = "$goBin;$env:Path"
    go get -tool "golang.org/x/mobile/cmd/gobind@$MobileVersion"
    if ($LASTEXITCODE) { throw 'Configuring the Go bindings module failed' }
    go mod tidy
    if ($LASTEXITCODE) { throw 'Resolving Go dependencies failed' }
    New-Item -ItemType Directory -Force -Path libs | Out-Null
    gomobile bind -target $Targets -androidapi 26 -javapkg il.homegallery.nativebridge -o libs/tailbridge.aar .
    if ($LASTEXITCODE) { throw 'Building the Android bridge failed' }
} finally {
    Pop-Location
}
