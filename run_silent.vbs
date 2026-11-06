Set WshShell = CreateObject("WScript.Shell")
strPath = Wscript.ScriptFullName
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objFile = objFSO.GetFile(strPath)
strFolder = objFSO.GetParentFolderName(objFile)

WshShell.CurrentDirectory = strFolder

Set oEnv = WshShell.Environment("PROCESS")
oEnv("PYTHONPATH") = strFolder

Dim pyExe
If objFSO.FileExists(strFolder & "\.venv\Scripts\pythonw.exe") Then
    pyExe = strFolder & "\.venv\Scripts\pythonw.exe"
ElseIf objFSO.FileExists("C:\Python313\pythonw.exe") Then
    pyExe = "C:\Python313\pythonw.exe"
ElseIf objFSO.FileExists("C:\Python312\pythonw.exe") Then
    pyExe = "C:\Python312\pythonw.exe"
Else
    pyExe = "pythonw.exe"
End If

' Chay backend server an cua so
WshShell.Run """" & pyExe & """ -m server.desktop_app", 0, False

' Cho server khoi dong va mo trinh duyet
WScript.Sleep 1500
WshShell.Run "cmd /c start http://localhost:8001", 0, False
