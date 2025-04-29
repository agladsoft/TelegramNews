from config import *
from telethon import TelegramClient, events
from telethon.tl.types import UpdateEditMessage

client = TelegramClient('session_name', API_ID, API_HASH)

@client.on(events.Raw)
async def handler(update):
    if isinstance(update, UpdateEditMessage):
        chat_id = update.message.chat_id
        msg_id = update.message.id
        reactions = update.message.reactions.results if update.message.reactions else []
        print(f"Новое изменение реакций в чате {chat_id}, сообщение {msg_id}: {reactions}")

client.start()
client.run_until_disconnected()
