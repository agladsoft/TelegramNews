import re
import aiohttp
import asyncio
from config import *
from telethon import TelegramClient, events


class TelegramNewsBot:
    def __init__(self, channels, limit=2):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH) # type: ignore
        self.channels = channels
        self.limit = limit
        self._sent_group_ids = set()

    @staticmethod
    def escape_telegram_usernames(text):
        """
        Экранирует символы подчеркивания в никнеймах Telegram (@username_with_underscores)
        чтобы избежать ошибок парсинга MarkdownV2.
        """
        import re
        # Экранируем все подчеркивания в словах, начинающихся с @ и содержащих _
        def replacer(match):
            return match.group(0).replace('_', '\\_')
        # Слово начинается с @, за которым идут буквы/цифры/подчеркивания, и есть хотя бы один _
        return re.sub(r'@\w*_\w*', replacer, text)

    def escape_markdown_v2(self, text):
        """
        Escape Markdown v2 and convert Telegram-style formatting to Markdown.

        This function escapes Markdown syntax in Telegram messages, except for URLs.
        It also converts Telegram-style formatting (e.g. **bold**, __italic__, etc.) to Markdown.

        :param text: The text to escape and convert
        :return: The escaped and converted text
        """
        # Экранируем никнеймы с подчеркиванием
        text = self.escape_telegram_usernames(text)

        # Обрабатываем ссылки отдельно, чтобы не экранировать URL
        link_pattern = re.compile(r'(\[([^]]+)]\(([^)]+)\))')
        pos = 0
        result = ''

        for m in link_pattern.finditer(text):
            # Экранируем текст до текущей ссылки
            before = text[pos:m.start()]
            before = re.sub(PATTERN_URL, r'\\\1', before)

            # Экранируем только текст внутри []
            link_text = re.sub(PATTERN_URL, r'\\\1', m.group(2))
            url = m.group(3)  # URL не экранируем

            result += before + f'[{link_text}]({url})'
            pos = m.end()

        # Экранируем текст после последней ссылки
        after = text[pos:]
        after = re.sub(PATTERN_URL, r'\\\1', after)
        result += after

        # Преобразуем стилевое форматирование Markdown
        formatting_rules = [
            (r'\*\*(.+?)\*\*', r'*\1*'),  # Жирный текст
            (r'__(.+?)__', r'__\1__'),  # Подчёркнутый текст
            (r'_(.+?)_', r'_\1_'),  # Курсив
            (r'~(.+?)~', r'~\1~'),  # Зачёркнутый текст
            (r'\|\|(.+?)\|\|', r'||\1||')  # Спойлер
        ]

        for pattern, replacement in formatting_rules:
            result = re.sub(pattern, replacement, result)

        return result

    def format_caption(self, message, channel):
        """
        Formats a caption for a message based on its source and content.

        The caption will include the source title and a link to the message in the source
        channel. If the source channel has no username, the caption will only include the
        source title.

        The content of the message is escaped using Markdown v2 rules.

        :param message: The message to format the caption for
        :param channel: The source channel of the message
        :return: The formatted caption
        """
        source_title = channel.lstrip('@') if channel else 'Unknown'
        source_username = channel.lstrip('@') if channel else None

        if source_username:
            post_link = f"https://t.me/{source_username}/{getattr(message, 'id', '')}"
            safe_title = re.sub(PATTERN_URL, r'\\\1', source_title)
            caption = f"🔁 Переслано из [{safe_title}]({post_link})"
        else:
            safe_title = re.sub(PATTERN_URL, r'\\\1', source_title)
            caption = f"🔁 Переслано из {safe_title}"
        if message.text:
            caption += "\n\n" + self.escape_markdown_v2(message.text)
        return caption

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
        safe_title = re.sub(PATTERN_URL, r'\\1', channel.lstrip('@') or 'Unknown')
        post_link = f"https://t.me/{channel.lstrip('@')}/{getattr(first, 'id', '')}"
        caption = f"🔁 Переслано из [{safe_title}]({post_link})\n\n{self.escape_markdown_v2(text)}"
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
