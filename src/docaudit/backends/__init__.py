# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Backends concretos.

Cada módulo importa sua dependência pesada tardiamente, dentro da classe, para
que `import docaudit` continue custando só Pydantic, pypdfium2 e Pillow. Um backend
ausente vira `ImportError` com o nome do extra a instalar, em
`docaudit.registry.get_backend`.
"""
