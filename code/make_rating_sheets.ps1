# make_rating_sheets.ps1 — builds 評価シート_R1.xlsx / _R2.xlsx with Excel (COM), from order_R*.csv
# Usage: powershell -File make_rating_sheets.ps1 -Raters 2
param([int]$Raters = 2)
$pkg = Join-Path $PSScriptRoot "..\rater_package"
$pkg = (Resolve-Path $pkg).Path
$headers = @("Position 順番", "Code 原稿番号", "Soundness 技術的妥当性 (1-5)",
             "Reproducibility 再現性 (1-5)", "Significance 重要性 (1-5)", "Comment コメント (任意)")
$widths = @(9, 11, 16, 15, 15, 70)

function Add-RatingSheet($ws, $title, $codes) {
    $ws.Cells.Item(1, 1).Value2 = $title
    $ws.Cells.Item(1, 1).Font.Bold = $true
    $ws.Cells.Item(1, 1).Font.Size = 13
    $ws.Cells.Item(2, 1).Value2 = "マニュアルの採点基準に従い、上から順に記入してください。点数欄はプルダウンから選べます。"
    for ($j = 0; $j -lt $headers.Count; $j++) {
        $c = $ws.Cells.Item(3, $j + 1)
        $c.Value2 = $headers[$j]; $c.Font.Bold = $true; $c.WrapText = $true
        $c.Interior.Color = 0xD9D9D9
        $ws.Columns.Item($j + 1).ColumnWidth = $widths[$j]
    }
    $ws.Rows.Item(3).RowHeight = 45
    $n = $codes.Count
    for ($i = 0; $i -lt $n; $i++) {
        $ws.Cells.Item(4 + $i, 1).Value2 = [string]$codes[$i].position
        $ws.Cells.Item(4 + $i, 2).Value2 = [string]$codes[$i].code
    }
    $last = 3 + $n
    foreach ($col in @("C", "D", "E")) {
        $v = $ws.Range("${col}4:${col}$last").Validation
        $v.Delete(); $v.Add(3, 1, 1, "1,2,3,4,5")
        $v.ErrorMessage = "1〜5の整数を選んでください"
    }
    $rng = $ws.Range("A3:F$last")
    $rng.Borders.LineStyle = 1
    $ws.Range("A4:E$last").HorizontalAlignment = -4108
    $ws.Range("F4:F$last").WrapText = $true
    $ws.Range("C4:E$last").Interior.Color = 0xF2FFFF
    $ws.Activate()
    $ws.Application.ActiveWindow.SplitRow = 3
    $ws.Application.ActiveWindow.FreezePanes = $true
}

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
try {
    for ($r = 1; $r -le $Raters; $r++) {
        $order = Import-Csv (Join-Path $pkg "order_R$r.csv")
        $wb = $xl.Workbooks.Add()
        while ($wb.Worksheets.Count -lt 3) { [void]$wb.Worksheets.Add([Type]::Missing, $wb.Worksheets.Item($wb.Worksheets.Count)) }
        $ws1 = $wb.Worksheets.Item(1); $ws1.Name = "評価"
        $ws2 = $wb.Worksheets.Item(2); $ws2.Name = "練習"
        $ws3 = $wb.Worksheets.Item(3); $ws3.Name = "評価者情報"
        Add-RatingSheet $ws2 "練習用（分析には使いません）: P00_practice.docx" @([pscustomobject]@{position = 0; code = "P00"})
        Add-RatingSheet $ws1 "評価シート — 評価者 R$r（$(@($order).Count)本）" $order
        $info = @(@("評価者ID", "R$r"), @("氏名", ""), @("所属", ""), @("専門分野", ""),
                  @("この研究に著者・共同研究者・助言者として関わっていない", ""),
                  @("論文の謝辞への氏名掲載", ""), @("備考", ""))
        for ($i = 0; $i -lt $info.Count; $i++) {
            $ws3.Cells.Item($i + 1, 1).Value2 = $info[$i][0]; $ws3.Cells.Item($i + 1, 1).Font.Bold = $true
            $ws3.Cells.Item($i + 1, 2).Value2 = $info[$i][1]
        }
        $ws3.Columns.Item(1).ColumnWidth = 52; $ws3.Columns.Item(2).ColumnWidth = 40
        $v = $ws3.Range("B5").Validation; $v.Delete(); $v.Add(3, 1, 1, "はい,いいえ")
        $v = $ws3.Range("B6").Validation; $v.Delete(); $v.Add(3, 1, 1, "可,不可")
        $ws3.Range("A1:B7").Borders.LineStyle = 1
        $ws3.Range("B1:B7").Interior.Color = 0xF2FFFF
        $ws1.Activate()
        $out = Join-Path $pkg "R$r\評価シート_R$r.xlsx"
        if (Test-Path $out) { Remove-Item $out -Confirm:$false }
        $wb.SaveAs($out, 51)
        $wb.Close($false)
        "saved $out"
    }
} finally { $xl.Quit() }
