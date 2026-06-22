Set shell = CreateObject("WScript.Shell")
Dim scriptDir
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\.venv\Scripts\pythonw.exe"" """ & scriptDir & "\run.py""", 0, False
