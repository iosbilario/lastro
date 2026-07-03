# Lastro : verificador para Windows, 100% PowerShell nativo. Sem exe, sem
# SmartScreen, sem instalar nada: o desgaste do SSD vem do proprio Windows
# (StorageReliabilityCounter), a bateria do powercfg, tudo assinado pela
# Microsoft. Rodar com:
#   irm https://raw.githubusercontent.com/iosbilario/lastro/main/site/go.ps1 | iex
# Regra de ouro (a mesma do agente Python): leitura que falha PARA com
# instrucao clara. Nenhum numero e inventado, nunca.
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$VERSAO = "1.7.1"
$SELF_URL = "https://raw.githubusercontent.com/iosbilario/lastro/main/site/go.ps1"
$SITE = "https://iosbilario.github.io/lastro"
$CLIENT_ID = "Ov23liWw9JYNfAI8V5in"
$REPO_PASSAPORTE = "lastro-passaporte"
$REKOR = "https://rekor.sigstore.dev"

# ---------------------------------------------------------------- utilidades

function Sha256Hex([byte[]]$bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "" }
    finally { $sha.Dispose() }
}

function Falha($msg) {
    Write-Host ""
    Write-Host "lastro: parou sem emitir nada." -ForegroundColor Red
    Write-Host $msg -ForegroundColor Red
    if (-not $env:LASTRO_LIB) { Read-Host "pressione Enter para fechar" | Out-Null }
    throw $msg
}

function JsonBonito($obj) { ($obj | ConvertTo-Json -Depth 10) + "`n" }

# ------------------------------------------------------------------ leituras

function Le-Serie {
    $uuid = (Get-CimInstance Win32_ComputerSystemProduct).UUID
    if (-not $uuid -or $uuid -eq "00000000-0000-0000-0000-000000000000") {
        Falha "nao consegui ler um identificador estavel da placa. Sem serie estavel nao ha passaporte."
    }
    $h = (Sha256Hex ([Text.Encoding]::UTF8.GetBytes($uuid))).ToUpper()
    "BR-$($h.Substring(0,2))-$($h.Substring(2,4))"
}

function Estado-Ssd($desgaste) {
    if ($desgaste -ge 0.6) { "critico" } elseif ($desgaste -ge 0.4) { "atencao" } else { "saudavel" }
}

function Acha-Smartctl {
    $c = Get-Command smartctl -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("C:\Program Files\smartmontools\bin\smartctl.exe",
                     "C:\Program Files (x86)\smartmontools\bin\smartctl.exe")) {
        if (Test-Path $p) { return $p }
    }
    $null
}

function Le-Ssd-Smartctl($exe) {
    # smartctl le o SMART direto do disco: e a fonte mais confiavel quando existe.
    try { $scan = (& $exe --scan -j | Out-String | ConvertFrom-Json) } catch { return $null }
    foreach ($disp in @($scan.devices)) {
        try { $dados = (& $exe -A -i -j $disp.name | Out-String | ConvertFrom-Json) } catch { continue }
        $desgaste = $null; $cru = $null
        $nvme = $dados.nvme_smart_health_information_log
        if ($nvme -and $null -ne $nvme.percentage_used) {
            $pct = [double]$nvme.percentage_used
            $desgaste = [math]::Round([math]::Min(1.0, $pct / 100), 3)
            $cru = "Percentage Used: $pct% (smartctl)"
        } elseif ($dados.ata_smart_attributes.table) {
            $attr = $dados.ata_smart_attributes.table | Where-Object { $_.id -in 177, 233 } | Select-Object -First 1
            if ($attr) {
                $desgaste = [math]::Round([math]::Max(0.0, [math]::Min(1.0, 1 - [double]$attr.value / 100)), 3)
                $cru = "$($attr.name): $($attr.value)/100 (smartctl)"
            }
        }
        if ($null -eq $desgaste) { continue }
        $cap = $null
        if ($dados.user_capacity.bytes) { $cap = [math]::Round([double]$dados.user_capacity.bytes / 1e9) }
        return @{
            orgao = [ordered]@{ desgaste = $desgaste; valor_cru = $cru; estado = (Estado-Ssd $desgaste) }
            capacidade_gb = $cap
        }
    }
    $null
}

function Le-Ssd {
    # 1) smartctl, se existir: leitura SMART direta, a fonte de verdade.
    $exe = Acha-Smartctl
    if ($exe) {
        $r = Le-Ssd-Smartctl $exe
        if ($r) { return $r }
    }
    # 2) contador nativo do Windows. Wear=0 e AMBIGUO: pode ser disco novo ou
    #    driver que nao reporta (visto em campo: driver devolvendo 0 com SMART
    #    real de 13%). Numero possivelmente falso nao entra no laudo.
    $discos = Get-PhysicalDisk | Sort-Object DeviceId
    $semPermissao = $false
    $vimosZero = $false
    foreach ($d in $discos) {
        try { $rc = $d | Get-StorageReliabilityCounter } catch { $semPermissao = $true; continue }
        if ($null -eq $rc.Wear) { continue }
        if ([double]$rc.Wear -le 0) { $vimosZero = $true; continue }
        $desgaste = [math]::Round([math]::Min(1.0, [double]$rc.Wear / 100), 3)
        return @{
            orgao = [ordered]@{
                desgaste = $desgaste
                valor_cru = "Percentage Used: $($rc.Wear)% (contador nativo do Windows)"
                estado = (Estado-Ssd $desgaste)
            }
            capacidade_gb = [math]::Round([double]$d.Size / 1e9)
        }
    }
    if ($vimosZero) {
        Falha ("o contador nativo do Windows reportou desgaste 0, e neste driver isso pode ser`n" +
               "falso (disco novo e driver mudo dao a mesma resposta). Numero duvidoso nao entra`n" +
               "no laudo. Para a leitura SMART direta, instale o smartmontools e rode de novo:`n" +
               "  winget install smartmontools.smartmontools")
    }
    if ($semPermissao) {
        Falha "o Windows negou a leitura do contador de desgaste: rode como administrador."
    }
    Falha ("nenhum disco desta maquina expoe indicador de desgaste.`n" +
           "Alternativa: instale o smartmontools (winget install smartmontools.smartmontools) e rode de novo.")
}

function Le-Bateria {
    # powercfg /batteryreport: recargas + capacidade, assinado pela Microsoft.
    $tmp = Join-Path $env:TEMP "lastro-bateria.xml"
    try { powercfg /batteryreport /xml /output $tmp 2>$null | Out-Null } catch { return $null }
    if (-not (Test-Path $tmp)) { return $null }
    try {
        [xml]$rel = Get-Content $tmp -Raw
        Remove-Item $tmp -Force
        $bat = $rel.BatteryReport.Batteries.Battery | Select-Object -First 1
        if (-not $bat) { return $null }
        $projeto = [double]$bat.DesignCapacity
        $cheia = [double]$bat.FullChargeCapacity
        if ($projeto -le 0 -or $cheia -le 0) { return $null }
        $saude = [math]::Round($cheia / $projeto * 100, 1)
        # formula transparente: fim de vida = 70% da capacidade de projeto
        # (1.0/0.0 forcam a sobrecarga double do .NET; com int, o PS arredonda o argumento)
        $desgaste = [math]::Round([math]::Max(0.0, [math]::Min(1.0, (100 - $saude) / 30)), 3)
        $estado = if ($desgaste -ge 0.8) { "critico" } elseif ($desgaste -ge 0.5) { "atencao" } else { "saudavel" }
        $orgao = [ordered]@{ desgaste = $desgaste; saude_pct = $saude; estado = $estado }
        if ([int]$bat.CycleCount -gt 0) { $orgao.recargas = [int]$bat.CycleCount }
        $orgao
    } catch { $null }
}

function Le-Memoria {
    $os = Get-CimInstance Win32_OperatingSystem
    $total = [double]$os.TotalVisibleMemorySize
    if ($total -le 0) { return $null }
    $uso = [math]::Round((1 - ([double]$os.FreePhysicalMemory / $total)), 2)
    $estado = if ($uso -ge 0.9) { "critico" } elseif ($uso -ge 0.7) { "atencao" } else { "saudavel" }
    [ordered]@{ desgaste = $uso; swap_frequente = $false; estado = $estado }
}

function Monta-Laudo {
    $ssd = Le-Ssd
    $cs = Get-CimInstance Win32_ComputerSystem
    $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    $os = Get-CimInstance Win32_OperatingSystem
    # proveniencia: o hash do proprio script, conferivel contra releases.json
    $eu = ""
    try { $eu = (Invoke-RestMethod $SELF_URL) -replace "`r`n", "`n" } catch {}
    $meuSha = if ($eu) { Sha256Hex ([Text.Encoding]::UTF8.GetBytes($eu)) } else { ("0" * 64) }

    $orgaos = [ordered]@{ ssd = $ssd.orgao }
    $bat = Le-Bateria
    if ($bat) { $orgaos.bateria = $bat }
    $mem = Le-Memoria
    if ($mem) { $orgaos.memoria = $mem }

    [ordered]@{
        versao = "1"
        serie = Le-Serie
        maquina = [ordered]@{
            modelo = if ($cs.Model) { $cs.Model.Trim() } else { "modelo desconhecido" }
            cpu = if ($cpu) { $cpu.Trim() } else { "desconhecido" }
            ram_gb = [math]::Round([double]$cs.TotalPhysicalMemory / 1GB)
            armazenamento_gb = $ssd.capacidade_gb
            so = ($os.Caption -replace "Microsoft ", "").Trim()
            comprado_em = $null
        }
        aferido_em = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssK")
        agente = [ordered]@{ nome = "lastro-agent"; versao = $VERSAO; sha256 = $meuSha }
        orgaos = $orgaos
    }
}

# ------------------------------------------------------- caderneta e prognostico

function Caderneta-Dir {
    $d = Join-Path $env:LOCALAPPDATA "Lastro\laudos"
    New-Item -ItemType Directory -Force $d | Out-Null
    $d
}

function Caderneta-Local($serie) {
    $laudos = @()
    Get-ChildItem (Caderneta-Dir) -Filter "*.json" | Sort-Object Name | ForEach-Object {
        try {
            $l = Get-Content $_.FullName -Raw | ConvertFrom-Json
            if ($l.serie -eq $serie) { $laudos += $l }
        } catch {}
    }
    $laudos
}

function Calcula-Prognostico($laudo, $historico) {
    # formula legivel (SPEC): taxa = variacao de desgaste / meses; restantes = (1-atual)/taxa
    if (-not $historico -or $historico.Count -lt 1) { return $null }
    $primeiro = $historico[0]
    $meses = ((Get-Date $laudo.aferido_em) - (Get-Date $primeiro.aferido_em)).TotalDays / 30.44
    if ($meses -le 0) { return $null }
    $melhor = $null
    foreach ($nome in $laudo.orgaos.Keys) {
        $antigo = $primeiro.orgaos.$nome
        if ($null -eq $antigo) { continue }
        $taxa = ($laudo.orgaos[$nome].desgaste - $antigo.desgaste) / $meses
        if ($taxa -le 0) { continue }
        $rest = (1 - $laudo.orgaos[$nome].desgaste) / $taxa
        if ($null -eq $melhor -or $rest -lt $melhor.meses) { $melhor = @{ orgao = $nome; meses = $rest } }
    }
    if ($null -eq $melhor) { return $null }
    [ordered]@{
        meses_restantes = [int][math]::Round($melhor.meses)
        margem_meses = [int][math]::Max(1.0, [math]::Round($melhor.meses * 0.2))
        gargalo = $melhor.orgao
    }
}

# ------------------------------------------------ carimbo publico (Rekor)

function DerInteiro([byte[]]$b) {
    $i = 0; while ($i -lt $b.Length - 1 -and $b[$i] -eq 0) { $i++ }
    $b = $b[$i..($b.Length - 1)]
    if ($b[0] -ge 0x80) { $b = @([byte]0) + $b }
    ,([byte[]](@([byte]2, [byte]$b.Length) + $b))
}

function Carimba-Rekor([byte[]]$conteudo) {
    $chave = New-Object System.Security.Cryptography.ECDsaCng 256
    $chave.HashAlgorithm = [System.Security.Cryptography.CngAlgorithm]::Sha256
    $rs = $chave.SignData($conteudo)                       # r||s (64 bytes)
    $r = DerInteiro $rs[0..31]; $s = DerInteiro $rs[32..63]
    $corpo = [byte[]]($r + $s)
    $derSig = [byte[]](@([byte]0x30, [byte]$corpo.Length) + $corpo)
    $blob = $chave.Key.Export([System.Security.Cryptography.CngKeyBlobFormat]::EccPublicBlob)
    $spkiPrefixo = [byte[]](0x30,0x59,0x30,0x13,0x06,0x07,0x2A,0x86,0x48,0xCE,0x3D,0x02,0x01,
                             0x06,0x08,0x2A,0x86,0x48,0xCE,0x3D,0x03,0x01,0x07,0x03,0x42,0x00,0x04)
    $spki = [byte[]]($spkiPrefixo + $blob[8..71])
    $b64 = [Convert]::ToBase64String($spki)
    $pem = "-----BEGIN PUBLIC KEY-----`n"
    for ($i = 0; $i -lt $b64.Length; $i += 64) {
        $pem += $b64.Substring($i, [math]::Min(64, $b64.Length - $i)) + "`n"
    }
    $pem += "-----END PUBLIC KEY-----`n"
    $digesto = Sha256Hex $conteudo
    $corpoReq = @{
        apiVersion = "0.0.1"; kind = "hashedrekord"
        spec = @{
            data = @{ hash = @{ algorithm = "sha256"; value = $digesto } }
            signature = @{
                content = [Convert]::ToBase64String($derSig)
                publicKey = @{ content = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pem)) }
            }
        }
    } | ConvertTo-Json -Depth 8
    $resp = Invoke-RestMethod -Method Post -Uri "$REKOR/api/v1/log/entries" `
        -ContentType "application/json" -Body $corpoReq
    $uuid = ($resp.PSObject.Properties | Select-Object -First 1).Name
    $entrada = $resp.$uuid
    [ordered]@{
        registro = "rekor.sigstore.dev"; uuid = $uuid; indice = $entrada.logIndex
        integrado_em = [DateTimeOffset]::FromUnixTimeSeconds($entrada.integratedTime).UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ss+00:00")
        sha256 = $digesto
    }
}

# ------------------------------------------------ certificado-arquivo

function Gera-Certificado($laudo, $historico, $carimbo, [byte[]]$laudoBytes) {
    $m = $laudo.maquina
    $specs = @($m.cpu, "$($m.ram_gb) GB", "SSD $($m.armazenamento_gb) GB", $m.so) -join " · "
    $nomes = @{ ssd = "SSD (desgaste NAND)"; bateria = "Bateria"; memoria = "Memória (pressão)" }
    $cores = @{ saudavel = "ok"; atencao = "warn"; critico = "bad" }
    $linhas = ""
    foreach ($org in $laudo.orgaos.Keys) {
        $d = $laudo.orgaos[$org]; $pct = [math]::Round($d.desgaste * 100)
        $cru = if ($d.valor_cru) { $d.valor_cru } else { "$pct% de desgaste" }
        $linhas += "<tr><td>$($nomes[$org])<div class='medidor'><i class='$($cores[$d.estado])' style='width:$pct%'></i></div></td>" +
                   "<td class='d'><span class='mono'>$cru · $($d.estado)</span></td></tr>"
    }
    $p = $laudo.prognostico
    if ($p) {
        $anos = [math]::Floor($p.meses_restantes / 12); $meses = $p.meses_restantes % 12
        $partes = @(); if ($anos) { $partes += "$anos ano$(if($anos -ne 1){'s'})" }
        if ($meses -or -not $anos) { $partes += "$meses mes$(if($meses -ne 1){'es'})" }
        $progR = "prognóstico de vida útil restante"; $progV = [char]0x2248 + " " + ($partes -join " e ")
        $progS = "gargalo: $($p.gargalo) · margem ±$($p.margem_meses) meses"
    } else {
        $progR = "prognóstico"; $progV = "primeira aferição"
        $progS = "re-afira em algumas semanas para medir a taxa de desgaste"
    }
    $hist = ""
    if ($historico.Count -gt 1) {
        $pontos = ($historico | ForEach-Object { "$($_.aferido_em.Substring(0,10)): $([math]::Round($_.orgaos.ssd.desgaste*100))%" }) -join " · "
        $hist = "<div class='specs mono' style='margin:0 0 14px'>caderneta (SSD): $pontos</div>"
    }
    $prova = @{ laudo_b64 = [Convert]::ToBase64String($laudoBytes); carimbo = $carimbo } | ConvertTo-Json -Depth 6 -Compress

    $modelo = (New-Object Net.WebClient).DownloadString(
        "https://raw.githubusercontent.com/iosbilario/lastro/main/site/cert-modelo.html")
    $html = $modelo -replace "%%SERIE%%", $laudo.serie -replace "%%NLAUDOS%%", $historico.Count `
        -replace "%%MODELO%%", $m.modelo -replace "%%SPECS%%", $specs `
        -replace "%%PROG_ROTULO%%", $progR -replace "%%PROG_VALOR%%", $progV -replace "%%PROG_SUB%%", $progS `
        -replace "%%ORGAOS%%", $linhas -replace "%%HISTORICO%%", $hist `
        -replace "%%CARIMBO_EM%%", $carimbo.integrado_em -replace "%%REKOR_UUID%%", $carimbo.uuid.Substring(0,16) `
        -replace "%%REKOR_INDICE%%", $carimbo.indice -replace "%%LAUDO_SHA%%", $carimbo.sha256.Substring(0,16) `
        -replace "%%VERSAO%%", $laudo.agente.versao -replace "%%SITE%%", $SITE `
        -replace "%%PROVA%%", $prova.Replace('$', '$$')
    $destino = Join-Path ([Environment]::GetFolderPath("Desktop")) `
        "lastro-certificado-$($laudo.serie)-$($laudo.aferido_em.Substring(0,10)).html"
    $html | Out-File -FilePath $destino -Encoding utf8
    $destino
}

# ------------------------------------------------ publicacao via GitHub (opcional)

function Api($url, $token, $dados, $metodo) {
    $accept = "application/json"
    if ($url -like "*api.github.com*") { $accept = "application/vnd.github+json" }
    $h = @{ Accept = $accept }
    if ($token) { $h.Authorization = "Bearer $token" }
    if ($null -ne $dados) {
        if (-not $metodo) { $metodo = "Post" }
        Invoke-RestMethod -Method $metodo -Uri $url -Headers $h -ContentType "application/json" `
            -Body ($dados | ConvertTo-Json -Depth 8)
    } else {
        if (-not $metodo) { $metodo = "Get" }
        Invoke-RestMethod -Method $metodo -Uri $url -Headers $h
    }
}

function Autoriza-GitHub {
    $d = Api "https://github.com/login/device/code" $null @{ client_id = $CLIENT_ID; scope = "public_repo" }
    Write-Host ""
    Write-Host "=== autorizacao no GitHub ===" -ForegroundColor Green
    Write-Host "  1) vou abrir $($d.verification_uri) no navegador"
    Write-Host "  2) digite este codigo:  $($d.user_code)" -ForegroundColor Yellow
    Start-Process $d.verification_uri
    $intervalo = [int]$d.interval; if ($intervalo -lt 5) { $intervalo = 5 }
    while ($true) {
        Start-Sleep -Seconds $intervalo
        $r = Api "https://github.com/login/oauth/access_token" $null @{
            client_id = $CLIENT_ID; device_code = $d.device_code
            grant_type = "urn:ietf:params:oauth:grant-type:device_code" }
        if ($r.access_token) { Write-Host "  autorizado."; return $r.access_token }
        if ($r.error -eq "authorization_pending") { continue }
        if ($r.error -eq "slow_down") { $intervalo += 5; continue }
        Falha "autorizacao nao concluida: $($r.error)"
    }
}

function Publica-GitHub($laudo, $token) {
    $login = (Api "https://api.github.com/user" $token).login
    $base = "https://api.github.com/repos/$login/$REPO_PASSAPORTE"
    try { Api $base $token | Out-Null } catch {
        Write-Host "criando o seu repositorio de passaporte: $login/$REPO_PASSAPORTE"
        Api "https://api.github.com/user/repos" $token @{
            name = $REPO_PASSAPORTE; auto_init = $true
            description = "Passaporte de saude do meu equipamento (Lastro)."
            homepage = "$SITE/laudo.html?p=$login/$REPO_PASSAPORTE" } | Out-Null
        Api "$base/topics" $token @{ names = @("lastro-passaporte") } "Put" | Out-Null
    }
    $manifesto = $null
    try { $manifesto = Invoke-RestMethod "https://raw.githubusercontent.com/$login/$REPO_PASSAPORTE/main/data/caderneta.json" } catch {}
    if (-not $manifesto -or $manifesto.sample) {
        $manifesto = @{ descricao = "Indice da Caderneta, mantido pelo lastro-agent."; sample = $false; laudos = @() }
    }
    $ref = $null
    foreach ($t in 1..10) {
        try { $ref = Api "$base/git/ref/heads/main" $token; break } catch { Start-Sleep 2 }
    }
    if (-not $ref) { Falha "o repositorio foi criado mas o branch main nao apareceu. Rode de novo." }
    $pai = $ref.object.sha
    $arvorePai = (Api "$base/git/commits/$pai" $token).tree.sha
    $nome = $laudo.aferido_em.Substring(0,10) + ".json"
    # @(...) externo: com um item so, o pipeline devolveria string e o JSON sairia sem array
    $laudosLista = @(@($manifesto.laudos) + @($nome) | Select-Object -Unique | Sort-Object)
    $manifesto = @{ descricao = $manifesto.descricao; sample = $false; laudos = $laudosLista }
    $arvore = Api "$base/git/trees" $token @{
        base_tree = $arvorePai
        tree = @(
            @{ path = "data/laudos/$nome"; mode = "100644"; type = "blob"; content = (JsonBonito $laudo) },
            @{ path = "data/latest.json"; mode = "100644"; type = "blob"; content = (JsonBonito $laudo) },
            @{ path = "data/caderneta.json"; mode = "100644"; type = "blob"; content = (JsonBonito $manifesto) }
        ) }
    $commit = Api "$base/git/commits" $token @{
        message = "laudo: afericao $($laudo.aferido_em.Substring(0,10)) (serie $($laudo.serie))"
        tree = $arvore.sha; parents = @($pai) }
    Api "$base/git/refs/heads/main" $token @{ sha = $commit.sha } "Patch" | Out-Null
    Write-Host "laudo publicado: commit $($commit.sha.Substring(0,7)) em $login/$REPO_PASSAPORTE"
    foreach ($t in 1..15) {
        try {
            Invoke-RestMethod "https://raw.githubusercontent.com/$login/$REPO_PASSAPORTE/main/data/latest.json?r=$t" | Out-Null
            break
        } catch { Start-Sleep 3 }
    }
    "$SITE/laudo.html?p=$login/$REPO_PASSAPORTE"
}

# ---------------------------------------------------------------------- main

function Lastro-Main {
    $eAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
              ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $eAdmin) {
        if ($env:LASTRO_NO_ELEVATE -eq "1") { Falha "sem administrador nao ha leitura SMART (elevacao desativada por LASTRO_NO_ELEVATE)." }
        Write-Host "a leitura de desgaste exige administrador; o Windows vai pedir permissao (UAC)..."
        Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-Command","irm $SELF_URL | iex"
        return
    }

    Write-Host "Lastro : passaporte de saude do equipamento" -ForegroundColor Green
    Write-Host "1/3 lendo o hardware desta maquina..."
    $laudo = Monta-Laudo
    Write-Host "    SSD: $($laudo.orgaos.ssd.valor_cru) ($($laudo.orgaos.ssd.estado))"

    Write-Host ""
    Write-Host "2/3 como quer emitir?"
    Write-Host "  [1] certificado-arquivo, sem precisar de conta nenhuma (recomendado)"
    Write-Host "  [2] link publico via GitHub (usa ou cria sua conta)"
    $escolha = Read-Host "  escolha [1]"
    if (-not $escolha) { $escolha = "1" }

    $historico = Caderneta-Local $laudo.serie
    $prog = Calcula-Prognostico $laudo $historico
    if ($prog) { $laudo.prognostico = $prog }

    if ($escolha -eq "2") {
        Write-Host "3/3 autorizando no GitHub (nada e enviado sem isso)..."
        $token = Autoriza-GitHub
        $url = Publica-GitHub $laudo $token
        Write-Host ""
        Write-Host "pronto. Seu certificado:" -ForegroundColor Green
        Write-Host "  $url"
        Write-Host "  versao para o anuncio: $url&certificado"
        Start-Process $url
    } else {
        Write-Host "3/3 emitindo o certificado (nenhuma conta, nenhum cadastro)..."
        $laudoTexto = JsonBonito $laudo
        $laudoBytes = [Text.Encoding]::UTF8.GetBytes($laudoTexto)
        $arqLocal = Join-Path (Caderneta-Dir) "$($laudo.aferido_em.Substring(0,10)).json"
        $laudoTexto | Out-File $arqLocal -Encoding utf8
        Write-Host "    depositando o hash no diario publico (Rekor)..."
        $carimbo = Carimba-Rekor $laudoBytes
        Write-Host "    carimbado: $($carimbo.integrado_em) · indice $($carimbo.indice)"
        $arquivo = Gera-Certificado $laudo (@($historico) + @($laudo)) $carimbo $laudoBytes
        Write-Host ""
        Write-Host "pronto. Seu certificado esta na Area de Trabalho:" -ForegroundColor Green
        Write-Host "  $arquivo"
        Write-Host "  anexe no anuncio; o comprador confere em $SITE/conferir.html"
        Start-Process $arquivo

        Write-Host ""
        Write-Host "quer tambem o link publico do passaporte? Ele doa os dados anonimos"
        Write-Host "(so modelo e desgaste) para o Observatorio. Usa/cria conta GitHub gratuita."
        $extra = Read-Host "  publicar tambem? [s/N]"
        if ($extra -eq "s") {
            $token = Autoriza-GitHub
            $url = Publica-GitHub $laudo $token
            Write-Host "link publico: $url" -ForegroundColor Green
            Start-Process $url
        }
    }
    Read-Host "`npressione Enter para fechar" | Out-Null
}

if (-not $env:LASTRO_LIB) { Lastro-Main }
