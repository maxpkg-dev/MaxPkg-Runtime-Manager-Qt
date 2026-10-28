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
    -- runpy with the absolute path, not python.ExecuteFile: run while Python is already on the stack,
    -- python.ExecuteFile keeps the caller's __file__ and bootstrap.py would look for the wrong folder.
    local pythonPath = substituteString (substituteString bootstrapPath @"\" "/") "'" @"\'"
    python.Execute ("import runpy; runpy.run_path('" + pythonPath + "', run_name='__main__')")
)
