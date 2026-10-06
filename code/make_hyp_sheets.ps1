# make_hyp_sheets.ps1 — 仮説評価の回答シート（評価シート_仮説_R1/R2.xlsx）を Excel(COM) で作成する
param([int]$Raters = 2)
$res = (Resolve-Path (Join-Path $PSScriptRoot "..\results\hypothesis_eval")).Path
$pkg = Join-Path $PSScriptRoot "..\rater_package_hypotheses"
New-Item -ItemType Directory -Force $pkg | Out-Null
$pkg = (Resolve-Path $pkg).Path
$headers = @("Position 順番", "Set 組ID", "Most useful 最も有用 (A/B/C)", "Least useful 最も有用でない (A/B/C)", "Most novel 最も新しい (A/B/C)", "Least novel 最も新しくない (A/B/C)", "Comment コメント (任意)")
$widths = @(9, 10, 18, 20, 18, 20, 55)

function Add-Sheet($ws, $title, $rows) {
    $ws.Cells.Item(1, 1).Value2 = $title
    $ws.Cells.Item(1, 1).Font.Bold = $true; $ws.Cells.Item(1, 1).Font.Size = 13
    $ws.Cells.Item(2, 1).Value2 = "冊子の各組を読み、有用性と新しさのそれぞれについて、最も高い仮説と最も低い仮説を A/B/C からプルダウンで選んでください（同じ観点で同じ記号は選べません）。"
    for ($j = 0; $j -lt $headers.Count; $j++) {
        $c = $ws.Cells.Item(3, $j + 1); $c.Value2 = $headers[$j]; $c.Font.Bold = $true; $c.WrapText = $true
        $c.Interior.Color = 0xD9D9D9; $ws.Columns.Item($j + 1).ColumnWidth = $widths[$j]
    }
    $ws.Rows.Item(3).RowHeight = 34
    $n = @($rows).Count
    for ($i = 0; $i -lt $n; $i++) {
        $ws.Cells.Item(4 + $i, 1).Value2 = [string]$rows[$i].position
        $ws.Cells.Item(4 + $i, 2).Value2 = [string]$rows[$i].tid
    }
    $last = 3 + $n
    foreach ($col in @("C", "D", "E", "F")) {
        $v = $ws.Range("${col}4:${col}$last").Validation; $v.Delete(); $v.Add(3, 1, 1, "A,B,C")
        $v.ErrorMessage = "A, B, C のいずれかを選んでください"
    }
    $ws.Range("C4:F$last").Interior.Color = 0xF2FFFF
    $fc = $ws.Range("C4:D$last").FormatConditions.Add(2, 0, '=AND($C4<>"",$C4=$D4)')
    $fc.Interior.Color = 0x9999FF
    $fc2 = $ws.Range("E4:F$last").FormatConditions.Add(2, 0, '=AND($E4<>"",$E4=$F4)')
    $fc2.Interior.Color = 0x9999FF
    $ws.Range("A3:G$last").Borders.LineStyle = 1
    $ws.Range("A4:F$last").HorizontalAlignment = -4108
    $ws.Range("G4:G$last").WrapText = $true
    $ws.Activate(); $ws.Application.ActiveWindow.SplitRow = 3; $ws.Application.ActiveWindow.FreezePanes = $true
}

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
try {
    for ($r = 1; $r -le $Raters; $r++) {
        $order = @(Import-Csv (Join-Path $res "order_R$r.csv"))
        $wb = $xl.Workbooks.Add()
        while ($wb.Worksheets.Count -lt 3) { [void]$wb.Worksheets.Add([Type]::Missing, $wb.Worksheets.Item($wb.Worksheets.Count)) }
        $ws1 = $wb.Worksheets.Item(1); $ws1.Name = "評価"
        $ws2 = $wb.Worksheets.Item(2); $ws2.Name = "練習"
        $ws3 = $wb.Worksheets.Item(3); $ws3.Name = "評価者情報"
        Add-Sheet $ws2 "練習用（分析には使いません）" @([pscustomobject]@{ position = 0; tid = "P0" })
        Add-Sheet $ws1 "評価シート（仮説） — 評価者 R$r（$($order.Count)組）" $order
        $info = @(@("評価者ID", "R$r"), @("氏名", ""), @("所属", ""), @("専門分野", ""),
                  @("この研究に著者・共同研究者・助言者として関わっていない", ""), @("論文の謝辞への氏名掲載", ""), @("備考", ""))
        for ($i = 0; $i -lt $info.Count; $i++) {
            $ws3.Cells.Item($i + 1, 1).Value2 = $info[$i][0]; $ws3.Cells.Item($i + 1, 1).Font.Bold = $true
            $ws3.Cells.Item($i + 1, 2).Value2 = $info[$i][1]
        }
        $ws3.Columns.Item(1).ColumnWidth = 52; $ws3.Columns.Item(2).ColumnWidth = 40
        $v = $ws3.Range("B5").Validation; $v.Delete(); $v.Add(3, 1, 1, "はい,いいえ")
        $v = $ws3.Range("B6").Validation; $v.Delete(); $v.Add(3, 1, 1, "可,不可")
        $ws3.Range("A1:B7").Borders.LineStyle = 1; $ws3.Range("B1:B7").Interior.Color = 0xF2FFFF
        $ws1.Activate()
        $dir = Join-Path $pkg "R$r"; New-Item -ItemType Directory -Force $dir | Out-Null
        $out = Join-Path $dir "評価シート_仮説_R$r.xlsx"
        if (Test-Path $out) { Remove-Item $out -Confirm:$false }
        $wb.SaveAs($out, 51); $wb.Close($false)
        "saved $out"
    }
} finally { $xl.Quit() }
