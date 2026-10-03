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

    @property
    def plataforma(self) -> str | None:
        """Sistema que PUBLICOU a contratação no PNCP (ex.: "Compras.gov.br",
        ou o nome da empresa integradora de um portal privado). Não prova
        onde a disputa correu, e os nomes não são padronizados entre
        integradoras — agrupar exige um de-para do lado de quem consome."""
        return self.raw.get("usuarioNome")

    @property
    def link_sistema_origem(self) -> str | None:
        """Link da contratação na plataforma de origem; pode vir vazio."""
        return self.raw.get("linkSistemaOrigem") or None

    @property
    def fontes_orcamentarias(self) -> list[str]:
        """Origem do recurso (ex.: ["Municipal"], ["Estadual"]) — uma compra
        pode ter mais de uma. Não é a plataforma. Lista vazia quando o órgão
        não informou (comum em contratação antiga); o objeto completo, com
        código e descrição, segue em `.raw["fontesOrcamentarias"]`."""
        return [f.get("nome") for f in (self.raw.get("fontesOrcamentarias") or [])
                if isinstance(f, dict) and f.get("nome")]

    @property
    def modo_disputa(self) -> str | None:
        """Ex.: "Aberto", "Fechado", "Aberto-Fechado", "Não se aplica"
        (comum em dispensa e inexigibilidade)."""
        return self.raw.get("modoDisputaNome")


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

    @property
    def situacao(self) -> str | None:
        """Situação declarada do item (ex.: "Homologado", "Deserto",
        "Fracassado", "Em andamento") — use isto em vez de inferir deserto
        pela ausência de resultado."""
        return self.raw.get("situacaoCompraItemNome")

    @property
    def tipo_beneficio(self) -> str | None:
        """Benefício ME/EPP previsto para o item (ex.: "Sem benefício",
        "Não se aplica", "Participação exclusiva para ME/EPP"). É o campo
        que diz se o item era exclusivo."""
        return self.raw.get("tipoBeneficioNome")

    @property
    def criterio_julgamento(self) -> str | None:
        """Ex.: "Menor preço", "Maior desconto", "Técnica e preço"."""
        return self.raw.get("criterioJulgamentoNome")


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

    @property
    def situacao(self) -> str | None:
        """Situação do resultado (ex.: "Informado", "Cancelado")."""
        return self.raw.get("situacaoCompraItemResultadoNome")

    @property
    def porte_fornecedor(self) -> str | None:
        """Porte declarado do vencedor (ex.: "ME", "EPP", "Demais")."""
        return self.raw.get("porteFornecedorNome")

    @property
    def natureza_juridica(self) -> str | None:
        """Ex.: "Sociedade Empresária Limitada". O código vem em
        `.raw["naturezaJuridicaId"]` como TEXTO ("2062"), não número."""
        return self.raw.get("naturezaJuridicaNome")

    @property
    def beneficio_me_epp(self) -> bool:
        """Indicador `aplicacaoBeneficioMeEpp` do portal. NÃO diz se o item
        era exclusivo para ME/EPP: num item de participação exclusiva,
        vencido por uma ME, o portal manda `False` (visto no envelope real)
        — exclusividade se lê em `Item.tipo_beneficio`. Campo ausente vira
        `False`, nunca `None`."""
        return bool(self.raw.get("aplicacaoBeneficioMeEpp"))


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

    # A vigência muda de nome entre os dois hosts do portal: `vigenciaFim`
    # em api/consulta (o que `Motor.atas` devolve), `dataVigenciaFim` em
    # api/pncp (o registro individual da ata). As duas grafias são lidas.

    @property
    def vigencia_inicio(self) -> str | None:
        return primeiro(self.raw, "vigenciaInicio", "dataVigenciaInicio")

    @property
    def vigencia_fim(self) -> str | None:
        """Fim da vigência COMO ESTÁ HOJE no portal. Prorrogação de ata
        não é termo aditivo: é retificação que sobrescreve este valor, e o
        anterior se perde na fonte. Quem precisa saber se (e de quanto) a
        ata foi prorrogada guarda o valor antigo antes do upsert."""
        return primeiro(self.raw, "vigenciaFim", "dataVigenciaFim")

    @property
    def data_publicacao(self) -> str | None:
        """Quando a ata entrou no PNCP. Igual a `data_atualizacao` numa ata
        nunca retificada — inclusive nas publicadas com atraso, em que as
        duas são tardias: `data_atualizacao` recente, sozinha, não indica
        alteração."""
        return self.raw.get("dataPublicacaoPncp")

    @property
    def data_atualizacao(self) -> str | None:
        return self.raw.get("dataAtualizacao")

    @property
    def cancelado(self) -> bool:
        return bool(self.raw.get("cancelado"))

    @property
    def data_cancelamento(self) -> str | None:
        return self.raw.get("dataCancelamento")


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
