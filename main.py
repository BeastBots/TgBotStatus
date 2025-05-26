#!/usr/bin/env python3
from asyncio import sleep
from logging import basicConfig, INFO, getLogger
from json import loads as json_loads
from time import time
from os import getenv, path as ospath 
from datetime import datetime
import traceback
from collections import defaultdict, OrderedDict

from pytz import utc, timezone
from dotenv import load_dotenv
from requests import get as rget
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.raw import functions
from pyrogram.enums import ParseMode

basicConfig(level=INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
log = getLogger(__name__)

# Configuration loading
if CONFIG_ENV_URL := getenv('CONFIG_ENV_URL'):
    try:
        res = rget(CONFIG_ENV_URL)
        if res.status_code == 200:
            log.info("Downloading .env from CONFIG_ENV_URL")
            with open('.env', 'wb+') as f:
                f.write(res.content)
        else:
            log.error(f"Failed to Download .env due to Error Code {res.status_code}")
    except Exception as e:
        log.error(f"CONFIG_ENV_URL: {e}")

if CONFIG_JSON_URL := getenv('CONFIG_JSON_URL'):
    try:
        res = rget(CONFIG_JSON_URL)
        if res.status_code == 200:
            log.info("Downloading config.json from CONFIG_JSON_URL")
            with open('config.json', 'wb+') as f:
                f.write(res.content)
        else:
            log.error(f"Failed to download config.json due to Error Code {res.status_code}")
    except Exception as e:
        log.error(f"CONFIG_JSON_URL: {e}")

load_dotenv('.env', override=True)

# Environment variables
API_ID = int(getenv("API_ID", 0))
API_HASH = getenv("API_HASH")
PYRO_SESSION = getenv('PYRO_SESSION')
BOT_TOKEN = getenv('BOT_TOKEN')
HEADER_MSG = getenv("HEADER_MSG", "🔥 **Mirror Beast Gateways!**")
FOOTER_MSG = getenv("FOOTER_MSG", "— Powered by Beast")
MSG_BUTTONS = getenv("MSG_BUTTONS")
TIME_ZONE = getenv("TIME_ZONE", "Asia/Kolkata")

# Validation
if PYRO_SESSION is None:
    log.error('PYRO_SESSION is not set')
    exit(1)
if not ospath.exists('config.json'):
    log.error("config.json not Found!")
    exit(1)

try:
    config = json_loads(open('config.json', 'r').read())
    bots = config['bots']
    channels = config['channels']
except Exception as e:
    log.error(str(e))
    log.error("Error: config.json is not valid")
    exit(1)

# Initialize clients
log.info("Connecting pyroBotClient")
try:
    client = Client("TgBotStatus", api_id=API_ID, api_hash=API_HASH, session_string=PYRO_SESSION, no_updates=True)
except BaseException as e:
    log.warning(e)
    exit(1)

bot = None
if BOT_TOKEN:
    try:
        bot = Client("TgBotStatusBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, no_updates=True)
        log.info("Bot token client initialized")
    except BaseException as e:
        log.warning(f"Failed to initialize bot client: {e}")

class BotStatusManager:
    def __init__(self):
        self.bot_stats = {}
        self.available_bots = 0
        self.total_bots = len(bots.keys())
        self.groups = self._extract_groups_from_config()
        
    def _extract_groups_from_config(self):
        """Extract unique group names from bot configuration and maintain order"""
        groups = OrderedDict()
        
        for bot_id, bot_data in bots.items():
            group_name = bot_data.get('group', 'OTHER')  # Default to 'OTHER' if no group specified
            if group_name not in groups:
                groups[group_name] = []
                
        log.info(f"Found groups in config: {list(groups.keys())}")
        return groups
        
    def progress_bar(self, current, total):
        total_balls = min(total, 20)  # Limit visual length
        pct = current / total * 100 if total > 0 else 0
        p = min(max(pct, 0), 100)
        cFull = int(p // (100 / total_balls))
        p_str = '⬤' * cFull + '○' * (total_balls - cFull)
        return f"[{p_str}] {round(pct, 2)}%"
    
    @staticmethod
    def get_readable_time(seconds):
        if seconds <= 0:
            return '0ms'
        
        mseconds = int(seconds * 1000)
        periods = [('d', 86400000), ('h', 3600000), ('m', 60000), ('s', 1000), ('ms', 1)]
        result = ''
        
        for period_name, period_seconds in periods:
            if mseconds >= period_seconds:
                period_value, mseconds = divmod(mseconds, period_seconds)
                result += f'{int(period_value)}{period_name}'
                
        return result if result else '0ms'
    
    @staticmethod
    def get_readable_file_size(size_in_bytes):
        if size_in_bytes is None:
            return '0B'
        
        SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB']
        index = 0
        
        while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
            size_in_bytes /= 1024
            index += 1
            
        return f'{size_in_bytes:.2f}{SIZE_UNITS[index]}' if index > 0 else f'{int(size_in_bytes)}B'

    async def get_bot_mention(self, user_id):
        try:
            user = await client.get_users(user_id)
            return user.mention
        except Exception as e:
            log.error(f"Failed to get user mention for {user_id}: {e}")
            return str(user_id)

    def make_buttons(self):
        if not MSG_BUTTONS:
            return None
            
        btns = []
        for row in MSG_BUTTONS.split('||'):
            row_btns = []
            for sbtn in row.split('|'):
                try:
                    btext, link = sbtn.split('#', maxsplit=1)
                    row_btns.append(InlineKeyboardButton(btext.strip(), url=link.strip()))
                except ValueError:
                    log.warning(f"Invalid button format: {sbtn}")
                    continue
            if row_btns:
                btns.append(row_btns)
        
        return InlineKeyboardMarkup(btns) if btns else None

    async def edit_message(self, chat_id, message_id, text, media_url=None):
        """Edit message using bot client if available, otherwise fallback to user client"""
        editing_client = bot if bot else client
        
        try:
            if media_url:
                # For media messages, set parse_mode on InputMediaPhoto
                media = InputMediaPhoto(
                    media=media_url, 
                    caption=text,
                    parse_mode=ParseMode.HTML
                )
                post_msg = await editing_client.edit_message_media(
                    int(chat_id),
                    int(message_id),
                    media
                )
            else:
                post_msg = await editing_client.edit_message_text(
                    int(chat_id), 
                    int(message_id), 
                    text,
                    disable_web_page_preview=True,
                    parse_mode=ParseMode.HTML
                )
            
            # Add buttons if bot token is available
            if bot and MSG_BUTTONS:
                buttons = self.make_buttons()
                if buttons:
                    await bot.edit_message_reply_markup(post_msg.chat.id, post_msg.id, buttons)
                    
        except FloodWait as f:
            log.warning(f"FloodWait: {f.value}s")
            await sleep(f.value * 1.2)
            await self.edit_message(chat_id, message_id, text, media_url)
        except MessageNotModified:
            log.debug("Message not modified - content unchanged")
        except Exception as e:
            log.error(f"Error editing message: {str(e)}")
            log.error(traceback.format_exc())

    async def update_all_channels(self, status_msg, media_url=None):
        """Update all configured channels with status message"""
        _channels = channels.values()
        if len(_channels) == 0:
            log.warning("No channels configured")
            return
            
        for channel in _channels:
            log.info(f"Updating Channel ID: {channel['chat_id']}, Message ID: {channel['message_id']}")
            await sleep(1.5)  # Rate limiting
            
            try:
                await self.edit_message(
                    channel['chat_id'], 
                    channel['message_id'], 
                    status_msg, 
                    media_url
                )
            except Exception as e:
                log.error(f"Failed to update channel {channel['chat_id']}: {str(e)}")
                continue

    def format_status_message(self):
        """Format the complete status message with dynamic grouping from JSON"""
        # Group bots by their group property from JSON
        grouped_bots = defaultdict(list)
        
        for bot_id, stats in self.bot_stats.items():
            bot_data = bots.get(bot_id, {})
            group_name = bot_data.get('group', 'OTHER')  # Default group if not specified
            grouped_bots[group_name].append((bot_id, stats, bot_data))
        
        # Sort bots within each group by their order in the original config
        for group_name in grouped_bots:
            grouped_bots[group_name].sort(key=lambda x: list(bots.keys()).index(x[0]))
        
        header = f"<blockquote><b>{HEADER_MSG}</b></blockquote>\n\n"
        status_msg = header + f"• <b>Available Bots:</b> {self.available_bots}\n\n"
        
        # Use the groups found in config to maintain order
        for group_name in self.groups.keys():
            if group_name not in grouped_bots:
                continue
                
            # Add group header
            status_msg += f"<blockquote><b>{group_name}</b></blockquote>\n"
            
            # Add bots in this group
            for bot_id, stats, bot_data in grouped_bots[group_name]:
                custom_name = bot_data.get('custom_name', stats.get('bot_uname', bot_id))
                status = stats.get('status', 'Unknown')
                response_time = stats.get('response_time', '')
                
                if response_time and status == "Alive 🔥":
                    status_msg += f"• <b>{custom_name}</b> is <code>{status}</code> ({response_time})\n"
                else:
                    status_msg += f"• <b>{custom_name}</b> is <code>{status}</code>\n"
            
            status_msg += "\n"
        
        # Handle any bots that might not have a group (fallback)
        if 'OTHER' in grouped_bots and 'OTHER' not in self.groups:
            status_msg += f"<blockquote><b>OTHER</b></blockquote>\n"
            for bot_id, stats, bot_data in grouped_bots['OTHER']:
                custom_name = bot_data.get('custom_name', stats.get('bot_uname', bot_id))
                status = stats.get('status', 'Unknown')
                response_time = stats.get('response_time', '')
                
                if response_time and status == "Alive 🔥":
                    status_msg += f"• <b>{custom_name}</b> is <code>{status}</code> ({response_time})\n"
                else:
                    status_msg += f"• <b>{custom_name}</b> is <code>{status}</code>\n"
            status_msg += "\n"
        
        # Add footer
        footer_info = [
            "• All DC: 4 Powered, Premium Bots",
            "• All Bots Have 4GB Leech Support", 
            "• No Limits ~ Mirror Leech Unlimited",
            "• No Shorteners ~ No Ads",
            "• Premium Google Drive | Index Links"
        ]
        
        status_msg += "<blockquote>" + "\n".join(footer_info) + "</blockquote>\n\n"
        status_msg += f"<i>{FOOTER_MSG}</i>"
        
        return status_msg

    async def check_bot_status(self, bot_id, bot_data):
        """Check individual bot status"""
        self.bot_stats.setdefault(bot_id, {})
        self.bot_stats[bot_id]['bot_uname'] = bot_data['bot_uname']
        self.bot_stats[bot_id]['host'] = bot_data.get('host', 'Unknown')
        
        pre_time = time()
        
        try:
            log.info(f"Checking bot: {bot_data['bot_uname']} (Group: {bot_data.get('group', 'OTHER')})")
            
            # Send start command
            sent_msg = await client.send_message(bot_data['bot_uname'], "/start")
            await sleep(5)
            
            # Get recent messages
            history_msgs = await client.invoke(
                functions.messages.GetHistory(
                    peer=await client.resolve_peer(bot_data['bot_uname']),
                    offset_id=0,
                    offset_date=0, 
                    add_offset=0,
                    limit=1,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
            
            if sent_msg.id == history_msgs.messages[0].id:
                self.bot_stats[bot_id]["status"] = "DED 💀"
            else:
                resp_time = history_msgs.messages[0].date - int(pre_time)
                self.available_bots += 1
                self.bot_stats[bot_id]["response_time"] = self.get_readable_time(resp_time)
                self.bot_stats[bot_id]["status"] = "Alive 🔥"
                
            await client.read_chat_history(bot_data['bot_uname'])
            
        except Exception as e:
            log.error(f"Error checking bot {bot_data['bot_uname']}: {str(e)}")
            log.error(traceback.format_exc())
            self.bot_stats[bot_id]["status"] = "DED 💀"
        
        log.info(f"Bot {bot_data['bot_uname']} status: {self.bot_stats[bot_id]['status']}")

    async def run_status_check(self):
        """Main status checking workflow"""
        start_time = time()
        self.available_bots = 0
        
        log.info("Starting bot status checks...")
        log.info(f"Groups detected: {list(self.groups.keys())}")
        
        # Initial status message
        header = f"<blockquote><b>{HEADER_MSG}</b></blockquote>\n\n"
        initial_msg = header + f"""• <b>Available Bots:</b> <i>Checking...</i>

• <code>Updating Gateways...</code>

<b>Status Update Stats:</b>
<b>Bots Verified:</b> 0 out of {self.total_bots}
<b>Time Elapsed:</b> 0s"""

        await self.update_all_channels(initial_msg, getenv("MEDIA"))
        
        # Check each bot
        bot_no = 0
        for bot_id, bot_data in bots.items():
            if not bot_id or not bot_data:
                log.warning(f"Skipping invalid bot: {bot_id}")
                continue
                
            await self.check_bot_status(bot_id, bot_data)
            bot_no += 1
            
            # Update progress
            progress_msg = header + f"""• <b>Available Bots:</b> <i>Checking...</i>

<b>Status Update Stats:</b>
<b>Bots Checked:</b> {bot_no} out of {self.total_bots}
<b>Progress:</b> {self.progress_bar(bot_no, self.total_bots)}
<b>Time Elapsed:</b> {self.get_readable_time(time() - start_time)}"""

            await self.update_all_channels(progress_msg, getenv("MEDIA"))
        
        # Final status message
        final_msg = self.format_status_message()
        await self.update_all_channels(final_msg, getenv("MEDIA"))
        
        log.info(f"Status check completed in {self.get_readable_time(time() - start_time)}")

async def main():
    """Main application entry point"""
    try:
        log.info("Starting bot status monitoring...")
        
        # Initialize clients
        async with client:
            if bot:
                async with bot:
                    status_manager = BotStatusManager()
                    await status_manager.run_status_check()
            else:
                status_manager = BotStatusManager()
                await status_manager.run_status_check()
                
        log.info("Bot status monitoring completed successfully")
        
    except Exception as e:
        log.error(f"Critical error in main workflow: {str(e)}")
        log.error(traceback.format_exc())

if __name__ == "__main__":
    client.run(main())