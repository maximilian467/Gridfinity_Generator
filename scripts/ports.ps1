# Hilfsfunktion: erster freier TCP-Port ab $Start
function Get-FreePort([int]$Start) {
    for ($p = $Start; $p -lt $Start + 200; $p++) {
        $l = $null
        try {
            $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
            $l.Start(); $l.Stop()
            return $p
        } catch { if ($l) { try { $l.Stop() } catch {} } }
    }
    throw "Kein freier Port ab $Start gefunden"
}
