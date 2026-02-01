$ErrorActionPreference = 'Continue'
$log = 'C:\Users\ajtwl\OneDrive\바탕 화면\lol_pick_ai\logs\collect_20260126_233812.log'
$py  = "C:\Users\ajtwl\AppData\Local\Programs\Python\Python313\python.exe"
$args = @(
  'collector_graph.py',
  '--seed','파뽀마블#KRI',
  '--target_patch','latest2',
  '--matches_per_player','20',
  '--max_players','2000',
  '--db','lol_graph.db',
  '--fast','--debug'
)
& $py @args 2>&1 | Tee-Object -FilePath $log
exit $LASTEXITCODE
