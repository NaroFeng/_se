param(
    [Parameter(Position = 0)]
    [string]$Resource,

    [Parameter(Position = 1)]
    [string]$Id
)

$BASE_URL = "https://jsonplaceholder.typicode.com"

function Decode-Chunked {
    param([string]$Data)
    $out = ""
    $i = 0
    while ($i -lt $Data.Length) {
        $crlf = $Data.IndexOf("`r`n", $i)
        if ($crlf -lt 0) { break }
        $sizeStr = ($Data.Substring($i, $crlf - $i).Trim() -split ';', 2)[0]
        $size = 0
        if (-not [int]::TryParse($sizeStr, [System.Globalization.NumberStyles]::HexNumber, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$size)) {
            break
        }
        if ($size -eq 0) { break }
        $out += $Data.Substring($crlf + 2, $size)
        $i = $crlf + 2 + $size + 2
    }
    return $out
}

function Show-Usage {
    @"
Usage: fetch_raw.ps1 <resource> [id]

Examples:
  fetch_raw.ps1 posts
  fetch_raw.ps1 posts 1
  fetch_raw.ps1 users
"@
    exit 1
}

if (-not $Resource) { Show-Usage }

$path = "/$Resource"
if ($Id) { $path = "$path/$Id" }

$uri = [System.Uri]::new($BASE_URL)
$Server = $uri.Host
if ($uri.IsDefaultPort) {
    $port = if ($uri.Scheme -eq "https") { 443 } else { 80 }
} else {
    $port = $uri.Port
}
$useTls = $uri.Scheme -eq "https"

$client = [System.Net.Sockets.TcpClient]::new()
$client.Connect($Server, $port)

$stream = $client.GetStream()
$comm = $stream
if ($useTls) {
    $ssl = [System.Net.Security.SslStream]::new($stream, $false)
    $ssl.AuthenticateAsClient($Server)
    $comm = $ssl
}

$req = "GET $path HTTP/1.1`r`nHost: $Server`r`nUser-Agent: fetch_raw.ps1`r`nAccept: */*`r`nConnection: close`r`n`r`n"
$reqBytes = [System.Text.Encoding]::UTF8.GetBytes($req)
$comm.Write($reqBytes, 0, $reqBytes.Length)

$ms = New-Object System.IO.MemoryStream
$comm.CopyTo($ms)
$client.Close()

$text = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
$sep = "`r`n`r`n"
$idx = $text.IndexOf($sep)
if ($idx -lt 0) {
    [Console]::Error.WriteLine("Malformed HTTP response")
    exit 1
}

$head = $text.Substring(0, $idx)
$body = $text.Substring($idx + 4)

$lines = $head -split "`r`n"
$statusLine = $lines[0]
$parts = $statusLine.Split(' ', 3)
$status = 0
[int]::TryParse($parts[1], [ref]$status) | Out-Null
$reason = if ($parts.Count -ge 3) { $parts[2] } else { "" }

$headers = @{}
for ($i = 1; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match '^([^:]+):\s*(.*)$') {
        $headers[$Matches[1].ToLower()] = $Matches[2]
    }
}

$te = ""
if ($headers.ContainsKey('transfer-encoding')) { $te = $headers['transfer-encoding'].ToLower() }
if ($te -eq 'chunked') {
    $body = Decode-Chunked -Data $body
}

if ($status -ge 200 -and $status -lt 300) {
    [Console]::Out.Write($body)
    if (-not $body.EndsWith("`n")) { [Console]::Out.Write("`n") }
    exit 0
} else {
    [Console]::Error.WriteLine("HTTP $status $reason")
    [Console]::Error.Write($body)
    exit 1
}
