"""Tests do router heurístico (model=auto)."""

from win_runner.router import explain


def test_opus_for_refactor():
    d = explain("refatorar o módulo de auth para padrão hexagonal")
    assert d.spec == "opus"


def test_opus_for_architecture():
    d = explain("desenhar a arquitetura do novo serviço de billing")
    assert d.spec == "opus"


def test_haiku_for_rename():
    d = explain("renomeie a função handleX para handle_x")
    assert d.spec == "haiku"


def test_haiku_for_remove():
    d = explain("remova os imports não usados de utils.py")
    assert d.spec == "haiku"


def test_default_sonnet_for_neutral():
    d = explain("adicione um endpoint GET /users/{id} retornando JSON")
    assert d.spec == "sonnet"


def test_long_description_promotes_to_opus():
    desc = "este pedido tem um contexto muito longo " * 20  # > 400 chars
    d = explain(desc)
    assert d.spec == "opus"
    assert "length" in d.rule


def test_category_overrides_keywords():
    # Mesmo com palavra mecânica, category=refactor força opus.
    d = explain("renomeie tudo", category="refactor")
    assert d.spec == "opus"
    assert "category" in d.rule


def test_category_cleanup_for_haiku():
    d = explain("ajuste qualquer coisa que precise", category="cleanup")
    assert d.spec == "haiku"


def test_decision_has_reason():
    d = explain("teste")
    assert d.reason
    assert d.rule
    assert 0.0 <= d.score <= 1.0
