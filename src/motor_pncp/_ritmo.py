"""Ritmo das requisições: intervalo mínimo por host e bloqueio após 429.

O PNCP limita por IP de origem, não por processo (resposta oficial a um
chamado, out/2026). Dois processos na mesma máquina — uma sincronização e
um monitor, por exemplo — somam requisições sem saber um do outro. Por
isso o ritmo, por padrão, é guardado num arquivo pequeno por host, travado
pelo sistema operacional: qualquer processo que use o motor espera a vez
dos outros. Se o arquivo não puder ser usado (sem permissão, disco cheio),
o motor volta ao ritmo só deste processo, avisa no log e segue — ritmo é
cortesia com o portal, não pode derrubar a coleta.

Onde fica o arquivo: na pasta do usuário (`~/.motor_pncp/`), de
propósito. No Windows, processos iniciados de dentro de um app empacotado
(MSIX) enxergam `%LOCALAPPDATA%` virtualizado, e a trava ali seria
invisível para os apps nativos; a pasta do usuário não sofre isso. A
variável de ambiente `MOTOR_PNCP_RITMO` ou `Config.pasta_ritmo` troca o
local (os testes usam isso).

Processo que morre segurando a trava não deixa trava presa: o sistema
operacional solta a trava quando o processo termina.
"""
import logging
import os
import pathlib
import re
import threading
import time
import urllib.parse

_log = logging.getLogger("motor_pncp")

if os.name == "nt":
    import msvcrt

    def _tentar_travar(f):
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _soltar(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:  # pragma: no cover - o CI roda Linux, mas a máquina de produção é Windows
    import fcntl

    def _tentar_travar(f):
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _soltar(f):
        fcntl.flock(f, fcntl.LOCK_UN)

_PASSO_TRAVA = 0.05  # espera entre tentativas de pegar a trava (checa cancelamento)


def chave_do_host(url_base):
    """`https://pncp.gov.br/api/consulta` → `pncp.gov.br_api_consulta`."""
    p = urllib.parse.urlsplit(url_base)
    return re.sub(r"[^A-Za-z0-9.]+", "_", f"{p.netloc}{p.path}").strip("_") or "padrao"


def pasta_padrao():
    return pathlib.Path(os.environ.get("MOTOR_PNCP_RITMO")
                        or pathlib.Path.home() / ".motor_pncp")


class Ritmo:
    """Garante `intervalo` segundos entre requisições ao mesmo host e
    respeita o bloqueio aberto por um 429 — entre as threads deste
    processo sempre, e entre processos quando `pasta` é dada.

    `dormir(segundos)` é a espera do `Cliente` (acorda e levanta
    `SyncCancelado` se a coleta for cancelada).
    """

    def __init__(self, pasta=None):
        self._pasta = pathlib.Path(pasta) if pasta else None
        self._trava = threading.Lock()       # threads deste processo
        self._local = {}                      # chave -> [ultima, bloqueado_ate]
        self._avisado = False

    # ── estado: arquivo quando dá, memória quando não ────────────────────

    def _arquivo(self, chave):
        if self._pasta is None:
            return None
        try:
            self._pasta.mkdir(parents=True, exist_ok=True)
            # byte 0 é o travado; os números vão depois dele
            return open(self._pasta / f"ritmo-{chave}.lock", "a+b")
        except OSError as e:
            self._desligar(e)
            return None

    def _desligar(self, erro):
        if not self._avisado:
            _log.warning("ritmo compartilhado indisponível (%s) — seguindo com o "
                         "ritmo só deste processo", erro)
            self._avisado = True
        self._pasta = None

    @staticmethod
    def _ler(f):
        f.seek(1)
        partes = f.read().decode("ascii", "replace").split()
        try:
            return float(partes[0]), float(partes[1])
        except (IndexError, ValueError):
            return 0.0, 0.0

    @staticmethod
    def _gravar(f, ultima, bloqueado_ate):
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            f.write(b" ")
        f.seek(1)
        f.truncate()
        f.write(f"{ultima:.6f} {bloqueado_ate:.6f}".encode("ascii"))
        f.flush()

    def _com_estado(self, chave, dormir, alterar):
        """Abre (e trava) o estado do host, chama `alterar(ultima,
        bloqueado_ate) -> (ultima, bloqueado_ate)` e grava o resultado."""
        with self._trava:
            f = self._arquivo(chave)
            if f is None:
                ultima, bloq = self._local.get(chave, (0.0, 0.0))
                self._local[chave] = alterar(ultima, bloq)
                return
            with f:
                while not _tentar_travar(f):
                    dormir(_PASSO_TRAVA)
                try:
                    ultima, bloq = self._ler(f)
                    self._gravar(f, *alterar(ultima, bloq))
                except OSError as e:
                    self._desligar(e)
                finally:
                    try:
                        _soltar(f)
                    except OSError:
                        pass

    # ── o que o Cliente usa ─────────────────────────────────────────────

    def aguardar(self, chave, intervalo, dormir):
        """Espera a vez desta requisição e marca o instante dela."""
        def alterar(ultima, bloqueado_ate):
            alvo = max(ultima + intervalo, bloqueado_ate)
            espera = alvo - time.time()
            if espera > 0:
                dormir(espera)
            return time.time(), bloqueado_ate

        self._com_estado(chave, dormir, alterar)

    def bloquear(self, chave, segundos, dormir):
        """Registra que o host pediu trégua por `segundos` — todo processo
        que usa este ritmo espera até lá antes da próxima requisição."""
        ate = time.time() + segundos
        self._com_estado(chave, dormir,
                         lambda ultima, bloq: (ultima, max(bloq, ate)))
