from typing import Any

from telegram import Message, Update
from telegram.error import BadRequest


TELEGRAM_SAFE_LIMIT = 3200


def split_long_message(message: str, limit: int = TELEGRAM_SAFE_LIMIT) -> list[str]:
    text = str(message or "").strip()

    if not text:
        return ["No message content available."]

    chunks = []
    current_chunk = ""

    for line in text.splitlines():
        while len(line) > limit:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            chunks.append(line[:limit])
            line = line[limit:]

        candidate = f"{current_chunk}\n{line}" if current_chunk else line

        if len(candidate) > limit:
            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = line
        else:
            current_chunk = candidate

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def edit_message_safely(
    message: Message,
    text: str,
    parse_mode: str | None = None,
) -> bool:
    try:
        await message.edit_text(
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
        return True
    except BadRequest:
        return False


async def reply_long_message(
    update: Update,
    text: str,
    title: str | None = None,
    parse_mode: str | None = None,
) -> None:
    if not update.message:
        return

    chunks = split_long_message(text)

    for index, chunk in enumerate(chunks, start=1):
        if title and len(chunks) > 1:
            message_text = f"{title} Part {index}/{len(chunks)}\n\n{chunk}"
        else:
            message_text = chunk

        await update.message.reply_text(
            text=message_text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )


async def edit_or_reply_long_message(
    update: Update,
    loading_message: Message,
    text: str,
    title: str | None = None,
    parse_mode: str | None = None,
) -> None:
    chunks = split_long_message(text)

    if len(chunks) == 1:
        edited = await edit_message_safely(
            message=loading_message,
            text=chunks[0],
            parse_mode=parse_mode,
        )

        if not edited:
            await reply_long_message(
                update=update,
                text=chunks[0],
                title=title,
                parse_mode=parse_mode,
            )

        return

    await edit_message_safely(
        message=loading_message,
        text="✅ Report ready. Sending in parts below...",
        parse_mode=None,
    )

    await reply_long_message(
        update=update,
        text=text,
        title=title,
        parse_mode=parse_mode,
    )


async def send_long_message_to_chat(
    bot: Any,
    chat_id: str | int,
    text: str,
    title: str | None = None,
    parse_mode: str | None = None,
) -> None:
    chunks = split_long_message(text)

    for index, chunk in enumerate(chunks, start=1):
        if title and len(chunks) > 1:
            message_text = f"{title} Part {index}/{len(chunks)}\n\n{chunk}"
        else:
            message_text = chunk

        await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )