-- Installs MaxPkg Package Manager, its startup loader and the Manager MacroScript action.
-- Copyright (c) 2026 Lukianenko Vasyl
-- https://maxpkg.dev
-- Developed by https://3dground.net (3DGROUND)

(
    local minimumMaxYear = 2022

    fn ensureSlash folderPath = (
        if (folderPath == undefined or folderPath == "") do return ""
        local normalizedPath = substituteString folderPath "/" @"\"
        if ((substring normalizedPath normalizedPath.count 1) == @"\") do return normalizedPath
        return normalizedPath + @"\"
    )

    fn makeFileWritable filePath = (
        if (filePath == undefined or filePath == "" or not (doesFileExist filePath)) do return true
        try (
            setFileAttribute filePath #readOnly false
            return true
        ) catch (
            return false
        )
    )

    fn forceDeleteFile filePath = (
        if (filePath == undefined or filePath == "" or not (doesFileExist filePath)) do return true
        if (not (makeFileWritable filePath)) do return false
        try (
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
                if (not (makeFileWritable existingFile)) do return false
            )
            directoryClass.Delete folderPath true
            return not (doesDirectoryExist folderPath)
        ) catch (
            return false
        )
    )

    fn replaceFile sourceFilePath targetFilePath = (
        if (not (doesFileExist sourceFilePath)) do throw ("Source file does not exist:\n" + sourceFilePath)
        local targetFolder = getFilenamePath targetFilePath
        if (not (makeDir targetFolder all: true)) do throw ("Could not create target folder:\n" + targetFolder)
        if (not (forceDeleteFile targetFilePath)) do throw ("Could not remove the previous file:\n" + targetFilePath)
        if (not (copyFile sourceFilePath targetFilePath)) do throw ("Could not copy file:\n" + sourceFilePath)
        return true
    )

    fn copyTree sourceRoot targetRoot = (
        if (not (doesDirectoryExist sourceRoot)) do throw ("Source folder does not exist:\n" + sourceRoot)
        local directoryClass = dotNetClass "System.IO.Directory"
        local searchOption = dotNetClass "System.IO.SearchOption"
        if (not (makeDir targetRoot all: true)) do throw ("Could not create folder:\n" + targetRoot)
        for sourceFile in (directoryClass.GetFiles sourceRoot "*" searchOption.AllDirectories) do (
            local relativePath = substring sourceFile (sourceRoot.count + 1) (sourceFile.count - sourceRoot.count)
            if ((findString relativePath "__pycache__") == undefined) do replaceFile sourceFile (targetRoot + relativePath)
        )
        return true
    )

    fn writeTextFile filePath fileContent = (
        local fileStream = undefined
        try (
            makeDir (getFilenamePath filePath) all: true
            if (not (forceDeleteFile filePath)) do return false
            fileStream = createFile filePath
            if (fileStream == undefined) do return false
            format "%" fileContent to: fileStream
            close fileStream
            return true
        ) catch (
            try (
                if (fileStream != undefined) do close fileStream
            ) catch (
            )
            return false
        )
    )

    fn maxScriptPathLiteral filePath = (
        return "@\"" + (substituteString filePath "\"" "") + "\""
    )

    -- Python files are run with runpy and their absolute path, never python.ExecuteFile: called while Python is
    -- already on the stack, python.ExecuteFile keeps the caller's __file__ and the entry finds the wrong folder.
    fn pythonRunCommand pythonFilePath = (
        local pythonPath = substituteString (substituteString pythonFilePath @"\" "/") "'" @"\'"
        return "import runpy; runpy.run_path('" + pythonPath + "', run_name='__main__')"
    )

    fn maxScriptStringLiteral sourceContent = (
        local literalContent = substituteString (sourceContent as string) @"\" @"\\"
        literalContent = substituteString literalContent "\"" "\\\""
        return "\"" + literalContent + "\""
    )

    fn runPython pythonFilePath = (
        if (not (doesFileExist pythonFilePath)) do throw ("Package Manager file is missing:\n" + pythonFilePath)
        python.Execute (pythonRunCommand pythonFilePath)
        return true
    )

    fn writeStartupShim shimPath runtimeRoot = (
        local entryFile = runtimeRoot + @"python\startup.py"
        local shimContent = ""
        shimContent += "-- Starts MaxPkg Package Manager with 3ds Max. Written by install.ms.\n"
        shimContent += "(\n"
        shimContent += "    local entryPath = " + (maxScriptPathLiteral entryFile) + "\n"
        shimContent += "    if (doesFileExist entryPath) do (\n"
        shimContent += "        try (\n"
        shimContent += "            python.Execute " + (maxScriptStringLiteral (pythonRunCommand entryFile)) + "\n"
        shimContent += "        ) catch (\n"
        shimContent += "            format \"MaxPkg Package Manager could not start: %\\n\" (getCurrentException())\n"
        shimContent += "        )\n"
        shimContent += "    )\n"
        shimContent += ")\n"
        return writeTextFile shimPath shimContent
    )

    fn writeManagerMacro runtimeRoot = (
        local macroRoot = ensureSlash (getDir #userMacros)
        local macroFilePath = macroRoot + "maxpkg-runtime-qt.mcr"
        local macroContent = ""
        macroContent += "-- Opens MaxPkg Manager (Qt) from a user-configured 3ds Max action. Written by install.ms.\n"
        macroContent += "macroScript MaxPkg_Qt_Manager\n"
        macroContent += "category: \"MaxPkg\"\n"
        macroContent += "buttonText: \"MaxPkg Manager (Qt)\"\n"
        macroContent += "tooltip: \"Open MaxPkg Manager (Qt)\"\n"
        macroContent += "iconName: " + (maxScriptPathLiteral (runtimeRoot + @"assets\icons\maxpkg-logo.svg")) + "\n"
        macroContent += "(\n"
        macroContent += "    on execute do (\n"
        macroContent += "        local entryPath = " + (maxScriptPathLiteral (runtimeRoot + @"python\open.py")) + "\n"
        macroContent += "        if (doesFileExist entryPath) then (\n"
        macroContent += "            python.Execute " + (maxScriptStringLiteral (pythonRunCommand (runtimeRoot + @"python\open.py"))) + "\n"
        macroContent += "        ) else (\n"
        macroContent += "            messageBox \"MaxPkg Package Manager is not installed. Install it again from maxpkg.dev.\" title: \"MaxPkg\"\n"
        macroContent += "        )\n"
        macroContent += "    )\n"
        macroContent += ")\n"
        forceDeleteFile (macroRoot + "MaxPkg-MaxPkg_Qt_Manager.mcr")
        if (not (writeTextFile macroFilePath macroContent)) do return false
        fileIn macroFilePath
        return true
    )

    fn isFolderEmpty folderPath = (
        return (getFiles (folderPath + "*")).count == 0 and (getDirectories (folderPath + "*")).count == 0
    )

    -- Removes the previous MaxScript/.NET Runtime (MaxPkg-Runtime-Manager): stops it, deletes its startup script,
    -- MacroScripts and program files. Its settings.ini moves to the new data folder (imported on first start) and
    -- packages installed under data\packages\ stay where they are, because their own scripts point there.
    fn removeLegacyRuntime temporaryRoot targetRoot sourceRoot = (
        global MaxPkg
        -- The Qt Package Manager defines MaxPkg too (isPackageManager); stop.py handles that one.
        if (MaxPkg != undefined and not (isProperty MaxPkg #isPackageManager)) do (
            if (isProperty MaxPkg #shutdown) do (
                try (
                    MaxPkg.shutdown()
                ) catch (
                    format "MaxPkg could not stop the previous Runtime: %\n" (getCurrentException())
                )
            )
            MaxPkg = undefined
        )
        local userMacrosRoot = ensureSlash (getDir #userMacros)
        local legacyFiles = #(
            (ensureSlash (getDir #userStartupScripts)) + "maxpkg-runtime-startup.ms",
            userMacrosRoot + "maxpkg-runtime-manager.mcr",
            userMacrosRoot + "MaxPkg-MaxPkg_Manager.mcr"
        )
        for legacyFile in legacyFiles do (
            if (not (forceDeleteFile legacyFile)) do throw ("Could not remove the previous Runtime file:\n" + legacyFile)
        )
        local legacyRoot = temporaryRoot + @"MaxPkg-Runtime-Manager\"
        if (not (doesDirectoryExist legacyRoot)) do return true
        if ((findString (toLower sourceRoot) (toLower legacyRoot)) == 1) do return true  -- never delete the running installer
        local legacySettings = legacyRoot + "settings.ini"
        local targetSettings = targetRoot + "settings.ini"
        if ((doesFileExist legacySettings) and not (doesFileExist targetSettings)) do (
            makeDir targetRoot all: true
            if (not (copyFile legacySettings targetSettings)) do throw ("Could not keep the previous settings:\n" + legacySettings)
        )
        local packagesRoot = legacyRoot + @"data\packages\"
        local keepPackages = (doesDirectoryExist packagesRoot) and (getDirectories (packagesRoot + "*")).count > 0
        for legacyFolder in (getDirectories (legacyRoot + "*")) do (
            local folderName = toLower (pathConfig.stripPathToLeaf (substring legacyFolder 1 (legacyFolder.count - 1)))
            if (not (keepPackages and folderName == "data")) do (
                if (not (forceDeleteFolder legacyFolder)) do throw ("Could not remove the previous Runtime folder:\n" + legacyFolder)
            )
        )
        for legacyFile in (getFiles (legacyRoot + "*")) do (
            if (not (forceDeleteFile legacyFile)) do throw ("Could not remove the previous Runtime file:\n" + legacyFile)
        )
        if (isFolderEmpty legacyRoot) do forceDeleteFolder legacyRoot
        format "MaxPkg removed the previous Runtime from %\n" legacyRoot
        return true
    )

    local sourceFile = getSourceFileName()
    if (sourceFile == undefined or sourceFile == "") do sourceFile = getThisScriptFileName()
    local sourceRoot = ensureSlash (getFilenamePath sourceFile)
    local temporaryRoot = ensureSlash (getDir #temp)
    local targetRoot = temporaryRoot + @"MaxPkg-Runtime-Manager-Qt\"
    local runtimeVersion = "Unknown"
    try (
        runtimeVersion = getINISetting (sourceRoot + "version.ini") "Runtime" "Version"
    ) catch (
        runtimeVersion = "Unknown"
    )

    try (
        local maxYear = (maxVersion())[8]
        if (maxYear == undefined or maxYear < minimumMaxYear) do (
            throw ("MaxPkg Package Manager requires 3ds Max " + (minimumMaxYear as string) + " or newer.")
        )
        if ((toLower sourceRoot) == (toLower targetRoot)) do throw "The Package Manager cannot be installed over its source folder."
        if (temporaryRoot == "") do throw "The 3ds Max temporary folder is unavailable."
        removeLegacyRuntime temporaryRoot targetRoot sourceRoot
        local stopEntry = targetRoot + @"python\stop.py"
        if (doesFileExist stopEntry) do (
            try (
                runPython stopEntry
            ) catch (
                format "MaxPkg could not stop the running Package Manager: %\n" (getCurrentException())
            )
        )
        makeDir targetRoot all: true
        -- Code and assets are replaced completely; settings.ini, logs, cache and downloads are kept.
        if (not (forceDeleteFolder (targetRoot + @"python\"))) do throw ("Could not remove the previous Package Manager code:\n" + targetRoot + @"python\")
        if (not (forceDeleteFolder (targetRoot + @"assets\"))) do throw ("Could not remove the previous Package Manager assets:\n" + targetRoot + @"assets\")
        copyTree (sourceRoot + @"python\") (targetRoot + @"python\")
        copyTree (sourceRoot + @"assets\") (targetRoot + @"assets\")
        replaceFile (sourceRoot + "StartMaxPkg.ms") (targetRoot + "StartMaxPkg.ms")
        replaceFile (sourceRoot + "version.ini") (targetRoot + "version.ini")
        replaceFile (sourceRoot + "uninstall.ms") (targetRoot + "uninstall.ms")
        local shimPath = (ensureSlash (getDir #userStartupScripts)) + "maxpkg-runtime-qt-startup.ms"
        if (not (writeStartupShim shimPath targetRoot)) do throw "Could not create the startup script."
        if (not (writeManagerMacro targetRoot)) do throw "Could not create the MaxPkg Manager (Qt) MacroScript."
        runPython (targetRoot + @"python\welcome.py")
        format "MaxPkg Package Manager % was installed to %\n" runtimeVersion targetRoot
    ) catch (
        messageBox ("MaxPkg Package Manager " + runtimeVersion + " could not be installed.\n\n" + (getCurrentException()) + "\n\nYour 3ds Max scenes were not changed. Close MaxPkg windows, restart 3ds Max and run the installer again.") title: "MaxPkg Runtime Setup"
    )
)
