Option Explicit
Dim shell, fso, base, launcher, pyw
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(base, "desktop.py")
pyw = fso.BuildPath(base, ".venv\Scripts\pythonw.exe")
If Not fso.FileExists(pyw) Then
    MsgBox "Brak lokalnego srodowiska Desktop. Uruchom najpierw INSTALUJ_TRYB_DESKTOP.bat.", 16, "RK KANCELARIA"
    WScript.Quit 1
End If
shell.Run Chr(34) & pyw & Chr(34) & " " & Chr(34) & launcher & Chr(34), 0, False
