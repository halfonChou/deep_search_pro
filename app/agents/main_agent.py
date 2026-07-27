from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.infra.db import Database
from app.infra.emitter import EventEmitter


@dataclass
class AgentDeps:
    settings: Settings
    emitter: EventEmitter
    session_dir: Path
    thread_id:str = ""
    tools:list = field(default_factory=list)
    db:Database | None = None
    pdf_converter:object | None = None
    retriever:object | None = None

def build_main_agent(deps:AgentDeps):
    from app.infra.llm import build_chat_model
    from app.prompt import main_agent_prompt
    from app.tools.doc_tools import build_doc_tools
    from app.tools.search_tools import build_search_tools

    model = build_chat_model(deps.settings)
    search_tools = build_search_tools(deps.emitter,deps.settings)
    doc_tools = build_doc_tools(deps.session_dir, deps.emitter)

    all_tools = search_tools + doc_tools + deps.tools

    return {
        "model": model,
        "prompt": main_agent_prompt(),
        "tools": all_tools,
    }
