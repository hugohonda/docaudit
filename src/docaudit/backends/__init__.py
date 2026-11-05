"""Backends concretos.

Cada módulo importa sua dependência pesada tardiamente, dentro da classe, para
que `import docaudit` continue custando só Pydantic, pypdfium2 e Pillow. Um backend
ausente vira `ImportError` com o nome do extra a instalar, em
`docaudit.registry.get_backend`.
"""
