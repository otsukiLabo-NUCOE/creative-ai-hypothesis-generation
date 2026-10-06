# collect_hyp_ratings.ps1 — 返送された 評価シート_仮説_R*.xlsx を ratings_hyp_R*.csv（UTF-8）に変換する
# Usage: powershell -ExecutionPolicy Bypass -File collect_hyp_ratings.ps1 -InDir <返送ファイルのフォルダ>
#        then: python analyze_hypothesis_eval.py <InDir>\ratings_hyp_R1.csv <InDir>\ratings_hyp_R2.csv [--llm ...]
param([Parameter(Mandatory = $true)][string]$InDir)
$InDir = (Resolve-Path $InDir).Path
$cols = @("position", "tid", "most_useful", "least_useful", "most_novel", "least_novel", "comment")
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
try {
    foreach ($f in Get-ChildItem $InDir -Filter "評価シート_仮説_R*.xlsx") {
        $rater = [regex]::Match($f.BaseName, "R\d+").Value
        $wb = $xl.Workbooks.Open($f.FullName, 0, $true)
        $ws = $wb.Worksheets.Item("評価")
        $rows = @()
        for ($r = 4; $r -le 100; $r++) {
            $tid = [string]$ws.Cells.Item($r, 2).Value2
            if (-not $tid) { break }
            $o = [ordered]@{ rater = $rater }
            for ($c = 0; $c -lt $cols.Count; $c++) { $o[$cols[$c]] = ([string]$ws.Cells.Item($r, $c + 1).Value2).Trim().ToUpper() }
            $o["comment"] = [string]$ws.Cells.Item($r, 7).Value2
            $rows += [pscustomobject]$o
        }
        $wb.Close($false)
        $out = Join-Path $InDir "ratings_hyp_$rater.csv"
        $rows | Export-Csv -Path $out -NoTypeInformation -Encoding UTF8
        $bad = ($rows | Where-Object { -not $_.most_useful -or -not $_.least_useful -or -not $_.most_novel -or -not $_.least_novel -or
                                       $_.most_useful -eq $_.least_useful -or $_.most_novel -eq $_.least_novel }).Count
        "$($f.Name): $($rows.Count) rows -> $out  (incomplete or invalid rows: $bad)"
    }
} finally { $xl.Quit() }
