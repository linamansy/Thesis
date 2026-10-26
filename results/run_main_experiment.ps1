# Runs the real experiment: repetitions 1, 2, 3 (default run ids ollama_rep1..3), each with C1, C2, C3 on all 13 cases.
# Stops at the first failure. Rerun this same script to resume: complete conditions are skipped,
# unfinished ones continue (run_experiment.py skips finished cases itself).
Set-Location "C:\Users\user\Downloads\Thesis"
$env:PYTHONIOENCODING = "utf-8"
$log = "results\logs\main_experiment_console.log"
function Note($text) { "=== $(Get-Date -Format s) $text" | Out-File -Append -Encoding utf8 $log }

Note "START (PID $PID)"
foreach ($rep in 1..3) {
    foreach ($cond in "C1", "C2", "C3") {
        $info = "results\runs\ollama_rep$rep\run_info.json"
        if ((Test-Path $info) -and (Get-Content $info -Raw | ConvertFrom-Json).conditions.$cond.complete) {
            Note "rep $rep $cond already complete, skipped"
            continue
        }
        Note "rep $rep $cond START"
        & .\.venv\Scripts\python.exe -u run_experiment.py --condition $cond --repetition $rep 2>&1 |
            ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
        $code = $LASTEXITCODE
        Note "rep $rep $cond END (exit code $code)"
        if ($code -ne 0) { Note "STOPPED at rep $rep $cond. Fix the cause, then run this script again to resume."; exit $code }
    }
}
Note "ALL DONE: ollama_rep1, ollama_rep2, ollama_rep3 complete"
