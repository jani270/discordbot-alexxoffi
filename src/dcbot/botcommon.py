import functools
import json
import threading
import time
import os
from lib.hypixel.hypixelv2 import SBAPIRequest, RequestType
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

# This variable is set to False on first on_ready call
is_initial_start = True

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
    DISCARDED = "DISCARDED"

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
        self.announcement_channel_id = challenge_dict[
            'announcement_channel_id']

        if 'announcement_message_id' in challenge_dict:
            self.announcement_message_id = \
                challenge_dict['announcement_message_id']
        else:
            self.announcement_message_id = None
        self.players = challenge_dict['players']

        pass

    async def delete_announcement(self):
        message = await get_message_by_id(
            self.announcement_channel_id,
            self.announcement_message_id)
        await message.delete()

    async def discard(self):
        self.status = ChallengeStatus.DISCARDED
        await self.update_challenge_embed()
        challenge_scheduler.removeTask(self)
        self.archive_to_disk()

    def archive_to_disk(self):
        with open(f"./data/xp_events/{self.uuid}.json", 'w') as f:
            f.write(self.serialize())

    def get_player(self, payload):
        for player in self.players:
            if str(player['mcname']) == str(payload):
                return player
            if str(player['mcuuid']) == str(payload):
                return player
            if str(player['discordid']) == str(payload):
                return player
        return None

    def get_pending_players(self):
        pending_players = []
        for player in self.players:
            if player['state'] == "PENDING":
                pending_players.append(player)
        return pending_players

    def get_total_players(self):
        return self.players

    def get_active_players(self):
        active_players = []
        for player in self.players:
            if player['state'] == "ACTIVE":
                active_players.append(player)
        return active_players

    def get_accepted_players(self):
        accepted_players = []
        for player in self.players:
            if player['state'] == "ACCEPTED":
                accepted_players.append(player)
        return accepted_players

    def get_errored_players(self):
        errored_players = []
        for player in self.players:
            if player['state'] == "ERRORED":
                errored_players.append(player)
        return errored_players

    def get_disqualified_players(self):
        disqualified_players = []
        for player in self.players:
            if player['state'] == "DISQUALIFIED":
                disqualified_players.append(player)
        return disqualified_players

    def get_finished_players(self):
        finished_players = []
        for player in self.players:
            if player['state'] == "FINISHED":
                finished_players.append(player)
        return finished_players

    async def update_challenge_embed(self):
        message = await get_message_by_id(
            self.announcement_channel_id, self.announcement_message_id)
        if message is None:
            print("Event Announcement message tried to be updated, but "
                  + "failed!")
            return
        await message.edit(content=None, embed=self.get_embed())
        return

    def get_type_name(self):
        if self.status == ChallengeStatus.OPEN:
            return "(Type HIDDEN)"
        return self.type.name

    def get_leaderboard(self):
        players = self.get_finished_players()
        lb_text = "```Error while calculating leaderboard...\n\nSorry!```"
        lb_entries = []
        try:
            players = sorted(
                players, key=lambda k: k['stat_delta'], reverse=True)
            if len(players) > 15:
                players = players[:15]
            for index, player in enumerate(players):
                lb_entries.append(
                    f"{index+1}. {player['mcname']}: "
                    + f"+{player['stat_delta']:.0f}")
        except Exception:
            return lb_text
        else:
            lb_text = "\n".join(lb_entries)
            lb_text = "```" + lb_text + "```"
        return lb_text

    def get_embed(self, language="en", announcement=True):
        if self.status == ChallengeStatus.OPEN:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Open to join")
            embed.add_field(
                name="Join until",
                value=self.entries_close_time.strftime("%a %d.%m.%Y - %H:%M"))
            embed.add_field(
                name="Event starts",
                value=self.start_time.strftime("%a %d.%m.%Y - %H:%M"))
            embed.add_field(
                name="Event ends",
                value=self.end_time.strftime("%a %d.%m.%Y - %H:%M"))
            join_cost = self.pay_in if self.pay_in != 0 else "No cost"
            embed.add_field(name="Join cost", value=join_cost)
            if self.auto_accept:
                embed.add_field(
                    name="Instant join",
                    value="Join without approval by admin")
            else:
                embed.add_field(
                    name="Wait for entry place",
                    value="After joining, wait for an admin to approve your "
                    + "entry")
            total_participants = len(self.players)
            pending_participants = (len(self.get_pending_players()))
            pen_partic_text = f" ({pending_participants} pending)" if \
                pending_participants != 0 else ""
            embed.add_field(
                name="Participants",
                value=f"{total_participants}/100{pen_partic_text}")
            embed.add_field(
                name="Join now!",
                value="Use command `chall join` to join this event right "
                + "now!")

        elif self.status == ChallengeStatus.PENDING:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Starts soon (Can not join)")
            embed.add_field(
                name="Event starts",
                value=self.start_time.strftime("%a %d.%m.%Y - %H:%M"))
            embed.add_field(
                name="Event ends",
                value=self.end_time.strftime("%a %d.%m.%Y - %H:%M"))
            total_participants = len(self.players)
            pending_participants = (len(self.get_pending_players()))
            pen_partic_text = f" ({pending_participants} pending)" if \
                pending_participants != 0 else ""
            embed.add_field(
                name="Participants",
                value=f"{total_participants}/100{pen_partic_text}")
            embed.add_field(
                name="Watch your status",
                value="Use command `chall status` to see if you are "
                + "participating!")

        elif self.status == ChallengeStatus.STARTING:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Currently starting...")

        elif self.status == ChallengeStatus.RUNNING:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Running")
            total_participants = str(len(self.get_total_players()))
            pending_participants = str(len(self.get_pending_players()))
            active_participants = str(len(self.get_active_players()))
            errored_participants = str(len(self.get_errored_players()))
            disqualified_participants = str(
                len(self.get_disqualified_players()))
            part_text = f"`+{total_participants:>3}` Total entries\n" \
                + f"`-{pending_participants:>3}` Never were accepted\n" \
                + f"`-{disqualified_participants:>3}` Disqualified " \
                + "(Deactivated API)\n" \
                + f"`-{errored_participants:>3}` Error during data " \
                + "collection (Sorry!)\n" \
                + f"`={active_participants:>3}` Actually participating"
            embed.add_field(
                name="Participants",
                value=part_text)
            embed.add_field(
                name="Watch your status",
                value="Use command `chall status` to see if you are "
                + "participating!")

        elif self.status == ChallengeStatus.ENDING:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Ending... (Gathering data)")

        elif self.status == ChallengeStatus.ENDED:
            embed = Embed(title=self.title, description=f"UUID: `{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Ended")
            embed.add_field(
                name="Leaderboard",
                value=self.get_leaderboard(),
                inline=False)
            total_participants = str(
                len(self.get_total_players()) - len(
                    self.get_pending_players()))
            errored_participants = str(len(self.get_errored_players()))
            disqualified_participants = str(
                len(self.get_disqualified_players()))
            finished_participants = str(len(self.get_finished_players()))
            part_text = f"`+{total_participants:>3}` Accepted entries\n" \
                + f"`-{disqualified_participants:>3}` Disqualified " \
                + "(Deactivated API)\n" \
                + f"`-{errored_participants:>3}` Error during data " \
                + "collection (Sorry!)\n" \
                + f"`={finished_participants:>3}` Successfully participated"
            embed.add_field(
                name="Participants",
                value=part_text)
            embed.add_field(
                name="See your results",
                value="Use command `chall results` to see your own results "
                + "In this event. You might need the UUID of this challenge "
                + "for this command (found above).")

        elif self.status == ChallengeStatus.DISCARDED:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(name="Event Type", value=self.get_type_name())
            embed.add_field(name="Status", value="Event discarded")

        else:
            embed = Embed(title=self.title, description=f"`{self.uuid}`")
            embed.add_field(
                name="ERROR",
                value="Unknown or invalid event status.")
        return embed

    def gather_start_player_data(self):
        start_time = time.time()
        tracked_ids = []
        while len(self.get_accepted_players()) > 0:
            if time.time() - start_time >= 180:
                # TODO: Abort and set every ACCEPTED player to ERRORED
                print("Challenge start timed out. Bye!")
                break
            print(
                "New round of gathering data, "
                + f"awaiting {len(self.get_accepted_players())} data sets")
            for player in self.get_accepted_players():
                print(f"Adding {player['mcuuid']} to API request")
                tracked_ids.append((player['profileid'], player['mcuuid']))
                apirequest = SBAPIRequest(
                    RequestType.PROFILE,
                    (player['profileid'],),
                    player['profileid'])
                hypixel_api.input.put(apirequest)
            api_start_time = time.time()
            while True:
                if (time.time() - api_start_time >= 20) or \
                        len(tracked_ids) == 0:
                    print("Data-gathering round ended")
                    tracked_ids = []
                    break
                for current_id in tracked_ids:
                    if current_id[0] in hypixel_api.output:
                        print(f"Found {current_id[0]} in API output")
                        apioutput = hypixel_api.output.pop(current_id[0])
                        print(f"Removing {current_id[0]} from round tracking")
                        tracked_ids.remove(current_id)
                        if 'dd_error' in apioutput:
                            print("API output contains: 'TIMEOUT/NOTFOUND'")
                            continue
                        profiledata = apioutput['profile']
                        playerdata = self.get_player(current_id[1])
                        print(
                            f"Removing player {current_id[0]} from challenge")
                        self.players.remove(playerdata)
                        stat_start = get_profile_challenge_stat(
                            profiledata,
                            playerdata['mcuuid'],
                            self.type)
                        if stat_start is None:
                            playerdata['state'] = "DISQUALIFIED"
                            print("Adding new player data DISQUAL to event")
                            self.players.append(playerdata)
                            print(self.get_player(current_id[1]))
                            continue
                        playerdata['stat_start'] = stat_start
                        playerdata['state'] = "ACTIVE"
                        print("Adding new player data ACTIVE to event")
                        self.players.append(playerdata)
                        print(self.get_player(current_id[1]))

    def gather_end_player_data(self):
        start_time = time.time()
        tracked_ids = []
        while len(self.get_active_players()) > 0:
            if time.time() - start_time >= 180:
                # TODO: Abort and set every ACCEPTED player to ERRORED
                print("Challenge start timed out. Bye!")
                break
            print(
                "New round of gathering data, "
                + f"awaiting {len(self.get_active_players())} data sets")
            for player in self.get_active_players():
                print(f"Adding {player['mcuuid']} to API request")
                tracked_ids.append((player['profileid'], player['mcuuid']))
                apirequest = SBAPIRequest(
                    RequestType.PROFILE,
                    (player['profileid'],),
                    player['profileid'])
                hypixel_api.input.put(apirequest)
            api_start_time = time.time()
            while True:
                if (time.time() - api_start_time >= 20) or \
                        len(tracked_ids) == 0:
                    print("Data-gathering round ended")
                    tracked_ids = []
                    break
                for current_id in tracked_ids:
                    if current_id[0] in hypixel_api.output:
                        print(f"Found {current_id[0]} in API output")
                        apioutput = hypixel_api.output.pop(current_id[0])
                        print(f"Removing {current_id[0]} from round tracking")
                        tracked_ids.remove(current_id)
                        if 'dd_error' in apioutput:
                            print("API output contains: 'TIMEOUT/NOTFOUND'")
                            continue
                        profiledata = apioutput['profile']
                        playerdata = self.get_player(current_id[1])
                        print(
                            f"Removing player {current_id[0]} from challenge")
                        self.players.remove(playerdata)
                        stat_end = get_profile_challenge_stat(
                            profiledata,
                            playerdata['mcuuid'],
                            self.type)
                        if stat_end is None:
                            playerdata['state'] = "DISQUALIFIED"
                            print("Adding new player data DISQUAL to event")
                            self.players.append(playerdata)
                            print(self.get_player(current_id[1]))
                            continue
                        playerdata['stat_end'] = stat_end
                        playerdata['stat_delta'] = stat_end - \
                            playerdata['stat_start']
                        playerdata['state'] = "FINISHED"
                        print("Adding new player data FINISHED to event")
                        self.players.append(playerdata)
                        print(self.get_player(current_id[1]))

    def needs_tick(self):
        timenow = time.time()
        if self.status == ChallengeStatus.OPEN and \
                self.entries_close_time.timestamp() <= timenow:
            return True
        elif self.status == ChallengeStatus.PENDING and \
                self.start_time.timestamp() <= timenow:
            return True
        elif self.status == ChallengeStatus.STARTING:
            return False
        elif self.status == ChallengeStatus.RUNNING and \
                self.end_time.timestamp() <= timenow:
            return True
        elif self.status == ChallengeStatus.ENDING:
            return False
        elif self.status == ChallengeStatus.ENDED:
            return False
        elif self.status == ChallengeStatus.DISCARDED:
            return False
        return False

    def tick(self):

        def updateAnnouncementWrapper():
            client.loop.create_task(self.update_challenge_embed())

        if self.status == ChallengeStatus.OPEN:
            self.status = ChallengeStatus.PENDING
            client.loop.call_soon_threadsafe(updateAnnouncementWrapper)

        elif self.status == ChallengeStatus.PENDING:
            self.status = ChallengeStatus.STARTING
            client.loop.call_soon_threadsafe(updateAnnouncementWrapper)
            time.sleep(2)
            # Artificial sleep to let discord update the message embed before
            # thread locks
            self.gather_start_player_data()
            self.status = ChallengeStatus.RUNNING
            client.loop.call_soon_threadsafe(updateAnnouncementWrapper)

        elif self.status == ChallengeStatus.STARTING:
            raise RuntimeError("Challenge with type 'STARTING' cannot tick!")

        elif self.status == ChallengeStatus.RUNNING:
            self.status = ChallengeStatus.ENDING
            client.loop.call_soon_threadsafe(updateAnnouncementWrapper)
            time.sleep(2)
            # Artificial sleep to let discord update the message embed before
            # thread locks
            self.gather_end_player_data()
            self.status = ChallengeStatus.ENDED
            client.loop.call_soon_threadsafe(updateAnnouncementWrapper)
            self.archive_to_disk()
            challenge_scheduler.removeTask(self)

        elif self.status == ChallengeStatus.ENDING:
            raise RuntimeError("Challenge with type 'ENDING' cannot tick!")

        elif self.status == ChallengeStatus.ENDED:
            raise RuntimeError("Challenge with type 'ENDED' cannot tick!")

        elif self.status == ChallengeStatus.DISCARDED:
            raise RuntimeError("Challenge with type 'DISCARDED cannot tick!")

        else:
            raise RuntimeError("Challenge in invalid state cannot tick!")

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
            'announcement_message_id': self.announcement_message_id,
            'announcement_channel_id': self.announcement_channel_id,
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
            'announcement_channel_id': challenge_dict[
                'announcement_channel_id'],
            'players': challenge_dict['players']
        })


class ChallengeScheduler(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.scheduled_tasks = []
        self.shall_stop = False

    def stop(self):
        self.shall_stop = True

    def addTask(self, task):
        self.scheduled_tasks.append(task)

    def removeTask(self, task):
        self.scheduled_tasks.remove(task)

    def save_all_tracked(self):
        if len(self.scheduled_tasks) == 0:
            return
        save_object = {}
        for challenge in self.scheduled_tasks:
            save_object[challenge.uuid] = challenge.serialize()
        with open('./data/tracked_challenges.json', 'w') as f:
            f.write(json.dumps(save_object, indent=2))

    def load_all_tracked(self):
        if not os.path.isfile('./data/tracked_challenges.json'):
            return
        with open('./data/tracked_challenges.json', 'r') as f:
            data = f.read()
            read_data = json.loads(data) if data != "" else {}
        for chall_uuid in read_data:
            challenge = ChallengeEvent.deserialize(read_data[chall_uuid])
            self.addTask(challenge)

    def getTask(self, uuid):
        for task in self.scheduled_tasks:
            if task.uuid == uuid:
                return task
        return None

    def getAllTasks(self):
        return self.scheduled_tasks

    def run(self):
        while(True):
            if self.shall_stop:
                break

            for task in self.scheduled_tasks:
                if not isinstance(task, ChallengeEvent):
                    self.removeTask(task)
                if task.needs_tick():
                    task.tick()
            time.sleep(1)


# All currently tracked tasks
challenge_scheduler = None


def get_profile_challenge_stat(profile_data, player_uuid, challenge_type):
    try:
        player_data = profile_data['members'][player_uuid]
        type_path = challenge_type.value.split('/')
        stat_data = player_data
        while len(type_path) > 0:
            stat_data = stat_data[type_path.pop(0)]
    except Exception:
        return None
    else:
        return stat_data


async def get_member_by_id_or_ping(selector):
    user_id = str(selector).lstrip("<@!").lstrip("<@").rstrip(">")
    guild = main_guild
    try:
        member = guild.get_member(user_id)
        if member is None:
            member = await guild.fetch_member(user_id)
        return member
    except Exception:
        return None


async def get_channel_by_id_or_ping(selector):
    channel_id = str(selector).lstrip("<#").rstrip(">")
    guild = main_guild
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            channel = await client.fetch_channel(channel_id)
        return channel
    except Exception:
        return None


async def get_message_by_id(channel_id, message_id):
    channel = await get_channel_by_id_or_ping(channel_id)
    if channel is None:
        return None
    message = await channel.fetch_message(message_id)
    if message is None:
        return None
    return message


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
