from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    # Вход
    user_query: str
    input_source: str              # chat | whisper | file
    has_file: bool
    file_content: Optional[str]

    # Роутер
    intent: str                    # recommend | follow_up | clarify | refuse | unsafe
    risk: str                      # low | high
    user_summary: str
    has_text_fragment: bool

    # Экстрактор
    genres: List[str]
    extracted_tropes: List[str]
    excluded_tropes: List[str]

    # Поиск / магазины / ответ
    search_results: List[Dict[str, Any]]
    store_links: Dict[str, List[Dict[str, Any]]]
    final_answer: str
    route: str
