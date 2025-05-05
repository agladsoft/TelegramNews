import aiohttp
import asyncio
from config import *
from telethon import TelegramClient, events


class TelegramNewsBot:
    def __init__(self, channels, limit=20):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH) # type: ignore
        self.channels = channels
        self.limit = limit
        self._sent_group_ids = set()

    @staticmethod
    async def send_to_n8n(data):
        """
        Asynchronously sends a payload to the n8n webhook.

        :param data: The payload to send to n8n
        :return: None
        """
        async with aiohttp.ClientSession() as session:
            await session.post(WEBHOOK_URL, json=data)

    @staticmethod
    def _group_messages(messages):
        """
        Groups messages by their grouped_id or id, and returns a list of sorted lists.

        Each sublist contains messages with the same grouped_id or id, sorted by their id.

        :param messages: List of messages to group
        :return: List of sorted lists of messages
        """
        grouped, order = {}, []
        for m in messages:
            key = m.grouped_id or m.id
            if key not in grouped:
                order.append(key)
                grouped[key] = []
            grouped[key].append(m)
        return [sorted(grouped[k], key=lambda message: message.id) for k in order]

    @staticmethod
    def escape_text(text: str) -> str:
        """
        Escapes special characters in a given string so that it can be safely used as a markdown string.

        :param text: The string to escape
        :return: The escaped string
        """
        # sourcery skip: assign-if-exp, inline-immediately-returned-variable, use-join
        special_chars = "_*[]()~`>#+-=|{}.!"
        escaped_text = ''
        for char in text:
            if char in special_chars:
                escaped_text += '\\' + char
            else:
                escaped_text += char
        return escaped_text

    def _build_payload(self, channel, msgs):
        """
        Builds a payload to be sent to the n8n webhook from a list of messages.

        The payload includes the channel name, the concatenated text of all messages,
        a caption that includes the source title and a link to the first message in the
        source channel, and the message and channel IDs of the last message in the list.

        :param channel: The source channel of the messages
        :param msgs: The list of messages to build the payload from
        :return: A dictionary with the payload to be sent to n8n
        """
        text = ''.join(m.text or '' for m in msgs)
        first = msgs[0]
        post_link = f"https://t.me/{channel.lstrip('@')}/{getattr(first, 'id', '')}"
        caption = self.escape_text(f"🔁 Переслано из {post_link}\n\n{text}")

        return {
            "channel": channel,
            "text": text,
            "caption": caption,
            "message_id": msgs[-1].id,
            "from_channel_id": msgs[-1].chat_id
        }

    async def fetch_messages(self):
        """
        Fetches the latest messages from each channel, groups them by their grouped_id or id,
        and sends a payload to the n8n webhook for each group.

        The payload includes the channel name, the concatenated text of all messages,
        a caption that includes the source title and a link to the first message in the
        source channel, and the message and channel IDs of the last message in the list.

        :return: None
        """
        await self.client.start()
        for channel in self.channels:
            msgs = [m async for m in self.client.iter_messages(channel, self.limit)]
            for group in self._group_messages(msgs):
                await self.send_to_n8n(self._build_payload(channel, group))
        await self.client.disconnect()
        print(f"✅ Отправлены последние {self.limit} логических сообщений из каждого канала в n8n")

    async def listen_for_new_messages(self):
        """
        Listens for new messages in the channels and sends a payload to the n8n webhook for each logical message.

        The payload includes the channel name, the concatenated text of all messages,
        a caption that includes the source title and a link to the first message in the
        source channel, and the message and channel IDs of the last message in the list.

        :return: None
        """
        self._sent_group_ids.clear()
        @self.client.on(events.NewMessage(chats=self.channels))
        async def handler(event):
            msg = event.message
            chat = event.chat
            channel = chat.username if chat and chat.username else chat.title if chat else 'unknown'
            gid = msg.grouped_id or msg.id
            if gid in self._sent_group_ids:
                return
            msgs = [m async for m in self.client.iter_messages(chat, limit=20)]
            for group in self._group_messages(msgs):
                key = group[0].grouped_id or group[0].id
                if key == gid:
                    await self.send_to_n8n(self._build_payload(channel, group))
                    self._sent_group_ids.add(gid)
                    break
        await self.client.start()
        print("👂 Слушаю новые сообщения и отправляю их в n8n...")
        await self.client.run_until_disconnected()


if __name__ == "__main__":
    bot = TelegramNewsBot(CHANNELS)
    asyncio.run(bot.listen_for_new_messages())
