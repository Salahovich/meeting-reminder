Set shell = CreateObject("WScript.Shell")
Dim scriptDir
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir & "\electron"
shell.Run """" & scriptDir & "\electron\node_modules\electron\dist\electron.exe"" """ & scriptDir & "\electron""", 0, False
