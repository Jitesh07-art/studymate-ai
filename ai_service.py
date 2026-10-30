"""Server-side AI calls and clearly labeled local demo examples."""
import json
import re


class AIError(Exception):
    pass


def _client(config):
    if not config["AI_API_KEY"]:
        raise AIError("Add your AI_API_KEY to .env, or turn on demo mode in .env to try sample content.")
    try:
        from openai import OpenAI
        options = {"api_key": config["AI_API_KEY"], "timeout": 40, "max_retries": 1}
        if config["AI_BASE_URL"]:
            options["base_url"] = config["AI_BASE_URL"]
        return OpenAI(**options)
    except Exception as exc:
        raise AIError("The AI service could not be initialized. Check your provider settings.") from exc


def _request(config, system, user, json_mode=False):
    try:
        kwargs = {"model": config["AI_MODEL"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_tokens": 2400}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        result = _client(config).chat.completions.create(**kwargs)
        text = result.choices[0].message.content or ""
        if not text.strip():
            raise AIError("The AI returned an empty response. Please try again.")
        return json.loads(text) if json_mode else text.strip()
    except AIError:
        raise
    except Exception as exc:
        # Do not echo provider details, which can contain sensitive request data.
        raise AIError("The AI request failed. Check your connection, model name, and provider limits, then try again.") from exc


def summarize(config, notes, subject, length, language):
    if config["AI_DEMO_MODE"]:
        sentences = re.split(r"(?<=[.!?])\s+", notes.strip())
        picked = sentences[:2 if length == "Short" else 4 if length == "Medium" else 7]
        return "## " + (subject or "Key ideas") + "\n\n" + "\n".join("- " + s for s in picked if s)
    prompt = f"Summarize the supplied notes in {length.lower()} length. Write in {language}. Preserve key facts, definitions, formulas, and technical terms. Use headings and bullets when useful. Never add facts not present; clearly say when something is unclear. Subject: {subject or 'General study'}.\n\nNOTES:\n{notes}"
    return _request(config, "You are a careful study assistant. Only use the provided source material.", prompt)


def generate_quiz(config, notes, subject, topic, count, difficulty):
    if config["AI_DEMO_MODE"]:
        lines = [line.strip(" -•") for line in notes.splitlines() if len(line.strip(" -•")) > 12]
        if not lines:
            lines = ["StudyMate AI keeps learning material organized."]
        return [{"question": f"Which statement is supported by these notes? ({i + 1})", "options": [lines[i % len(lines)], "This topic is unrelated to the notes.", "The notes provide no information.", "All statements are incorrect."], "answer_index": 0, "explanation": "This option is drawn directly from the supplied notes."} for i in range(count)]
    prompt = f"Create exactly {count} {difficulty.lower()} multiple-choice questions from the notes. Subject: {subject}. Topic: {topic}. Return JSON object {{\"questions\":[{{\"question\":string,\"options\":[four strings],\"answer_index\":integer 0-3,\"explanation\":string}}]}}. Ensure exactly one correct answer and explanations grounded only in notes.\n\nNOTES:\n{notes}"
    data = _request(config, "You create accurate study quizzes. Return valid JSON only.", prompt, True)
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list) or len(questions) != count:
        raise AIError("The AI returned an incomplete quiz. Please try generating it again.")
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str) or not q["question"].strip() or not isinstance(q.get("options"), list) or len(q["options"]) != 4 or not all(isinstance(o, str) and o.strip() for o in q["options"]) or type(q.get("answer_index")) is not int or q["answer_index"] not in range(4) or not isinstance(q.get("explanation"), str) or not q["explanation"].strip():
            raise AIError("The AI returned an invalid quiz format. Please try again.")
    return questions


def generate_flashcards(config, notes, subject, topic, count=8):
    if config["AI_DEMO_MODE"]:
        lines = [line.strip(" -•") for line in notes.splitlines() if line.strip()]
        return [{"question": f"What should you remember about {topic or subject or 'this topic'}?", "answer": line} for line in lines[:count]] or [{"question": "What is in your notes?", "answer": notes[:300]}]
    prompt = f"Create 5 to {count} concise question-and-answer flashcards based only on the notes. Return JSON {{\"cards\":[{{\"question\":string,\"answer\":string}}]}}. Topic: {topic}.\n\nNOTES:\n{notes}"
    data = _request(config, "You create accurate study flashcards. Return valid JSON only.", prompt, True)
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, list) or not cards or len(cards) > count or any(not isinstance(c, dict) or not isinstance(c.get("question"), str) or not c["question"].strip() or not isinstance(c.get("answer"), str) or not c["answer"].strip() for c in cards):
        raise AIError("The AI returned invalid flashcards. Please try again.")
    return cards
