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
    def cnpj(self):
        return self.raw.get("cnpj")

    @property
    def razao_social(self):
        return self.raw.get("razaoSocial")

    @property
    def esfera(self):
        return (self.raw.get("poderId"), self.raw.get("esferaId"))


@dataclass(frozen=True)
class Contratacao:
    raw: dict[str, Any]

    @property
    def numero_controle(self):
        return self.raw.get("numeroControlePNCP")

    @property
    def ano(self):
        return self.raw.get("anoCompra")

    @property
    def sequencial(self):
        return self.raw.get("sequencialCompra")

    @property
    def orgao_cnpj(self):
        return (self.raw.get("orgaoEntidade") or {}).get("cnpj")

    @property
    def orgao_nome(self):
        return (self.raw.get("orgaoEntidade") or {}).get("razaoSocial")

    @property
    def unidade_nome(self):
        return (self.raw.get("unidadeOrgao") or {}).get("nomeUnidade")

    @property
    def modalidade_id(self):
        return self.raw.get("modalidadeId")

    @property
    def situacao(self):
        return self.raw.get("situacaoCompraNome")

    @property
    def objeto(self):
        return self.raw.get("objetoCompra")

    @property
    def valor_estimado(self):
        return num(self.raw.get("valorTotalEstimado"))

    @property
    def valor_homologado(self):
        return num(self.raw.get("valorTotalHomologado"))

    @property
    def data_atualizacao(self):
        return self.raw.get("dataAtualizacao")

    @property
    def data_publicacao(self):
        return self.raw.get("dataPublicacaoPncp")


@dataclass(frozen=True)
class Item:
    raw: dict[str, Any]

    @property
    def numero_item(self):
        return self.raw.get("numeroItem")

    @property
    def descricao(self):
        return self.raw.get("descricao")

    @property
    def tem_resultado(self):
        return bool(self.raw.get("temResultado"))

    @property
    def quantidade(self):
        return num(self.raw.get("quantidade"))

    @property
    def valor_unitario_estimado(self):
        return num(self.raw.get("valorUnitarioEstimado"))

    @property
    def valor_total_estimado(self):
        return num(self.raw.get("valorTotal"))

    @property
    def data_atualizacao(self):
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class Resultado:
    raw: dict[str, Any]

    @property
    def cancelado(self):
        return bool(self.raw.get("dataCancelamento"))

    @property
    def fornecedor_ni(self):
        return primeiro(self.raw, "niFornecedor")

    @property
    def fornecedor_nome(self):
        return self.raw.get("nomeRazaoSocialFornecedor")

    @property
    def valor_unitario_homologado(self):
        return num(self.raw.get("valorUnitarioHomologado"))

    @property
    def valor_total_homologado(self):
        return num(self.raw.get("valorTotalHomologado"))

    @property
    def quantidade_homologada(self):
        return num(self.raw.get("quantidadeHomologada"))

    @property
    def data_resultado(self):
        return self.raw.get("dataResultado")


@dataclass(frozen=True)
class Contrato:
    raw: dict[str, Any]

    @property
    def numero_controle(self):
        return self.raw.get("numeroControlePncpCompra")

    @property
    def ano(self):
        return self.raw.get("anoContrato")

    @property
    def sequencial(self):
        return self.raw.get("sequencialContrato")

    @property
    def orgao_cnpj(self):
        return (self.raw.get("orgaoEntidade") or {}).get("cnpj")

    @property
    def valor_global(self):
        return num(self.raw.get("valorGlobal"))

    @property
    def data_atualizacao(self):
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class Ata:
    raw: dict[str, Any]

    @property
    def numero_controle(self):
        return self.raw.get("numeroControlePNCPAta")

    @property
    def orgao_cnpj(self):
        return (self.raw.get("orgaoEntidade") or {}).get("cnpj")

    @property
    def vigencia_fim(self):
        return self.raw.get("vigenciaFim")

    @property
    def data_atualizacao(self):
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class PlanoPca:
    """Um Plano de Contratações Anual — `.raw["itens"]` traz a lista de
    itens do plano; achatar em linhas (se for o seu schema) é decisão de
    quem persiste, não do motor."""
    raw: dict[str, Any]

    @property
    def id_pca(self):
        return self.raw.get("idPcaPncp")

    @property
    def ano(self):
        return self.raw.get("anoPca")

    @property
    def orgao_cnpj(self):
        return self.raw.get("orgaoEntidadeCnpj")

    @property
    def itens(self):
        return self.raw.get("itens") or []

    @property
    def data_atualizacao(self):
        return self.raw.get("dataAtualizacao")


@dataclass(frozen=True)
class TermoAditivo:
    raw: dict[str, Any]

    @property
    def sequencial(self):
        return self.raw.get("sequencialTermoContrato")

    @property
    def tipo(self):
        return self.raw.get("tipoTermoContratoNome")

    @property
    def valor_global(self):
        return num(self.raw.get("valorGlobal"))

    @property
    def valor_acrescido(self):
        return num(self.raw.get("valorAcrescido"))

    @property
    def data_assinatura(self):
        return self.raw.get("dataAssinatura")
