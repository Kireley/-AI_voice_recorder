import aiohttp

async def ask_yandex_gpt(api_key: str, folder_id: str, system_prompt: str, user_text: str) -> str:
    url = "https://api.cloud." + "yandex.net/foundationModels/v1/completion"
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id": folder_id,
    }
    payload = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-4-lite/latest",
        "completionOptions": {"stream": False, "temperature": 0.1, "maxTokens": "2000"},
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": f"<transcript>{user_text}</transcript>"},
        ],
    }

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                alternatives = data.get("result", {}).get("alternatives", [])
                if alternatives:
                    reply = alternatives[0]["message"]["text"].strip()
                    if "не могу обсуждать эту тему" not in reply.lower():
                        return reply
    return ""

