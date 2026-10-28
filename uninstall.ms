-- Removes MaxPkg Package Manager: its toolbar, startup loader, MacroScript action, settings and local files.
-- Copyright (c) 2026 Lukianenko Vasyl
-- https://maxpkg.dev
-- Developed by https://3dground.net (3DGROUND)

(
    fn forceDeleteFile filePath = (
        if (filePath == undefined or filePath == "" or not (doesFileExist filePath)) do return true
        try (
            setFileAttribute filePath #readOnly false
            deleteFile filePath
            return not (doesFileExist filePath)
        ) catch (
            return false
        )
    )

    fn forceDeleteFolder folderPath = (
        if (folderPath == undefined or folderPath == "" or not (doesDirectoryExist folderPath)) do return true
        try (
            local directoryClass = dotNetClass "System.IO.Directory"
            local searchOption = dotNetClass "System.IO.SearchOption"
            for existingFile in (directoryClass.GetFiles folderPath "*" searchOption.AllDirectories) do (
                setFileAttribute existingFile #readOnly false
            )
            directoryClass.Delete folderPath true
            return not (doesDirectoryExist folderPath)
        ) catch (
            return false
        )
    )

    local sourceFile = getSourceFileName()
    if (sourceFile == undefined or sourceFile == "") do sourceFile = getThisScriptFileName()
    local runtimeRoot = getFilenamePath sourceFile
    local expectedRoot = (getDir #temp) + @"\MaxPkg-Runtime-Manager-Qt\"
    local problems = #()

    -- Only the installed copy may remove itself; a repository checkout is never deleted.
    if ((toLower runtimeRoot) != (toLower expectedRoot)) then (
        messageBox ("This uninstaller only removes the installed Package Manager in:\n" + expectedRoot) title: "MaxPkg"
    ) else (
        local stopEntry = runtimeRoot + @"python\stop.py"
        if (doesFileExist stopEntry) do (
            try (
                -- runpy with the absolute path: python.ExecuteFile keeps a calling Python's __file__.
                local pythonPath = substituteString (substituteString stopEntry @"\" "/") "'" @"\'"
                python.Execute ("import runpy; runpy.run_path('" + pythonPath + "', run_name='__main__')")
            ) catch (
                append problems ("The Package Manager could not be stopped: " + getCurrentException())
            )
        )
        global MaxPkg
        if (MaxPkg != undefined and isProperty MaxPkg #isPackageManager) do MaxPkg = undefined
        local macroRoot = (getDir #userMacros) + @"\"
        local removableFiles = #(
            (getDir #userStartupScripts) + @"\maxpkg-runtime-qt-startup.ms",
            macroRoot + "maxpkg-runtime-qt.mcr",
            macroRoot + "MaxPkg-MaxPkg_Qt_Manager.mcr"
        )
        for removableFile in removableFiles do (
            if (not (forceDeleteFile removableFile)) do append problems ("Could not remove " + removableFile)
        )
        if (not (forceDeleteFolder runtimeRoot)) do append problems ("Could not remove " + runtimeRoot)
        if (problems.count == 0) then (
            messageBox "MaxPkg Package Manager was removed. Your scenes and installed scripts were not changed." title: "MaxPkg"
        ) else (
            local problemText = ""
            for problem in problems do problemText += problem + "\n"
            messageBox ("MaxPkg Package Manager was removed with problems:\n\n" + problemText + "\nRestart 3ds Max and run uninstall.ms again.") title: "MaxPkg"
        )
    )
)
