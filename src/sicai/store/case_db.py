"""Base estruturada do processo (SQLite).

Guarda o texto integral de cada página e os registros extraídos (pessoas,
crimes, equipamentos, eventos). Todo registro carrega as fontes que o
sustentam: lista de {"documento", "pagina"}.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager

from sicai import config

CATEGORIAS = ("pessoa", "crime", "equipamento", "evento")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    processo_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    nome        TEXT NOT NULL,
    tipo_peca   TEXT NOT NULL DEFAULT 'outro',
    paginas     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (processo_id, document_id)
);
CREATE TABLE IF NOT EXISTS paginas (
    processo_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    pagina      INTEGER NOT NULL,
    texto       TEXT NOT NULL,
    PRIMARY KEY (processo_id, document_id, pagina)
);
CREATE TABLE IF NOT EXISTS registros (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id TEXT NOT NULL,
    categoria   TEXT NOT NULL,
    chave       TEXT NOT NULL,
    dados       TEXT NOT NULL,
    fontes      TEXT NOT NULL,
    UNIQUE (processo_id, categoria, chave)
);
"""

_trava = threading.Lock()


class CaseDB:
    def __init__(self, caminho=None):
        self.caminho = str(caminho or (config.DATA_DIR / "sicai.sqlite"))
        if self.caminho != ":memory:":
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Uma conexão compartilhada: SQLite em memória some se a conexão fechar.
        self._conexao = sqlite3.connect(self.caminho, check_same_thread=False)
        self._conexao.row_factory = sqlite3.Row
        with self._transacao() as con:
            con.executescript(_ESQUEMA)

    @contextmanager
    def _transacao(self):
        with _trava:
            try:
                yield self._conexao
                self._conexao.commit()
            except Exception:
                self._conexao.rollback()
                raise

    # -------------------------------------------------------------- documentos
    def salvar_documento(
        self,
        processo_id: str,
        document_id: str,
        nome: str,
        tipo_peca: str,
        paginas: list[dict],
    ) -> None:
        """Grava o documento e suas páginas, substituindo uma versão anterior."""
        with self._transacao() as con:
            con.execute(
                "DELETE FROM paginas WHERE processo_id=? AND document_id=?",
                (processo_id, document_id),
            )
            con.execute(
                "INSERT OR REPLACE INTO documentos VALUES (?,?,?,?,?)",
                (processo_id, document_id, nome, tipo_peca, len(paginas)),
            )
            con.executemany(
                "INSERT INTO paginas VALUES (?,?,?,?)",
                [(processo_id, document_id, p["pagina"], p["texto"]) for p in paginas],
            )

    def listar_processos(self) -> list[dict]:
        with self._transacao() as con:
            linhas = con.execute(
                "SELECT processo_id, COUNT(*) AS documentos, SUM(paginas) AS paginas "
                "FROM documentos GROUP BY processo_id ORDER BY processo_id"
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def listar_documentos(self, processo_id: str) -> list[dict]:
        with self._transacao() as con:
            linhas = con.execute(
                "SELECT document_id, nome, tipo_peca, paginas FROM documentos "
                "WHERE processo_id=? ORDER BY nome",
                (processo_id,),
            ).fetchall()
        return [dict(linha) for linha in linhas]

    # --------------------------------------------------------------- registros
    def listar(self, processo_id: str, categoria: str) -> list[dict]:
        with self._transacao() as con:
            linhas = con.execute(
                "SELECT id, chave, dados, fontes FROM registros "
                "WHERE processo_id=? AND categoria=? ORDER BY id",
                (processo_id, categoria),
            ).fetchall()
        return [
            {
                "id": linha["id"],
                "chave": linha["chave"],
                "dados": json.loads(linha["dados"]),
                "fontes": json.loads(linha["fontes"]),
            }
            for linha in linhas
        ]

    def gravar(
        self,
        processo_id: str,
        categoria: str,
        chave: str,
        dados: dict,
        fontes: list[dict],
    ) -> None:
        """Cria o registro ou, se a chave já existe, substitui dados e une fontes."""
        if categoria not in CATEGORIAS:
            raise ValueError(f"categoria desconhecida: {categoria}")
        with self._transacao() as con:
            atual = con.execute(
                "SELECT id, fontes FROM registros "
                "WHERE processo_id=? AND categoria=? AND chave=?",
                (processo_id, categoria, chave),
            ).fetchone()
            if atual is None:
                con.execute(
                    "INSERT INTO registros (processo_id, categoria, chave, dados, fontes) "
                    "VALUES (?,?,?,?,?)",
                    (processo_id, categoria, chave, _json(dados), _json(_unicas(fontes))),
                )
                return
            unidas = _unicas(json.loads(atual["fontes"]) + list(fontes))
            con.execute(
                "UPDATE registros SET dados=?, fontes=? WHERE id=?",
                (_json(dados), _json(unidas), atual["id"]),
            )

    def atualizar(self, registro_id: int, chave: str, dados: dict, fontes: list[dict]) -> None:
        with self._transacao() as con:
            con.execute(
                "UPDATE registros SET chave=?, dados=?, fontes=? WHERE id=?",
                (chave, _json(dados), _json(_unicas(fontes)), registro_id),
            )

    def remover_fontes_do_documento(self, processo_id: str, documento: str) -> None:
        """Ao reingerir um documento, apaga o que só ele sustentava."""
        with self._transacao() as con:
            linhas = con.execute(
                "SELECT id, dados, fontes FROM registros WHERE processo_id=?",
                (processo_id,),
            ).fetchall()
            for linha in linhas:
                fontes = json.loads(linha["fontes"])
                restantes = [f for f in fontes if f.get("documento") != documento]
                if len(restantes) == len(fontes):
                    continue
                if not restantes:
                    con.execute("DELETE FROM registros WHERE id=?", (linha["id"],))
                    continue
                dados = json.loads(linha["dados"])
                # Papéis de pessoa também citam o documento de onde vieram.
                if isinstance(dados.get("papeis"), list):
                    dados["papeis"] = [
                        p for p in dados["papeis"] if p.get("documento") != documento
                    ]
                con.execute(
                    "UPDATE registros SET dados=?, fontes=? WHERE id=?",
                    (_json(dados), _json(restantes), linha["id"]),
                )

    def contagem(self, processo_id: str) -> dict:
        with self._transacao() as con:
            linhas = con.execute(
                "SELECT categoria, COUNT(*) AS n FROM registros "
                "WHERE processo_id=? GROUP BY categoria",
                (processo_id,),
            ).fetchall()
        return {linha["categoria"]: linha["n"] for linha in linhas}


def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _unicas(fontes: list[dict]) -> list[dict]:
    vistas = []
    for fonte in fontes:
        item = {"documento": fonte["documento"], "pagina": int(fonte["pagina"])}
        if item not in vistas:
            vistas.append(item)
    return vistas


_instancia: CaseDB | None = None


def obter_db() -> CaseDB:
    global _instancia
    if _instancia is None:
        _instancia = CaseDB()
    return _instancia
