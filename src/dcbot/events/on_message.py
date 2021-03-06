import importlib
from lib.stavlexer import stavlexer
from src.dcbot import client
from src.dcbot import botcommon
from src.translation import transget
from src.database import dbcommon
from src.database import sqlsession
from src.database.models.botuser import BotUser

DD_MAX_INIT_STAGE = 3


def is_command(message_content):
    shortprefix = dbcommon.get_bot_setting(botcommon.key_bot_prefix, '$')
    if message_content.startswith("<@!" + str(client.user.id) + "> ") or \
            message_content.startswith("<@" + str(client.user.id) + "> ") or \
            message_content.startswith(shortprefix):
        return True
    return False


def get_processed_argstack(message):
    shortprefix = dbcommon.get_bot_setting(botcommon.key_bot_prefix, '$')
    fullstring = "<<Error!>>"
    if message.startswith("<@!" + str(client.user.id) + ">") or \
            message.startswith("<@" + str(client.user.id) + ">"):
        fullstring = " ".join(message.split(" ")[1:])
    elif message.startswith(shortprefix):
        fullstring = message[1:]
    argstack = stavlexer.get_argv(fullstring)
    return argstack


async def on_message_init_mode(message, cmd_arg_stack, init_stage):
    if not is_command(message.content):
        return
    if init_stage == 0:
        if cmd_arg_stack[0] == "init":
            newuser = BotUser(
                user_discord_id=message.author.id,
                user_pref_lang=botcommon.default_user_preferred_language,
                user_permission_level=botcommon.key_permlevel_owner)
            sqlsession.add(newuser)
            sqlsession.commit()
            from src.dcbot.commands import chanset
            await chanset.invoke(
                message,
                [
                    'chanset',
                    'admin',
                    '<#' + str(message.channel.id) + '>'],
                newuser)
            dbcommon.set_bot_setting(
                botcommon.key_bot_mainserver,
                message.guild.id)
            dbcommon.set_bot_setting(botcommon.key_bot_init_stage, 1)
            await message.channel.send(transget(
                'init.stage0.successful',
                newuser.user_pref_lang))
            await message.channel.send(transget(
                'init.stage1.intro',
                newuser.user_pref_lang))

    elif init_stage == 1:
        currentuser = dbcommon.get_user_or_create(message.author.id)
        if cmd_arg_stack[0] == "init":
            await message.channel.send(transget(
                'init.stage1.intro',
                currentuser.user_pref_lang))

        elif cmd_arg_stack[0] == "setprefix":
            from src.dcbot.commands import setprefix
            if await setprefix.invoke(
                    message,
                    cmd_arg_stack,
                    currentuser):
                dbcommon.set_bot_setting(botcommon.key_bot_init_stage, 2)
                await message.channel.send(transget(
                    'init.stage1.successful',
                    currentuser.user_pref_lang))
                await message.channel.send(transget(
                    'init.stage2.intro',
                    currentuser.user_pref_lang))

    elif init_stage == 2:
        currentuser = dbcommon.get_user_or_create(message.author.id)
        if cmd_arg_stack[0] == "init":
            await message.channel.send(transget(
                'init.stage2.intro',
                currentuser.user_pref_lang))

        elif cmd_arg_stack[0] == "chanset":
            from src.dcbot.commands import chanset
            if await chanset.invoke(
                    message,
                    cmd_arg_stack,
                    currentuser):
                dbcommon.set_bot_setting(botcommon.key_bot_init_stage, 3)
                await message.channel.send(transget(
                    'init.stage2.successful',
                    currentuser.user_pref_lang))
                await message.channel.send(transget(
                    'init.stage3.intro',
                    currentuser.user_pref_lang))

    elif init_stage == 3:
        currentuser = dbcommon.get_user_or_create(message.author.id)
        if cmd_arg_stack[0] == "init":
            await message.channel.send(transget(
                'init.stage3.intro',
                currentuser.user_pref_lang))

        if cmd_arg_stack[0] == "addcmdchan":
            from src.dcbot.commands import addcmdchan
            if await addcmdchan.invoke(
                    message,
                    cmd_arg_stack,
                    currentuser):
                dbcommon.set_bot_setting(botcommon.key_bot_init_stage, 4)
                await message.channel.send(transget(
                    'init.stage3.successful',
                    currentuser.user_pref_lang))
                await message.channel.send(transget(
                    'init.completed',
                    currentuser.user_pref_lang))

    elif init_stage == 4:
        pass


async def on_message_command_mode(message, cmd_arg_stack):
    botuser = dbcommon.get_user_or_create(message.author.id)
    try:
        command = importlib.import_module(
            '.' + cmd_arg_stack[0],
            'src.dcbot.commands')
    except ImportError as e:
        print(e)
    else:
        try:
            if await command.invoke(message, cmd_arg_stack, botuser):
                pass
            else:
                pass
        except Exception as e:
            print(e)


async def on_process_message_mode(message):
    for processor in botcommon.registered_message_processors:
        processor_module = importlib.import_module(
            '.' + processor,
            'src.dcbot.messageprocessors')
        return_meta = await processor_module.invoke(message)
        if return_meta['continue'] is False:
            break


@client.event
async def on_message(message):

    if botcommon.is_bot_stopping is True:
        return

    if message.author == client.user:
        return
    cmd_arg_stack = get_processed_argstack(message.content)

    init_stage = int(dbcommon.get_bot_setting(botcommon.key_bot_init_stage, 0))
    if init_stage <= DD_MAX_INIT_STAGE:
        await on_message_init_mode(message, cmd_arg_stack, init_stage)
    elif is_command(message.content):
        await on_message_command_mode(message, cmd_arg_stack)
    else:
        await on_process_message_mode(message)
