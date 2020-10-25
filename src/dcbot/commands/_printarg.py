from discord import Embed
from src.dcbot import botcommon
from src.dcbot import client
from src.dcbot.botcommon import trytolog

CMD_METADATA = {
    'required_permlevel': botcommon.key_permlevel_admin,
    'required_channels': [botcommon.key_bot_adminchannel]}


@botcommon.requires_perm_level(level=CMD_METADATA['required_permlevel'])
@botcommon.requires_channel(CMD_METADATA['required_channels'])
async def invoke(message, arg_stack, botuser):
    await message.channel.send(str(arg_stack))
    return True