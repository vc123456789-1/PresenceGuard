# Run from any directory on 64-bit Windows with Python 3.12 and Inno Setup 6.4.3.
# Produces an onedir build, a portable ZIP and a per-user installer.
param([string]$Python = 'py', [string]$InnoCompiler = '')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
if (-not [Environment]::Is64BitOperatingSystem) { throw 'A 64-bit Windows build host is required.' }
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the build environment.' }
}
$arch = & $venvPython -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0 -or $arch -ne '64') { throw 'A 64-bit Python interpreter is required.' }
& $venvPython -m pip install -r requirements.txt -r packaging\requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$arguments = @('--noconfirm', '--clean', '--windowed', '--onedir', '--name', 'PresenceGuard', '--icon', 'packaging\app.ico', '--collect-all', 'cv2', '--collect-all', 'pystray')
$env:PYINSTALLER_CONFIG_DIR = Join-Path $project '.build-tools\pyinstaller-cache'
# Include only known public model resources, never user data or biometric templates.
foreach ($name in @('face_detection_yunet_2023mar.onnx', 'face_recognition_sface_2021dec.onnx', 'YUNET-LICENSE.txt', 'SFACE-LICENSE.txt')) {
    $path = Join-Path 'models' $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required model resource missing: $path" }
    $arguments += @('--add-data', "${path};models")
}
& $venvPython -m PyInstaller @arguments main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
if (-not (Test-Path -LiteralPath 'dist\PresenceGuard\PresenceGuard.exe')) { throw 'Executable missing from build.' }
Copy-Item -LiteralPath 'README.md' -Destination 'dist\PresenceGuard\README.md' -Force
New-Item -ItemType Directory -Force -Path 'dist\PresenceGuard\docs' | Out-Null
foreach ($document in @('MODELS.md', 'TEST_REPORT.md')) {
    $path = Join-Path 'docs' $document
    if (Test-Path -LiteralPath $path -PathType Leaf) { Copy-Item -LiteralPath $path -Destination 'dist\PresenceGuard\docs' -Force }
}
New-Item -ItemType Directory -Force -Path 'release' | Out-Null
$zip = Join-Path $project 'release\PresenceGuard-Portable-x64.zip'
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path 'dist\PresenceGuard' -DestinationPath $zip -CompressionLevel Optimal
if (-not $InnoCompiler) {
    $localCompiler = Join-Path $project '.build-tools\InnoSetup643\ISCC.exe'
    if (Test-Path -LiteralPath $localCompiler) { $InnoCompiler = $localCompiler }
    else { $candidate = Get-Command ISCC.exe -ErrorAction SilentlyContinue; if ($candidate) { $InnoCompiler = $candidate.Source } }
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler)) { throw 'Inno Setup compiler not found. Install it or pass -InnoCompiler with its path.' }
& $InnoCompiler 'packaging\installer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
& $venvPython 'packaging\source_zip.py'
if ($LASTEXITCODE -ne 0) { throw 'Source archive creation failed.' }
Write-Host 'Build artifacts are in release\.'
