Set WshShell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
query = "Select * from Win32_Process Where Name = 'python.exe' And CommandLine Like '%market_analyzer.py%'"
Set processes = wmi.ExecQuery(query)

isRunning = False
For Each p in processes
    isRunning = True
Next

scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Silent startup mode (no popups) if argument is passed
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "autostart" Then
        If Not isRunning Then
            WshShell.Run "python """ & scriptDir & "\market_analyzer.py""", 0, False
        End If
        WScript.Quit
    End If
End If

' Interactive UI mode
If isRunning Then
    response = MsgBox("The Market Analyzer is CURRENTLY RUNNING in the background." & vbCrLf & vbCrLf & "Would you like to STOP it?", vbYesNo + vbInformation, "Market Analyzer Manager")
    If response = vbYes Then
        For Each p in processes
            p.Terminate()
        Next
        MsgBox "Bot successfully stopped.", vbInformation, "Market Analyzer Manager"
    End If
Else
    response = MsgBox("The Market Analyzer is NOT RUNNING." & vbCrLf & vbCrLf & "Would you like to START it silently in the background?", vbYesNo + vbInformation, "Market Analyzer Manager")
    If response = vbYes Then
        WshShell.Run "python """ & scriptDir & "\market_analyzer.py""", 0, False
        MsgBox "Bot successfully started! It will run invisibly every 6 hours.", vbInformation, "Market Analyzer Manager"
    End If
End If
