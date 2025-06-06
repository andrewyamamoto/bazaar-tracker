#!/usr/bin/env python3
from typing import List
import models
from tortoise import Tortoise
from nicegui import app, ui, Tailwind
import time
import psycopg2
import sys
from datetime import datetime
import pytz


async def init_db() -> None:
    await Tortoise.init(db_url='asyncpg://postgres:postgres@localhost:5432/bazaar', modules={'models': ['models']})
    #await Tortopip install tortoise-orm[psycopg]ise.generate_schemas()


async def close_db() -> None:
    await Tortoise.close_connections()

app.on_startup(init_db)
app.on_shutdown(close_db)


@ui.refreshable
async def list_of_games() -> None:
    async def delete_game(game_id: int) -> None:
        game = await models.Game.get(id=game_id)
        await game.delete()
        await list_of_games.refresh()

    games: List[models.Game] = await models.Game.all()

    # Header row
    with ui.row().classes('w-full font-bold'):
        for header in ['Player', 'Season', 'Mode', 'Hero', 'Wins', 'Day End', 'Media', 'Notes', 'Played', 'Actions']:
            ui.label(header).classes('w-1/12 truncate')
    
    # Data rows
    for game in reversed(games):
        with ui.row().classes('w-full items-center'):
            ui.label(game.player.lower().capitalize()).classes('w-1/12 truncate')
            ui.label(str(game.season)).classes('w-1/12 truncate')
            ui.label("Ranked" if game.ranked else "Non-Ranked").classes('w-1/12 truncate')
            hero_colors = {
                'Dooley': 'bg-[#397d83] text-white',
                'Mak': 'bg-[#2da337] text-white',
                'Pygmalien': 'bg-[#f56a1f] text-white',
                'Vanessa': 'bg-[#6312de] text-white',
            }
            hero_class = hero_colors.get(game.hero.lower().capitalize(), 'bg-gray-200 text-gray-900')
            ui.label(game.hero).classes(
                f'w-1/12 inline-block truncate rounded-full px-3 py-1 {hero_class} text-sm font-semibold shadow text-center'
            )
            ui.label(str(game.wins)).classes('w-1/12 truncate')
            if game.wins == 10 and game.finished == 10:
                ui.label("Perfect Game").classes('w-1/12 truncate font-bold text-green-600')
            else:
                ui.label(str(game.finished)).classes('w-1/12 truncate')
            ui.label(game.media).classes('w-1/12 truncate')
            # Show notes with modal if truncated, link the text instead of adding a view button
            max_length = 20
            if game.notes and len(game.notes) > max_length:
                def show_notes(notes=game.notes):
                    with ui.dialog() as dialog, ui.card():
                        ui.label(notes).classes('whitespace-pre-line')
                        ui.button('Close', on_click=dialog.close)
                    dialog.open()
                ui.label(game.notes[:max_length] + '...').classes('truncate inline text-primary cursor-pointer underline').on('click', show_notes)
            else:
                ui.label(game.notes).classes('w-1/12 truncate')

            if game.played:
                played_str = game.played.strftime('%Y-%m-%d %I:%M %p')
            else:
                played_str = ''
            ui.label(played_str).classes('')
            ui.button(icon="delete", on_click=lambda g=game.id: delete_game(g)).props('color=negative flat')


@ui.page('/')
async def index():
    async def create() -> None:
        
        await models.Game.create(
            player=player.value,
            season=season.value or 0,
            ranked=ranked.value,
            hero=hero.value,
            wins=wins.value,
            finished=finished.value,
            media=media.value,
            notes=notes.value,
            )
        player.value = ''
        season.value = None
        list_of_games.refresh()
        ui.notify('Run added!')
    
    with ui.column().classes('w-full'):
        ui.label('Bazaar Tracker').classes('text-3xl font-bold')
        ui.label('Track your bazaar games!').classes('text-lg')
        
    with ui.row().classes('flex w-full gap-4'):
        # Fixed-width column
        with ui.column().classes('w-[400px] shrink-0'):
            player = ui.select(['Sam', 'Andrew', 'Lincoln'], label='Player').classes('w-full')
            season = ui.select([1, 2, 3, 4, 5], label='Season').classes('w-full')
            
            with ui.row():
                ranked = ui.checkbox()
                ui.label().bind_text_from(ranked, 'value', lambda v: 'Ranked').classes('mt-3')

            hero = ui.select(['Dooley', 'Mak', 'Pygmalien','Vanessa'], label='Hero').classes('w-full')
            wins = ui.slider(min=0, max=10, step=1, value=0).classes('w-full')
            wins_label = ui.label(f"Wins: {wins.value}")
            wins_label.bind_text_from(wins, "value", lambda v: f"Wins: {v}")
            
            finished = ui.slider(min=0, max=20, step=1, value=0).classes('w-full')
            finished_label = ui.label(f"Day Finished: {finished.value}")
            finished_label.bind_text_from(finished, "value", lambda v: f"Day Finished: {v}")

            media = ui.input(label='Media').classes('w-full')
            
            # some sort of file upload handler here
            # ui.upload(on_upload=lambda e: ui.notify(f'Uploaded {e.name}')).classes('max-w-full')

            notes = ui.textarea(label='Notes').classes('w-full')
            ui.button('Add Run', on_click=create).classes('w-full').props('color=primary')

        # Flexible full-width column
        with ui.column().classes('flex-1'):
            await list_of_games()

        

ui.run(dark="true")
