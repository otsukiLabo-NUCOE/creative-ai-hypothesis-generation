# collect_ratings.ps1 — 返送された 評価シート_R*.xlsx を ratings_R*.csv（UTF-8）に変換する
# Usage: powershell -ExecutionPolicy Bypass -File collect_ratings.ps1 -InDir <返送ファイルのフォルダ>
#        -> <InDir>\ratings_R1.csv, ratings_R2.csv, ...  then:
#        python analyze_manuscript_experiment.py ratings <InDir>\ratings_R1.csv <InDir>\ratings_R2.csv
param([Parameter(Mandatory = $true)][string]$InDir)
$InDir = (Resolve-Path $InDir).Path
$cols = @("position", "code", "soundness", "reproducibility", "significance", "comment")
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
try {
    foreach ($f in Get-ChildItem $InDir -Filter "評価シート_R*.xlsx") {
        $rater = [regex]::Match($f.BaseName, "R\d+").Value
        $wb = $xl.Workbooks.Open($f.FullName, 0, $true)
        $ws = $wb.Worksheets.Item("評価")
        $rows = @()
        for ($r = 4; $r -le 200; $r++) {
            $code = [string]$ws.Cells.Item($r, 2).Value2
            if (-not $code) { break }
            $o = [ordered]@{ rater = $rater }
            for ($c = 0; $c -lt $cols.Count; $c++) { $o[$cols[$c]] = [string]$ws.Cells.Item($r, $c + 1).Value2 }
            $rows += [pscustomobject]$o
        }
        $wb.Close($false)
        $out = Join-Path $InDir "ratings_$rater.csv"
        $rows | Export-Csv -Path $out -NoTypeInformation -Encoding UTF8
        $empty = ($rows | Where-Object { -not $_.soundness -or -not $_.reproducibility -or -not $_.significance }).Count
        "$($f.Name): $($rows.Count) rows -> $out  (rows with missing scores: $empty)"
    }
} finally { $xl.Quit() }
