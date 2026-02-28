param(
    [string]$CondaEnv = "citwin-api",
    [string]$Database = "citwin_api_netascore",
    [string]$Password,
    [string]$NssmService = "citwin-api",
    [string]$ApiPort = "8000",
    [string]$ApiRootPath = "/api/citwin",
    [string]$LogPath = "C:\logs"
)

$RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$CondaPath = (& conda info --base).Trim()

$envs = conda env list
if ($envs -match "^\s*$CondaEnv\s") {
    # Write-Host "update conda environment"
    # conda env update -n $CondaEnv -f "$RepoPath\environment.yml"
} else {
    Write-Host "# create conda environment"
    conda env create -n $CondaEnv -f "$RepoPath\environment.yml"
    conda run -n citwin-api conda env config vars set PROJ_LIB="$CondaPath\envs\$CondaEnv\Library\share\proj"
}

$env:PGPASSWORD = $Password
$exists = psql -U postgres -h localhost -p 5432 -tAc "SELECT 1 FROM pg_database WHERE datname='$Database';"
if ($exists -ne "1") {
    Write-Host "# create database"
    psql -U postgres -h localhost -p 5432 -c "CREATE DATABASE $Database"
}

if (-not (Get-Service $NssmService -ErrorAction SilentlyContinue)) {
    Write-Host "# install service"
    nssm install $NssmService "$RepoPath\start.bat" $CondaEnv $ApiPort $ApiRootPath
    nssm set $NssmService AppDirectory $RepoPath
    nssm set $NssmService AppStdout "$LogPath\$NssmService-out.log"
    nssm set $NssmService AppStderr "$LogPath\$NssmService-err.log"
    nssm start $NssmService
} else {
    Write-Host "# restart service"
    nssm restart $NssmService
}
