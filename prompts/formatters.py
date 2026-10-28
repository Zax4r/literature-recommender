def build_user_context(query: str | None, file_text: str | None)->str:
    safe_query = query.strip() if query else ""
    safe_file = file_text.strip() if file_text else ""

    if safe_query and safe_file:
        return (
            f"Пожелание пользователя: {safe_query}\n\n"
            f"--- НАЧАЛО ПРИКРЕПЛЕННОГО ТЕКСТА ---\n"
            f"{safe_file}\n"
            f"--- КОНЕЦ ПРИКРЕПЛЕННОГО ТЕКСТА ---"
        )
    elif safe_file:
        return (
            f"--- НАЧАЛО ПРИКРЕПЛЕННОГО ТЕКСТА ---\n"
            f"{safe_file}\n"
            f"--- КОНЕЦ ПРИКРЕПЛЕННОГО ТЕКСТА ---"
        )
    return f"Пожелание пользователя: {safe_query}"