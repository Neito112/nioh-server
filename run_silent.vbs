Set WshShell = CreateObject("WScript.Shell")
strPath = Wscript.ScriptFullName
Set objFSO = CreateObject("Scripting.FileSystemObject")
Set objFile = objFSO.GetFile(strPath)
strFolder = objFSO.GetParentFolderName(objFile)

WshShell.CurrentDirectory = strFolder

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

scriptPath = strFolder & "\server\desktop_app.py"

' Chay backend server an cua so (chinh python se mo trinh duyet 1 lan duy nhat khi san sang)
WshShell.Run """" & pyExe & """ """ & scriptPath & """", 0, False
