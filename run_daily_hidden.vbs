' Launches the daily job-search runner with a hidden console window (no flash).
' Self-locating: paths are derived from this script's own folder, so it works
' from any clone location without editing. Uses python.exe (real stdout/stderr)
' run hidden (window style 0).
Dim fso, here, py, script
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
py = here & "\.venv\Scripts\python.exe"
script = here & "\run_daily.py"
CreateObject("WScript.Shell").Run """" & py & """ """ & script & """", 0, True
