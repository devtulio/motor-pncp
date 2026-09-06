import pytest

from motor_pncp.configuracao import Config


def test_config_default_e_valido():
    Config()  # não levanta


@pytest.mark.parametrize("campo", ["tentativas_padrao", "tentativas_curtas"])
def test_config_rejeita_tentativas_menor_que_1(campo):
    """tentativas=0 faria o laço de retry não rodar nenhuma vez — uma
    falha de configuração virando silenciosamente "sem dados"."""
    with pytest.raises(ValueError, match="tentativas"):
        Config(**{campo: 0})
