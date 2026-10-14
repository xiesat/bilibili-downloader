<#
.SYNOPSIS
    打包 B站视频下载器（PyInstaller）。

.DESCRIPTION
    默认产出 onedir 目录（启动快、便于排查），体积约 93MB，不含 ffmpeg。
    加 -OneFile 产出单个自解压 exe（下载即用，但冷启动慢 3-6 秒）。
    加 -BundleFFmpeg 内置 ffmpeg 静态包，产物约 170MB，可完全离线。
    加 -RunTests 打包前先跑单元测试。

.EXAMPLE
    .\build.ps1
    .\build.ps1 -OneFile
    .\build.ps1 -RunTests -BundleFFmpeg
#>
[CmdletBinding()]
param(
    [switch]$BundleFFmpeg,
    [switch]$OneFile,
    [switch]$RunTests,
    [switch]$SkipSelftest
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$appName = 'B站视频下载器'
$venvPy = Join-Path $root '.venv/Scripts/python.exe'

if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "未找到虚拟环境 $venvPy。请先执行： python -m venv .venv 然后 .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt"
}

if ($RunTests) {
    Write-Host '[1/5] 运行单元测试' -ForegroundColor Cyan
    & $venvPy -m pytest
    if ($LASTEXITCODE -ne 0) { throw '单元测试未通过，打包中止' }
}

Write-Host '[2/5] 清理旧的构建产物' -ForegroundColor Cyan
foreach ($name in @('build', 'dist')) {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

if ($BundleFFmpeg) {
    $env:BILIDOWN_BUNDLE_FFMPEG = '1'
    Write-Host '     本次打包将内置 ffmpeg' -ForegroundColor Yellow
} else {
    Remove-Item Env:\BILIDOWN_BUNDLE_FFMPEG -ErrorAction SilentlyContinue
}
if ($OneFile) {
    $env:BILIDOWN_ONEFILE = '1'
} else {
    Remove-Item Env:\BILIDOWN_ONEFILE -ErrorAction SilentlyContinue
}

Write-Host '[3/5] 调用 PyInstaller' -ForegroundColor Cyan
& $venvPy -m PyInstaller --noconfirm --clean (Join-Path $root 'build.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败' }

if ($OneFile) {
    $exePath = Join-Path $root "dist/$appName.exe"
    $outDir = $null
} else {
    $outDir = Join-Path $root "dist/$appName"
    $exePath = Join-Path $outDir "$appName.exe"
}

if (-not (Test-Path -LiteralPath $exePath)) { throw "未找到产物可执行文件 $exePath" }

Write-Host '[4/5] 运行内置自检' -ForegroundColor Cyan
if ($SkipSelftest) {
    Write-Host '     已跳过' -ForegroundColor Yellow
} else {
    $report = Join-Path $root 'dist/selftest.json'
    if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report -Force }
    # Start-Process 的 -ArgumentList 不会自动给数组元素加引号，
    # 路径含空格时会被拆成多个参数，必须手工拼好带引号的命令行。
    $argLine = '--selftest "' + $report + '"'
    $proc = Start-Process -FilePath $exePath -ArgumentList $argLine -Wait -PassThru
    if (Test-Path -LiteralPath $report) {
        $json = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($json.ok) {
            Write-Host '     自检通过' -ForegroundColor Green
        } else {
            Write-Host '     自检未通过，详情见 dist/selftest.json' -ForegroundColor Red
            $json.errors | ForEach-Object { Write-Host ('       - ' + ($_ -split "`n")[0]) -ForegroundColor Red }
        }
        Write-Host ('     界面截图：' + $json.checks.gui.screenshot)
    } else {
        Write-Host ('     自检进程退出码 ' + $proc.ExitCode + '，未生成报告') -ForegroundColor Red
    }
}

Write-Host '[5/5] 产物统计' -ForegroundColor Cyan
if ($OneFile) {
    $sizeMb = (Get-Item -LiteralPath $exePath).Length / 1MB
    Write-Host ('     单文件 : ' + $exePath)
    Write-Host ('     大小   : ' + ('{0:N1} MB' -f $sizeMb)) -ForegroundColor Green
} else {
    $files = Get-ChildItem -LiteralPath $outDir -Recurse -File
    $totalMb = ($files | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host ('     目录   : ' + $outDir)
    Write-Host ('     文件数 : ' + $files.Count)
    Write-Host ('     总大小 : ' + ('{0:N1} MB' -f $totalMb)) -ForegroundColor Green
    Write-Host ('     入口   : ' + $exePath)
}
Write-Host ''
Write-Host '分发时把整个目录打包成 zip 即可。' -ForegroundColor Gray
