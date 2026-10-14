<#
.SYNOPSIS
    构建并发布一个 GitHub Release。

.DESCRIPTION
    自动完成整条链路：
      跑单元测试 -> 构建 onedir 并压缩成 zip -> 构建单文件 exe ->
      计算 SHA256 -> 生成发布说明 -> 创建 GitHub Release 并上传附件。

    ⚠️ 附件名一律使用 ASCII。
    GitHub 会清洗附件名里的非 ASCII 字符，中文会被替换成点号，
    最终用户下载到的会变成 B.-v2.0.0-win64.zip 这种看不懂的名字。

.EXAMPLE
    .\release.ps1 -Version v2.1.0
    .\release.ps1 -Version v2.1.0 -Draft
    .\release.ps1 -Version v2.1.0 -NotesFile .\notes.md -Prerelease
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$NotesFile = '',
    [switch]$Draft,
    [switch]$Prerelease,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$app = 'B站视频下载器'
$nl = [Environment]::NewLine
$venvPy = Join-Path $root '.venv/Scripts/python.exe'

if ($Version -notmatch '^v\d+\.\d+\.\d+') {
    throw "版本号格式应为 vX.Y.Z，收到：$Version"
}
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "未找到虚拟环境 $venvPy"
}

$gh = 'C:\Program Files\GitHub CLI\gh.exe'
if (-not (Test-Path -LiteralPath $gh)) {
    $found = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $found) { throw '未找到 gh CLI，请先安装并执行 gh auth login' }
    $gh = $found.Source
}

$dirty = git status --porcelain
if ($dirty) { throw '工作区不干净，请先提交或暂存改动再发布' }

$art = Join-Path $root 'artifacts'
if (Test-Path -LiteralPath $art) { Remove-Item -LiteralPath $art -Recurse -Force }
New-Item -ItemType Directory -Force -Path $art | Out-Null

$prefix = 'bilibili-downloader-' + $Version + '-win64'
$zipPath = Join-Path $art ($prefix + '.zip')
$exePath = Join-Path $art ($prefix + '.exe')

Write-Host '[1/6] 构建 onedir' -ForegroundColor Cyan
$buildArgs = @()
if (-not $SkipTests) { $buildArgs += '-RunTests' }
& pwsh -NoProfile -File (Join-Path $root 'build.ps1') @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'onedir 构建失败' }

Write-Host '[2/6] 压缩 zip' -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $root ("dist/" + $app + "/*")) -DestinationPath $zipPath -CompressionLevel Optimal -Force

Write-Host '[3/6] 构建单文件 exe' -ForegroundColor Cyan
& pwsh -NoProfile -File (Join-Path $root 'build.ps1') -OneFile -SkipSelftest
if ($LASTEXITCODE -ne 0) { throw 'onefile 构建失败' }
Copy-Item -LiteralPath (Join-Path $root ("dist/" + $app + ".exe")) -Destination $exePath -Force

Write-Host '[4/6] 计算校验和' -ForegroundColor Cyan
$shaZip = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
$shaExe = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
$sizeZip = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
$sizeExe = [math]::Round((Get-Item -LiteralPath $exePath).Length / 1MB, 1)

Write-Host '[5/6] 生成发布说明' -ForegroundColor Cyan
if ($NotesFile -and (Test-Path -LiteralPath $NotesFile)) {
    $notes = Get-Content -LiteralPath $NotesFile -Raw -Encoding UTF8
} else {
    $prev = git tag --sort=-v:refname | Where-Object { $_ -ne $Version } | Select-Object -First 1
    $range = if ($prev) { $prev + '..HEAD' } else { 'HEAD' }
    $changes = git log $range --no-merges --pretty=format:'- %s (%h)'
    $notes = @(
        '# B站视频下载器 ' + $Version
        ''
        '## 下载'
        ''
        '| 文件 | 适用场景 | 体积 |'
        '| --- | --- | --- |'
        '| ' + $prefix + '.zip | 推荐。解压后双击 exe，启动快 | ' + $sizeZip + ' MB |'
        '| ' + $prefix + '.exe | 单文件下载即用，冷启动约 2.5 秒 | ' + $sizeExe + ' MB |'
        ''
        '两个版本功能完全一致，只是打包形式不同。'
        ''
        '## 校验和'
        ''
        '    SHA256 (' + $prefix + '.zip)  ' + $shaZip
        '    SHA256 (' + $prefix + '.exe)  ' + $shaExe
        ''
        '## 关于 ffmpeg'
        ''
        '本发布未内置 ffmpeg。首次使用时在界面点「一键下载」获取（约 60MB，只需一次）。'
        '没有 ffmpeg 时程序会自动降级为渐进式单文件模式（720P，免合并），不会静默失败。'
        ''
        '## 系统要求'
        ''
        '- Windows 10 / 11（64 位）'
        '- 无需安装 Python'
        ''
        '## 本次变更'
        ''
        $changes
        ''
        '## 问题反馈'
        ''
        'https://github.com/xiesat/bilibili-downloader/issues'
    ) -join $nl
}

$notesOut = Join-Path $art 'RELEASE_NOTES.md'
Set-Content -LiteralPath $notesOut -Value $notes -Encoding UTF8

Write-Host '[6/6] 创建 GitHub Release' -ForegroundColor Cyan
$releaseArgs = @('release', 'create', $Version, $zipPath, $exePath, '--title', ('B站视频下载器 ' + $Version), '--notes-file', $notesOut, '--target', 'main')
if ($Draft) { $releaseArgs += '--draft' }
if ($Prerelease) { $releaseArgs += '--prerelease' }
& $gh @releaseArgs

Write-Host ''
Write-Host '发布完成：' -ForegroundColor Green
Write-Host ('  zip : ' + $zipPath + '  (' + $sizeZip + ' MB)')
Write-Host ('  exe : ' + $exePath + '  (' + $sizeExe + ' MB)')
Write-Host ('  页面: https://github.com/xiesat/bilibili-downloader/releases/tag/' + $Version)
