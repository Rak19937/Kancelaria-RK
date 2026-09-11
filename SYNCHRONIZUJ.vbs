Option Explicit
Dim shell, fso, base, pyw, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = fso.BuildPath(base, ".venv\Scripts\pythonw.exe")
script = fso.BuildPath(base, "rk_sync.py")
If Not fso.FileExists(pyw) Then
    MsgBox "Brak środowiska RK KANCELARIA. Uruchom najpierw INSTALUJ_PELNA_WERSJE.bat.", 16, "RK KANCELARIA"
    WScript.Quit 1
End If
shell.Run Chr(34) & pyw & Chr(34) & " " & Chr(34) & script & Chr(34) & " --gui", 0, False
