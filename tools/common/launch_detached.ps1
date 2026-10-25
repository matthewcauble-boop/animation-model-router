# Launch a long Python job detached and with NO console window, so it survives the agent being interrupted
# and never pops a terminal on the user's screen.
#   powershell -File tools/common/launch_detached.ps1 -Script tools/bakeoff/bake.py -Args "bake/jobs.json" -Log bake/work/launch.log
# The job itself writes STATUS.json; check that (or the newest file times in its folder), not the agent.
param(
  [Parameter(Mandatory = $true)][string]$Script,
  [string]$Args = "",
  [string]$Log = "detached.log"
)
$pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = (Get-Command python.exe).Source }   # falls back to python.exe, still hidden below
$argList = @("-u", $Script) + ($Args -split ' ' | Where-Object { $_ -ne '' })
$p = Start-Process -FilePath $pyw -ArgumentList $argList -WindowStyle Hidden -PassThru `
       -RedirectStandardOutput $Log -RedirectStandardError ($Log + ".err")
Write-Output ("started pid {0}; log {1}" -f $p.Id, $Log)
