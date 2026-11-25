"""O formato de `Result` em JSON é um contrato: o esquema publicado é o do código."""

import json
from pathlib import Path

from tests.support import make_pdf
from tests.support.fixtures import TEXT_CENTRAL

from docaudit import process
from docaudit.types import SCHEMA_VERSION, Result

PUBLISHED = Path(__file__).resolve().parents[2] / "docs" / "response" / "result.schema.json"


def current() -> str:
    schema = Result.model_json_schema()
    return json.dumps(schema, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def test_the_published_schema_is_the_schema_of_the_code():
    """Mudou um campo: regrave com `just schema`; se quebra quem lê, suba `SCHEMA_VERSION`."""
    assert PUBLISHED.read_text() == current()


def test_the_schema_names_its_version():
    schema = json.loads(PUBLISHED.read_text())
    assert schema["properties"]["schema_version"]["default"] == SCHEMA_VERSION


def test_a_json_written_before_the_field_reads_as_version_one():
    result = process(make_pdf(TEXT_CENTRAL), policy="all_cheap", cheap=["text_layer"])
    old = json.loads(result.model_dump_json())
    del old["schema_version"]
    assert Result.model_validate(old).schema_version == "1"
