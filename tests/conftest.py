"""Fixtures da suíte.

`tests.support` traz a suíte de contrato e os construtores de PDF. Não é
distribuída: os módulos importam pytest, que é dependência de desenvolvimento e
não extra.
"""

pytest_plugins = ["tests.support.fixtures"]
