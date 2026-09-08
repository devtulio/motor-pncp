"""Registros tipados que o motor devolve.

Cada um é um envelope fino em cima do JSON cru do PNCP: `raw` continua
sendo a fonte da verdade (o campo que você deveria guardar), e as
`@property` só dão autocomplete/checagem de tipo pros campos que o
próprio motor precisa manipular (datas, números, chaves de junção) ou
que quase todo consumidor usa. Não é um mapeamento exaustivo do schema —
a API do PNCP ganha campo novo sem aviso, e um dataclass exaustivo
quebraria ou ficaria desatualizado a cada mudança. Campo que você precisa
e não tem `@property` aqui: pegue de `.raw` diretamente.
"""
from dataclasses import dataclass
from typing import Any

from .dominio import num, primeiro


@dataclass(frozen=True)
class Orgao:
    raw: dict[str, Any]

    @property
    def cnpj(self) -> str | None:
        return self.raw.get("cnpj")

    @property
    def razao_social(self) -> str | None:
        return self.raw.get("razaoSocial")

    @property
    def esfera(self) -> str | None:
        """`M`/`E`/`F`/`N` — municipal/estadual/federal/não informada.
        Órgão de esfera estadual/federal pode aparecer nas contratações de
        um município por ter uma unidade lá (um presídio, um campus); é
        quem consome que decide o que fazer com isso (ex.: não tratar como
        órgão do próprio município)."""
        return self.raw.get("esferaId")


@dataclass(frozen=True)
class Contratacao:
    raw: dict[str, Any]

    @property
    def numero_controle(self) -> str | None:
        return self.raw.get("numeroControlePNCP")

    @property
    def ano(self) -> int | None:
        return self.raw.get("anoCompra")

    @property
    def sequencial(self) -> int | None:
        return self.raw.get("sequencialCompra")

    @property
    def orgao_cnpj(self) -> str | None:
        return (self.raw.get("orgaoEntidade") or {}).get("cnpj")

    @property
    def orgao_nome(self) -> str | None:
        return (self.raw.get("orgaoEntidade") or {}).get("razaoSocial")

    @property
    def unidade_nome(self) -> str | None:
        return (self.raw.get("unidadeOrgao") or {}).get("nomeUnidade")

    @property
    def modalidade_id(self) -> int | None:
        return self.raw.get("modalidadeId")

    @property
    def situacao(self) -> str | None:
        return self.raw.get("situacaoCompraNome")

    @property
    def objeto(self) -> str | None:
        return self.raw.get("objetoCompra")

    @property
    def valor_estimado(self) -> float | None:
        return num(self.raw.get("valorTotalEstimado"))

    @property
    def valor_homologado(self) -> float | None:
        return num(self.raw.get("valorTotalHomologado"))

    @property
    def data_atualizacao(self) -> str | None:
        return self.raw.get("dataAtualizacao")

    @property
    def data_publicacao(self) -> str | None:
        return self.raw.get("dataPublicacaoPncp")


@dataclass(frozen=True)
class Item:
    raw: dict[str, Any]

    @property
    def numero_item(self) -> int | None:
        return self.raw.get("numeroItem")

    @property
    def descricao(self) -> str | None:
        return self.raw.get("descricao")

    @property
    def tem_resultado(self) -> bool:
        return bool(self.raw.get("temResultado"))

    @property
    def quantidade(self) -> float | None:
        return num(self.raw.get("quantidade"))

    @property
    def valor_unitario_estimado(self) -> float | None:
        return num(self.raw.get("valorUnitarioEstimado"))

    @property
    def valor_total_estimado(self) -> float | None:
        return num(self.raw.get("valorTotal"))

    @property
    def data_atualizacao(self) -> str | None:
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class Resultado:
    raw: dict[str, Any]

    @property
    def cancelado(self) -> bool:
        return bool(self.raw.get("dataCancelamento"))

    @property
    def fornecedor_ni(self) -> str | None:
        return primeiro(self.raw, "niFornecedor")

    @property
    def fornecedor_nome(self) -> str | None:
        return self.raw.get("nomeRazaoSocialFornecedor")

    @property
    def valor_unitario_homologado(self) -> float | None:
        return num(self.raw.get("valorUnitarioHomologado"))

    @property
    def valor_total_homologado(self) -> float | None:
        return num(self.raw.get("valorTotalHomologado"))

    @property
    def quantidade_homologada(self) -> float | None:
        return num(self.raw.get("quantidadeHomologada"))

    @property
    def data_resultado(self) -> str | None:
        return self.raw.get("dataResultado")


@dataclass(frozen=True)
class Contrato:
    raw: dict[str, Any]

    @property
    def numero_controle(self) -> str | None:
        return self.raw.get("numeroControlePncpCompra")

    @property
    def ano(self) -> int | None:
        return self.raw.get("anoContrato")

    @property
    def sequencial(self) -> int | None:
        return self.raw.get("sequencialContrato")

    @property
    def orgao_cnpj(self) -> str | None:
        return (self.raw.get("orgaoEntidade") or {}).get("cnpj")

    @property
    def valor_global(self) -> float | None:
        return num(self.raw.get("valorGlobal"))

    @property
    def data_atualizacao(self) -> str | None:
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class Ata:
    raw: dict[str, Any]

    @property
    def numero_controle(self) -> str | None:
        return self.raw.get("numeroControlePNCPAta")

    @property
    def orgao_cnpj(self) -> str | None:
        # o envelope real de /v1/atas/atualizacao traz `cnpjOrgao` plano,
        # não `orgaoEntidade.cnpj` como contratações/contratos — lendo só o
        # aninhado, esta property devolvia None em toda ata (pego pela
        # fixture real; os dicts inventados dos testes nunca perceberiam)
        return ((self.raw.get("orgaoEntidade") or {}).get("cnpj")
                or self.raw.get("cnpjOrgao"))

    @property
    def vigencia_fim(self) -> str | None:
        return self.raw.get("vigenciaFim")

    @property
    def data_atualizacao(self) -> str | None:
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class PlanoPca:
    """Um Plano de Contratações Anual — `.raw["itens"]` traz a lista de
    itens do plano; achatar em linhas (se for o seu schema) é decisão de
    quem persiste, não do motor."""
    raw: dict[str, Any]

    @property
    def id_pca(self) -> str | None:
        return self.raw.get("idPcaPncp")

    @property
    def ano(self) -> int | None:
        return self.raw.get("anoPca")

    @property
    def orgao_cnpj(self) -> str | None:
        return self.raw.get("orgaoEntidadeCnpj")

    @property
    def itens(self) -> list:
        return self.raw.get("itens") or []

    @property
    def data_atualizacao(self) -> str | None:
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class TermoAditivo:
    raw: dict[str, Any]

    @property
    def sequencial(self) -> int | None:
        return self.raw.get("sequencialTermoContrato")

    @property
    def tipo(self) -> str | None:
        return self.raw.get("tipoTermoContratoNome")

    @property
    def valor_global(self) -> float | None:
        return num(self.raw.get("valorGlobal"))

    @property
    def valor_acrescido(self) -> float | None:
        return num(self.raw.get("valorAcrescido"))

    @property
    def data_assinatura(self) -> str | None:
        return self.raw.get("dataAssinatura")
