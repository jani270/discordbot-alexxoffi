import functools
import json
from datetime import datetime
from discord import Embed
from enum import Enum, unique
from src.database import dbcommon
from src.dcbot import client
from src.translation import transget

# Server Keys
key_bot_mainserver = "bot_main_server"

# Singlechannel keys
key_bot_adminchannel = "bot_admin_channel"
key_bot_logchannel = "bot_log_channel"
key_bot_applychannel = "bot_gapply_channel"
key_bot_applydestchannel = "bot_gapplydest_channel"
key_bot_splashchannel = "bot_gsplash_channel"
key_bot_newpublicvoicechannel = "bot_newpublicvoice_channel"
key_bot_newprivatevoicechannel = "bot_newprivatevoice_channel"

# Multichannel keys
key_bot_userchannel = "bot_user_botchannel"

# Permission keys
key_permlevel_fullmuted = -10
key_permlevel_restricted = -1
key_permlevel_user = 0
key_permlevel_elevated = 1
key_permlevel_moderator = 10
key_permlevel_supermod = 50
key_permlevel_admin = 90
key_permlevel_owner = 100

# More bot settings keys
key_bot_init_stage = "bot_init_stage"
key_bot_prefix = "bot_shortprefix"
default_user_preferred_language = "de"

key_color_info = 0xDEDEDE
key_color_muted = 0x2E2E2E
key_color_okay = 0x7DDE4D
key_color_warning = 0xEFA43D
key_color_danger = 0xEF3D3D

# Common quick-access variables for the bot, may be None if not initialized yet
main_guild = None

# Voice channel object:
bot_voice_channels = []

# Currently registered commands
registered_bot_commands = []
# Currently registered message processors
registered_message_processors = []

# Hypixel API
hypixel_api = None

# Is the bot currently shutting down? This is used for disabling events
# while cleaning up the server and is set from inside the 'stop' command
is_bot_stopping = False


# Stat types for Hypixel skyblock skill leveling challenges
# Name "Skill leveling challenges" is bad - it supports all stats,
# not only skills
@unique
class StatTypes(Enum):
    FARMING = "experience_skill_farming"
    COMBAT = "experience_skill_combat"
    MINING = "experience_skill_mining"
    FORAGING = "experience_skill_foraging"
    FISHING = "experience_skill_fishing"
    ENCHANTING = "experience_skill_enchanting"
    ALCHEMY = "experience_skill_alchemy"
    TAMING = "experience_skill_taming"
    CARPENTRY = "experience_skill_carpentry"
    RUNECRAFTING = "experience_skill_runecrafting"
    CATACOMBS = "dungeons/dungeon_types/catacombs/experience"
    SLAYER_REVENANT = "slayer_bosses/zombie/xp"
    SLAYER_TARANTULA = "slayer_bosses/spider/xp"
    SLAYER_SVEN = "slayer_bosses/wolf/xp"

    @classmethod
    def has_value(cls, value):
        return str(value) in cls._value2member_map_

    def describe(self):
        return self.name, self.value

    def __str__(self):
        return f"{self.value}"

# Challenge types for Hypixel skyblock skill leveling challenges
@unique
class ChallengeStatus(Enum):
    OPEN = "OPEN"
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    ENDING = "ENDING"
    ENDED = "ENDED"

    @classmethod
    def has_value(cls, value):
        return str(value) in cls._value2member_map_

    def describe(self):
        return self.name, self.value

    def __str__(self):
        return f"{self.value}"


# A Skill leveling challenge object
class ChallengeEvent():

    def __init__(self, challenge_dict):
        self.uuid = challenge_dict['uuid']
        self.title = challenge_dict['title']
        self.type = challenge_dict['type']
        self.status = challenge_dict['status']
        self.entries_close_time = challenge_dict['entries_close_time']
        self.start_time = challenge_dict['start_time']
        self.end_time = challenge_dict['end_time']
        self.pay_in = challenge_dict['pay_in']
        self.auto_accept = challenge_dict['auto_accept']
        if 'announcement_message_id' in challenge_dict:
            self.announcement_message_id = \
                challenge_dict['announcement_message_id']
        else:
            self.announcement_message_id = None
        self.players = challenge_dict['players']
        pass

    def get_embed(self):
        embed = Embed(title=self.title)
        embed.add_field(name="Event UUID", value=self.uuid, inline=False)
        embed.add_field(name="Event Type", value=self.type.name)
        embed.add_field(name="Event Status", value=self.status.name)
        embed.add_field(name="Join until", value=self.entries_close_time)
        embed.add_field(name="Event starts", value=self.start_time)
        embed.add_field(name="Event ends", value=self.end_time)
        embed.add_field(name="Join cost", value=str(self.pay_in) + " Coins") \
            if self.pay_in != 0 else \
            embed.add_field(name="Join cost", value="No cost")
        embed.add_field(
            name="Moderator needs to accept joins",
            value=not self.auto_accept)
        embed.add_field(
            name="Current participants",
            value=str(len(self.players)) + "/100")
        embed.add_field(
            name="Join now",
            value="using `$chall join <mc-username>` in a bot-commands "
            + "channel!",
            inline=False) if self.status == ChallengeStatus.OPEN else None
        return embed

    def serialize(self):
        return json.dumps({
            'uuid': self.uuid,
            'title': self.title,
            'type': self.type.name,
            'status': self.status.name,
            'entries_close_time': self.entries_close_time.timestamp(),
            'start_time': self.start_time.timestamp(),
            'end_time': self.end_time.timestamp(),
            'pay_in': self.pay_in,
            'auto_accept': self.auto_accept,
            'anouncement_message_id': self.announcement_message_id,
            'players': self.players
        }, indent=2)

    @staticmethod
    def deserialize(input):
        challenge_dict = json.loads(input)
        return ChallengeEvent({
            'uuid': challenge_dict['uuid'],
            'title': challenge_dict['title'],
            'type': StatTypes[challenge_dict['type']],
            'status': ChallengeStatus[challenge_dict['status']],
            'entries_close_time': datetime.fromtimestamp(
                challenge_dict['entries_close_time']),
            'start_time': datetime.fromtimestamp(challenge_dict['start_time']),
            'end_time': datetime.fromtimestamp(challenge_dict['end_time']),
            'pay_in': challenge_dict['pay_in'],
            'auto_accept': challenge_dict['auto_accept'],
            'announcement_message_id': challenge_dict[
                'announcement_message_id'],
            'players': challenge_dict['players']
        })


# Challenges open for members to enter
open_challenges = {}

# Challenges starting soon, so entries are closed already
pending_challenges = {}

# Challenges currently active
active_challenges = {}


async def get_member_by_id_or_ping(selector):
    user_id = selector.lstrip("<@!").lstrip("<@").rstrip(">")
    guild = main_guild
    try:
        member = guild.get_member(user_id)
        if member is None:
            member = await guild.fetch_member(user_id)
        return member
    except Exception:
        return None


async def get_channel_by_id_or_ping(selector):
    channel_id = selector.lstrip("<#").rstrip(">")
    guild = main_guild
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            channel = await client.fetch_channel(channel_id)
        return channel
    except Exception:
        return None


# Decorator for permission constraints on commands
def requires_perm_level(level):

    def decorator(func):
        @functools.wraps(func)
        async def decorated(*args, **kwargs):
            if args[2].user_permission_level >= level:
                return await func(*args, **kwargs)
            else:
                return None
        return decorated
    return decorator


# Decorator for channel constraints on commands
def requires_channel(channel_key_list):
    def decorator(func):
        @functools.wraps(func)
        async def decorated(*args, **kwargs):
            full_channel_list = []
            for channel_key in channel_key_list:
                channels = dbcommon.get_channel_ids_from_key(channel_key)
                full_channel_list = full_channel_list + channels
            full_channel_list = list(dict.fromkeys(full_channel_list))
            if full_channel_list == [None] or full_channel_list == [] or \
                    full_channel_list is None:
                return await func(*args, **kwargs)
            full_channel_list = [int(x) for x in full_channel_list]
            if args[0].channel.id in full_channel_list:
                return await func(*args, **kwargs)
        return decorated
    return decorator


async def trytolog(message, arg_stack, botuser, embed):
    logchannel_id = dbcommon.get_bot_setting(key_bot_logchannel, 0)
    try:
        logchannel = await client.fetch_channel(logchannel_id)
    except Exception:
        await message.channel.send(
            transget('dcbot.log.error.channel', botuser.user_pref_lang))
        await message.channel.send(embed=embed)
        return
    else:
        if logchannel is None:
            await message.channel.send(
                transget('dcbot.log.error.channel', botuser.user_pref_lang))
            await message.channel.send(embed=embed)
            return
        else:
            await logchannel.send(embed=embed)
            return
