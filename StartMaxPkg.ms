-- Starts (or restarts) MaxPkg Runtime on Python + Qt and opens the Manager.
-- Copyright (c) 2026 Lukianenko Vasyl
-- https://maxpkg.dev
-- Developed by https://3dground.net (3DGROUND)

(
    local entryPath = getThisScriptFileName()
    local bootstrapPath = (getFilenamePath entryPath) + @"python\bootstrap.py"
    if (not (doesFileExist bootstrapPath)) do (
        throw "MaxPkg bootstrap is missing. Restore the complete MaxPkg folder."
    )
    python.ExecuteFile bootstrapPath
)
