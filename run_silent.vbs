Set WshShell = CreateObject("WScript.Shell")
strPath = Wscript.ScriptFullName
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objFile = objFSO.GetFile(strPath)
strFolder = objFSO.GetParentFolderName(objFile)

WshShell.CurrentDirectory = strFolder

If objFSO.FileExists(strFolder & "\.venv\Scripts\pythonw.exe") Then
    WshShell.Run """" & strFolder & "\.venv\Scripts\pythonw.exe"" -m server.desktop_app", 0, False
ElseIf objFSO.FileExists(strFolder & "\.venv\Scripts\python.exe") Then
    WshShell.Run """" & strFolder & "\.venv\Scripts\python.exe"" -m server.desktop_app", 0, False
Else
    WshShell.Run "pythonw -m server.desktop_app", 0, False
End If
