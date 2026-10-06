# judge.ps1 - blinded LLM-as-judge evaluation (Windows PowerShell 5.1; no Python needed)
#   Stage 1 (absolute): every manuscript scored 3 times (seeds 1-3) with the calibrated rubric
#   Stage 2 (pairwise): every pair in pairs.csv judged in both orders (A/B and B/A)
#   Stage 3 (hypotheses): the 30 hypothesis sets of the human evaluation, each judged in 3 orders
# Each judgment is saved as soon as it is finished; re-running skips finished judgments.
param(
    [string]$Endpoint = "http://127.0.0.1:8090/v1/chat/completions",
    [string]$ModelLabel = "unknown-model",
    [string]$Stage = "all"            # all | absolute | pairwise | hypotheses
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$res = Join-Path $root ("results\" + $ModelLabel)
$absDir = Join-Path $res "absolute"
$pairDir = Join-Path $res "pairwise"
New-Item -ItemType Directory -Force $absDir, $pairDir | Out-Null
Start-Transcript -Path (Join-Path $res "judge_log.txt") -Append | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Read-Text($p) { return [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8) }
$system = Read-Text (Join-Path $root "prompts\system.txt")
$absTpl = Read-Text (Join-Path $root "prompts\absolute.txt")
$pairTpl = Read-Text (Join-Path $root "prompts\pairwise.txt")
$criteria = @("originality", "soundness", "reproducibility", "significance")

function Invoke-Judge([string]$userText, [int]$seed, [int]$maxTokens) {
    $payload = @{
        messages    = @(@{ role = "system"; content = $system }, @{ role = "user"; content = $userText })
        temperature = 0.7; top_p = 0.95; max_tokens = $maxTokens; seed = $seed
    }
    $json = $payload | ConvertTo-Json -Depth 6 -Compress
    $t0 = Get-Date
    try {
        $r = Invoke-RestMethod -Method Post -Uri $Endpoint -Body $utf8.GetBytes($json) `
            -ContentType "application/json; charset=utf-8" -TimeoutSec 7200
    } catch {
        Write-Host ("  [server error] " + $_.Exception.Message)
        Start-Sleep 10
        return @{ content = ""; parsed = $null; seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
    }
    $content = [string]$r.choices[0].message.content
    $parsed = $null
    $m = [regex]::Match($content, "\{[\s\S]*\}")
    if ($m.Success) { try { $parsed = $m.Value | ConvertFrom-Json } catch { $parsed = $null } }
    return @{ content = $content; parsed = $parsed; seconds = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) }
}

function Save-Json($obj, $path) { [IO.File]::WriteAllText($path, ($obj | ConvertTo-Json -Depth 8), $utf8) }

$codes = @(Get-ChildItem (Join-Path $root "manuscripts") -Filter "M*.md" | Sort-Object Name | ForEach-Object { $_.BaseName })
$text = @{}
foreach ($c in $codes) { $text[$c] = Read-Text (Join-Path $root "manuscripts\$c.md") }

# ---------------------------------------------------------------- Stage 1: absolute scores
if ($Stage -eq "all" -or $Stage -eq "absolute") {
    $n = 0; $total = $codes.Count * 3
    foreach ($c in $codes) {
        foreach ($run in 1..3) {
            $n++
            $out = Join-Path $absDir "${c}_run$run.json"
            if (Test-Path $out) { continue }
            $user = $absTpl.Replace("{CODE}", $c).Replace("{TEXT}", $text[$c])
            $ok = $false
            for ($a = 0; $a -lt 4 -and -not $ok; $a++) {
                $j = Invoke-Judge $user ($run + 100 * $a) 700
                $p = $j.parsed
                if ($p) { $ok = $true; foreach ($k in $criteria) { $v = $p.$k -as [int]; if (-not $v -or $v -lt 1 -or $v -gt 5) { $ok = $false } } }
            }
            if (-not $ok) { Write-Host "[absolute] $c run$run : no valid answer, skipped"; continue }
            Save-Json @{ code = $c; run = $run; model = $ModelLabel; attempt = $a - 1; seconds = $j.seconds
                         judgment = $p; raw = $j.content } $out
            Write-Host ("[absolute {0}/{1}] {2} run{3}: O={4} S={5} R={6} Sig={7} ({8}s)" -f $n, $total, $c, $run,
                        $p.originality, $p.soundness, $p.reproducibility, $p.significance, $j.seconds)
        }
    }
}

# ---------------------------------------------------------------- Stage 2: pairwise comparisons
if ($Stage -eq "all" -or $Stage -eq "pairwise") {
    $pairs = @(Import-Csv (Join-Path $root "pairs.csv"))
    $n = 0; $total = $pairs.Count * 2
    foreach ($pr in $pairs) {
        foreach ($order in @("AB", "BA")) {
            $n++
            $out = Join-Path $pairDir ("{0}_{1}.json" -f $pr.pair_id, $order)
            if (Test-Path $out) { continue }
            if ($order -eq "AB") { $first = $pr.a; $second = $pr.b } else { $first = $pr.b; $second = $pr.a }
            $user = $pairTpl.Replace("{TEXT_A}", $text[$first]).Replace("{TEXT_B}", $text[$second])
            $ok = $false
            for ($a = 0; $a -lt 4 -and -not $ok; $a++) {
                $j = Invoke-Judge $user (1 + 100 * $a) 400
                $p = $j.parsed
                if ($p) { $ok = $true; foreach ($k in ($criteria + "overall")) { if (@("A", "B") -notcontains ([string]$p.$k).Trim()) { $ok = $false } } }
            }
            if (-not $ok) { Write-Host "[pairwise] $($pr.pair_id) $order : no valid answer, skipped"; continue }
            Save-Json @{ pair_id = $pr.pair_id; order = $order; shown_as_A = $first; shown_as_B = $second
                         model = $ModelLabel; attempt = $a - 1; seconds = $j.seconds; judgment = $p; raw = $j.content } $out
            Write-Host ("[pairwise {0}/{1}] {2} {3}: A={4} B={5} overall={6} ({7}s)" -f $n, $total, $pr.pair_id, $order,
                        $first, $second, $p.overall, $j.seconds)
        }
    }
}

# ---------------------------------------------------------------- Stage 3: hypothesis sets (same 30 sets as the human raters)
if (($Stage -eq "all" -or $Stage -eq "hypotheses") -and (Test-Path (Join-Path $root "hypothesis_sets.json"))) {
    $hypDir = Join-Path $res "hypotheses"
    New-Item -ItemType Directory -Force $hypDir | Out-Null
    $hypTpl = Read-Text (Join-Path $root "prompts\hypotheses.txt")
    # PowerShell 5.1 emits a JSON array from the pipeline as ONE object, so @(... | ConvertFrom-Json) would give a
    # single element holding all 30 sets. -InputObject plus an explicit check avoids that.
    $sets = ConvertFrom-Json -InputObject (Read-Text (Join-Path $root "hypothesis_sets.json"))
    $sets = @($sets)
    if ($sets.Count -ne 30 -or ($sets[0].tid -isnot [string])) { throw "hypothesis_sets.json was not read as 30 sets (got $($sets.Count))" }
    $rotations = @(@("A", "B", "C"), @("B", "C", "A"), @("C", "A", "B"))   # each set judged in 3 orders
    $n = 0; $total = $sets.Count * 3
    foreach ($s in $sets) {
        for ($k = 0; $k -lt 3; $k++) {
            $n++
            $rot = $rotations[$k]
            $out = Join-Path $hypDir ("{0}_rot{1}.json" -f $s.tid, ($k + 1))
            if (Test-Path $out) { continue }
            $user = $hypTpl
            for ($i = 0; $i -lt 3; $i++) {
                $item = $s.items.($rot[$i])
                $user = $user.Replace("{H$($i + 1)}", "Hypothesis: " + $item.hypothesis + "`nDescription: " + $item.description)
            }
            $ok = $false
            for ($a = 0; $a -lt 4 -and -not $ok; $a++) {
                $j = Invoke-Judge $user (1 + 100 * $a) 300
                $p = $j.parsed
                if ($p) {
                    $v = @(([string]$p.most_useful).Trim(), ([string]$p.least_useful).Trim(), ([string]$p.most_novel).Trim(), ([string]$p.least_novel).Trim())
                    $ok = (@($v | Where-Object { @("1", "2", "3") -notcontains $_ }).Count -eq 0) -and ($v[0] -ne $v[1]) -and ($v[2] -ne $v[3])
                }
            }
            if (-not $ok) { Write-Host "[hypotheses] $($s.tid) rot$($k + 1) : no valid answer, skipped"; continue }
            $map = @{ "1" = $rot[0]; "2" = $rot[1]; "3" = $rot[2] }     # displayed number -> original letter
            Save-Json @{ tid = $s.tid; rotation = ($rot -join ""); model = $ModelLabel; attempt = $a - 1; seconds = $j.seconds
                         most_useful = $map[$v[0]]; least_useful = $map[$v[1]]; most_novel = $map[$v[2]]; least_novel = $map[$v[3]]
                         judgment = $p; raw = $j.content } $out
            Write-Host ("[hypotheses {0}/{1}] {2} order {3}: useful +{4} -{5} | novel +{6} -{7} ({8}s)" -f $n, $total, $s.tid,
                        ($rot -join ""), $map[$v[0]], $map[$v[1]], $map[$v[2]], $map[$v[3]], $j.seconds)
        }
    }
    $hr = Get-ChildItem $hypDir -Filter *.json | ForEach-Object {
        $d = Read-Text $_.FullName | ConvertFrom-Json
        [pscustomobject]@{ rater = "LLM-" + $d.rotation; tid = $d.tid; most_useful = $d.most_useful; least_useful = $d.least_useful
                           most_novel = $d.most_novel; least_novel = $d.least_novel; comment = $d.judgment.rationale }
    }
    if ($hr) { $hr | Export-Csv (Join-Path $res "hypothesis_rankings.csv") -NoTypeInformation -Encoding UTF8 }
}

# ---------------------------------------------------------------- summary CSVs
$abs = Get-ChildItem $absDir -Filter *.json | ForEach-Object {
    $d = Read-Text $_.FullName | ConvertFrom-Json
    [pscustomobject]@{ rater = "LLM-run$($d.run)"; code = $d.code; originality = $d.judgment.originality
        soundness = $d.judgment.soundness; reproducibility = $d.judgment.reproducibility
        significance = $d.judgment.significance; comment = $d.judgment.rationale }
}
if ($abs) { $abs | Export-Csv (Join-Path $res "absolute_ratings.csv") -NoTypeInformation -Encoding UTF8 }
$pw = Get-ChildItem $pairDir -Filter *.json | ForEach-Object {
    $d = Read-Text $_.FullName | ConvertFrom-Json
    $o = [ordered]@{ pair_id = $d.pair_id; order = $d.order; shown_as_A = $d.shown_as_A; shown_as_B = $d.shown_as_B }
    foreach ($k in ($criteria + "overall")) {
        $w = ([string]$d.judgment.$k).Trim()
        $o["winner_$k"] = $(if ($w -eq "A") { $d.shown_as_A } else { $d.shown_as_B })
    }
    [pscustomobject]$o
}
if ($pw) { $pw | Export-Csv (Join-Path $res "pairwise_results.csv") -NoTypeInformation -Encoding UTF8 }
Write-Host ("Done. absolute: {0}/90, pairwise: {1}/180  -> {2}" -f @($abs).Count, @($pw).Count, $res)
Stop-Transcript | Out-Null
