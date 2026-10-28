@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "REPOSITORY=maxpkg-dev/MaxPkg-Runtime-Manager-Qt"
set "WORKFLOW=publish-runtime.yml"
set "RELEASE_BRANCH=main"
set "PROJECT_ROOT=%~dp0"

pushd "%PROJECT_ROOT%" >nul || goto :pushd_failed

where git >nul 2>&1 || goto :git_missing
where gh >nul 2>&1 || goto :gh_missing
gh auth status --hostname github.com >nul 2>&1 || goto :gh_auth_missing

for /f "delims=" %%I in ('git status --porcelain') do goto :dirty_worktree

for /f "delims=" %%I in ('git branch --show-current') do set "CURRENT_BRANCH=%%I"
if /i not "%CURRENT_BRANCH%"=="%RELEASE_BRANCH%" goto :wrong_branch

echo Checking origin/%RELEASE_BRANCH%...
git fetch origin %RELEASE_BRANCH% --quiet || goto :fetch_failed

for /f "delims=" %%I in ('git rev-parse HEAD') do set "LOCAL_COMMIT=%%I"
for /f "delims=" %%I in ('git rev-parse origin/%RELEASE_BRANCH%') do set "REMOTE_COMMIT=%%I"
if not "%LOCAL_COMMIT%"=="%REMOTE_COMMIT%" goto :not_pushed

for /f "usebackq delims=" %%V in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$content = [System.IO.File]::ReadAllText('version.ini'); $match = [regex]::Match($content, '(?m)^Version=(\d+\.\d+\.\d+)\s*$'); if (-not $match.Success) { exit 1 }; $match.Groups[1].Value"`) do set "RUNTIME_VERSION=%%V"
if not defined RUNTIME_VERSION goto :version_failed

set "RELEASE_TAG=v%RUNTIME_VERSION%"

echo Checking release %RELEASE_TAG%...
gh release view "%RELEASE_TAG%" --repo "%REPOSITORY%" >nul 2>&1
if not errorlevel 1 goto :release_exists

git ls-remote --exit-code --tags origin "refs/tags/%RELEASE_TAG%" >nul 2>&1
if not errorlevel 1 goto :tag_exists

echo.
echo Repository: %REPOSITORY%
echo Branch:     %RELEASE_BRANCH%
echo Version:    %RUNTIME_VERSION%
echo Tag:        %RELEASE_TAG%
echo Asset:      MaxPkg-Runtime-Manager-Qt.mzp
echo.
choice /C YN /N /M "Create this release? [Y/N]: "
if errorlevel 2 goto :cancelled

echo.
echo Starting GitHub Actions workflow...
gh workflow run "%WORKFLOW%" --repo "%REPOSITORY%" --ref "%RELEASE_BRANCH%" --field "version=%RUNTIME_VERSION%" || goto :workflow_failed

echo.
echo Release workflow started successfully.
echo Follow its progress here:
echo https://github.com/%REPOSITORY%/actions/workflows/%WORKFLOW%
start "" "https://github.com/%REPOSITORY%/actions/workflows/%WORKFLOW%"
goto :success

:dirty_worktree
echo ERROR: The repository has uncommitted or untracked files.
echo Commit and push the prepared release before publishing it.
goto :failure

:wrong_branch
echo ERROR: Current branch is "%CURRENT_BRANCH%". Switch to "%RELEASE_BRANCH%" first.
goto :failure

:not_pushed
echo ERROR: Local HEAD does not match origin/%RELEASE_BRANCH%.
echo Commit and push the release, then run this file again.
goto :failure

:release_exists
echo ERROR: GitHub Release %RELEASE_TAG% already exists.
goto :failure

:tag_exists
echo ERROR: Git tag %RELEASE_TAG% already exists.
goto :failure

:git_missing
echo ERROR: Git was not found in PATH.
goto :failure

:gh_missing
echo ERROR: GitHub CLI was not found in PATH.
echo Install it from https://cli.github.com/ and run gh auth login.
goto :failure

:gh_auth_missing
echo ERROR: GitHub CLI is not signed in.
echo Run: gh auth login
goto :failure

:fetch_failed
echo ERROR: Could not update origin/%RELEASE_BRANCH%.
goto :failure

:version_failed
echo ERROR: Could not read Version from version.ini.
goto :failure

:workflow_failed
echo ERROR: GitHub Actions workflow could not be started.
goto :failure

:pushd_failed
echo ERROR: Could not open the project directory.
goto :failure_without_popd

:cancelled
echo.
echo Release cancelled.
popd >nul
exit /b 0

:success
popd >nul
echo.
pause
exit /b 0

:failure
popd >nul

:failure_without_popd
echo.
pause
exit /b 1
