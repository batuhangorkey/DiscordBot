# Buildpacks
# https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
# https://github.com/xrisk/heroku-opus.git
import asyncio
import itertools
import logging
import os
import random
import time

import discord
import youtube_dl
from discord.ext import commands, tasks
from youtube_search import YoutubeSearch

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    # 'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn'
}

player_emojis = {
    'stop': u'\u23F9',
    'play_pause': u'\u23EF',
    'next_track': u'\u23ED',
    'backward': u'\u21AA',
    'forward': u'\u21A9'
}

playlist_emojis = {
    'dislike': u'\U0001F44E',
    'like': u'\U0001F44D'
}

# if not discord.opus.is_loaded():
#     discord.opus.load_opus('opus')
# ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

youtube_dl.utils.bug_reports_message = lambda: ''


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')
        self.duration = data.get('duration')
        self.start_time = data.get('start_time')
        self.filename = data.get('filename')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, start_time=0):
        loop = loop or asyncio.get_event_loop()
        try:
            with youtube_dl.YoutubeDL(ytdl_format_options) as ytdl:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        except youtube_dl.utils.DownloadError as error:
            return logging.error(error)
        if 'entries' in data:
            data = data['entries'][0]
        with youtube_dl.YoutubeDL(ytdl_format_options) as ytdl:
            filename = data['url'] if stream else ytdl.prepare_filename(data)
        data['filename'] = filename
        data['start_time'] = start_time
        data['duration'] = time.strftime('%M:%S', time.gmtime(data.get('duration')))
        if start_time != 0:
            ffmpeg_options['options'] = '-vn -ss {}'.format(time.strftime('%M:%S', time.gmtime(start_time)))
        else:
            ffmpeg_options['options'] = '-vn'
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


# TODO:
#  DJ ROLE
#  SPOTIFY CONNECTION
#  CLEAR QUEUE METHOD
class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.handlers = {}
        self.main_loop.start()

    def cog_unload(self):
        self.main_loop.cancel()

    def create_handler(self, ctx):
        self.handlers[ctx.guild.id] = Handler(self.bot, ctx)
        self.handlers[ctx.guild.id].ctx = ctx
        self.handlers[ctx.guild.id].create_task()

    @commands.command(help='Joins authors voice channel.')
    async def join(self, ctx, *, channel: discord.VoiceChannel = None):
        if ctx.voice_client:
            self.handlers[ctx.guild.id].channel = channel
            return await ctx.voice_client.move_to(channel)
        if channel is None and ctx.author.voice.channel:
            await ctx.author.voice.channel.connect()
        else:
            await channel.connect()
        self.create_handler(ctx)

    @commands.command(help="Downloads audio from a Youtube url.")
    async def download(self, ctx, *, url):
        async with ctx.typing():
            logging.info('Requested: {}'.format(url))
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            if player is None:
                return await ctx.send('Bir şeyler yanlış. Bir daha dene')
            _file = discord.File(open(player.filename, "rb"), filename=player.title)
            await ctx.send(content="İndirilen dosya: ", file=_file)
            try:
                os.remove(player.filename)
            finally:
                logging.info("Deleted {}".format(player.filename))

    @commands.command(help="Streams from a url. Doesn't predownload.")
    async def stream(self, ctx, *, url):
        start = time.process_time()
        async with ctx.typing():
            audio = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            if audio is None:
                return await ctx.send('Birşeyler yanlış. Bir daha dene')
            await self.handlers[ctx.guild.id].source_handler(ctx, audio)
        logging.info('Elapsed time: {}'.format(time.process_time() - start))

    @commands.command(help='Plays url and search string from Youtube.')
    async def play(self, ctx, *, search_string: str):
        start = time.process_time()
        async with ctx.typing():
            audio = await YTDLSource.from_url(search_string, loop=self.bot.loop)
            if isinstance(audio, YTDLSource):
                await self.handlers[ctx.guild.id].source_handler(ctx.channel, audio)
            else:
                return await ctx.send('Bir şeyler yanlış. @Batuhan#8438')
        logging.info(f'Elapsed time: {time.process_time() - start} | String: {search_string}')

    @commands.command(help='Searches youtube. 10 results', hidden=True)
    async def search(self, ctx, *, search_string):
        start = time.process_time()
        self.handlers[ctx.guild.id].search_list.clear()
        results = YoutubeSearch(search_string, max_results=10).to_dict()
        embed = discord.Embed(colour=0x8B0000)
        for i, _ in list(enumerate(results)):
            k = '[{} - {}](https://www.youtube.com{})'
            embed.add_field(name=' - '.join([str(i + 1), _['title']]),
                            value=k.format(_['channel'], _['duration'], _['url_suffix']))
            self.handlers[ctx.guild.id].search_list.append('https://www.youtube.com{}'.format(_['url_suffix']))
        async with ctx.typing():
            await ctx.send(embed=embed, delete_after=20)
        if self.bot.get_cog('Events'):
            self.bot.remove_cog('Events')
        self.bot.add_cog(Events(self.bot, ctx))
        print('Method: {} | Elapsed time: {}'.format('search', time.process_time() - start))

    @commands.command(help='Plays random songs')
    async def playrandom(self, ctx):
        async with ctx.typing():
            if not ctx.voice_client.is_playing() or not ctx.voice_client.is_paused():
                if not self.handlers[ctx.guild.id].play_random:
                    source = await YTDLSource.from_url(self.handlers[ctx.guild.id].get_song(),
                                                       loop=self.bot.loop,
                                                       stream=True)
                    if source is None:
                        return await ctx.send('Bir şeyler yanlış. Bir daha dene')
                    await self.handlers[ctx.guild.id].source_handler(ctx, source)
            self.handlers[ctx.guild.id].play_random = not self.handlers[ctx.guild.id].play_random
        await self.handlers[ctx.guild.id].update_footer()

    @commands.command(help='Changes volume to the value.')
    async def volume(self, ctx, volume: int):
        await ctx.message.delete()
        if ctx.voice_client is None:
            return await ctx.send('Ses kanalına bağlı değilim.')

        ctx.voice_client.source.volume = volume / 100
        await ctx.send('Ses seviyesi %{} oldu.'.format(volume))

    @commands.command(hidden=True)
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.pause()
            embed = self.handlers[ctx.guild.id].last_message.embeds[0]
            embed.description = 'Durduruldu'
            await self.handlers[ctx.guild.id].last_message.edit(embed=embed)

    @commands.command(hidden=True)
    async def resume(self, ctx):
        if ctx.voice_client is not None and ctx.voice_client.source:
            ctx.voice_client.resume()
            embed = self.handlers[ctx.guild.id].last_message.embeds[0]
            embed.description = 'Oynatılıyor'
            await self.handlers[ctx.guild.id].last_message.edit(embed=embed)

    @commands.command(help='Skips current video.')
    async def skip(self, ctx):
        if ctx.voice_client.source:
            ctx.voice_client.stop()

    @commands.command(help='Disconnects the bot from voice channel.')
    async def stop(self, ctx):
        handler = self.handlers.get(ctx.guild.id)
        if handler:
            if handler.task:
                handler.task.cancel()
            handler.play_random = False
            handler.reset_playlist()
            for _ in range(handler.queue.qsize()):
                handler.queue.get_nowait()
                handler.queue.task_done()
            await self.bot.default_presence()
            if ctx.voice_client is not None:
                await ctx.voice_client.disconnect()
            await asyncio.sleep(0.1)
            handler.remove_current()

    @commands.command(hidden=True)
    async def add_link(self, ctx, url: str):
        try:
            with youtube_dl.YoutubeDL(ytdl_format_options) as ytdl:
                data = await self.bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        except youtube_dl.utils.DownloadError as error:
            logging.error(error)
            return await ctx.send('Yanlış bir şeyler oldu.')
        added_songs = []
        failed_songs = []
        conn = self.bot.get_pymysql_connection()
        try:
            if 'entries' in data:
                entries = [_ for _ in data.get('entries')]
            else:
                entries = [data]
            for entry in entries:
                if entry.get('webpage_url') in self.handlers[ctx.guild.id].db_playlist:
                    await ctx.send('Bu şarkı listede var: {}'.format(entry.get('title')))
                    continue
                with conn.cursor() as cursor:
                    cursor.execute('INSERT INTO playlist (url) VALUES ("{}")'.format(entry.get('webpage_url')))
                    conn.commit()

                    cursor.execute('SELECT url FROM playlist where url="{}"'.format(entry.get('webpage_url')))
                    data = cursor.fetchone()
                if data:
                    added_songs.append(entry.get('title'))
                else:
                    failed_songs.append(entry.get('title'))
            await ctx.send('Eklenen şarkılar:\n'
                           '```{}```'.format('\n'.join(added_songs)))
            if len(failed_songs) > 0:
                await ctx.send('\nBaşına bir şey gelen şarkılar:\n'
                               '```{}```'.format('\n'.join(failed_songs)))
            self.handlers[ctx.guild.id].reset_db_playlist()
            await self.handlers[ctx.guild.id].update_footer()
        except Exception as error:
            logging.error(error)
        finally:
            conn.close()

    @commands.command(help='Go to the time on the video')
    async def goto(self, ctx, target_time: int):
        async with ctx.typing():
            self.handlers[ctx.guild.id].time_cursor = target_time
            ctx.voice_client.pause()
            url = ctx.voice_client.source.url
            audio = await YTDLSource.from_url(url=url, loop=self.bot.loop, start_time=target_time)
            ctx.voice_client.source = audio
            self.handlers[ctx.guild.id].source_start_time = time.time()
            await self.handlers[ctx.guild.id].send_player_embed(audio)
            for _ in range(self.handlers[ctx.guild.id].queue.qsize() - 1):
                a = self.handlers[ctx.guild.id].queue.get_nowait()
                self.handlers[ctx.guild.id].queue.task_done()
                self.handlers[ctx.guild.id].queue.put_nowait(a)

    @commands.command(hidden=True)
    async def set_skip_time(self, ctx, time_set: int):
        async with ctx.typing():
            self.handlers[ctx.guild.id].time_setting = time_set

    # TODO: Write this method
    @commands.command(hidden=True)
    async def fancy_player(self, ctx):
        pass

    @goto.before_invoke
    async def ensure_source(self, ctx):
        if ctx.voice_client.source is None:
            await ctx.send('Ortada ileri alınacak video yok.')
            raise commands.CommandError('Audio source empty.')

    @stream.before_invoke
    @play.before_invoke
    @search.before_invoke
    @playrandom.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                self.create_handler(ctx)
            else:
                await ctx.send('Ses kanalında değilsin.')
                raise commands.CommandError('Author not connected to a voice channel.')

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        if self.handlers.get(reaction.message.guild.id) is not None:
            guild_id = reaction.message.guild.id
            if reaction.message.id == self.handlers[guild_id].last_message.id:
                if reaction.emoji == player_emojis['next_track']:
                    return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('skip'))
                if reaction.emoji == player_emojis['play_pause']:
                    return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('pause'))
                if reaction.emoji == player_emojis['stop']:
                    return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('stop'))
                if reaction.emoji == player_emojis['backward']:
                    delta_time = time.time() - self.handlers[guild_id].source_start_time
                    target_time = self.handlers[guild_id] \
                                      .time_cursor + delta_time - self.handlers[guild_id].time_setting
                    return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('goto'),
                                                                    target_time=target_time)
                if reaction.emoji == player_emojis['forward']:
                    delta_time = time.time() - self.handlers[guild_id].source_start_time
                    target_time = self.handlers[guild_id] \
                                      .time_cursor + delta_time + self.handlers[guild_id].time_setting
                    return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('goto'),
                                                                    target_time=target_time)
                if reaction.emoji == playlist_emojis['dislike']:
                    self.handlers[guild_id].dislike()
                    return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('skip'))
                if reaction.emoji == playlist_emojis['like']:
                    await self.handlers[guild_id].like()

    @tasks.loop(minutes=5)
    async def main_loop(self):
        for _, handler in self.handlers.items():
            if handler.voice_client.is_connected() and not handler.is_playing():
                await handler.voice_client.disconnect()

    @main_loop.before_loop
    async def before_idle(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot:
            return
        guild_id = reaction.message.guild.id
        if self.handlers.get(guild_id) is not None and reaction.message.id == self.handlers[guild_id].last_message.id:
            if reaction.emoji == player_emojis['play_pause']:
                return await self.handlers[guild_id].ctx.invoke(self.bot.get_command('resume'))


class Events(commands.Cog):
    def __init__(self, bot, ctx):
        self.bot = bot
        self._ctx = ctx

    @property
    def ctx(self):
        return self._ctx

    @commands.Cog.listener()
    async def on_message(self, msg):
        try:
            if msg.author is self.bot.user and msg.author is not self.ctx.author:
                return
            index = int(msg.content)
            if index < 1 or 10 < index:
                return
            music = self.bot.get_cog('Music')
            handler = music.handlers[self.ctx.guild.id]
            await self.ctx.invoke(music.bot.get_command('play'), search_string=handler.search_list[index - 1])
            music.search_list.clear()
        except ValueError as error:
            logging.error(error)
        except Exception as error:
            logging.error(error)
        finally:
            self.bot.remove_cog('Events')


class Handler:
    def __init__(self, bot, ctx):
        self.channel = ctx.channel
        self.voice_client: discord.VoiceClient = ctx.voice_client
        self._random_playlist = []
        self._last_message = None
        self.bot = bot
        self.ctx = None
        self.current = None

        self.queue = asyncio.Queue(loop=bot.loop)
        self.play_next = asyncio.Event(loop=bot.loop)
        self.task = None

        self.search_list = []
        self.random_playlist = []
        self.queue_value = []

        self.source_start_time = None
        self.time_cursor = None
        self.time_setting = 30

        self.play_random = False
        self.footer = 'Rastgele çalma {} | Müzik listesi uzunluğu ({}) - v{}'
        self.fancy_format = True

        self.reset_db_playlist()

    @property
    def last_message(self):
        return self._last_message

    @property
    def db_playlist(self):
        return self._random_playlist

    def is_playing(self):
        return self.voice_client.is_playing()

    def remove_current(self):
        if self.current:
            os.remove(self.current.filename)
            self.current = None

    def create_task(self):
        if self.task:
            self.task.cancel()
        self.task = self.bot.loop.create_task(self.queue_handler())

    def reset_db_playlist(self):
        self._random_playlist = self.bot.get_random_playlist()
        self.random_playlist = self._random_playlist.copy()

    def reset_playlist(self):
        self.random_playlist = self._random_playlist.copy()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next.set)

    def get_player_message_body(self, source: YTDLSource):
        try:
            if source.start_time != 0:
                description = 'Şimdi oynatılıyor - {} dan başladı'.format(time.strftime('%M:%S',
                                                                                        time.gmtime(source.start_time)))
            else:
                description = 'Şimdi oynatılıyor'
            embed = discord.Embed(title='{0.title} ({0.duration}) by {0.uploader}'.format(source),
                                  url=source.url,
                                  description=description,
                                  colour=0x8B0000)
            embed.set_footer(text=self.footer.format('açık' if self.play_random else 'kapalı',
                                                     len(self._random_playlist),
                                                     self.bot.git_hash))
            embed.set_thumbnail(url=source.thumbnail)
            return embed
        except Exception as error:
            logging.error(error)
        finally:
            pass

    async def update_footer(self):
        try:
            if self.last_message is None:
                return
            embed = self.last_message.embeds[0]
            embed.set_footer(text=self.footer.format('açık' if self.play_random else 'kapalı',
                                                     len(self._random_playlist),
                                                     self.bot.git_hash))
            await self.last_message.edit(embed=embed)
        finally:
            pass

    async def send_player_embed(self):
        if self.last_message:
            embed = self.get_player_message_body(self.voice_client.source)
            embed.clear_fields()
            for i, value in list(enumerate(self.queue_value)):
                embed.add_field(name=str(i + 1), value=value)
            return await self.last_message.edit(embed=embed)
        else:
            embed = self.get_player_message_body(self.voice_client.source)
            for i, value in list(enumerate(self.queue_value)):
                embed.add_field(name=str(i + 1), value=value)

        if self.last_message is not None:
            await self._last_message.delete()
        self._last_message = await self.channel.send(embed=embed)

        if self.play_random:
            for _ in playlist_emojis.values():
                await self.last_message.add_reaction(_)
        for _ in player_emojis.values():
            await self.last_message.add_reaction(_)

    def get_song(self):
        if len(self.random_playlist) == 0:
            self.reset_playlist()
        cum_weights = list(itertools.accumulate([rating for url, rating in self.random_playlist]))
        song = random.choices(self.random_playlist, cum_weights=cum_weights, k=1)[0]
        self.random_playlist.remove(song)
        return song[0]

    async def source_handler(self, channel, source):
        self.channel = channel
        if self.queue.empty():
            if self.voice_client.source:
                self.queue_value.append(source.title)
                await self.send_player_embed()
        else:
            self.queue_value.append(source.title)
            await self.send_player_embed()
        await self.queue.put(source)

    async def queue_handler(self):
        while True:
            try:
                self.remove_current()
                self.play_next.clear()
                self.time_cursor = 0
                if len(self.queue_value) > 0:
                    self.queue_value.pop(0)
                if self.queue.empty():
                    if self.play_random and self.voice_client is not None:
                        async with self.channel.typing():
                            source = await YTDLSource.from_url(self.get_song(),
                                                               loop=self.bot.loop,
                                                               stream=True)
                            if source:
                                await self.queue.put(source)
                            else:
                                self.play_random = False
                                await self.update_footer()
                                await self.channel.send('Birşeyler kırıldı.')
                    elif self.last_message:
                        await self.bot.default_presence()
                        embed = self.last_message.embeds[0]
                        embed.description = 'Şarkı bitti'
                        embed.clear_fields()
                        await self.last_message.edit(embed=embed)
                self.current = await self.queue.get()
                self.voice_client.play(self.current,
                                       after=lambda e: print('Player error: %s' % e)
                                       if e else self.toggle_next())
                await self.send_player_embed()
                self.source_start_time = time.time()
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,
                                                                         name=self.current.title))
                await self.play_next.wait()
            except asyncio.CancelledError:
                break

    def dislike(self):
        if self.voice_client.source is None:
            return
        url = self.voice_client.source.url
        if url not in [url for url, s in self._random_playlist]:
            return
        conn = self.bot.get_pymysql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE playlist SET dislike = dislike + 1 WHERE url = "{}"'.format(url))
            conn.commit()
        finally:
            conn.close()
            return

    async def like(self):
        if self.voice_client.source is None:
            return
        url = self.voice_client.source.url
        if url not in [url for url, s in self._random_playlist]:
            return await self.channel.send('Sadece şarkı listesindeki şarkılar beğenilebilir.')
        conn = self.bot.get_pymysql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE playlist SET like_count = like_count + 1 WHERE url = "{}"'.format(url))
            conn.commit()
        finally:
            conn.close()
            return
