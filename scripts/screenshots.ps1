# Captures each report page from the running Power BI Desktop window into docs/img/.
# Run after scripts/verify.ps1 -KeepOpen. Page tabs are selected through UI Automation.
param([string[]]$Pages = @("Overview", "Vendors", "Work queue"))
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$outDir = Join-Path $root "docs\img"
New-Item -ItemType Directory -Force $outDir | Out-Null
Add-Type -AssemblyName System.Drawing, UIAutomationClient, UIAutomationTypes
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  public struct RECT { public int L, T, R, B; }
}
"@
[Win]::SetProcessDPIAware() | Out-Null
$p = Get-Process PBIDesktop | Where-Object { $_.MainWindowTitle -eq "RecoveryBI" } | Select-Object -First 1
if (-not $p) { throw "open the report first (scripts/verify.ps1 -KeepOpen)" }
$h = $p.MainWindowHandle
[Win]::ShowWindow($h, 3) | Out-Null
[Win]::SetForegroundWindow($h) | Out-Null
$rootEl = [System.Windows.Automation.AutomationElement]::FromHandle($h)

function Capture([string]$path) {
    $r = New-Object Win+RECT; [Win]::GetWindowRect($h, [ref]$r) | Out-Null
    $bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $dc = $g.GetHdc(); [Win]::PrintWindow($h, $dc, 2) | Out-Null; $g.ReleaseHdc($dc)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
}

function Find([string]$name, [string]$type) {
    $cond = New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::NameProperty), $name
    for ($i = 0; $i -lt 10; $i++) {
        $el = $rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) |
            Where-Object { $_.Current.ControlType.ProgrammaticName -match $type } | Select-Object -First 1
        if ($el) { return $el }
        Start-Sleep -Seconds 1
    }
}

function Activate($el) {
    $pat = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pat)) { $pat.Select() }
    elseif ($el.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pat)) { $pat.Invoke() }
}

# Crop to the report page: the white rectangle left of the Filters pane, between ribbon and page tabs.
function CropToPage([string]$src, [string]$dst, [int]$right, [int]$top, [int]$bottom) {
    $bmp = [System.Drawing.Bitmap]::FromFile($src)
    # The page is a white rectangle on a grey canvas. Find its top-left corner, then follow its first
    # row and column (page margin, always white) until they leave the page.
    $isWhite = { param($x, $y) $c = $bmp.GetPixel($x, $y); $c.R -gt 250 -and $c.G -gt 250 -and $c.B -gt 250 }
    $midY = [int](($top + $bottom) / 2)
    $x0 = 0; while ($x0 -lt $right -and -not (& $isWhite $x0 $midY)) { $x0++ }
    $y0 = $top; while ($y0 -lt $bottom -and -not (& $isWhite ($x0 + 4) $y0)) { $y0++ }
    $x1 = $x0; while ($x1 + 1 -lt $bmp.Width -and (& $isWhite ($x1 + 1) ($y0 + 3))) { $x1++ }
    $y1 = $bottom - 1; while ($y1 -gt $y0 -and -not (& $isWhite ($x0 + 3) $y1)) { $y1-- }  # up from the grey canvas
    $rect = New-Object System.Drawing.Rectangle $x0, $y0, ($x1 - $x0 + 1), ($y1 - $y0 + 1)
    $crop = $bmp.Clone($rect, $bmp.PixelFormat); $bmp.Dispose()
    $crop.Save($dst, [System.Drawing.Imaging.ImageFormat]::Png); $crop.Dispose()
}

# Dismiss teaching popups (e.g. "Optimize your report for mobile"): their close button is the
# "Close" button with class close-btn; the window's own close button has another class.
$cond = New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::NameProperty), "Close"
$rootEl.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond) |
    Where-Object { $_.Current.ClassName -eq "close-btn" } | ForEach-Object { Activate $_; Start-Sleep -Seconds 1 }
$win = New-Object Win+RECT; [Win]::GetWindowRect($h, [ref]$win) | Out-Null
$filters = (Find "Filters" "Text|Header|Group|Button").Current.BoundingRectangle

foreach ($name in $Pages) {
    $tab = Find $name "TabItem"
    if (-not $tab) { Write-Warning "page tab '$name' not found"; continue }
    Activate $tab
    Start-Sleep -Seconds 6
    $slug = $name.ToLower() -replace " ", "-"
    $raw = Join-Path $outDir "raw-$slug.png"
    Capture $raw
    $tabTop = [int]($tab.Current.BoundingRectangle.Top - $win.T)
    $right = if ($filters) { [int]($filters.Left - $win.L) } else { [int](($win.R - $win.L) * 0.6) }
    CropToPage $raw (Join-Path $outDir "$slug.png") $right 300 ($tabTop - 10)
    Remove-Item $raw
    Write-Output (Join-Path $outDir "$slug.png")
}
