import discord
from discord import guild_only
from dotenv import load_dotenv
import random
import os
from aiohttp import ClientSession
import asyncio
from aiohttp import ClientSession
import asyncio

load_dotenv()

bot = discord.Bot()
loading_messages = [
    "Thinking...",
    "Caw caw...",
    "Wondering...",
    "Reading...",
    "Searching...",
    "Hmmm...",
    "Getting a snack...",
    "Meow, I mean, caw caw...",
    "Getting some water...",
    "Doing some pushups...",
    "Don't forget to hydrate...",
    "Caw caw caw...",
    "Thinking...",
    "Wondering...",
    "Taking notes...",
    "Listening to a podcast...",
    "Use coupon code FH for 10% off crow feed...",
]


@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")


# 0.1.11 - anhropic opus#

@bot.slash_command(description="DrugCrow will give you a random drug fact.")
@guild_only()
async def drugs(ctx, message: str):
    # only respond in public channel
    if ctx.channel.type == discord.ChannelType.private:
        return await ctx.send("Please ask me in a public channel.")
    user_name = ctx.author.display_name
    if not message:
        return await ctx.respond("Caw caw")
    await ctx.respond(f"Working on message from {user_name}")
    request = {"message": message, "name": "DrugCrow"}
    # try:
    try:
        async with ClientSession() as session:
            response = await session.post(
                os.getenv("DRUGCROW_URL") + "/answer",
                json=request,
                timeout=400.0,
                headers={"Authorization": f"Bearer {os.getenv('AUTH_TOKEN')}"},  # noqa
            )
            response.raise_for_status()
            data = await response.json()
            await ctx.respond(data)
    except:
        with open('drugcrow.png', 'rb') as f:
            picture = discord.File(f)
            await ctx.send(file=picture)
            await ctx.send("This is not my fault. Give me a better prompt next time.")


bot.run(os.getenv("DISCORD_TOKEN"))
