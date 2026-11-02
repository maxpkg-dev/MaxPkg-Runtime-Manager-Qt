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

    fn runPython pythonFilePath = (
        if (not (doesFileExist pythonFilePath)) do throw ("Package Manager file is missing:\n" + pythonFilePath)
        python.Execute (pythonRunCommand pythonFilePath)
        return true
    )

    -- MaxScript that runs one of the program's Python files. A startup or macro folder can be shared by several 3ds Max
    -- versions, so the file is looked up in the temp folder of the 3ds Max running the script (never a fixed path),
    -- and 3ds Max older than 2022 (release 24000) skips it: it has neither the Python nor the Qt the program needs.
    fn pythonEntryLines entryName indent missingLine = (
        local lines = ""
        lines += indent + "if ((maxVersion())[1] >= 24000) do (\n"
        lines += indent + "    local entryPath = (getDir #temp) + @\"\\MaxPkg-Runtime-Manager-Qt\\python\\" + entryName + "\"\n"
        lines += indent + "    if (doesFileExist entryPath) then (\n"
        lines += indent + "        try (\n"
        lines += indent + "            local pythonPath = substituteString (substituteString entryPath @\"\\\" \"/\") \"'\" @\"\\'\"\n"
        lines += indent + "            python.Execute (\"import runpy; runpy.run_path('\" + pythonPath + \"', run_name='__main__')\")\n"
        lines += indent + "        ) catch (\n"
        lines += indent + "            format \"MaxPkg Package Manager could not start: %\\n\" (getCurrentException())\n"
        lines += indent + "        )\n"
        lines += indent + "    ) else (\n"
        lines += indent + "        " + missingLine + "\n"
        lines += indent + "    )\n"
        lines += indent + ")\n"
        return lines
    )

    fn writeStartupShim shimPath = (
        local shimContent = ""
        shimContent += "-- Starts MaxPkg Package Manager with 3ds Max. Written by install.ms.\n"
        shimContent += "(\n"
        shimContent += pythonEntryLines "startup.py" "    " "()"
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
        macroContent += pythonEntryLines "open.py" "        " "messageBox \"MaxPkg Package Manager is not installed. Install it again from maxpkg.dev.\" title: \"MaxPkg\""
        macroContent += "    )\n"
        macroContent += ")\n"
        forceDeleteFile (macroRoot + "MaxPkg-MaxPkg_Qt_Manager.mcr")
        if (not (writeTextFile macroFilePath macroContent)) do return false
        fileIn macroFilePath
        return true
    )

    -- The 3ds Max year. maxVersion() has it as item 8 only since 3ds Max 2019; older releases give the release
    -- number (18000 is 3ds Max 2016), which counts up by 1000 a year.
    fn currentMaxYear = (
        local versionInfo = maxVersion()
        if (versionInfo.count >= 8 and (classOf versionInfo[8]) == Integer and versionInfo[8] > 2000) do return versionInfo[8]
        return 1998 + (versionInfo[1] / 1000)
    )

    fn isFolderEmpty folderPath = (
        return (getFiles (folderPath + "*")).count == 0 and (getDirectories (folderPath + "*")).count == 0
    )

    -- True for a folder inside this 3ds Max's own profile (...\2024 - 64bit\ENU\). A folder set up by hand may be shared
    -- with another 3ds Max version, which can still be running the previous Runtime from it.
    fn isOwnFolder folderPath = (
        local profileRoot = ""
        try (
            profileRoot = ensureSlash (getDir #maxData)
        ) catch (
            return false
        )
        if (profileRoot == "") do return false
        return (findString (toLower (ensureSlash folderPath)) (toLower profileRoot)) == 1
    )

    -- Stops the previous MaxScript/.NET Runtime in this session and frees the MaxPkg global for the Package Manager.
    -- Its files stay until the Package Manager has started. The Qt Package Manager defines MaxPkg too (isPackageManager);
    -- stop.py handles that one.
    fn stopLegacyRuntime = (
        global MaxPkg
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
    )

    -- Its settings.ini is copied before the first start, which reads it.
    fn keepLegacySettings legacyRoot targetRoot = (
        local legacySettings = legacyRoot + "settings.ini"
        local targetSettings = targetRoot + "settings.ini"
        if ((doesFileExist legacySettings) and not (doesFileExist targetSettings)) do (
            if (not (copyFile legacySettings targetSettings)) do format "MaxPkg could not copy the previous settings: %\n" legacySettings
        )
    )

    fn isPackageManagerRunning = (
        global MaxPkg
        return MaxPkg != undefined and (isProperty MaxPkg #isPackageManager) and MaxPkg.isStarted()
    )

    -- The Package Manager did not start: takes back what stops the previous Runtime from starting (version.ini and the
    -- startup script) and starts that Runtime again, so the user is not left without one.
    fn restoreLegacyRuntime legacyRoot targetRoot shimPath = (
        global MaxPkg
        local stopEntry = targetRoot + @"python\stop.py"
        try (
            if (doesFileExist stopEntry) do python.Execute (pythonRunCommand stopEntry)
        ) catch (
            format "MaxPkg could not stop the Package Manager: %\n" (getCurrentException())
        )
        if (MaxPkg != undefined and (isProperty MaxPkg #isPackageManager)) do MaxPkg = undefined
        forceDeleteFile shimPath
        forceDeleteFile (targetRoot + "version.ini")
        try (
            fileIn (legacyRoot + "startup.ms")
        ) catch (
            format "MaxPkg could not start the previous Runtime again: %\n" (getCurrentException())
        )
    )

    -- A kept startup.ms older than 1.2.1 does not check for the Package Manager: started next to it, that Runtime would
    -- shut it down. The original moves to startup-1x.ms and a small startup.ms decides, the same way 1.2.1 does.
    fn guardLegacyStartup legacyRoot = (
        local startupFile = legacyRoot + "startup.ms"
        if (not (doesFileExist startupFile)) do return false
        local fileClass = dotNetClass "System.IO.File"
        if ((findString (fileClass.ReadAllText startupFile) "MaxPkg-Runtime-Manager-Qt") != undefined) do return true
        local originalFile = legacyRoot + "startup-1x.ms"
        forceDeleteFile originalFile
        if (not (renameFile startupFile originalFile)) do return false
        local guardContent = ""
        guardContent += "-- Written by the MaxPkg Package Manager installer: this Runtime does not start next to it.\n"
        guardContent += "(\n"
        guardContent += "    local managerFolder = (getDir #temp) + @\"\\MaxPkg-Runtime-Manager-Qt\\\"\n"
        guardContent += "    local isManagerInstalled = (maxVersion())[1] >= 24000 and doesFileExist (managerFolder + @\"python\\startup.py\") and doesFileExist (managerFolder + \"version.ini\")\n"
        guardContent += "    if (not isManagerInstalled) do fileIn " + (maxScriptPathLiteral originalFile) + "\n"
        guardContent += ")\n"
        return writeTextFile startupFile guardContent
    )

    -- Deletes the previous Runtime (MaxPkg-Runtime-Manager) once the Package Manager runs: its startup script,
    -- MacroScripts and program files. Packages under data\packages\ stay where they are, because their own scripts point
    -- there. A failure here is only logged: the Package Manager already works, and the previous Runtime does not start
    -- next to it (its startup.ms checks for the Package Manager's folder).
    fn removeLegacyFiles legacyRoot temporaryRoot sourceRoot = (
        local startupRoot = ensureSlash (getDir #userStartupScripts)
        local userMacrosRoot = ensureSlash (getDir #userMacros)
        -- In a shared folder, another 3ds Max version may still use the startup script and macros. They load the program
        -- files by a fixed path, so those stay as well, or that 3ds Max would get an error at every start.
        if (not ((isOwnFolder startupRoot) and (isOwnFolder userMacrosRoot) and (isOwnFolder temporaryRoot))) do (
            format "MaxPkg kept the previous Runtime: its folders may be shared with another 3ds Max version.\n"
            if (not (guardLegacyStartup legacyRoot)) do format "MaxPkg could not guard the previous Runtime's startup script.\n"
            return false
        )
        -- The startup script goes first: left without its program files, it would fail at every start.
        local legacyFiles = #(
            startupRoot + "maxpkg-runtime-startup.ms",
            userMacrosRoot + "maxpkg-runtime-manager.mcr",
            userMacrosRoot + "MaxPkg-MaxPkg_Manager.mcr"
        )
        for legacyFile in legacyFiles do (
            if (not (forceDeleteFile legacyFile)) do (
                format "MaxPkg could not remove the previous Runtime file: %\n" legacyFile
                return false
            )
        )
        if (not (doesDirectoryExist legacyRoot)) do return true
        if ((findString (toLower sourceRoot) (toLower legacyRoot)) == 1) do return false  -- never delete the running installer
        local packagesRoot = legacyRoot + @"data\packages\"
        local keepPackages = (doesDirectoryExist packagesRoot) and (getDirectories (packagesRoot + "*")).count > 0
        for legacyFolder in (getDirectories (legacyRoot + "*")) do (
            local folderName = toLower (pathConfig.stripPathToLeaf (substring legacyFolder 1 (legacyFolder.count - 1)))
            if (not (keepPackages and folderName == "data")) do (
                if (not (forceDeleteFolder legacyFolder)) do format "MaxPkg could not remove the previous Runtime folder: %\n" legacyFolder
            )
        )
        for legacyFile in (getFiles (legacyRoot + "*")) do (
            if (not (forceDeleteFile legacyFile)) do format "MaxPkg could not remove the previous Runtime file: %\n" legacyFile
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

    fn installPackageManager sourceRoot temporaryRoot targetRoot runtimeVersion = (
        try (
            if ((toLower sourceRoot) == (toLower targetRoot)) do throw "The Package Manager cannot be installed over its source folder."
            if (temporaryRoot == "") do throw "The 3ds Max temporary folder is unavailable."
            local legacyRoot = temporaryRoot + @"MaxPkg-Runtime-Manager\"
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
            replaceFile (sourceRoot + "uninstall.ms") (targetRoot + "uninstall.ms")
            if (not (writeManagerMacro targetRoot)) do throw "Could not create the MaxPkg Manager (Qt) MacroScript."
            -- These two come last: from here on the previous Runtime no longer starts next to the Package Manager.
            -- Until here a failure leaves that Runtime working and untouched.
            local shimPath = (ensureSlash (getDir #userStartupScripts)) + "maxpkg-runtime-qt-startup.ms"
            replaceFile (sourceRoot + "version.ini") (targetRoot + "version.ini")
            if (not (writeStartupShim shimPath)) do throw "Could not create the startup script."
            local hasLegacyRuntime = doesFileExist (legacyRoot + "startup.ms")
            stopLegacyRuntime()
            keepLegacySettings legacyRoot targetRoot
            local startError = ""
            try (
                runPython (targetRoot + @"python\welcome.py")
            ) catch (
                startError = getCurrentException()
            )
            if (not (isPackageManagerRunning())) do (
                if (hasLegacyRuntime) do restoreLegacyRuntime legacyRoot targetRoot shimPath
                throw ("The Package Manager did not start. " + startError)
            )
            try (
                removeLegacyFiles legacyRoot temporaryRoot sourceRoot
            ) catch (
                format "MaxPkg could not remove the previous Runtime: %\n" (getCurrentException())
            )
            format "MaxPkg Package Manager % was installed to %\n" runtimeVersion targetRoot
            return true
        ) catch (
            messageBox ("MaxPkg Package Manager " + runtimeVersion + " could not be installed.\n\n" + (getCurrentException()) + "\n\nYour 3ds Max scenes were not changed. Close MaxPkg windows, restart 3ds Max and run the installer again.") title: "MaxPkg Runtime Setup"
            return false
        )
    )

    -- Checked before anything else: on an older 3ds Max nothing is removed, copied or written.
    local maxYear = currentMaxYear()
    if (maxYear < minimumMaxYear) then (
        messageBox ("MaxPkg Package Manager " + runtimeVersion + " needs 3ds Max " + (minimumMaxYear as string) + \
                    " or newer.\n\nThis is 3ds Max " + (maxYear as string) + ". Nothing was installed or changed: " + \
                    "your scripts, toolbars and an earlier MaxPkg Runtime keep working as before.") \
            title: "MaxPkg Package Manager"
    ) else (
        installPackageManager sourceRoot temporaryRoot targetRoot runtimeVersion
    )
)
